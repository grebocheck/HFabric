"""Durable history access for generated mp4 artifacts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import JobType, ModelFamily
from ..db.models import Video

_VIDEO_FAMILIES = {family.value for family in ModelFamily if family.job_type is JobType.VIDEO}


async def recover_output_history(session: AsyncSession, outputs_dir: Path) -> int:
    """Recover completed bundles after an interrupted result transaction."""
    paths = tuple((await session.execute(select(Video.path))).scalars().all())
    records = await asyncio.to_thread(_recoverable_bundles, outputs_dir, paths)
    session.add_all(Video(**record) for record in records)
    return len(records)


def _recoverable_bundles(outputs_dir: Path, stored_paths: tuple[str, ...]) -> list[dict]:
    root = outputs_dir.resolve()
    known = set()
    for path in stored_paths:
        try:
            known.add(Path(path).resolve())
        except (OSError, RuntimeError):
            continue
    records = []
    for directory, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if not name.startswith(".") and name not in {"uploads", "chat_uploads"}]
        for name in filenames:
            if not name.startswith("video_") or not name.endswith(".json"):
                continue
            sidecar = Path(directory) / name
            try:
                if not sidecar.resolve().is_relative_to(root) or sidecar.stat().st_size > 1024 * 1024:
                    continue
                video = sidecar.with_suffix(".mp4").resolve()
                if video in known or not video.is_relative_to(root) or not video.is_file() or video.stat().st_size == 0:
                    continue
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if not isinstance(meta, dict) or not isinstance(meta.get("family"), str) or meta["family"] not in _VIDEO_FAMILIES:
                    continue
                dimensions = {key: meta.get(key) for key in ("width", "height", "frames")}
                if any(type(value) is not int or not 0 < value < 2**31 for value in dimensions.values()):
                    continue
                fps = meta.get("fps")
                if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 240:
                    continue
                companions = {}
                for key, suffix in (("poster_path", ".poster.webp"), ("thumb_path", ".thumb.webp")):
                    path = video.with_suffix(suffix)
                    companions[key] = str(path) if path.resolve().is_relative_to(root) and path.is_file() else None
                seed = meta.get("seed")
                records.append({
                    "job_id": None, "path": str(video), **companions, **dimensions,
                    "seed": seed if type(seed) is int and 0 <= seed < 2**63 else None,
                    "fps": fps, "duration_s": dimensions["frames"] / fps,
                    "family": meta["family"], "params": meta,
                    "created_at": datetime.fromtimestamp(sidecar.stat().st_mtime, UTC),
                })
                known.add(video)
            except (OSError, ValueError, RuntimeError, OverflowError):
                # Partial/corrupt bundles remain on disk for diagnosis.
                continue
    return records


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
    paths = (
        video.path,
        video.poster_path,
        video.thumb_path,
        str(Path(video.path).with_suffix(".json")),
    )
    await asyncio.to_thread(_unlink_video_files, paths)
    await session.delete(video)
    return True


def _unlink_video_files(paths: tuple[str | None, ...]) -> None:
    for raw in paths:
        if not raw:
            continue
        try:
            Path(raw).unlink(missing_ok=True)
        except OSError:
            pass


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
