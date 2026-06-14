"""Model download manager API (P18.4).

Curated, hardware-aware starter-model catalog + a background downloader. Mirrors
the llama.cpp runtime manager: GET returns catalog + disk budget + live status,
POST starts a background download the UI polls.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from ..services import model_download_service as downloads

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


@router.get("")
async def get_downloads(refresh: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(downloads.state, refresh=refresh)


@router.post("/start")
async def start_downloads(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Begin a background download of the selected catalog keys."""
    if downloads.is_downloading():
        raise HTTPException(409, "a model download is already running")
    keys = list((body or {}).get("keys") or [])
    if not keys:
        raise HTTPException(422, "keys is required")
    try:
        downloads.start(keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if downloads.is_downloading():
        # Fire-and-forget: the heavy download runs in a thread; the UI polls status.
        asyncio.create_task(asyncio.to_thread(downloads.run_blocking, keys))
        await asyncio.sleep(0)  # let the task start before we report
    return downloads.get_status()
