"""Model download manager API (P18.4).

Curated, hardware-aware starter-model catalog + a background downloader. Mirrors
the llama.cpp runtime manager: GET returns catalog + disk budget + live status,
POST starts a background download the UI polls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..backends.registry import ModelRegistry
from ..services import model_download_service as downloads
from .deps import get_registry

logger = logging.getLogger("hfabric")

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


async def _run_then_rescan(keys: list[str], registry: ModelRegistry) -> None:
    """Run the blocking download, then rescan so the new files show up without a
    restart (P24.8). The rescan runs on the loop thread (no ``await`` inside
    ``scan``), so it can't interleave with a concurrent request's descriptor read."""
    try:
        await asyncio.to_thread(downloads.run_blocking, keys)
    finally:
        try:
            registry.scan()
        except Exception:  # noqa: BLE001 - a rescan hiccup must not crash the task
            logger.warning("event=downloads.rescan.failed", exc_info=True)


async def _run_custom_then_rescan(items: list[dict[str, Any]], registry: ModelRegistry) -> None:
    try:
        await asyncio.to_thread(downloads.run_blocking_custom, items)
    finally:
        try:
            registry.scan()
        except Exception:  # noqa: BLE001 - a rescan hiccup must not crash the task
            logger.warning("event=downloads.rescan.failed", exc_info=True)


@router.get("")
async def get_downloads(refresh: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(downloads.state, refresh=refresh)


@router.post("/start")
async def start_downloads(
    body: dict[str, Any] | None = None,
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, Any]:
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
        # When it finishes we rescan so the catalog reflects disk without a restart.
        asyncio.create_task(_run_then_rescan(keys, registry))
        await asyncio.sleep(0)  # let the task start before we report
    return downloads.get_status()


@router.post("/custom")
async def start_custom_downloads(
    body: dict[str, Any] | None = None,
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Download user-supplied models from any source (HuggingFace repo+file or a
    direct URL) into the right kind folder, then rescan (P25.3)."""
    if downloads.is_downloading():
        raise HTTPException(409, "a model download is already running")
    items = list((body or {}).get("items") or [])
    if not items:
        raise HTTPException(422, "items is required")
    try:
        downloads.start_custom(items)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if downloads.is_downloading():
        asyncio.create_task(_run_custom_then_rescan(items, registry))
        await asyncio.sleep(0)
    return downloads.get_status()
