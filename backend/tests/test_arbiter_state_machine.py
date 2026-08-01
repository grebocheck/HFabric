"""State-machine regression tests for GPU ownership and rollback semantics."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.backends.base import GpuBackend, ModelDescriptor
from app.config import settings
from app.core.arbiter import (
    ArbiterCleanupError,
    GpuArbiter,
    GpuBusyConflict,
    GpuLaneConflict,
    PinOwnershipConflict,
    ResidentPinConflict,
    _measured_from_report,
)
from app.core.enums import ModelFamily
from app.core.events import EventBus
from app.services import model_profile_service
from app.util import sysmon


class _Backend(GpuBackend):
    def __init__(
        self,
        model_id: str,
        *,
        keep_warm: bool = False,
        load_error: BaseException | None = None,
        load_before_error: bool = False,
        unload_error: BaseException | None = None,
        park_result: bool = False,
    ) -> None:
        super().__init__(
            ModelDescriptor(
                id=model_id,
                name=model_id,
                family=ModelFamily.GGUF,
                path=Path(f"{model_id}.gguf"),
                size_bytes=4,
            )
        )
        self.keep_warm = keep_warm
        self.load_error = load_error
        self.load_before_error = load_before_error
        self.unload_error = unload_error
        self.park_result = park_result
        self.stop_requests = 0

    @property
    def can_keep_warm(self) -> bool:
        return self.keep_warm

    async def load(self) -> None:
        if self.load_before_error:
            self._loaded = True
        if self.load_error is not None:
            raise self.load_error
        self._loaded = True
        self._warm = False

    async def unload(self) -> None:
        if self.unload_error is not None:
            raise self.unload_error
        self._loaded = False
        self._warm = False

    async def park(self) -> bool:
        if not self.park_result:
            return False
        self._loaded = False
        self._warm = True
        return True

    def request_stop(self) -> None:
        self.stop_requests += 1


async def test_execution_lease_blocks_competing_transitions():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")
    other = _Backend("other")

    await arbiter.acquire(resident, "job-1")
    await arbiter.acquire(resident, "job-1")

    with pytest.raises(GpuBusyConflict, match="job-1"):
        await arbiter.acquire(other, "job-2")
    with pytest.raises(GpuBusyConflict, match="job-1"):
        await arbiter.request_free()
    with pytest.raises(GpuBusyConflict, match="job-1"):
        await arbiter.ensure(other)

    assert await arbiter.release("unknown") is False
    assert await arbiter.release("job-1") is True
    await arbiter.ensure(other)
    assert arbiter.current is other


async def test_busy_paths_tracks_current_and_warm_residents():
    arbiter = GpuArbiter(EventBus())
    current = _Backend("current")
    warm = _Backend("warm")
    warm._warm = True
    arbiter._current = current
    arbiter._warm_backends.append(warm)

    assert arbiter.busy_paths() == {
        current.descriptor.path.resolve(),
        warm.descriptor.path.resolve(),
    }

    arbiter._current = None
    arbiter._warm_backends.clear()
    assert arbiter.busy_paths() == set()


async def test_free_and_pin_transitions_return_typed_conflicts():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")

    assert await arbiter.unpin() is False
    with pytest.raises(RuntimeError, match="no loaded resident"):
        await arbiter.pin_current("api", "LLM API")

    await arbiter.ensure(resident)
    original = await arbiter.pin_current("api", "LLM API")
    assert arbiter.resident_pin == original
    assert arbiter.resident_pin is not original
    await arbiter.pin_current("api", "Renamed API")

    with pytest.raises(PinOwnershipConflict, match="Renamed API"):
        await arbiter.pin_current("voice", "Voice")
    with pytest.raises(PinOwnershipConflict, match="Renamed API"):
        await arbiter.unpin("voice")
    with pytest.raises(ResidentPinConflict, match="Renamed API"):
        await arbiter.request_free()

    assert await arbiter.unpin("api") is True
    await arbiter.activate_lane("tts", "TTS")
    with pytest.raises(GpuLaneConflict, match="TTS"):
        await arbiter.free_all()
    await arbiter.deactivate_lane("tts")
    await arbiter.request_free()
    assert arbiter.current is None


async def test_release_pin_validates_owner_lease_and_restores_on_unload_failure():
    arbiter = GpuArbiter(EventBus())
    assert await arbiter.release_pin("api") is False

    resident = _Backend("resident", unload_error=RuntimeError("unload failed"))
    await arbiter.ensure(resident)
    await arbiter.pin_current("api", "LLM API")

    with pytest.raises(PinOwnershipConflict):
        await arbiter.release_pin("other")

    arbiter._active_uses["job"] = resident
    with pytest.raises(GpuBusyConflict, match="job"):
        await arbiter.release_pin("api")
    arbiter._active_uses.clear()

    with pytest.raises(RuntimeError, match="unload failed"):
        await arbiter.release_pin("api", unload=True)
    assert arbiter.resident_pin is not None
    assert arbiter.current is resident

    resident.unload_error = None
    assert await arbiter.release_pin("api", unload=True) is True
    assert arbiter.current is None


async def test_ensure_pinned_fast_path_guards_and_owner_conflicts():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")

    pin = await arbiter.ensure_pinned(resident, "api", "LLM API")
    assert await arbiter.ensure_pinned(resident, "api", "LLM API") == pin

    with pytest.raises(PinOwnershipConflict):
        await arbiter.ensure_pinned(_Backend("other"), "voice", "Voice")
    with pytest.raises(GpuBusyConflict, match="worker is active"):
        await arbiter.ensure_pinned(
            resident,
            "api",
            "LLM API",
            idle_guard=lambda: "worker is active",
        )

    arbiter._active_uses["job"] = resident
    with pytest.raises(GpuBusyConflict, match="job"):
        await arbiter.ensure_pinned(resident, "api", "LLM API")
    arbiter._active_uses.clear()

    await arbiter.unpin("api")
    await arbiter.free_all()
    await arbiter.activate_lane("voice", "Voice", exclusive=True)
    with pytest.raises(GpuLaneConflict, match="Voice"):
        await arbiter.ensure_pinned(resident, "api", "LLM API")


async def test_failed_pin_handoff_restores_previous_resident_and_pin():
    arbiter = GpuArbiter(EventBus())
    previous = _Backend("previous")
    broken = _Backend("broken", load_error=RuntimeError("load failed"))

    await arbiter.ensure_pinned(previous, "api", "LLM API")
    with pytest.raises(RuntimeError, match="load failed"):
        await arbiter.ensure_pinned(broken, "api", "LLM API")

    assert arbiter.current is previous
    assert previous.loaded
    assert arbiter.resident_pin is not None
    assert arbiter.resident_pin["model_id"] == "previous"


async def test_failed_pin_target_that_partially_loaded_is_cleaned_up():
    arbiter = GpuArbiter(EventBus())
    broken = _Backend(
        "broken",
        load_error=RuntimeError("load failed late"),
        load_before_error=True,
    )

    with pytest.raises(RuntimeError, match="load failed late"):
        await arbiter.ensure_pinned(broken, "api", "LLM API")

    assert not broken.loaded
    assert arbiter.current is None
    assert arbiter.resident_pin is None


async def test_failed_worker_load_that_partially_loaded_is_cleaned_up():
    arbiter = GpuArbiter(EventBus())
    broken = _Backend(
        "broken",
        load_error=RuntimeError("load failed late"),
        load_before_error=True,
    )

    with pytest.raises(RuntimeError, match="load failed late"):
        await arbiter.ensure(broken)

    assert not broken.loaded
    assert arbiter.current is None


async def test_exclusive_lane_rejects_competing_owners_and_can_roll_back():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")
    await arbiter.ensure(resident)

    with pytest.raises(GpuLaneConflict, match="model is resident"):
        await arbiter.activate_lane("voice", "Voice", exclusive=True)

    await arbiter.activate_lane("tts", "TTS")
    with pytest.raises(GpuLaneConflict, match="TTS"):
        await arbiter.activate_lane(
            "voice",
            "Voice",
            exclusive=True,
            unload_resident=True,
        )
    await arbiter.deactivate_lane("tts")

    previous = await arbiter.activate_lane(
        "voice",
        "Voice",
        exclusive=True,
        unload_resident=True,
    )
    assert previous is resident
    assert await arbiter.activate_lane("voice", "Voice", exclusive=True) is None
    with pytest.raises(GpuLaneConflict, match="Voice"):
        await arbiter.activate_lane("tts", "TTS")
    with pytest.raises(GpuLaneConflict, match="Voice"):
        await arbiter.pin_current("api", "LLM API")

    await arbiter.rollback_lane("voice", previous)
    assert arbiter.current is resident
    assert resident.loaded
    assert not arbiter.exclusive_lane_active


async def test_exclusive_lane_obeys_active_use_and_idle_guard():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")
    await arbiter.acquire(resident, "job")

    with pytest.raises(GpuBusyConflict, match="job"):
        await arbiter.activate_lane(
            "voice",
            "Voice",
            exclusive=True,
            unload_resident=True,
        )
    await arbiter.release("job")
    with pytest.raises(GpuBusyConflict, match="queue is active"):
        await arbiter.activate_lane(
            "voice",
            "Voice",
            exclusive=True,
            unload_resident=True,
            idle_guard=lambda: "queue is active",
        )


async def test_launch_settings_and_empty_lane_rollback_publish_consistent_state():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")
    applied: list[str] = []
    await arbiter.ensure(resident)

    assert await arbiter.reconfigure(
        lambda: applied.append("matching"),
        family=resident.descriptor.family,
    )
    assert arbiter.current is None

    assert not await arbiter.reconfigure(
        lambda: applied.append("non-matching"),
        family=ModelFamily.LTX_VIDEO,
    )
    await arbiter.rollback_lane("missing", None)
    assert applied == ["matching", "non-matching"]


async def test_force_shutdown_requests_stop_and_reports_all_cleanup_errors():
    arbiter = GpuArbiter(EventBus())
    current = _Backend("current", unload_error=RuntimeError("current failed"))
    warm = _Backend("warm", unload_error=RuntimeError("warm failed"))
    current._loaded = True
    warm._warm = True
    arbiter._current = current
    arbiter._warm_backends.append(warm)
    arbiter._active_uses["job"] = current
    arbiter._resident_pin = {"id": "api", "label": "API"}
    arbiter._lanes["voice"] = "Voice"
    arbiter._exclusive_lanes.add("voice")

    with pytest.raises(ArbiterCleanupError) as raised:
        await arbiter.force_shutdown()

    assert len(raised.value.errors) == 2
    assert "current failed" in str(raised.value)
    assert current.stop_requests == 1
    assert arbiter.current is None
    assert arbiter.resident_pin is None
    assert arbiter.status()["lanes"] == []
    assert arbiter._warm_backends == []


async def test_force_compatibility_flag_uses_terminal_cleanup():
    arbiter = GpuArbiter(EventBus())
    resident = _Backend("resident")
    await arbiter.ensure(resident)

    await arbiter.free_all(force=True)

    assert arbiter.current is None
    assert not resident.loaded


async def test_keep_warm_swap_parks_then_resumes_backend(monkeypatch):
    monkeypatch.setattr(settings, "keep_warm_models", True)
    monkeypatch.setattr(settings, "keep_warm_max_models", 1)
    monkeypatch.setattr(settings, "stub_mode", True)
    arbiter = GpuArbiter(EventBus())
    first = _Backend("first", keep_warm=True, park_result=True)
    second = _Backend("second")

    await arbiter.ensure(first)
    await arbiter.ensure(second)
    assert first.warm
    assert first in arbiter._warm_backends

    await arbiter.ensure(first)
    assert first.loaded
    assert first not in arbiter._warm_backends
    assert arbiter.current is first


@pytest.mark.parametrize(
    ("enabled", "maximum", "keep_warm", "expected"),
    [
        (False, 1, True, (False, "keep-warm disabled")),
        (True, 0, True, (False, "keep-warm max is zero")),
        (True, 1, False, (False, "backend does not support keep-warm")),
    ],
)
def test_keep_warm_policy_reasons(
    monkeypatch,
    enabled,
    maximum,
    keep_warm,
    expected,
):
    monkeypatch.setattr(settings, "keep_warm_models", enabled)
    monkeypatch.setattr(settings, "keep_warm_max_models", maximum)
    monkeypatch.setattr(settings, "stub_mode", True)
    arbiter = GpuArbiter(EventBus())

    assert (
        arbiter._keep_warm_decision(
            _Backend("model", keep_warm=keep_warm),
            allow_keep_warm=True,
        )
        == expected
    )


def test_real_keep_warm_policy_accounts_for_incoming_model(monkeypatch):
    monkeypatch.setattr(settings, "keep_warm_models", True)
    monkeypatch.setattr(settings, "keep_warm_max_models", 2)
    monkeypatch.setattr(settings, "stub_mode", False)
    arbiter = GpuArbiter(EventBus())
    warm = _Backend("warm", keep_warm=True)
    incoming = _Backend("incoming")
    seen: dict[str, float] = {}
    monkeypatch.setattr(sysmon, "estimate_ram_need_gb", lambda *_args: 3.25)

    def can_keep_warm(*_args, incoming_need_gb):
        seen["incoming_need_gb"] = incoming_need_gb
        return True, "fits"

    monkeypatch.setattr(sysmon, "can_keep_warm", can_keep_warm)

    assert arbiter._keep_warm_decision(
        warm,
        allow_keep_warm=True,
        incoming=incoming,
    ) == (True, "fits")
    assert seen == {"incoming_need_gb": 3.25}


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (None, (None, None)),
        (
            {
                "memory": {
                    "start": {
                        "ram": {"process_rss_gb": 1.0},
                        "vram": {"used_gb": 2.0},
                    },
                    "end": {
                        "ram": {"process_rss_gb": 1.2},
                        "vram": {"used_gb": 2.2},
                    },
                }
            },
            (None, None),
        ),
        (
            {
                "memory": {
                    "start": {
                        "ram": {"process_rss_gb": 1.0},
                        "vram": {"used_gb": 2.0},
                    },
                    "end": {
                        "ram": {"process_rss_gb": 2.234},
                        "vram": {"used_gb": 2.75},
                    },
                }
            },
            (1.23, 0.75),
        ),
        (
            {
                "memory": {
                    "start": {"ram": {"process_rss_gb": 1.0}},
                    "end": {
                        "ram": {"process_rss_gb": 1.5},
                        "accelerator_process": {"reserved_gb": 4.567},
                    },
                }
            },
            (0.5, 4.57),
        ),
        (
            {
                "memory": {
                    "start": {},
                    "end": {"cuda_process": {"reserved_gb": 2.345}},
                }
            },
            (None, 2.35),
        ),
    ],
)
def test_memory_measurement_extracts_only_meaningful_deltas(report, expected):
    assert _measured_from_report(report) == expected


async def test_profile_recording_is_best_effort(monkeypatch):
    backend = _Backend("measured")
    backend._load_report = {
        "memory": {
            "start": {"ram": {"process_rss_gb": 1.0}},
            "end": {
                "ram": {"process_rss_gb": 2.0},
                "accelerator_process": {"reserved_gb": 3.0},
            },
        }
    }
    monkeypatch.setattr(settings, "stub_mode", False)
    monkeypatch.setattr(settings, "learn_memory_profiles", True)
    recorded: list[dict] = []
    learned: list[tuple] = []

    @asynccontextmanager
    async def fake_scope():
        yield object()

    async def record(_session, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr("app.db.session.session_scope", fake_scope)
    monkeypatch.setattr(model_profile_service, "record", record)
    monkeypatch.setattr(
        sysmon,
        "set_learned_profile",
        lambda model_id, **values: learned.append((model_id, values)),
    )

    arbiter = GpuArbiter(EventBus())
    await arbiter.record_profile(backend)
    assert recorded == [
        {
            "model_id": "measured",
            "family": "gguf",
            "quant": None,
            "ram_gb": 1.0,
            "vram_gb": 3.0,
        }
    ]
    assert learned == [("measured", {"ram_gb": 1.0, "vram_gb": 3.0})]

    monkeypatch.setattr(
        model_profile_service,
        "record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    await arbiter.record_profile(backend)
