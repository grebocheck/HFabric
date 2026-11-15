from __future__ import annotations

import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from PIL import Image
import pytest
from sqlalchemy import select

from app.backends.base import ModelDescriptor
from app.backends.video_diffusers import DiffusersVideoBackend
from app.config import settings
from app.core.enums import ModelFamily
from app.core.job_results import JobResultService
from app.db.models import Video
from app.db.session import init_db, session_scope
from app.main import app
from app.services import video_service


@pytest.fixture
def video_bundle(monkeypatch):
    backend = DiffusersVideoBackend(ModelDescriptor(id="video", name="Video", family=ModelFamily.LTX_VIDEO, path=Path("stub"), size_bytes=0))
    meta = {"seed": 7, "width": 16, "height": 16, "frames": 1, "fps": 8, "duration_s": 0.125, "family": "ltx-video", "prompt": "retained result"}

    def write(_frames, metadata, video, poster, thumb):
        video.write_bytes(b"encoded-mp4")
        poster.write_bytes(b"poster")
        thumb.write_bytes(b"thumbnail")
        video.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")

    monkeypatch.setattr(backend, "_write_bundle", write)
    return backend, meta


def test_failed_video_encoding_leaves_no_partial_files(video_bundle, monkeypatch):
    backend, meta = video_bundle

    def fail(_frames, _meta, video, _poster, _thumb):
        video.write_bytes(b"partial")
        raise OSError("encoder failed")

    monkeypatch.setattr(backend, "_write_bundle", fail)
    with pytest.raises(OSError, match="encoder failed"):
        backend._persist([Image.new("RGB", (16, 16))], meta)
    assert not [path for path in settings.outputs_dir.rglob("*") if path.is_file()]
    assert not list(settings.outputs_dir.rglob(".video-*"))


def test_failed_video_publication_rolls_back_the_bundle(video_bundle, monkeypatch):
    from app.backends import video_diffusers

    backend, meta = video_bundle
    real_replace = video_diffusers.os.replace
    count = 0

    def fail_third(source, destination):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("disk full")
        real_replace(source, destination)

    monkeypatch.setattr(video_diffusers.os, "replace", fail_third)
    with pytest.raises(OSError, match="disk full"):
        backend._persist([Image.new("RGB", (16, 16))], meta)
    assert not [path for path in settings.outputs_dir.rglob("*") if path.is_file()]


async def test_cancelled_video_discards_all_artifacts(video_bundle):
    backend, meta = video_bundle
    record = backend._persist([Image.new("RGB", (16, 16))], meta)
    results = JobResultService(None, None, lambda: None)
    await results.discard_video(record)
    assert not [path for path in settings.outputs_dir.rglob("*") if path.is_file()]


async def test_completed_video_without_db_commit_recovers_once_at_startup(video_bundle):
    backend, meta = video_bundle
    record = backend._persist([Image.new("RGB", (16, 16))], meta)
    # The generated bundle exists, but no result transaction ever committed.
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            videos = (await client.get("/api/videos")).json()
            assert len(videos) == 1
            assert videos[0]["params"]["prompt"] == meta["prompt"]
            assert (await client.get(videos[0]["url"])).content == b"encoded-mp4"
    async with session_scope() as session:
        assert await video_service.recover_output_history(session, settings.outputs_dir) == 0
        rows = (await session.execute(select(Video))).scalars().all()
        assert len(rows) == 1
        assert rows[0].path == record["path"]


async def test_recovery_ignores_corrupt_and_inflight_sidecars():
    await init_db()
    root = settings.outputs_dir
    root.mkdir(parents=True, exist_ok=True)
    for directory, metadata in ((root, {"family": []}), (root / ".video-staging", {"family": "ltx-video", "width": 16, "height": 16, "frames": 1, "fps": 8})):
        directory.mkdir(exist_ok=True)
        (directory / "video_7_test.mp4").write_bytes(b"mp4")
        (directory / "video_7_test.json").write_text(json.dumps(metadata), encoding="utf-8")
    async with session_scope() as session:
        assert await video_service.recover_output_history(session, root) == 0
