"""Durable history access for generated mp4 artifacts."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Video


async def list_videos(
    session: AsyncSession, *, limit: int = 100, offset: int = 0
) -> list[Video]:
    stmt = select(Video).order_by(Video.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def get_video(session: AsyncSession, video_id: str) -> Video | None:
    return await session.get(Video, video_id)


async def delete_video(session: AsyncSession, video_id: str) -> bool:
    video = await session.get(Video, video_id)
    if video is None:
        return False
    paths = [video.path, video.poster_path, video.thumb_path, str(Path(video.path).with_suffix(".json"))]
    for raw in paths:
        if not raw:
            continue
        try:
            Path(raw).unlink(missing_ok=True)
        except OSError:
            pass
    await session.delete(video)
    return True


def to_out_dict(video: Video) -> dict:
    return {
        "id": video.id,
        "job_id": video.job_id,
        "seed": video.seed,
        "width": video.width,
        "height": video.height,
        "frames": video.frames,
        "fps": video.fps,
        "duration_s": video.duration_s,
        "family": video.family,
        "params": video.params or {},
        "created_at": video.created_at,
        "url": f"/api/videos/{video.id}/file",
        "poster_url": f"/api/videos/{video.id}/poster" if video.poster_path else None,
        "thumb_url": f"/api/videos/{video.id}/thumb" if video.thumb_path else None,
    }
