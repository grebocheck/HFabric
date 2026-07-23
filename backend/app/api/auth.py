"""Browser authentication helpers that keep bearer tokens out of asset URLs."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..util import security
from .contracts import ERROR_RESPONSES

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    responses=ERROR_RESPONSES,
)


class AssetSessionOut(BaseModel):
    expires_at: int


@router.post("/asset-session", response_model=AssetSessionOut)
async def create_asset_session(request: Request, response: Response) -> AssetSessionOut:
    value, expires_at = security.create_asset_session()
    response.set_cookie(
        key=security.ASSET_SESSION_COOKIE,
        value=value,
        max_age=security.ASSET_SESSION_TTL_SECONDS,
        expires=security.ASSET_SESSION_TTL_SECONDS,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return AssetSessionOut(expires_at=expires_at)


@router.delete("/asset-session", status_code=204)
async def delete_asset_session() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(
        key=security.ASSET_SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
