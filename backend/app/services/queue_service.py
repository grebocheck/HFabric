"""Queue CRUD. Pure DB operations; routers handle event emission + worker wakeup."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import JobStatus, JobType
from ..db.models import Job
from ..schemas import JobCreate
from ..util.request_context import current_request_id


async def create_job(session: AsyncSession, payload: JobCreate) -> Job:
    params = dict(payload.params)
    request_id = current_request_id()
    if request_id:
        params["_request_id"] = request_id
    job = Job(
        type=payload.type,
        model_id=payload.model_id,
        params=params,
        priority=payload.priority,
        status=JobStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    return job


async def list_jobs(
    session: AsyncSession,
    *,
    status: JobStatus | None = None,
    type: JobType | None = None,
    limit: int = 200,
) -> list[Job]:
    stmt = select(Job)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if type is not None:
        stmt = stmt.where(Job.type == type)
    stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def cancel_job(session: AsyncSession, job_id: str) -> Job | None:
    job = await session.get(Job, job_id)
    if job and job.status == JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
    return job


async def set_priority(session: AsyncSession, job_id: str, priority: int) -> Job | None:
    job = await session.get(Job, job_id)
    if job and job.status == JobStatus.QUEUED:
        job.priority = priority
    return job


async def clear_finished(session: AsyncSession) -> int:
    rows = (await session.execute(
        select(Job).where(Job.status.in_([JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED]))
    )).scalars().all()
    for job in rows:
        await session.delete(job)
    return len(rows)
