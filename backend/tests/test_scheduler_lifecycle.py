"""Lifecycle and failure-path coverage for the serialized queue worker."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete

from app.backends.base import (
    GenerationCancelled,
    ImageBackend,
    LLMBackend,
    ModelDescriptor,
    UpscaleBackend,
    VideoBackend,
)
from app.core.arbiter import ArbiterConflict
from app.core.enums import JobStatus, JobType, ModelFamily
from app.core.events import Event
from app.core.job_results import JobSnapshot
from app.core.scheduler import Worker
from app.db.models import Job
from app.db.session import init_db, session_scope


class _Bus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


class _Arbiter:
    def __init__(self) -> None:
        self.current = None
        self.resident_pin = None
        self.exclusive_lane_active = False
        self.acquire_error: BaseException | None = None
        self.release_error: BaseException | None = None
        self.release_calls: list[str] = []
        self.force_shutdown_calls = 0

    async def acquire(self, backend, job_id: str) -> None:
        if self.acquire_error is not None:
            raise self.acquire_error
        await backend.load()
        self.current = backend

    async def release(self, job_id: str) -> bool:
        self.release_calls.append(job_id)
        if self.release_error is not None:
            raise self.release_error
        return True

    async def record_profile(self, _backend) -> None:
        return None

    async def force_shutdown(self) -> None:
        self.force_shutdown_calls += 1


class _Lifecycle:
    def __init__(
        self,
        model_id: str,
        family: ModelFamily,
        result: Any,
        *,
        execute_error: BaseException | None = None,
        cleanup: dict[str, Any] | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        super().__init__(
            ModelDescriptor(
                id=model_id,
                name=model_id,
                family=family,
                path=Path(f"{model_id}.bin"),
                size_bytes=1,
            )
        )
        self.result = result
        self.execute_error = execute_error
        self.cleanup = cleanup
        self.cleanup_error = cleanup_error
        self.on_execute = None
        self.stop_requests = 0
        self.after_job_failed: list[bool] = []

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    def request_stop(self) -> None:
        self.stop_requests += 1

    async def _execute(self, progress=None, on_token=None):
        if self.on_execute is not None:
            self.on_execute()
        if progress is not None:
            await progress(0.25, "working")
            await progress(1.0, None)
        if on_token is not None:
            await on_token("token")
        if self.execute_error is not None:
            raise self.execute_error
        return self.result

    async def after_job(
        self,
        _job_id: str,
        _params: dict[str, Any],
        *,
        failed: bool = False,
    ) -> dict[str, Any] | None:
        self.after_job_failed.append(failed)
        if self.cleanup_error is not None:
            raise self.cleanup_error
        return self.cleanup


class _Image(_Lifecycle, ImageBackend):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            "image",
            ModelFamily.SDXL,
            [{"path": "image.png"}],
            **kwargs,
        )

    async def generate(self, _params, progress):
        return await self._execute(progress=progress)


class _Upscale(_Lifecycle, UpscaleBackend):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            "upscale",
            ModelFamily.UPSCALER,
            [{"path": "upscaled.png"}],
            **kwargs,
        )

    async def upscale(self, _params, progress):
        return await self._execute(progress=progress)


class _Video(_Lifecycle, VideoBackend):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            "video",
            ModelFamily.LTX_VIDEO,
            {"path": "video.mp4"},
            **kwargs,
        )

    async def generate(self, _params, progress):
        return await self._execute(progress=progress)


class _Llm(_Lifecycle, LLMBackend):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            "llm",
            ModelFamily.GGUF,
            {"text": "answer", "tool_calls": [{"name": "search"}]},
            **kwargs,
        )

    async def complete(self, _params, on_token=None):
        return await self._execute(on_token=on_token)


class _Registry:
    def __init__(self, backend) -> None:
        self.backend = backend

    def get_backend(self, _model_id: str):
        return self.backend


class _Results:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enrich_image_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return {**params, "_enriched": True}

    async def finish_image(self, snap, records) -> None:
        self.calls.append(("finish_image", snap.id, records))

    async def finish_video(self, snap, record) -> None:
        self.calls.append(("finish_video", snap.id, record))

    async def finish_llm(self, snap, text, tool_calls) -> None:
        self.calls.append(("finish_llm", snap.id, text, tool_calls))

    async def mark_cancelled(self, snap, text=None) -> None:
        self.calls.append(("cancelled", snap.id, text))

    async def fail(self, snap, error: str) -> None:
        self.calls.append(("failed", snap.id, error))


def _backend(kind: str, **kwargs):
    return {
        "image": _Image,
        "upscale": _Upscale,
        "video": _Video,
        "llm": _Llm,
    }[kind](**kwargs)


def _worker(kind: str, **backend_kwargs):
    backend = _backend(kind, **backend_kwargs)
    bus = _Bus()
    arbiter = _Arbiter()
    worker = Worker(bus, arbiter, _Registry(backend))
    results = _Results()
    worker._results = results
    return worker, backend, bus, arbiter, results


@pytest.mark.parametrize(
    ("kind", "job_type", "finish_call"),
    [
        ("image", JobType.IMAGE, "finish_image"),
        ("upscale", JobType.UPSCALE, "finish_image"),
        ("video", JobType.VIDEO, "finish_video"),
        ("llm", JobType.LLM, "finish_llm"),
    ],
)
async def test_run_completes_every_backend_kind(kind, job_type, finish_call):
    worker, backend, bus, arbiter, results = _worker(
        kind,
        cleanup={"released_mb": 10},
    )
    snap = JobSnapshot(
        "job",
        job_type,
        backend.descriptor.id,
        {"_request_id": "request"},
        1.2345,
    )

    await worker._run(snap)

    assert results.calls[0][0] == finish_call
    assert backend.after_job_failed == [False]
    assert arbiter.release_calls == ["job"]
    assert worker.running_job_id is None
    event_types = [event["type"] for event in bus.events]
    assert "job.started" in event_types
    assert "job.cleanup" in event_types
    if job_type is JobType.LLM:
        assert "llm.token" in event_types
    else:
        assert "job.progress" in event_types


@pytest.mark.parametrize(
    ("kind", "job_type"),
    [
        ("image", JobType.IMAGE),
        ("upscale", JobType.UPSCALE),
        ("video", JobType.VIDEO),
        ("llm", JobType.LLM),
    ],
)
async def test_run_honours_cancellation_after_backend_returns(kind, job_type):
    worker, backend, _bus, _arbiter, results = _worker(kind)
    backend.on_execute = lambda: setattr(worker, "_cancel_current", True)

    await worker._run(
        JobSnapshot("job", job_type, backend.descriptor.id, {}),
    )

    assert results.calls[0][0] == "cancelled"
    assert backend.after_job_failed == [True]
    assert worker._cancel_current is False


@pytest.mark.parametrize(
    ("error", "expected_call"),
    [
        (GenerationCancelled(), "cancelled"),
        (RuntimeError("generation failed"), "failed"),
    ],
)
async def test_run_normalizes_generation_failures(error, expected_call):
    worker, backend, _bus, _arbiter, results = _worker(
        "image",
        execute_error=error,
    )

    await worker._run(
        JobSnapshot("job", JobType.IMAGE, backend.descriptor.id, {}),
    )

    assert results.calls[0][0] == expected_call
    assert backend.after_job_failed == [True]


async def test_arbiter_conflict_requeues_without_backend_cleanup():
    worker, backend, bus, arbiter, results = _worker("image")
    arbiter.acquire_error = ArbiterConflict("busy")
    requeued: list[str] = []

    async def requeue(snap: JobSnapshot) -> None:
        requeued.append(snap.id)

    worker._requeue = requeue
    await worker._run(
        JobSnapshot(
            "job",
            JobType.IMAGE,
            backend.descriptor.id,
            {"_request_id": "request"},
        )
    )

    assert requeued == ["job"]
    assert results.calls == []
    assert arbiter.release_calls == []
    assert bus.events[-1]["reason"] == "gpu_state_conflict"


async def test_cleanup_and_lease_release_failures_do_not_escape():
    worker, backend, bus, arbiter, results = _worker(
        "image",
        cleanup_error=RuntimeError("cleanup failed"),
    )
    arbiter.release_error = RuntimeError("release failed")

    await worker._run(
        JobSnapshot("job", JobType.IMAGE, backend.descriptor.id, {}),
    )

    assert results.calls[0][0] == "finish_image"
    cleanup = next(event for event in bus.events if event["type"] == "job.cleanup")
    assert "cleanup failed" in cleanup["error"]
    assert worker.running_job_id is None


async def test_worker_controls_are_idempotent_and_interrupt_current_backend():
    worker, backend, _bus, arbiter, _results = _worker("image")
    gate = asyncio.Event()

    async def loop() -> None:
        await gate.wait()

    worker._loop = loop
    worker.start()
    task = worker._task
    worker.start()
    assert worker._task is task

    worker._current_job_id = "job"
    arbiter.current = None
    assert worker.cancel_running("job") is True
    arbiter.current = backend
    assert worker.cancel_running("other") is False
    assert worker.cancel_running("job") is True
    worker.notify()
    worker.request_stop()
    assert backend.stop_requests == 2
    assert worker._wakeup.is_set()

    gate.set()
    assert task is not None
    await task
    assert await worker.stop(cleanup_arbiter=True)
    assert worker._task is None
    assert arbiter.force_shutdown_calls == 1


async def test_run_requeues_if_voice_activates_after_selection(monkeypatch):
    from app.services.voice_engine import realtime

    monkeypatch.setattr(realtime, "session_active", lambda: True)
    worker, backend, _bus, arbiter, results = _worker("image")
    requeued: list[str] = []

    async def requeue(snap: JobSnapshot) -> None:
        requeued.append(snap.id)

    worker._requeue = requeue
    await worker._run(
        JobSnapshot("job", JobType.IMAGE, backend.descriptor.id, {}),
    )

    assert requeued == ["job"]
    assert results.calls == []
    assert arbiter.release_calls == []
    assert worker.running_job_id is None


async def test_stop_consumes_completed_task_failure():
    worker, _backend, _bus, _arbiter, _results = _worker("image")

    async def fail() -> None:
        raise RuntimeError("loop failed")

    worker._task = asyncio.create_task(fail())
    await asyncio.sleep(0)

    assert await worker.stop(cleanup_arbiter=False)
    assert worker._task is None


@pytest.fixture
async def scheduler_jobs_db():
    await init_db()
    async with session_scope() as session:
        await session.execute(delete(Job))
    yield
    async with session_scope() as session:
        await session.execute(delete(Job))


async def test_requeue_only_resets_matching_running_job(scheduler_jobs_db):
    worker, _backend, _bus, _arbiter, _results = _worker("image")
    async with session_scope() as session:
        running = Job(
            type=JobType.IMAGE,
            model_id="image",
            status=JobStatus.RUNNING,
            progress=0.75,
            params={},
        )
        queued = Job(
            type=JobType.IMAGE,
            model_id="queued",
            status=JobStatus.QUEUED,
            progress=0.25,
            params={},
        )
        session.add_all([running, queued])
        await session.flush()
        running_id = running.id
        queued_id = queued.id

    await worker._requeue(
        JobSnapshot(running_id, JobType.IMAGE, "image", {}),
    )
    await worker._requeue(
        JobSnapshot(queued_id, JobType.IMAGE, "queued", {}),
    )
    await worker._requeue(
        JobSnapshot("missing", JobType.IMAGE, "missing", {}),
    )

    async with session_scope() as session:
        reset = await session.get(Job, running_id)
        untouched = await session.get(Job, queued_id)
        assert reset is not None
        assert reset.status == JobStatus.QUEUED
        assert reset.progress == 0.0
        assert reset.started_at is None
        assert untouched is not None
        assert untouched.progress == 0.25


async def test_pick_next_parks_voice_once_then_resumes(
    monkeypatch,
    scheduler_jobs_db,
):
    from app.services.voice_engine import realtime

    active = True
    monkeypatch.setattr(realtime, "session_active", lambda: active)
    worker, _backend, bus, _arbiter, _results = _worker("image")

    assert await worker._pick_next() is None
    assert await worker._pick_next() is None
    assert [event["reason"] for event in bus.events] == ["voice_lane"]

    active = False
    assert await worker._pick_next() is None
    assert [event["reason"] for event in bus.events] == ["voice_lane", "idle"]
