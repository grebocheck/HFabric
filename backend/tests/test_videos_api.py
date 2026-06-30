from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app.api import videos


def _row(tmp_path, *, poster: bool = True, thumb: bool = True):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    poster_path = tmp_path / "poster.webp"
    thumb_path = tmp_path / "thumb.webp"
    if poster:
        poster_path.write_bytes(b"poster")
    if thumb:
        thumb_path.write_bytes(b"thumb")
    return SimpleNamespace(
        id="clip",
        job_id="job",
        path=str(video),
        poster_path=str(poster_path) if poster else None,
        thumb_path=str(thumb_path) if thumb else None,
        seed=1,
        width=256,
        height=256,
        frames=9,
        fps=8,
        duration_s=1.125,
        family="ltx-video",
        params={"prompt": "p"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_video_api_handlers_return_files_and_output(monkeypatch, tmp_path):
    row = _row(tmp_path)
    calls: list[tuple[int, int]] = []

    async def list_videos(session, *, limit: int, offset: int):
        calls.append((limit, offset))
        return [row]

    async def get_video(session, video_id: str):
        assert video_id == "clip"
        return row

    async def delete_video(session, video_id: str) -> bool:
        assert video_id == "clip"
        return True

    monkeypatch.setattr(videos.video_service, "list_videos", list_videos)
    monkeypatch.setattr(videos.video_service, "get_video", get_video)
    monkeypatch.setattr(videos.video_service, "delete_video", delete_video)

    listed = await videos.list_videos(limit=7, offset=3, session=object())
    assert calls == [(7, 3)]
    assert listed[0].id == "clip"
    assert listed[0].poster_url == "/api/videos/clip/poster"

    deleted = await videos.delete_video("clip", session=object())
    assert deleted == {"deleted": "clip"}

    assert (await videos.video_file("clip", session=object())).media_type == "video/mp4"
    assert (await videos.video_poster("clip", session=object())).media_type == "image/webp"
    assert (await videos.video_thumb("clip", session=object())).media_type == "image/webp"


async def test_video_api_handlers_raise_clear_404s(monkeypatch, tmp_path):
    missing_media = _row(tmp_path, poster=False, thumb=False)
    missing_media.path = str(tmp_path / "missing.mp4")

    async def get_video(session, video_id: str):
        return missing_media if video_id == "clip" else None

    async def delete_video(session, video_id: str) -> bool:
        return False

    monkeypatch.setattr(videos.video_service, "get_video", get_video)
    monkeypatch.setattr(videos.video_service, "delete_video", delete_video)

    with pytest.raises(HTTPException) as delete_exc:
        await videos.delete_video("clip", session=object())
    assert delete_exc.value.status_code == 404

    with pytest.raises(HTTPException) as file_exc:
        await videos.video_file("clip", session=object())
    assert file_exc.value.status_code == 404

    with pytest.raises(HTTPException) as poster_exc:
        await videos.video_poster("clip", session=object())
    assert poster_exc.value.status_code == 404

    with pytest.raises(HTTPException) as thumb_exc:
        await videos.video_thumb("clip", session=object())
    assert thumb_exc.value.status_code == 404
