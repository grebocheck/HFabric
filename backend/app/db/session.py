"""Async SQLite engine + session helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings

SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_WRITE_ATTEMPTS = 3

logger = logging.getLogger("hfabric")


def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Apply the same concurrency/integrity policy to every pooled connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.fetchone()
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def configure_engine(candidate: AsyncEngine) -> AsyncEngine:
    """Attach SQLite runtime policy once, including to test-swapped engines."""
    sync_engine = candidate.sync_engine
    if not sync_engine.url.drivername.startswith("sqlite"):
        return candidate
    if not getattr(sync_engine, "_hfabric_sqlite_policy", False):
        event.listen(sync_engine, "connect", _set_sqlite_pragmas)
        sync_engine._hfabric_sqlite_policy = True
    return candidate


def create_db_engine(url: str) -> AsyncEngine:
    return configure_engine(create_async_engine(url, future=True))


engine = create_db_engine(settings.db_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"


def _alembic_config():
    from alembic.config import Config  # noqa: PLC0415

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    return cfg


def _upgrade_head(connection) -> None:
    from alembic import command  # noqa: PLC0415

    cfg = _alembic_config()
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def init_db() -> None:
    settings.ensure_dirs()
    configure_engine(engine)
    async with engine.begin() as conn:
        await run_migrations(conn)


async def run_migrations(conn: AsyncConnection) -> None:
    await conn.run_sync(_upgrade_head)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session for use in services and the worker loop."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


def _is_transient_sqlite_lock(exc: OperationalError) -> bool:
    message = str(exc).casefold()
    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database is busy" in message
    )


async def run_write[T](
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    attempts: int = SQLITE_WRITE_ATTEMPTS,
) -> T:
    """Replay a short idempotent write transaction only on transient lock errors.

    Callers opt in explicitly because replaying arbitrary mutations is unsafe.
    The normal API/worker path benefits from SQLite's bounded busy timeout even
    when it does not need retries.
    """
    if attempts < 1:
        raise ValueError("write attempts must be positive")
    for attempt in range(1, attempts + 1):
        try:
            async with session_scope() as session:
                return await operation(session)
        except OperationalError as exc:
            if not _is_transient_sqlite_lock(exc) or attempt == attempts:
                raise
            delay = 0.05 * (2 ** (attempt - 1))
            logger.warning(
                "event=db.write.retry attempt=%d max_attempts=%d delay_seconds=%.2f",
                attempt,
                attempts,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")
