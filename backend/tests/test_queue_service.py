from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.core.enums import JobStatus, JobType
from app.db.models import Job
from app.db.session import init_db, session_scope
from app.schemas import JobCreate
from app.services import queue_service


async def test_reorder_is_atomic_and_does_not_change_running_or_terminal_jobs(queue_db):
    async with session_scope() as session:
        jobs = [await queue_service.create_job(session, JobCreate(
            type=JobType.IMAGE, model_id="image", params={"prompt": str(index)},
        )) for index in range(4)]
        ids = [job.id for job in jobs]
        jobs[0].status = JobStatus.RUNNING
        jobs[1].status = JobStatus.DONE
    async with session_scope() as session:
        assert await queue_service.reorder_jobs(session, list(reversed(ids))) == 2
    async with session_scope() as session:
        rows = {job.id: job for job in (await session.execute(select(Job))).scalars()}
        assert rows[ids[0]].priority == rows[ids[1]].priority == 0
        assert rows[ids[3]].priority > rows[ids[2]].priority
        assert rows[ids[0]].status == JobStatus.RUNNING
        assert rows[ids[1]].status == JobStatus.DONE


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

        cancelled, changed = await queue_service.cancel_job(s, low.id)
        assert cancelled.status == JobStatus.CANCELLED
        assert changed
        assert (await queue_service.cancel_job(s, low.id))[1] is False
        assert await queue_service.cancel_job(s, "missing") == (None, False)

        changed = await queue_service.set_priority(s, high.id, 9)
        assert changed.priority == 9
        changed.status = JobStatus.RUNNING
        assert (await queue_service.set_priority(s, high.id, 1)).priority == 9

        assert await queue_service.clear_finished(s) == 1

    async with session_scope() as s:
        rows = await queue_service.list_jobs(s)
        assert [job.id for job in rows] == [high.id]
        assert rows[0].status == JobStatus.RUNNING
