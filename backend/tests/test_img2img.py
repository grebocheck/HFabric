"""img2img/inpainting source upload + generation plumbing (P13.4/P13.5).

The real diffusers Img2Img pipeline needs a GPU, but everything around it — the
upload endpoint, the param flow through the queue, the SDXL-only guard, and the
strength clamp — runs in STUB mode and is verified here.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
import pytest

from app.backends.base import ModelDescriptor
from app.backends.image_diffusers import DiffusersImageBackend
from app.config import settings
from app.core.enums import ModelFamily
from app.main import app

# ----------------------------------------------------------- pure unit tests


def test_strength_is_clamped_and_defaulted():
    assert DiffusersImageBackend._strength({}) == settings.img2img_default_strength
    assert DiffusersImageBackend._strength({"strength": 5.0}) == 1.0
    assert DiffusersImageBackend._strength({"strength": 0.0}) == 0.05
    assert DiffusersImageBackend._strength({"strength": "nope"}) == settings.img2img_default_strength
    assert DiffusersImageBackend._effective_strength({"strength": 0.35}, 2) == 0.5


async def test_img2img_rejected_for_non_sdxl():
    desc = ModelDescriptor(
        id="f", name="F", family=ModelFamily.FLUX, path=Path("x"), size_bytes=0, quant="nunchaku-fp4"
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    with pytest.raises(ValueError, match="img2img"):
        await backend.generate({"init_image": "a" * 32, "prompt": "x"}, progress)


async def test_inpaint_requires_source_image():
    desc = ModelDescriptor(
        id="s", name="S", family=ModelFamily.SDXL, path=Path("x"), size_bytes=0
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    with pytest.raises(ValueError, match="requires"):
        await backend.generate({"mask_image": "b" * 32, "prompt": "x"}, progress)


# ------------------------------------------------------------- ASGI plumbing


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


def _png_bytes(w=64, h=48) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _mask_bytes(w=64, h=48) -> bytes:
    buf = io.BytesIO()
    img = PILImage.new("L", (w, h), 0)
    for x in range(16, 48):
        for y in range(12, 36):
            img.putpixel((x, y), 255)
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_roundtrip(client):
    r = await client.post("/api/images/upload", files={"file": ("src.png", _png_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    token = body["init_image"]
    assert len(token) == 32 and body["width"] == 64
    # the stored file is fetchable, and a malformed token is rejected
    assert (await client.get(f"/api/images/upload/{token}")).status_code == 200
    assert (await client.get("/api/images/upload/not-a-token")).status_code == 404


async def test_mask_upload_roundtrip(client):
    r = await client.post("/api/images/upload-mask", files={"file": ("mask.png", _mask_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    token = body["mask_image"]
    assert len(token) == 32 and body["width"] == 64
    assert (await client.get(f"/api/images/upload/{token}")).status_code == 200


async def test_upload_rejects_non_image(client):
    r = await client.post("/api/images/upload", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 400


async def test_img2img_job_runs_in_stub(client):
    token = (await client.post(
        "/api/images/upload", files={"file": ("s.png", _png_bytes(), "image/png")}
    )).json()["init_image"]

    models = (await client.get("/api/models")).json()
    sdxl = next(m["id"] for m in models if m["job_type"] == "image")  # seeded stub is SDXL
    created = (await client.post("/api/jobs", json=[{
        "type": "image", "model_id": sdxl,
        "params": {"prompt": "redo", "steps": 2, "init_image": token, "strength": 0.4},
    }])).json()
    jid = created[0]["id"]

    loop = asyncio.get_event_loop()
    deadline = loop.time() + 30
    status = ""
    while loop.time() < deadline:
        status = (await client.get(f"/api/jobs/{jid}")).json()["status"]
        if status in ("done", "error", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert status == "done"

    job = (await client.get(f"/api/jobs/{jid}")).json()
    image_ids = job["result"]["image_ids"]
    assert len(image_ids) == 1


async def test_inpaint_job_runs_in_stub(client):
    token = (await client.post(
        "/api/images/upload", files={"file": ("s.png", _png_bytes(), "image/png")}
    )).json()["init_image"]
    mask = (await client.post(
        "/api/images/upload-mask", files={"file": ("m.png", _mask_bytes(), "image/png")}
    )).json()["mask_image"]

    models = (await client.get("/api/models")).json()
    sdxl = next(m["id"] for m in models if m["job_type"] == "image")
    created = (await client.post("/api/jobs", json=[{
        "type": "image",
        "model_id": sdxl,
        "params": {"prompt": "edit region", "steps": 2, "init_image": token, "mask_image": mask, "strength": 0.55},
    }])).json()
    jid = created[0]["id"]

    loop = asyncio.get_event_loop()
    deadline = loop.time() + 30
    status = ""
    while loop.time() < deadline:
        status = (await client.get(f"/api/jobs/{jid}")).json()["status"]
        if status in ("done", "error", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert status == "done"

    job = (await client.get(f"/api/jobs/{jid}")).json()
    image_ids = job["result"]["image_ids"]
    assert len(image_ids) == 1
