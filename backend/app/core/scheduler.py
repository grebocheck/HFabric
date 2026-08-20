"""Single-worker orchestration for serialized accelerator jobs.

Queue policy lives in :mod:`scheduler_planning`; result persistence and LLM
tool-call handling live in :mod:`job_results`. This module coordinates those
components with backend lifecycle and GPU ownership.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging

from sqlalchemy import func, select

from ..backends.base import (
    GenerationCancelled,
    ImageBackend,
    LLMBackend,
    UpscaleBackend,
    VideoBackend,
)
from ..backends.registry import ModelRegistry
from ..db.models import Job
from ..db.session import session_scope
from .arbiter import ArbiterConflict, GpuArbiter
from .enums import EventType, JobStatus, JobType
from .events import Event, EventBus
from .job_results import (
    JobResultService,
    JobSnapshot,
    friendly_job_error,
    split_llm_result,
)
from .scheduler_planning import plan_queue, select_in_tier

logger = logging.getLogger("hfabric")


class Worker:
    """Own queue admission, accelerator leases, and backend execution."""

    def __init__(
        self,
        bus: EventBus,
        arbiter: GpuArbiter,
        registry: ModelRegistry,
    ) -> None:
        self._bus = bus
        self._arbiter = arbiter
        self._registry = registry
        self._wakeup = asyncio.Event()
        self._results = JobResultService(bus, registry, self.notify)
        self._task: asyncio.Task | None = None
        self._running = False
        self._current_job_id: str | None = None
        self._cancel_current = False
        self._voice_parked = False
        self._resident_pin_parked = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="hfabric-worker")

    def request_stop(self) -> None:
        """Stop taking jobs and best-effort interrupt the in-flight backend."""
        self._running = False
        self._cancel_current = self._current_job_id is not None
        current = self._arbiter.current
        if current is not None and self._current_job_id is not None:
            current.request_stop()
        self._wakeup.set()

    async def stop(
        self,
        *,
        timeout: float = 15.0,
        cancel_timeout: float = 2.0,
        cleanup_arbiter: bool = True,
    ) -> bool:
        """Stop within a fixed bound even if a backend ignores cancellation."""
        self.request_stop()
        completed = True
        task = self._task
        if task is not None and task is not asyncio.current_task():
            done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
            if not done:
                completed = False
                logger.warning(
                    "event=shutdown.worker.timeout timeout_seconds=%.1f job_id=%s",
                    timeout,
                    self._current_job_id,
                )
                task.cancel()
                done, _ = await asyncio.wait(
                    {task},
                    timeout=max(0.0, cancel_timeout),
                )
                if not done:
                    logger.error(
                        "event=shutdown.worker.cancel_timeout timeout_seconds=%.1f job_id=%s",
                        cancel_timeout,
                        self._current_job_id,
                    )
            if task.done():
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    logger.exception("event=shutdown.worker.failed")
                self._task = None
        if cleanup_arbiter:
            await self._arbiter.force_shutdown()
        return completed

    def notify(self) -> None:
        """Wake the worker after queue state changes."""
        self._wakeup.set()

    @property
    def running_job_id(self) -> str | None:
        return self._current_job_id

    def cancel_running(self, job_id: str) -> bool:
        """Request cancellation when ``job_id`` is the active job."""
        if self._current_job_id != job_id:
            return False
        self._cancel_current = True
        current = self._arbiter.current
        if current is not None:
            current.request_stop()
        return True

    async def _loop(self) -> None:
        await self._requeue_orphans()
        while self._running:
            snapshot = await self._pick_next()
            if snapshot is None:
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=2.0)
                except TimeoutError:
                    pass
                continue
            await self._run(snapshot)

    async def _requeue_orphans(self) -> None:
        async with session_scope() as session:
            rows = (await session.execute(select(Job).where(Job.status == JobStatus.RUNNING))).scalars().all()
            for job in rows:
                job.status = JobStatus.QUEUED
                job.progress = 0.0

    async def _requeue(self, snap: JobSnapshot) -> None:
        async with session_scope() as session:
            job = await session.get(Job, snap.id)
            if job and job.status == JobStatus.RUNNING:
                job.status = JobStatus.QUEUED
                job.progress = 0.0
                job.started_at = None

    async def _pick_next(self) -> JobSnapshot | None:
        from ..services.voice_engine import realtime  # noqa: PLC0415

        if realtime.session_active() or self._arbiter.exclusive_lane_active:
            if not self._voice_parked:
                self._voice_parked = True
                await self._bus.publish(
                    Event(
                        EventType.ARBITER_NOTE,
                        reason="voice_lane",
                        message=("Live voice session holds the GPU — image/LLM jobs are parked."),
                    )
                )
            return None

        if self._voice_parked:
            self._voice_parked = False
            await self._bus.publish(
                Event(
                    EventType.ARBITER_NOTE,
                    reason="idle",
                    message="Voice session ended — resuming the queue.",
                )
            )

        async with session_scope() as session:
            pin = self._arbiter.resident_pin
            filters = [Job.status == JobStatus.QUEUED]
            if pin is not None:
                filters.append(Job.model_id == pin.get("model_id"))

            max_priority = select(func.max(Job.priority)).where(*filters).correlate(None).scalar_subquery()
            rows = (
                (
                    await session.execute(
                        select(Job)
                        .where(*filters, Job.priority == max_priority)
                        .order_by(Job.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                any_queued = False
                if pin is not None:
                    any_queued = (
                        await session.scalar(select(Job.id).where(Job.status == JobStatus.QUEUED).limit(1))
                    ) is not None
                if pin is not None and any_queued:
                    if not self._resident_pin_parked:
                        self._resident_pin_parked = True
                        await self._bus.publish(
                            Event(
                                EventType.ARBITER_NOTE,
                                reason="resident_pinned",
                                message=(
                                    f"{pin.get('label', 'Resident pin')} is keeping "
                                    f"{pin.get('model', pin.get('model_id'))} in VRAM — "
                                    "queued jobs for other models will wait."
                                ),
                                model_id=pin.get("model_id"),
                                model=pin.get("model"),
                                family=pin.get("family"),
                            )
                        )
                else:
                    self._resident_pin_parked = False
                return None
            if pin is not None:
                self._resident_pin_parked = False
            elif self._resident_pin_parked:
                self._resident_pin_parked = False
                await self._bus.publish(
                    Event(
                        EventType.ARBITER_NOTE,
                        reason="idle",
                        message="Resident pin released — resuming the queue.",
                    )
                )

            current = self._arbiter.current
            chosen = select_in_tier(
                rows,
                current.descriptor.id if current is not None else None,
                (current.descriptor.job_type.value if current is not None else None),
            )

            chosen.status = JobStatus.RUNNING
            chosen.started_at = datetime.now(UTC)
            created_at = chosen.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            queue_age_s = max(
                0.0,
                (chosen.started_at - created_at).total_seconds(),
            )
            return JobSnapshot(
                chosen.id,
                JobType(chosen.type),
                chosen.model_id,
                dict(chosen.params),
                queue_age_s,
            )

    async def _run(self, snap: JobSnapshot) -> None:
        self._current_job_id = snap.id
        self._cancel_current = False
        backend = None
        lease_acquired = False
        failed = False
        from ..services.voice_engine import realtime  # noqa: PLC0415

        if realtime.session_active():
            await self._requeue(snap)
            self._current_job_id = None
            return

        try:
            backend = self._registry.get_backend(snap.model_id)
            await self._arbiter.acquire(backend, snap.id)
            lease_acquired = True
            if self._cancel_current:
                raise GenerationCancelled()
            await self._bus.publish(
                Event(
                    EventType.JOB_STARTED,
                    job_id=snap.id,
                    job_type=snap.type.value,
                    queue_age_s=round(snap.queue_age_s, 3),
                    request_id=snap.params.get("_request_id"),
                )
            )

            last_emit = 0.0

            async def progress(frac: float, note: str | None) -> None:
                nonlocal last_emit
                now = asyncio.get_running_loop().time()
                if now - last_emit >= 0.1 or frac >= 1.0:
                    last_emit = now
                    await self._bus.publish(
                        Event(
                            EventType.JOB_PROGRESS,
                            job_id=snap.id,
                            progress=frac,
                            note=note,
                            request_id=snap.params.get("_request_id"),
                        )
                    )

            if snap.type is JobType.IMAGE:
                assert isinstance(backend, ImageBackend)
                records = await backend.generate(
                    self._results.enrich_image_params(snap.params),
                    progress,
                )
                if self._cancel_current:
                    failed = True
                    await self._results.discard_images(records)
                    await self._results.mark_cancelled(snap)
                else:
                    await self._results.finish_image(snap, records)
            elif snap.type is JobType.UPSCALE:
                assert isinstance(backend, UpscaleBackend)
                records = await backend.upscale(snap.params, progress)
                if self._cancel_current:
                    failed = True
                    await self._results.discard_images(records)
                    await self._results.mark_cancelled(snap)
                else:
                    await self._results.finish_image(snap, records)
            elif snap.type is JobType.VIDEO:
                assert isinstance(backend, VideoBackend)
                record = await backend.generate(snap.params, progress)
                if self._cancel_current:
                    failed = True
                    await self._results.mark_cancelled(snap)
                else:
                    await self._results.finish_video(snap, record)
            else:
                assert isinstance(backend, LLMBackend)

                async def on_token(token: str) -> None:
                    await self._bus.publish(
                        Event(
                            EventType.LLM_TOKEN,
                            job_id=snap.id,
                            token=token,
                            request_id=snap.params.get("_request_id"),
                        )
                    )

                result = await backend.complete(snap.params, on_token)
                text, native_tool_calls = split_llm_result(result)
                if self._cancel_current:
                    failed = True
                    await self._results.mark_cancelled(snap, text)
                else:
                    await self._results.finish_llm(
                        snap,
                        text,
                        native_tool_calls,
                    )
        except ArbiterConflict as exc:
            backend = None
            await self._requeue(snap)
            await self._bus.publish(
                Event(
                    EventType.ARBITER_NOTE,
                    reason=exc.code,
                    message=f"GPU ownership changed; re-queued job {snap.id}.",
                    job_id=snap.id,
                    request_id=snap.params.get("_request_id"),
                )
            )
        except GenerationCancelled:
            failed = True
            await self._results.mark_cancelled(snap)
        except Exception as exc:  # noqa: BLE001
            failed = True
            error = friendly_job_error(exc)
            logger.exception(
                "event=job.failed job_id=%s job_type=%s model_id=%s user_error=%s raw_error=%r",
                snap.id,
                snap.type.value,
                snap.model_id,
                error,
                exc,
            )
            await self._results.fail(snap, error)
        finally:
            if backend is not None:
                try:
                    cleanup = await backend.after_job(
                        snap.id,
                        snap.params,
                        failed=failed,
                    )
                    if cleanup:
                        await self._bus.publish(
                            Event(
                                "job.cleanup",
                                job_id=snap.id,
                                request_id=snap.params.get("_request_id"),
                                **cleanup,
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    error = friendly_job_error(exc)
                    logger.exception(
                        "event=job.cleanup.failed job_id=%s user_error=%s raw_error=%r",
                        snap.id,
                        error,
                        exc,
                    )
                    await self._bus.publish(
                        Event(
                            "job.cleanup",
                            job_id=snap.id,
                            error=error,
                            request_id=snap.params.get("_request_id"),
                        )
                    )
            if lease_acquired:
                try:
                    await self._arbiter.release(snap.id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "event=job.lease.release_failed job_id=%s",
                        snap.id,
                    )
            self._current_job_id = None
            self._cancel_current = False


__all__ = [
    "JobSnapshot",
    "Worker",
    "friendly_job_error",
    "plan_queue",
    "select_in_tier",
]
