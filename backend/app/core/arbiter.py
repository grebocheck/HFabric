"""The VRAM arbiter — the architectural heart of HFabric.

On a 16 GB card you cannot hold an LLM (~12 GB) and a diffusion model at the
same time. The arbiter enforces the invariant **at most one GPU resident at a
time**: requesting a different model unloads the current one first. Swaps are
serialized by a lock and announced on the event bus so the UI can show what is
happening.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from ..backends.base import GpuBackend
from .enums import EventType
from .events import Event, EventBus

logger = logging.getLogger("hfabric")


class ArbiterConflict(RuntimeError):
    """A requested GPU state transition conflicts with current ownership."""

    code = "gpu_state_conflict"

    def __init__(self, message: str, *, status: dict | None = None) -> None:
        super().__init__(message)
        self.status = status


class ResidentPinConflict(ArbiterConflict):
    """The resident model is owned by a pin that the caller did not release."""

    code = "resident_pinned"


class PinOwnershipConflict(ArbiterConflict):
    """A caller attempted to mutate a pin owned by another lifecycle."""

    code = "pin_ownership_conflict"


class GpuLaneConflict(ArbiterConflict):
    """An exclusive external GPU lane conflicts with a resident/lane request."""

    code = "gpu_lane_conflict"


class GpuBusyConflict(ArbiterConflict):
    """A transition requires an idle worker, but GPU work started first."""

    code = "gpu_busy"


class ArbiterCleanupError(RuntimeError):
    """Best-effort shutdown cleanup completed with one or more unload errors."""

    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = errors
        super().__init__("; ".join(str(error) or type(error).__name__ for error in errors))


class GpuArbiter:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = asyncio.Lock()
        self._current: GpuBackend | None = None
        self._warm_backends: list[GpuBackend] = []
        self._resident_pin: dict[str, str] | None = None
        # Short-lived execution leases close the ensure -> generate gap: a user
        # free/swap request cannot unload the backend while a job is using it.
        self._active_uses: dict[str, GpuBackend] = {}
        # Non-arbiter GPU consumers (voice session, TTS, transcribe) keyed by a
        # stable lane id -> human label. These don't hold a resident heavy model;
        # they're tracked purely so status()/the topbar report that the GPU is busy
        # instead of "idle" while one runs. Insertion-ordered.
        self._lanes: dict[str, str] = {}
        # Exclusive lanes (currently realtime Voice) cannot coexist with a heavy
        # resident. Keeping this distinction lets short TTS/transcribe lanes retain
        # their existing observability-only behavior.
        self._exclusive_lanes: set[str] = set()

    @property
    def current(self) -> GpuBackend | None:
        return self._current

    @property
    def resident_pin(self) -> dict[str, str] | None:
        return dict(self._resident_pin) if self._resident_pin is not None else None

    @property
    def exclusive_lane_active(self) -> bool:
        return bool(self._exclusive_lanes)

    def busy_paths(self) -> set[Path]:
        """Resolved on-disk paths of the resident + warm models — i.e. weights that
        must not be deleted out from under a load."""
        backends = list(self._warm_backends)
        if self._current is not None:
            backends.append(self._current)
        paths: set[Path] = set()
        for backend in backends:
            raw = getattr(backend.descriptor, "path", None)
            if raw is None:
                continue
            try:
                paths.add(Path(raw).resolve())
            except OSError:
                continue
        return paths

    async def ensure(self, backend: GpuBackend) -> None:
        """Guarantee ``backend`` is the sole GPU resident and loaded."""
        async with self._lock:
            await self._ensure_locked(backend)

    async def acquire(self, backend: GpuBackend, owner_id: str) -> None:
        """Atomically ensure a backend and lease it to one running GPU job."""
        async with self._lock:
            existing = self._active_uses.get(owner_id)
            if existing is backend:
                return
            if self._active_uses:
                raise self._usage_conflict(f"start GPU job {owner_id}")
            await self._ensure_locked(backend)
            self._active_uses[owner_id] = backend

    async def release(self, owner_id: str) -> bool:
        async with self._lock:
            return self._active_uses.pop(owner_id, None) is not None

    async def free_all(self, *, force: bool = False) -> None:
        """Unload every arbiter-owned model or fail without partial cleanup.

        ``force`` is retained for API compatibility, but normal user actions must
        release their pin/lane explicitly. Shutdown should use
        :meth:`force_shutdown`, which is best-effort across every resource.
        """
        if force:
            await self.force_shutdown()
            return
        async with self._lock:
            if self._active_uses:
                raise self._usage_conflict("free GPU memory")
            if self._resident_pin is not None:
                raise self._pin_conflict("free GPU memory")
            if self._lanes:
                labels = ", ".join(self._lanes.values())
                raise GpuLaneConflict(
                    f"cannot free GPU memory while an external lane is active: {labels}",
                    status=self.status(),
                )
            await self._free_all_locked()

    async def request_free(self) -> None:
        """Explicit user-facing free transition (typed conflicts, no force)."""
        await self.free_all()

    async def force_shutdown(self) -> None:
        """Best-effort terminal cleanup used only while the process is exiting."""
        errors: list[BaseException] = []
        async with self._lock:
            for backend in set(self._active_uses.values()):
                backend.request_stop()
            self._active_uses.clear()
            self._resident_pin = None
            self._lanes.clear()
            self._exclusive_lanes.clear()

            if self._current is not None:
                try:
                    await self._unload_current(allow_keep_warm=False)
                except Exception as exc:  # noqa: BLE001 - continue terminal cleanup
                    errors.append(exc)
                    self._current = None
            for backend in list(self._warm_backends):
                try:
                    await self._unload_warm(backend)
                except Exception as exc:  # noqa: BLE001 - continue terminal cleanup
                    errors.append(exc)
                    if backend in self._warm_backends:
                        self._warm_backends.remove(backend)
            await self._publish_status()
        if errors:
            raise ArbiterCleanupError(errors)

    async def pin_current(self, pin_id: str, label: str) -> dict[str, str]:
        """Keep the current resident model in VRAM until the pin is released."""
        async with self._lock:
            if self._exclusive_lanes:
                raise self._lane_conflict("pin a resident model")
            if self._resident_pin is not None and self._resident_pin.get("id") != pin_id:
                raise PinOwnershipConflict(
                    f"{self._resident_pin['label']} already owns the resident pin",
                    status=self.status(),
                )
            if self._current is None or not self._current.loaded:
                raise RuntimeError("no loaded resident model to pin")
            self._resident_pin = self._pin_payload(self._current, pin_id, label)
            await self._publish_status()
            return dict(self._resident_pin)

    async def unpin(self, pin_id: str | None = None) -> bool:
        async with self._lock:
            if self._resident_pin is None:
                return False
            if pin_id is not None and self._resident_pin.get("id") != pin_id:
                raise PinOwnershipConflict(
                    f"resident pin is owned by {self._resident_pin['label']}",
                    status=self.status(),
                )
            self._resident_pin = None
            await self._publish_status()
            return True

    async def release_pin(
        self,
        pin_id: str,
        *,
        unload: bool = False,
        idle_guard: Callable[[], str | None] | None = None,
    ) -> bool:
        """Release an owned pin and optionally unload its resident atomically."""
        async with self._lock:
            self._check_idle_guard(idle_guard)
            if self._active_uses:
                raise self._usage_conflict("enable LLM API serving")
            if self._resident_pin is None:
                return False
            if self._resident_pin.get("id") != pin_id:
                raise PinOwnershipConflict(
                    f"resident pin is owned by {self._resident_pin['label']}",
                    status=self.status(),
                )
            old_pin = dict(self._resident_pin)
            self._resident_pin = None
            try:
                if unload:
                    await self._free_all_locked(publish_status=False)
            except BaseException:
                self._resident_pin = old_pin
                await self._publish_status()
                raise
            await self._publish_status()
            return True

    async def ensure_pinned(
        self,
        backend: GpuBackend,
        pin_id: str,
        label: str,
        *,
        idle_guard: Callable[[], str | None] | None = None,
    ) -> dict[str, str]:
        """Atomically load/switch a backend and commit its resident pin.

        If the target load fails, the prior resident and pin are restored before
        the error escapes. ``idle_guard`` is evaluated under the arbiter lock so
        a worker cannot win the check-to-handoff race.
        """
        async with self._lock:
            self._check_idle_guard(idle_guard)
            if self._active_uses:
                raise self._usage_conflict("change launch settings")
            if self._exclusive_lanes:
                raise self._lane_conflict("enable LLM API serving")
            old_pin = dict(self._resident_pin) if self._resident_pin is not None else None
            if old_pin is not None and old_pin.get("id") != pin_id:
                raise PinOwnershipConflict(
                    f"{old_pin['label']} already owns the resident pin",
                    status=self.status(),
                )
            old_current = self._current
            if old_current is backend and backend.loaded:
                self._resident_pin = self._pin_payload(backend, pin_id, label)
                await self._publish_status()
                return dict(self._resident_pin)

            self._resident_pin = None
            try:
                await self._ensure_locked(backend, publish_status=False)
                self._resident_pin = self._pin_payload(backend, pin_id, label)
                await self._publish_status()
                return dict(self._resident_pin)
            except BaseException:  # rollback must also run for cancellation
                self._resident_pin = None
                if self._current is not None and self._current is not old_current:
                    try:
                        await self._unload_current(allow_keep_warm=False)
                    except BaseException:  # noqa: BLE001 - preserve original failure
                        logger.exception("event=arbiter.pin_handoff.target_cleanup_failed")
                        self._current = None
                elif (
                    backend is not old_current
                    and (backend.loaded or backend.warm)
                ):
                    try:
                        await backend.unload()
                    except BaseException:  # noqa: BLE001 - preserve original failure
                        logger.exception("event=arbiter.pin_handoff.target_cleanup_failed")
                    if backend in self._warm_backends:
                        self._warm_backends.remove(backend)
                if old_current is not None:
                    try:
                        await self._ensure_locked(old_current, publish_status=False)
                    except BaseException:  # noqa: BLE001 - preserve original failure
                        logger.exception("event=arbiter.pin_handoff.rollback_failed")
                        old_pin = None
                self._resident_pin = old_pin
                await self._publish_status()
                raise

    async def reconfigure(
        self,
        apply: Callable[[], None],
        *,
        family: object | None = None,
        idle_guard: Callable[[], str | None] | None = None,
    ) -> bool:
        """Apply launch configuration while model ownership is serialized.

        A matching resident is fully unloaded before ``apply`` runs. The return
        value reports an unload, not a reload.
        """
        async with self._lock:
            self._check_idle_guard(idle_guard)
            cur = self._current
            matches = cur is not None and (
                family is None or cur.descriptor.family is family
            )
            if matches and self._resident_pin is not None:
                raise self._pin_conflict("change launch settings")
            unloaded = False
            if matches:
                await self._unload_current(allow_keep_warm=False)
                unloaded = True
            try:
                apply()
            finally:
                if unloaded:
                    await self._publish_status()
            return unloaded

    async def record_profile(self, backend: GpuBackend) -> None:
        await self._record_profile(backend)

    async def activate_lane(
        self,
        lane_id: str,
        label: str,
        *,
        exclusive: bool = False,
        unload_resident: bool = False,
        idle_guard: Callable[[], str | None] | None = None,
    ) -> GpuBackend | None:
        """Register a non-arbiter GPU consumer so the status/topbar reflect it.

        Exclusive lanes are a controlled handoff: under the same lock they check
        the worker guard and pin, unload the resident, then reserve the lane.
        """
        async with self._lock:
            if (
                self._lanes.get(lane_id) == label
                and (not exclusive or lane_id in self._exclusive_lanes)
            ):
                return None
            if self._exclusive_lanes and lane_id not in self._exclusive_lanes:
                raise self._lane_conflict(f"activate {label}")
            if exclusive:
                previous = self._current
                self._check_idle_guard(idle_guard)
                if self._active_uses:
                    raise self._usage_conflict(f"activate {label}")
                other_lanes = [name for key, name in self._lanes.items() if key != lane_id]
                if other_lanes:
                    raise GpuLaneConflict(
                        f"cannot activate {label}; another GPU lane is active: "
                        f"{', '.join(other_lanes)}",
                        status=self.status(),
                    )
                if self._resident_pin is not None:
                    raise self._pin_conflict(f"activate {label}")
                if self._current is not None or self._warm_backends:
                    if not unload_resident:
                        raise GpuLaneConflict(
                            f"cannot activate {label} while a model is resident",
                            status=self.status(),
                        )
                    await self._free_all_locked(publish_status=False)
                self._exclusive_lanes.add(lane_id)
            else:
                previous = None
            self._lanes[lane_id] = label
            await self._publish_status()
            return previous

    async def deactivate_lane(self, lane_id: str) -> None:
        async with self._lock:
            removed = self._lanes.pop(lane_id, None) is not None
            self._exclusive_lanes.discard(lane_id)
            if removed:
                await self._publish_status()

    async def rollback_lane(
        self,
        lane_id: str,
        previous: GpuBackend | None,
    ) -> None:
        """Abort an exclusive handoff and restore its prior resident atomically."""
        async with self._lock:
            self._lanes.pop(lane_id, None)
            self._exclusive_lanes.discard(lane_id)
            try:
                if previous is not None:
                    await self._ensure_locked(previous, publish_status=False)
            finally:
                await self._publish_status()

    @asynccontextmanager
    async def gpu_lane(self, lane_id: str, label: str):
        """Scope a short-lived GPU lane (TTS/transcribe) so it is always released,
        even if the work raises."""
        await self.activate_lane(lane_id, label)
        try:
            yield
        finally:
            await self.deactivate_lane(lane_id)

    async def _ensure_locked(
        self, backend: GpuBackend, *, publish_status: bool = True
    ) -> None:
        if self._active_uses:
            raise self._usage_conflict(f"load {backend.descriptor.name}")
        if self._exclusive_lanes:
            raise self._lane_conflict(f"load {backend.descriptor.name}")
        if self._current is backend and backend.loaded:
            return
        if self._resident_pin is not None and self._current is not None and self._current is not backend:
            message = (
                f"{self._resident_pin['label']} is keeping "
                f"{self._current.descriptor.name} in VRAM"
            )
            await self._bus.publish(Event(
                EventType.ARBITER_NOTE,
                reason="resident_pinned",
                message=f"{message}. Turn it off before loading {backend.descriptor.name}.",
                model_id=self._current.descriptor.id,
                model=self._current.descriptor.name,
                family=self._current.descriptor.family.value,
                target_model_id=backend.descriptor.id,
                target_model=backend.descriptor.name,
                target_family=backend.descriptor.family.value,
            ))
            raise ResidentPinConflict(message, status=self.status())
        if self._current is not None and self._current is not backend:
            await self._bus.publish(Event(
                EventType.ARBITER_NOTE,
                reason="swap",
                message=(
                    f"Swapping models: unloading {self._current.descriptor.name} "
                    f"to free VRAM for {backend.descriptor.name}."
                ),
                model_id=backend.descriptor.id,
                model=backend.descriptor.name,
                family=backend.descriptor.family.value,
                unload_model_id=self._current.descriptor.id,
                unload_model=self._current.descriptor.name,
            ))
            await self._unload_current(allow_keep_warm=True, incoming=backend)
        if not backend.loaded:
            await self._guard_budget(backend)
            warm_resume = backend.warm
            load_started = asyncio.get_running_loop().time()
            await self._bus.publish(Event(
                EventType.MODEL_LOADING,
                resident=backend.resident_key,
                model=backend.descriptor.name,
                family=backend.descriptor.family.value,
                warm_resume=warm_resume,
            ))
            await backend.load()
            await self._record_profile(backend)
            if backend in self._warm_backends:
                self._warm_backends.remove(backend)
            await self._bus.publish(Event(
                EventType.MODEL_LOADED,
                resident=backend.resident_key,
                model=backend.descriptor.name,
                family=backend.descriptor.family.value,
                load_report=backend.load_report,
                warm_resume=warm_resume,
                duration_s=round(asyncio.get_running_loop().time() - load_started, 3),
            ))
        self._current = backend
        if publish_status:
            await self._publish_status()

    async def _free_all_locked(self, *, publish_status: bool = True) -> None:
        if self._current is not None:
            await self._unload_current(allow_keep_warm=False)
        for backend in list(self._warm_backends):
            await self._unload_warm(backend)
        if publish_status:
            await self._publish_status()

    def _pin_payload(
        self, backend: GpuBackend, pin_id: str, label: str
    ) -> dict[str, str]:
        return {
            "id": pin_id,
            "label": label,
            "resident": backend.resident_key,
            "model_id": backend.descriptor.id,
            "model": backend.descriptor.name,
            "family": backend.descriptor.family.value,
        }

    def _pin_conflict(self, action: str) -> ResidentPinConflict:
        assert self._resident_pin is not None
        return ResidentPinConflict(
            f"cannot {action}; {self._resident_pin['label']} is keeping "
            f"{self._resident_pin.get('model', 'the current model')} in VRAM",
            status=self.status(),
        )

    def _lane_conflict(self, action: str) -> GpuLaneConflict:
        labels = ", ".join(
            self._lanes[lane_id]
            for lane_id in self._exclusive_lanes
            if lane_id in self._lanes
        )
        return GpuLaneConflict(
            f"cannot {action} while an exclusive GPU lane is active: {labels}",
            status=self.status(),
        )

    def _usage_conflict(self, action: str) -> GpuBusyConflict:
        owners = ", ".join(self._active_uses)
        return GpuBusyConflict(
            f"cannot {action}; GPU work is still running ({owners})",
            status=self.status(),
        )

    def _check_idle_guard(
        self, idle_guard: Callable[[], str | None] | None
    ) -> None:
        if idle_guard is None:
            return
        detail = idle_guard()
        if detail:
            raise GpuBusyConflict(detail, status=self.status())

    async def _unload_current(
        self, *, allow_keep_warm: bool = False, incoming: GpuBackend | None = None
    ) -> None:
        cur = self._current
        assert cur is not None
        keep_warm, reason = self._keep_warm_decision(
            cur, allow_keep_warm=allow_keep_warm, incoming=incoming
        )
        unload_started = asyncio.get_running_loop().time()
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADING,
            resident=cur.resident_key,
            model=cur.descriptor.name,
            keep_warm=keep_warm,
            reason=reason,
        ))
        if keep_warm and await cur.park():
            if cur not in self._warm_backends:
                self._warm_backends.append(cur)
            await self._bus.publish(Event(
                EventType.MODEL_UNLOADED,
                resident=cur.resident_key,
                model=cur.descriptor.name,
                kept_warm=True,
                reason=reason,
                duration_s=round(asyncio.get_running_loop().time() - unload_started, 3),
            ))
            self._current = None
            return

        await cur.unload()
        if cur in self._warm_backends:
            self._warm_backends.remove(cur)
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADED,
            resident=cur.resident_key,
            model=cur.descriptor.name,
            kept_warm=False,
            reason=reason,
            duration_s=round(asyncio.get_running_loop().time() - unload_started, 3),
        ))
        self._current = None

    async def _unload_warm(self, backend: GpuBackend) -> None:
        unload_started = asyncio.get_running_loop().time()
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADING,
            resident=backend.resident_key,
            model=backend.descriptor.name,
            keep_warm=False,
            warm=True,
        ))
        await backend.unload()
        if backend in self._warm_backends:
            self._warm_backends.remove(backend)
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADED,
            resident=backend.resident_key,
            model=backend.descriptor.name,
            kept_warm=False,
            warm=True,
            duration_s=round(asyncio.get_running_loop().time() - unload_started, 3),
        ))

    def _keep_warm_decision(
        self, backend: GpuBackend, *, allow_keep_warm: bool, incoming: GpuBackend | None = None
    ) -> tuple[bool, str]:
        from ..config import settings  # noqa: PLC0415
        from ..util import sysmon  # noqa: PLC0415

        if not allow_keep_warm:
            return False, "forced unload"
        if not settings.keep_warm_models:
            return False, "keep-warm disabled"
        if settings.keep_warm_max_models <= 0:
            return False, "keep-warm max is zero"
        if len(self._warm_backends) >= settings.keep_warm_max_models and backend not in self._warm_backends:
            return False, "keep-warm pool is full"
        if not backend.can_keep_warm:
            return False, "backend does not support keep-warm"
        if settings.stub_mode:
            return True, "stub keep-warm"

        # During a swap the parked model and the incoming load must coexist in
        # RAM, so reserve the incoming model's share before agreeing to park.
        incoming_need_gb = 0.0
        if incoming is not None and not incoming.warm:
            i = incoming.descriptor
            incoming_need_gb = sysmon.estimate_ram_need_gb(i.family, i.size_bytes, i.quant, i.id)

        d = backend.descriptor
        return sysmon.can_keep_warm(
            d.family, d.size_bytes, d.quant, d.id, incoming_need_gb=incoming_need_gb
        )

    async def _record_profile(self, backend: GpuBackend) -> None:
        """Learn this model's measured RAM/VRAM from its load report.

        Best-effort: a telemetry/DB hiccup must never break a successful load.
        The load starts from a clean baseline (the previous model is already
        unloaded), so end-minus-start RSS is the model's own footprint."""
        from ..config import settings  # noqa: PLC0415

        if settings.stub_mode or not settings.learn_memory_profiles:
            return
        ram_gb, vram_gb = _measured_from_report(backend.load_report)
        if ram_gb is None and vram_gb is None:
            return
        d = backend.descriptor
        try:
            from ..db.session import session_scope  # noqa: PLC0415
            from ..services import model_profile_service as mps  # noqa: PLC0415
            from ..util import sysmon  # noqa: PLC0415

            async with session_scope() as s:
                await mps.record(
                    s, model_id=d.id, family=d.family.value, quant=d.quant,
                    ram_gb=ram_gb, vram_gb=vram_gb,
                )
            sysmon.set_learned_profile(d.id, ram_gb=ram_gb, vram_gb=vram_gb)
        except Exception:  # noqa: BLE001 - telemetry must not break a load
            pass

    async def _guard_budget(self, backend: GpuBackend) -> None:
        """Refuse a load that would risk the pagefile (raises MemoryError, which
        the worker turns into a clear job error instead of an OOM hang).

        Warm-parked models are RAM we control: before refusing, evict them one
        by one (the backend being loaded last, since dropping it forfeits its
        warm resume) and re-measure. Only refuse once the pool is empty. Before
        raising, publish a structured note so the UI can show *why* it refused."""
        from ..config import settings  # noqa: PLC0415
        from ..util import sysmon  # noqa: PLC0415

        if settings.stub_mode:
            return
        d = backend.descriptor
        decision = sysmon.ram_budget(d.family, d.size_bytes, d.quant, d.id)
        victims = [b for b in self._warm_backends if b is not backend]
        if backend in self._warm_backends:
            victims.append(backend)
        for victim in victims:
            if decision["ok"]:
                return
            await self._bus.publish(Event(
                EventType.ARBITER_NOTE,
                reason="warm_evict",
                message=(
                    f"Evicting warm {victim.descriptor.name} from RAM to make room "
                    f"for {d.name} (needs ~{decision['need_gb']:.1f} GB, only "
                    f"{decision['available_gb']:.1f} GB free)."
                ),
                model_id=victim.descriptor.id,
                model=victim.descriptor.name,
                family=victim.descriptor.family.value,
                target_model_id=d.id,
                target_model=d.name,
                target_family=d.family.value,
                predicted_gb=decision["need_gb"],
                available_gb=decision["available_gb"],
            ))
            await self._unload_warm(victim)
            decision = sysmon.ram_budget(d.family, d.size_bytes, d.quant, d.id)
        if decision["ok"]:
            return
        await self._bus.publish(Event(
            EventType.ARBITER_NOTE,
            reason="ram_budget",
            message=(
                f"Refused {d.name}: needs ~{decision['need_gb']:.1f} GB + "
                f"{decision['headroom_gb']:.0f} GB headroom, only "
                f"{decision['available_gb']:.1f} GB RAM free."
            ),
            model_id=d.id,
            model=d.name,
            family=d.family.value,
            predicted_gb=decision["need_gb"],
            available_gb=decision["available_gb"],
        ))
        raise MemoryError(sysmon.ram_budget_message(decision))

    def status(self) -> dict:
        cur = self._current
        return {
            "resident": cur.resident_key if cur else None,
            "model_id": cur.descriptor.id if cur else None,
            "model": cur.descriptor.name if cur else None,
            "family": cur.descriptor.family.value if cur else None,
            "warm": [
                {
                    "resident": b.resident_key,
                    "model_id": b.descriptor.id,
                    "model": b.descriptor.name,
                    "family": b.descriptor.family.value,
                }
                for b in self._warm_backends
            ],
            "lanes": [
                {"id": lane_id, "label": label}
                for lane_id, label in self._lanes.items()
            ],
            "pin": dict(self._resident_pin) if self._resident_pin is not None else None,
        }

    async def _publish_status(self) -> None:
        await self._bus.publish(Event(EventType.GPU_STATUS, **self.status()))


