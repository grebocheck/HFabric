"""Cancellation-safe helpers for filesystem artifacts built in worker threads."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any


async def build_temporary_artifact[T](
    path: Path,
    builder: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a blocking builder off-loop and avoid leaking its temporary file.

    Cancelling ``asyncio.to_thread`` does not stop the underlying OS/PIL/ZIP
    operation. Shield the worker and schedule cleanup after it really finishes,
    instead of unlinking a file that another thread is still writing.
    """
    operation = partial(builder, path, *args, **kwargs)
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        worker.add_done_callback(partial(_cleanup_finished_worker, path))
        raise
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _cleanup_finished_worker(path: Path, worker: asyncio.Task[Any]) -> None:
    try:
        worker.result()
    except BaseException:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
