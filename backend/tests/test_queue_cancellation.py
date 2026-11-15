from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.jobs import cancel_job
from app.core.enums import JobStatus, JobType
from app.db.models import Job
from app.db.session import init_db, session_scope
from app.services import queue_service


@pytest.mark.parametrize("status", [JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED])
async def test_cancel_terminal_job_keeps_its_status_and_emits_nothing(status):
    await init_db()
    async with session_scope() as session:
        session.add(Job(id="terminal", type=JobType.IMAGE, model_id="model", status=status))
    bus = SimpleNamespace(emit=Mock())
    worker = SimpleNamespace(cancel_running=Mock())
    async with session_scope() as session:
        result = await cancel_job("terminal", session, bus, worker)
    assert result.status == status
    bus.emit.assert_not_called()
    worker.cancel_running.assert_not_called()


async def test_repeated_cancel_emits_one_durable_transition():
    await init_db()
    async with session_scope() as session:
        session.add(Job(id="queued", type=JobType.IMAGE, model_id="model", status=JobStatus.QUEUED))
    bus = SimpleNamespace(emit=Mock())
    worker = SimpleNamespace(cancel_running=Mock())
    for _ in range(2):
        async with session_scope() as session:
            result = await cancel_job("queued", session, bus, worker)
            assert result.status == JobStatus.CANCELLED
            assert result.finished_at is not None
    assert bus.emit.call_count == 1


async def test_concurrent_cancellations_have_one_winner():
    await init_db()
    async with session_scope() as session:
        session.add(Job(id="queued", type=JobType.IMAGE, model_id="model", status=JobStatus.QUEUED))

    async def cancel():
        async with session_scope() as session:
            job, changed = await queue_service.cancel_job(session, "queued")
            return job.status, changed

    results = await asyncio.gather(cancel(), cancel())
    assert all(status == JobStatus.CANCELLED for status, _ in results)
    assert sum(changed for _, changed in results) == 1


async def test_cancel_cannot_overwrite_a_running_job():
    await init_db()
    async with session_scope() as session:
        session.add(Job(id="running", type=JobType.IMAGE, model_id="model", status=JobStatus.RUNNING))
    async with session_scope() as session:
        job, changed = await queue_service.cancel_job(session, "running")
        assert job.status == JobStatus.RUNNING
        assert not changed
