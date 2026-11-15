from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.arbiter import GpuArbiter
from app.core.enums import JobStatus, JobType
from app.core.events import EventBus
from app.core.job_results import JobResultService, JobSnapshot
from app.core.scheduler import Worker
from app.db.models import Conversation, Job, Message
from app.db.session import init_db, session_scope


def locked() -> OperationalError:
    return OperationalError("SELECT", {}, Exception("database is locked"))


@pytest.mark.parametrize("stage", ["bootstrap", "selection"])
async def test_worker_recovers_after_a_transient_db_fault(stage):
    worker = Worker(EventBus(), GpuArbiter(EventBus()), None)
    recovered = asyncio.Event()
    attempts = 0

    async def pick():
        nonlocal attempts
        attempts += 1
        if stage == "selection" and attempts == 1:
            raise locked()
        recovered.set()
        return None

    worker._requeue_orphans = AsyncMock(side_effect=[locked(), None] if stage == "bootstrap" else None)
    worker._pick_next = pick
    worker.start()
    try:
        await asyncio.wait_for(recovered.wait(), 3)
        assert worker.status()["ready"]
        assert worker.status()["error"] is None
        assert worker._task is not None and not worker._task.done()
    finally:
        await worker.stop(cleanup_arbiter=False)


async def test_persistence_retry_does_not_repeat_generation():
    worker = Worker(EventBus(), GpuArbiter(EventBus()), None)
    worker._requeue_orphans = AsyncMock()
    snap = JobSnapshot("job", JobType.IMAGE, "model", {})
    worker._run = AsyncMock(side_effect=locked())
    worker._results.fail = AsyncMock(side_effect=[locked(), None])
    recovered = asyncio.Event()
    selected = False

    async def pick():
        nonlocal selected
        if not selected:
            selected = True
            return snap
        recovered.set()
        return None

    worker._pick_next = pick
    worker.start()
    try:
        await asyncio.wait_for(recovered.wait(), 3)
        assert worker._run.await_count == 1
        assert worker._results.fail.await_count == 2
        assert worker.status()["ready"]
    finally:
        await worker.stop(cleanup_arbiter=False)


@pytest.mark.parametrize("status", [JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED])
async def test_recovery_never_overwrites_a_committed_terminal_result(status):
    await init_db()
    async with session_scope() as session:
        session.add(Job(id="terminal", type=JobType.IMAGE, model_id="model", status=status, result={"image_ids": ["saved"]}))
    bus = EventBus()
    results = JobResultService(bus, None, lambda: None)
    async with bus.subscribe() as events:
        await results.fail(JobSnapshot("terminal", JobType.IMAGE, "model", {}), "transient failure")
        assert events.empty()
    async with session_scope() as session:
        job = await session.get(Job, "terminal")
        assert job.status == status
        assert job.result == {"image_ids": ["saved"]}


async def test_health_reports_a_degraded_worker(app_client, monkeypatch):
    from app.main import app

    monkeypatch.setattr(app.state.worker, "status", lambda: {"state": "degraded", "ready": False, "error": "database unavailable"})
    health = (await app_client.get("/api/health")).json()
    assert health["status"] == "degraded"
    assert not health["worker"]["ready"]


async def test_tool_child_job_remains_linked_to_its_assistant_message():
    await init_db()
    async with session_scope() as session:
        session.add(Conversation(id="conversation"))
        await session.flush()
        session.add(Message(id="assistant", conversation_id="conversation", role="assistant", content="", job_id="parent"))
        session.add(Job(id="parent", type=JobType.LLM, model_id="llm", status=JobStatus.RUNNING))
    results = JobResultService(EventBus(), None, lambda: None)
    snap = JobSnapshot("parent", JobType.LLM, "llm", {
        "assistant_message_id": "assistant", "conversation_id": "conversation",
        "image_tool": {"model_id": "image", "assistant_message_id": "assistant", "conversation_id": "conversation"},
    })
    await results.finish_llm(snap, '{"tool":"generate_image","prompt":"a fox"}')
    async with session_scope() as session:
        parent = await session.get(Job, "parent")
        assistant = await session.get(Message, "assistant")
        child_id = parent.result["child_job_id"]
        assert assistant.job_id == child_id
        assert (await session.get(Job, child_id)).status == JobStatus.QUEUED
