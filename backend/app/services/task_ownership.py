"""Keep native work and its cleanup alive when an HTTP waiter disappears."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import logging
from typing import Any

logger = logging.getLogger("hfabric")
_TASKS: set[asyncio.Task] = set()


async def run_owned[T](work: Coroutine[Any, Any, T], *, name: str, timeout: float) -> T:
    """Timeout the waiter while the owner retains its locks/files/GPU lane.

    Python cannot interrupt a running native inference thread. The owner's
    finally blocks must therefore run after inference, even after a timeout.
    """
    task = asyncio.create_task(work, name=name)
    _TASKS.add(task)
    abandoned = False

    def finished(done: asyncio.Task) -> None:
        _TASKS.discard(done)
        if not done.cancelled():
            error = done.exception()
            if error is not None and abandoned:
                logger.error("event=background.failed task=%s", name, exc_info=error)

    task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        abandoned = True
        raise
