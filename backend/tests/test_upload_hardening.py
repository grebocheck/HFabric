from __future__ import annotations

import io

from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
import pytest

from app.api import transcription
from app.config import settings
from app.main import app


@pytest.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "outputs_dir", tmp_path / "outputs")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_image_upload_caps_cover_source_and_mask(client, monkeypatch):
    monkeypatch.setattr(settings, "image_upload_max_mb", 0)
    payload = _png_bytes()

    source = await client.post("/api/images/upload", files={"file": ("source.png", payload, "image/png")})
    mask = await client.post("/api/images/upload-mask", files={"file": ("mask.png", payload, "image/png")})

    assert source.status_code == 413
    assert mask.status_code == 413


async def test_transcription_upload_cap_runs_before_model_execution(client, monkeypatch):
    monkeypatch.setattr(settings, "transcription_max_upload_mb", 0)
    monkeypatch.setattr(
        transcription,
        "_model_map",
        lambda: {"stub": {"id": "stub", "engine": "faster-whisper", "path": "stub"}},
    )
    monkeypatch.setattr(transcription, "_has", lambda _module: True)

    response = await client.post(
        "/api/transcription/transcribe",
        data={"model_id": "stub"},
        files={"file": ("tone.wav", b"x", "audio/wav")},
    )

    assert response.status_code == 413


async def test_chat_attachment_upload_cap_runs_before_storage(client, monkeypatch):
    monkeypatch.setattr(settings, "chat_upload_max_mb", 0)

    response = await client.post(
        "/api/chat/uploads",
        files={"file": ("image.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 413


async def test_image_upload_sniffs_format_and_rejects_mime_mismatch(client):
    mismatch = await client.post(
        "/api/images/upload",
        files={"file": ("pretend.png", _jpeg_bytes(), "image/png")},
    )
    invalid = await client.post(
        "/api/images/upload-mask",
        files={"file": ("mask.png", b"not-an-image", "image/png")},
    )
    sniffed = await client.post(
        "/api/images/upload",
        files={"file": ("opaque.bin", _png_bytes(), "application/octet-stream")},
    )

    assert mismatch.status_code == 415
    assert "does not match" in mismatch.text
    assert invalid.status_code == 400
    assert sniffed.status_code == 200
    stored = settings.outputs_dir / "uploads" / f"{sniffed.json()['init_image']}.png"
    assert stored.is_file()


async def test_image_upload_promotes_decompression_bomb_warning_to_error(
    client,
    monkeypatch,
):
    # 8x8 is above this warning threshold but below Pillow's 2x hard-error
    # threshold, proving our warning filter itself is fail-closed.
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 40)

    response = await client.post(
        "/api/images/upload",
        files={"file": ("large.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 413
    assert "safe decode limit" in response.text
