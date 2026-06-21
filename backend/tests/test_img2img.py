"""img2img/inpainting source upload + generation plumbing (P13.4/P13.5).

The real diffusers Img2Img pipeline needs a GPU, but everything around it — the
upload endpoint, the param flow through the queue, the SDXL-only guard, and the
strength clamp — runs in STUB mode and is verified here.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
import pytest

from app.backends.base import ModelDescriptor
from app.backends.image_diffusers import DiffusersImageBackend
from app.config import settings
from app.core.enums import ModelFamily
from app.main import app

# ----------------------------------------------------------- pure unit tests


def test_strength_is_clamped_defaulted_and_gets_a_distilled_floor():
    assert DiffusersImageBackend._strength({}) == settings.img2img_default_strength
    assert DiffusersImageBackend._strength({"strength": 5.0}) == 1.0
    assert DiffusersImageBackend._strength({"strength": 0.0}) == 0.05
    assert DiffusersImageBackend._strength({"strength": "nope"}) == settings.img2img_default_strength
    assert DiffusersImageBackend._effective_strength({"strength": 0.35}, 2) == 0.5
    assert DiffusersImageBackend._strength({}, ModelFamily.QWEN_IMAGE) == settings.qwen_image_img2img_strength
    assert DiffusersImageBackend._strength({}, ModelFamily.Z_IMAGE) == settings.z_image_img2img_strength
    assert DiffusersImageBackend._effective_strength(
        {"strength": 0.1}, 9, ModelFamily.Z_IMAGE, min_effective_steps=4
    ) == pytest.approx(4 / 9)


async def test_img2img_allowed_for_flux_families():
    desc = ModelDescriptor(
        id="f", name="F", family=ModelFamily.FLUX, path=Path("x"), size_bytes=0, quant="nunchaku-fp4"
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    rows = await backend.generate({"init_image": "a" * 32, "prompt": "x", "steps": 1}, progress)
    assert rows[0]["params"]["family"] == "flux"


@pytest.mark.parametrize("family", [ModelFamily.QWEN_IMAGE, ModelFamily.Z_IMAGE])
async def test_img2img_and_inpaint_allowed_for_qwen_z_families(family):
    backend = DiffusersImageBackend(
        ModelDescriptor(id="edit", name="Edit", family=family, path=Path("x"), size_bytes=0)
    )
    async def progress(frac, note=None):
        return None

    img2img = await backend.generate({"init_image": "a" * 32, "prompt": "x", "steps": 9}, progress)
    inpaint = await backend.generate(
        {"init_image": "a" * 32, "mask_image": "b" * 32, "prompt": "x", "steps": 9},
        progress,
    )
    assert img2img[0]["params"]["family"] == family.value
    assert inpaint[0]["params"]["inpaint"] is True


def test_control_scale_is_clamped_and_defaulted():
    assert DiffusersImageBackend._control_scale({}) == settings.sdxl_controlnet_default_scale
    assert DiffusersImageBackend._control_scale({"control_scale": 5}) == 2.0
    assert DiffusersImageBackend._control_scale({"control_scale": "bad"}) == settings.sdxl_controlnet_default_scale


async def test_inpaint_requires_source_image():
    desc = ModelDescriptor(
        id="s", name="S", family=ModelFamily.SDXL, path=Path("x"), size_bytes=0
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    with pytest.raises(ValueError, match="requires"):
        await backend.generate({"mask_image": "b" * 32, "prompt": "x"}, progress)


async def test_controlnet_rejected_for_non_sdxl():
    desc = ModelDescriptor(
        id="f", name="F", family=ModelFamily.FLUX, path=Path("x"), size_bytes=0, quant="nunchaku-fp4"
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    with pytest.raises(ValueError, match="ControlNet"):
        await backend.generate({"control_image": "a" * 32, "prompt": "x"}, progress)


async def test_controlnet_can_be_combined_with_img2img():
    desc = ModelDescriptor(
        id="s", name="S", family=ModelFamily.SDXL, path=Path("x"), size_bytes=0
    )
    backend = DiffusersImageBackend(desc)

    async def progress(frac, note=None):
        return None

    rows = await backend.generate(
        {"init_image": "a" * 32, "control_image": "b" * 32, "prompt": "x", "steps": 1},
        progress,
    )
    assert rows[0]["params"]["controlnet"]["type"] == "canny"


async def test_flux2_reference_metadata_does_not_claim_strength():
    backend = DiffusersImageBackend(
        ModelDescriptor(id="f2", name="Klein", family=ModelFamily.FLUX2, path=Path("x"), size_bytes=0)
    )

    async def progress(frac, note=None):
        return None

    rows = await backend.generate({"init_image": "a" * 32, "prompt": "x", "steps": 1}, progress)
    params = rows[0]["params"]
    assert params["flux2_reference"] is True
    assert "strength" not in params


async def test_anima_img2img_allowed_but_mask_rejected():
    backend = DiffusersImageBackend(
        ModelDescriptor(id="a", name="Anima", family=ModelFamily.ANIMA, path=Path("x"), size_bytes=0)
    )

    async def progress(frac, note=None):
        return None

    rows = await backend.generate({"init_image": "a" * 32, "prompt": "x", "steps": 1}, progress)
    assert rows[0]["params"]["strength"] == 1.0
    with pytest.raises(ValueError, match="not inpainting"):
        await backend.generate(
            {"init_image": "a" * 32, "mask_image": "b" * 32, "prompt": "x"}, progress
        )


async def test_instruction_edit_requires_source_and_records_mode():
    backend = DiffusersImageBackend(
        ModelDescriptor(
            id="qe", name="Qwen Edit", family=ModelFamily.QWEN_IMAGE_EDIT, path=Path("x"), size_bytes=0
        )
    )

    async def progress(frac, note=None):
        return None

    with pytest.raises(ValueError, match="requires a source"):
        await backend.generate({"prompt": "change it"}, progress)
    rows = await backend.generate(
        {"init_image": "a" * 32, "edit_mode": "instruction", "prompt": "change it", "steps": 1},
        progress,
    )
    assert rows[0]["params"]["instruction_edit"] is True
    assert "strength" not in rows[0]["params"]


def test_resize_modes_preserve_aspect_and_outpaint_builds_border_mask():
    source = PILImage.new("RGB", (40, 80), "red")
    crop = DiffusersImageBackend._fit_image(source, 160, 80, "crop")
    pad = DiffusersImageBackend._fit_image(source, 160, 80, "pad")
    assert crop.size == (160, 80)
    assert pad.size == (160, 80)
    assert pad.getpixel((0, 0)) == (24, 28, 36)

    backend = DiffusersImageBackend(
        ModelDescriptor(id="s", name="S", family=ModelFamily.SDXL, path=Path("x"), size_bytes=0)
    )
    params = {
        "outpaint_left": 16,
        "outpaint_right": 16,
        "outpaint_top": 8,
        "outpaint_bottom": 8,
    }
    mask = backend._outpaint_canvas(PILImage.new("L", (1, 1), 0), 96, 80, params, mask=True)
    assert mask.getpixel((0, 0)) == 255
    assert mask.getpixel((48, 40)) == 0


def test_mask_grow_shrink_blur_and_invert_are_server_side():
    mask = PILImage.new("L", (21, 21), 0)
    mask.putpixel((10, 10), 255)
    grown = DiffusersImageBackend._apply_mask_ops(mask, {"mask_grow": 2})
    assert grown.getpixel((8, 10)) == 255
    shrunk = DiffusersImageBackend._apply_mask_ops(grown, {"mask_grow": -2})
    assert shrunk.getpixel((8, 10)) == 0
    blurred = DiffusersImageBackend._apply_mask_ops(mask, {"mask_blur": 2})
    assert 0 < blurred.getpixel((9, 10)) < 255
    inverted = DiffusersImageBackend._apply_mask_ops(mask, {"mask_invert": True})
    assert inverted.getpixel((0, 0)) == 255
    assert inverted.getpixel((10, 10)) == 0


@pytest.mark.parametrize(
    ("method", "class_name"),
    [
        ("_qwen_img2img_pipe", "QwenImageImg2ImgPipeline"),
        ("_qwen_inpaint_pipe", "QwenImageInpaintPipeline"),
        ("_z_image_img2img_pipe", "ZImageImg2ImgPipeline"),
        ("_z_image_inpaint_pipe", "ZImageInpaintPipeline"),
    ],
)
def test_qwen_z_edit_views_reuse_resident_components(monkeypatch, method, class_name):
    import diffusers

    calls = []

    class SharedView:
        def __init__(self, **components):
            calls.append(components)

    monkeypatch.setattr(diffusers, class_name, SharedView)
    backend = DiffusersImageBackend(
        ModelDescriptor(id="e", name="Edit", family=ModelFamily.QWEN_IMAGE, path=Path("x"), size_bytes=0)
    )
    components = {"transformer": object(), "vae": object(), "scheduler": object()}
    backend._pipe = SimpleNamespace(components=components)
    first = getattr(backend, method)()
    second = getattr(backend, method)()
    assert first is second
    assert calls == [components]


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