def _measured_from_report(report: dict | None) -> tuple[float | None, float | None]:
    """Extract (ram_gb, vram_gb) measurements from an image backend load report.

    RAM = the process RSS the load added (end - start); VRAM = the process
    reserved VRAM after the load (falls back to the device-used delta). Small or
    negative deltas (noise / gc) are dropped. LLM reports are ``None`` (the model
    is a separate process), so they contribute nothing here."""
    memory = (report or {}).get("memory") or {}
    start = memory.get("start") or {}
    end = memory.get("end") or {}

    def rss(snap: dict) -> float | None:
        return (snap.get("ram") or {}).get("process_rss_gb")

    ram_gb: float | None = None
    if rss(start) is not None and rss(end) is not None:
        delta = rss(end) - rss(start)
        if delta >= 0.3:
            ram_gb = round(delta, 2)

    vram_gb: float | None = None
    reserved = (
        (end.get("accelerator_process") or {}).get("reserved_gb")
        or (end.get("cuda_process") or {}).get("reserved_gb")
    )
    if reserved:
        vram_gb = round(reserved, 2)
    else:
        used_start = (start.get("vram") or {}).get("used_gb")
        used_end = (end.get("vram") or {}).get("used_gb")
        if used_start is not None and used_end is not None and used_end - used_start > 0.3:
            vram_gb = round(used_end - used_start, 2)

    return ram_gb, vram_gb
