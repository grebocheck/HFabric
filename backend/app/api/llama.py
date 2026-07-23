"""Manage the llama.cpp runtime: install, update, activate, and roll back."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from ..services import llama_manager
from .contracts import (
    ERROR_RESPONSES,
    LlamaInstallStatusOut,
    LlamaStateOut,
    LlamaUpdateOut,
    LlamaVerifyOut,
)

router = APIRouter(
    prefix="/api/llama",
    tags=["llama"],
    responses=ERROR_RESPONSES,
)


@router.get("", response_model=LlamaStateOut)
async def get_llama_state() -> LlamaStateOut:
    return await asyncio.to_thread(llama_manager.state)


@router.post("/install", response_model=LlamaInstallStatusOut)
async def install_llama(
    body: dict[str, Any] | None = None,
) -> LlamaInstallStatusOut:
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


@router.post("/check", response_model=LlamaUpdateOut)
async def check_llama_update(
    body: dict[str, Any] | None = None,
) -> LlamaUpdateOut:
    variant = (body or {}).get("variant")
    try:
        return await asyncio.to_thread(llama_manager.check_update, variant)
    except Exception as exc:  # noqa: BLE001 - surface GitHub/network errors plainly
        raise HTTPException(502, f"could not check for updates: {exc}") from exc


@router.post("/verify", response_model=LlamaVerifyOut)
async def verify_llama() -> LlamaVerifyOut:
    """Run the active build's `llama-server --version` health check."""
    return await asyncio.to_thread(llama_manager.verify_active)


@router.post("/activate", response_model=LlamaStateOut)
async def activate_llama(body: dict[str, Any]) -> LlamaStateOut:
    version_id = body.get("id")
    if not version_id:
        raise HTTPException(422, "id is required")
    try:
        await asyncio.to_thread(llama_manager.activate, str(version_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return await asyncio.to_thread(llama_manager.state)


@router.delete("/{version_id}", response_model=LlamaStateOut)
async def remove_llama(version_id: str) -> LlamaStateOut:
    try:
        await asyncio.to_thread(llama_manager.remove, version_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await asyncio.to_thread(llama_manager.state)
