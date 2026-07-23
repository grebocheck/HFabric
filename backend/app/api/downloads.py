"""Model download manager API.

Curated, hardware-aware starter-model catalog + a background downloader. Mirrors
the llama.cpp runtime manager: GET returns catalog + disk budget + live status,
POST starts a background download the UI polls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..backends.registry import ModelRegistry
from ..services import model_download_service as downloads
from .contracts import (
    ERROR_RESPONSES,
    DownloadStateOut,
    DownloadStatusOut,
    HfRepoFilesOut,
    HfSearchOut,
)
from .deps import get_registry

logger = logging.getLogger("hfabric")

router = APIRouter(
    prefix="/api/downloads",
    tags=["downloads"],
    responses=ERROR_RESPONSES,
)


async def _run_then_rescan(keys: list[str], registry: ModelRegistry) -> None:
    """Run the blocking download, then rescan so the new files show up without a
    restart. Registry publication is atomic, while the disk walk stays off-loop."""
    try:
        await asyncio.to_thread(downloads.run_blocking, keys)
    finally:
        try:
            await registry.scan_async()
        except Exception:  # noqa: BLE001 - a rescan hiccup must not crash the task
            logger.warning("event=downloads.rescan.failed", exc_info=True)


async def _run_custom_then_rescan(items: list[dict[str, Any]], registry: ModelRegistry) -> None:
    try:
        await asyncio.to_thread(downloads.run_blocking_custom, items)
    finally:
        try:
            await registry.scan_async()
        except Exception:  # noqa: BLE001 - a rescan hiccup must not crash the task
            logger.warning("event=downloads.rescan.failed", exc_info=True)


@router.get("", response_model=DownloadStateOut)
async def get_downloads(refresh: bool = False) -> DownloadStateOut:
    return await asyncio.to_thread(downloads.state, refresh=refresh)


@router.get("/hf/files", response_model=HfRepoFilesOut)
async def list_hf_repo_files(repo: str) -> HfRepoFilesOut:
    """List a HuggingFace repo's files and sizes so the UI can browse and pick."""
    try:
        files = await asyncio.to_thread(downloads.hf_list_files, repo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"repo": repo.strip(), "files": files}


@router.get("/hf/search", response_model=HfSearchOut)
async def search_hf_models(
    q: str = "",
    limit: int = 24,
    sort: str = "downloads",
    filter_tags: str | None = Query(default=None, alias="filter"),
) -> HfSearchOut:
    """Search Hugging Face model repos for the catalog-style Models tab."""
    filters = [tag.strip() for tag in (filter_tags or "").split(",") if tag.strip()]
    try:
        return await asyncio.to_thread(
            downloads.hf_search_models,
            q,
            limit=limit,
            sort=sort,
            filter_tags=filters,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/start", response_model=DownloadStatusOut)
async def start_downloads(
    body: dict[str, Any] | None = None,
    registry: ModelRegistry = Depends(get_registry),
) -> DownloadStatusOut:
    """Begin a background download of the selected catalog keys."""
    if downloads.is_downloading():
        raise HTTPException(409, "a model download is already running")
    keys = list((body or {}).get("keys") or [])
    if not keys:
        raise HTTPException(422, "keys is required")
    try:
        await asyncio.to_thread(downloads.start, keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if downloads.is_downloading():
        # Fire-and-forget: the heavy download runs in a thread; the UI polls status.
        # When it finishes we rescan so the catalog reflects disk without a restart.
        asyncio.create_task(_run_then_rescan(keys, registry))
        await asyncio.sleep(0)  # let the task start before we report
    return downloads.get_status()


@router.post("/custom", response_model=DownloadStatusOut)
async def start_custom_downloads(
    body: dict[str, Any] | None = None,
    registry: ModelRegistry = Depends(get_registry),
) -> DownloadStatusOut:
    """Download user-supplied models from any source (HuggingFace repo+file or a
    direct URL) into the right kind folder, then rescan."""
    if downloads.is_downloading():
        raise HTTPException(409, "a model download is already running")
    items = list((body or {}).get("items") or [])
    if not items:
        raise HTTPException(422, "items is required")
    try:
        await asyncio.to_thread(downloads.start_custom, items)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if downloads.is_downloading():
        asyncio.create_task(_run_custom_then_rescan(items, registry))
        await asyncio.sleep(0)
    return downloads.get_status()
