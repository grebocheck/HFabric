"""CivitAI browse API for the unified Models tab.

Read-only search + version-file listing. Downloads go through the shared custom
download pipeline (``POST /api/downloads/custom`` with source ``"civitai"``), so
this router does not start downloads itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..services import civitai_auth, civitai_service
from ..util import security

router = APIRouter(prefix="/api/civitai", tags=["civitai"])


def _require_loopback(request: Request) -> None:
    """Storing/clearing the API key is a local-only action (mirrors image reveal)."""
    client_host = request.client.host if request.client else None
    if not security.is_loopback_host(client_host):
        raise HTTPException(403, "managing the CivitAI key is only allowed from loopback clients")


@router.get("/search")
async def search_civitai(
    q: str = "",
    types: str | None = Query(default=None, description="comma-separated CivitAI types"),
    sort: str = "downloads",
    period: str = "AllTime",
    base_models: str | None = Query(default=None, alias="base_models"),
    nsfw: bool = False,
    limit: int = 24,
    page: int = 1,
) -> dict[str, Any]:
    type_list = [t.strip() for t in (types or "").split(",") if t.strip()]
    base_list = [b.strip() for b in (base_models or "").split(",") if b.strip()]
    try:
        return await asyncio.to_thread(
            civitai_service.search_models,
            q,
            types=type_list,
            sort=sort,
            period=period,
            base_models=base_list,
            nsfw=nsfw,
            limit=limit,
            page=page,
            headers=civitai_auth.auth_headers(),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/versions/{version_id}/files")
async def civitai_version_files(version_id: int, nsfw: bool = False) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            civitai_service.version_files, version_id, nsfw=nsfw, headers=civitai_auth.auth_headers()
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _auth_status() -> dict[str, Any]:
    return {"has_key": civitai_auth.has_key(), "has_cookie": civitai_auth.has_cookie()}


@router.get("/auth")
async def civitai_auth_status() -> dict[str, Any]:
    """Which CivitAI credentials are stored. The secrets themselves are never returned."""
    return _auth_status()


@router.put("/auth")
async def civitai_auth_save(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store a CivitAI API key and/or session cookie (loopback-only) and verify it.

    Send exactly one of ``api_key`` / ``session_cookie`` per call; the response's
    ``verified`` / ``reason`` describe the credential just saved."""
    _require_loopback(request)
    payload = body or {}
    api_key = payload.get("api_key")
    session_cookie = payload.get("session_cookie")

    if api_key is not None and str(api_key).strip():
        result = await asyncio.to_thread(civitai_auth.verify_key, str(api_key))
        civitai_auth.set_key(str(api_key))
        return {**_auth_status(), "which": "key", **result}
    if session_cookie is not None and str(session_cookie).strip():
        result = await asyncio.to_thread(civitai_auth.verify_cookie, str(session_cookie))
        civitai_auth.set_cookie(str(session_cookie))
        return {**_auth_status(), "which": "cookie", **result}
    raise HTTPException(422, "api_key or session_cookie is required")


@router.delete("/auth")
async def civitai_auth_clear(request: Request, target: str = "all") -> dict[str, Any]:
    """Forget the stored CivitAI key, cookie, or both (loopback-only)."""
    _require_loopback(request)
    if target in ("key", "all"):
        civitai_auth.clear_key()
    if target in ("cookie", "all"):
        civitai_auth.clear_cookie()
    return _auth_status()
