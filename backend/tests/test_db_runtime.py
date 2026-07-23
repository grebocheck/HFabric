from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.enums import JobStatus, JobType
from app.db import session as db_session
from app.db.models import Job, Message


async def test_sqlite_runtime_enables_wal_foreign_keys_and_bounded_busy_timeout(
    isolated_runtime,
):
    await db_session.init_db()

    async with db_session.engine.connect() as connection:
        journal_mode = (
            await connection.exec_driver_sql("PRAGMA journal_mode")
        ).scalar_one()
        foreign_keys = (
            await connection.exec_driver_sql("PRAGMA foreign_keys")
        ).scalar_one()
        busy_timeout = (
            await connection.exec_driver_sql("PRAGMA busy_timeout")
        ).scalar_one()
        synchronous = (
            await connection.exec_driver_sql("PRAGMA synchronous")
        ).scalar_one()

    assert str(journal_mode).casefold() == "wal"
    assert foreign_keys == 1
    assert busy_timeout == db_session.SQLITE_BUSY_TIMEOUT_MS
    assert synchronous == 1  # NORMAL

    with pytest.raises(IntegrityError):
        async with db_session.session_scope() as session:
            session.add(
                Message(
                    id="orphan-message",
                    conversation_id="missing-conversation",
                    role="user",
                    content="must fail",
                )
            )


async def test_concurrent_worker_and_api_style_writes_wait_instead_of_locking(
    isolated_runtime,
):
    await db_session.init_db()
    first_has_write_lock = asyncio.Event()
    release_first = asyncio.Event()

    async def worker_write() -> None:
        async with db_session.session_scope() as session:
            session.add(
                Job(
                    id="worker-write",
                    type=JobType.IMAGE,
                    status=JobStatus.QUEUED,
                    model_id="stub-sdxl",
                    params={},
                )
            )
            await session.flush()
            first_has_write_lock.set()
            await release_first.wait()

    async def api_write() -> None:
        await first_has_write_lock.wait()
        async with db_session.session_scope() as session:
            session.add(
                Job(
                    id="api-write",
                    type=JobType.LLM,
                    status=JobStatus.QUEUED,
                    model_id="stub-llm",
                    params={},
                )
            )
            await session.flush()

    worker_task = asyncio.create_task(worker_write())
    await first_has_write_lock.wait()
    api_task = asyncio.create_task(api_write())
    await asyncio.sleep(0.1)
    assert not api_task.done()

    release_first.set()
    await asyncio.gather(worker_task, api_task)

    async with db_session.session_scope() as session:
        count = (
            await session.execute(
                select(func.count(Job.id)).where(
                    Job.id.in_(["worker-write", "api-write"])
                )
            )
        ).scalar_one()
    assert count == 2


async def test_opt_in_write_replay_retries_only_transient_locks(
    isolated_runtime,
    caplog,
):
    await db_session.init_db()
    calls = 0

    async def transient_then_ok(_session):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError(
                "INSERT",
                {},
                sqlite3.OperationalError("database is locked"),
            )
        return "ok"

    with caplog.at_level("WARNING", logger="hfabric"):
        assert await db_session.run_write(transient_then_ok) == "ok"
    assert calls == 2
    assert "event=db.write.retry" in caplog.text

    calls = 0

    async def permanent_error(_session):
        nonlocal calls
        calls += 1
        raise OperationalError(
            "INSERT",
            {},
            sqlite3.OperationalError("no such table"),
        )

    with pytest.raises(OperationalError, match="no such table"):
        await db_session.run_write(permanent_error)
    assert calls == 1
