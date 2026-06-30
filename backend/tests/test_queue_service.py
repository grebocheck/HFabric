from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.core.enums import JobStatus, JobType
from app.db.models import Job
from app.db.session import init_db, session_scope
from app.schemas import JobCreate
from app.services import queue_service


@pytest.fixture
async def queue_db():
    await init_db()
    async with session_scope() as s:
        await s.execute(delete(Job))
    yield
    async with session_scope() as s:
        await s.execute(delete(Job))


async def test_queue_crud_filters_priority_cancel_and_clear(queue_db):
    async with session_scope() as s:
        low = await queue_service.create_job(
            s,
            JobCreate(type=JobType.IMAGE, model_id="image", params={"prompt": "p"}, priority=0),
        )
        high = await queue_service.create_job(
            s,
            JobCreate(type=JobType.LLM, model_id="llm", params={"prompt": "q"}, priority=5),
        )

    async with session_scope() as s:
        assert [job.id for job in await queue_service.list_jobs(s)] == [high.id, low.id]
        assert [job.id for job in await queue_service.list_jobs(s, type=JobType.IMAGE)] == [low.id]
        assert {job.id for job in await queue_service.list_jobs(s, status=JobStatus.QUEUED)} == {high.id, low.id}

        assert (await queue_service.get_job(s, high.id)).model_id == "llm"
        assert await queue_service.get_job(s, "missing") is None

        cancelled = await queue_service.cancel_job(s, low.id)
        assert cancelled.status == JobStatus.CANCELLED
        assert await queue_service.cancel_job(s, "missing") is None

        changed = await queue_service.set_priority(s, high.id, 9)
        assert changed.priority == 9
        changed.status = JobStatus.RUNNING
        assert (await queue_service.set_priority(s, high.id, 1)).priority == 9

        assert await queue_service.clear_finished(s) == 1

    async with session_scope() as s:
        rows = await queue_service.list_jobs(s)
        assert [job.id for job in rows] == [high.id]
        assert rows[0].status == JobStatus.RUNNING
