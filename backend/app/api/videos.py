"""Generated-video history and HTTP-range mp4 serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import VideoOut
from ..services import video_service
from .deps import get_session

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=list[VideoOut])
async def list_videos(
    limit: int = Query(100, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[VideoOut]:
    rows = await video_service.list_videos(session, limit=limit, offset=offset)
    return [VideoOut.model_validate(video_service.to_out_dict(row)) for row in rows]


@router.delete("/{video_id}")
async def delete_video(video_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await video_service.delete_video(session, video_id):
        raise HTTPException(404, "video not found")
    return {"deleted": video_id}


@router.get("/{video_id}/file")
async def video_file(video_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    video = await video_service.get_video(session, video_id)
    if not video or not Path(video.path).is_file():
        raise HTTPException(404, "video not found")
    # Starlette FileResponse supports single/multipart byte ranges and emits
    # Accept-Ranges, enabling native browser seek/scrub without loading all bytes.
    return FileResponse(video.path, media_type="video/mp4")


@router.get("/{video_id}/poster")
async def video_poster(video_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    video = await video_service.get_video(session, video_id)
    if not video or not video.poster_path or not Path(video.poster_path).is_file():
        raise HTTPException(404, "video poster not found")
    return FileResponse(video.poster_path, media_type="image/webp")


@router.get("/{video_id}/thumb")
async def video_thumb(video_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    video = await video_service.get_video(session, video_id)
    if not video or not video.thumb_path or not Path(video.thumb_path).is_file():
        raise HTTPException(404, "video thumbnail not found")
    return FileResponse(video.thumb_path, media_type="image/webp")
