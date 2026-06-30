from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.db.models import Video
from app.db.session import init_db, session_scope
from app.services import video_service


@pytest.fixture
async def video_db():
    await init_db()
    async with session_scope() as s:
        await s.execute(delete(Video))
    yield
    async with session_scope() as s:
        await s.execute(delete(Video))


async def test_list_get_and_to_out_dict(video_db, tmp_path):
    async with session_scope() as s:
        older = Video(
            id="old",
            job_id="job-old",
            path=str(tmp_path / "old.mp4"),
            width=512,
            height=320,
            frames=17,
            fps=8,
            duration_s=2.125,
            family="ltx-video",
            params={"prompt": "old"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        newer = Video(
            id="new",
            job_id="job-new",
            path=str(tmp_path / "new.mp4"),
            poster_path=str(tmp_path / "new.poster.webp"),
            thumb_path=str(tmp_path / "new.thumb.webp"),
            width=832,
            height=480,
            frames=49,
            fps=24,
            duration_s=2.042,
            family="wan-video",
            params={"prompt": "new"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1),
        )
        s.add_all([older, newer])

    async with session_scope() as s:
        assert [video.id for video in await video_service.list_videos(s)] == ["new", "old"]
        assert [video.id for video in await video_service.list_videos(s, limit=1, offset=1)] == ["old"]
        assert (await video_service.get_video(s, "new")).family == "wan-video"

        out = video_service.to_out_dict(await video_service.get_video(s, "new"))
        assert out["url"] == "/api/videos/new/file"
        assert out["poster_url"] == "/api/videos/new/poster"
        assert out["thumb_url"] == "/api/videos/new/thumb"
        assert out["params"] == {"prompt": "new"}

        old_out = video_service.to_out_dict(await video_service.get_video(s, "old"))
        assert old_out["poster_url"] is None
        assert old_out["thumb_url"] is None


async def test_delete_video_removes_row_and_best_effort_files(video_db, tmp_path):
    video_path = tmp_path / "clip.mp4"
    poster_path = tmp_path / "poster-dir"
    thumb_path = tmp_path / "clip.thumb.webp"
    sidecar = video_path.with_suffix(".json")
    video_path.write_bytes(b"mp4")
    poster_path.mkdir()
    thumb_path.write_bytes(b"webp")
    sidecar.write_text("{}", encoding="utf-8")

    async with session_scope() as s:
        s.add(Video(
            id="clip",
            job_id="job",
            path=str(video_path),
            poster_path=str(poster_path),
            thumb_path=str(thumb_path),
            params={},
        ))

    async with session_scope() as s:
        assert await video_service.delete_video(s, "missing") is False
        assert await video_service.delete_video(s, "clip") is True

    assert not video_path.exists()
    assert poster_path.exists()  # directory unlink raises OSError and is ignored
    assert not thumb_path.exists()
    assert not sidecar.exists()

    async with session_scope() as s:
        assert await video_service.get_video(s, "clip") is None
