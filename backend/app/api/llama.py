"""Manage the llama.cpp runtime: install, update, activate, roll back (P20.10)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from ..services import llama_manager

router = APIRouter(prefix="/api/llama", tags=["llama"])


@router.get("")
async def get_llama_state() -> dict[str, Any]:
    return llama_manager.state()


@router.post("/install")
async def install_llama(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a background download of the latest (or a specific) llama.cpp build."""
    if llama_manager.is_installing():
        raise HTTPException(409, "a llama.cpp install is already running")
    body = body or {}
    tag = body.get("tag")
    variant = body.get("variant")
    # Fire-and-forget: the heavy download runs in a thread; the UI polls status.
    asyncio.create_task(asyncio.to_thread(llama_manager.install_blocking, tag, variant))
    await asyncio.sleep(0)  # let the task flip status to "running" before we report
    return llama_manager.get_status()


@router.post("/check")
async def check_llama_update(body: dict[str, Any] | None = None) -> dict[str, Any]:
    variant = (body or {}).get("variant")
    try:
        return await asyncio.to_thread(llama_manager.check_update, variant)
    except Exception as exc:  # noqa: BLE001 - surface GitHub/network errors plainly
        raise HTTPException(502, f"could not check for updates: {exc}") from exc


@router.post("/activate")
async def activate_llama(body: dict[str, Any]) -> dict[str, Any]:
    version_id = body.get("id")
    if not version_id:
        raise HTTPException(422, "id is required")
    try:
        llama_manager.activate(str(version_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return llama_manager.state()


@router.delete("/{version_id}")
async def remove_llama(version_id: str) -> dict[str, Any]:
    try:
        llama_manager.remove(version_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return llama_manager.state()
