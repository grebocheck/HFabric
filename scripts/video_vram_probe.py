"""Direct VRAM/perf probe for the local video backend.

Loads the real Wan/LTX Diffusers pipeline (no FastAPI), runs one generation, and
reports peak VRAM + timing for each stage. Parameterised by env so the same
script can A/B the text-encoder offload and resolutions as separate processes
(VRAM only fully resets across processes).

    OFFLOAD=0|1  MODEL=wan2.2-ti2v-5b|ltx-video  MODE=t2v|i2v
    W=832 H=480 FRAMES=25 STEPS=8  python scripts/video_vram_probe.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time

from PIL import Image, ImageDraw
import torch

from app.backends.base import ModelDescriptor
from app.backends.video_diffusers import DiffusersVideoBackend
from app.config import settings
from app.core.enums import ModelFamily
from app.util import uploads as uploads_util

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def gb(n: float) -> float:
    return round(n / 1024**3, 2)


def vram() -> str:
    free, total = torch.cuda.mem_get_info()
    return (
        f"alloc={gb(torch.cuda.memory_allocated())} "
        f"peak={gb(torch.cuda.max_memory_allocated())} "
        f"reserved={gb(torch.cuda.memory_reserved())} "
        f"device_free={gb(free)}/{gb(total)}"
    )


def family_for_model(model: str) -> ModelFamily:
    lowered = model.lower()
    if "framepack" in lowered or "hunyuan" in lowered:
        return ModelFamily.HUNYUAN_VIDEO
    if "wan" in lowered:
        return ModelFamily.WAN_VIDEO
    return ModelFamily.LTX_VIDEO


def source_token(width: int, height: int) -> str:
    token = os.environ.get("INIT_IMAGE")
    if token:
        return token

    source_path = os.environ.get("INIT_IMAGE_PATH")
    image = Image.open(source_path).convert("RGB") if source_path else Image.new("RGB", (width, height), "#1d2530")
    if not source_path:
        draw = ImageDraw.Draw(image)
        draw.rectangle((width * 0.12, height * 0.18, width * 0.88, height * 0.82), outline="#e5d7a3", width=4)
        draw.text((width * 0.18, height * 0.42), "FramePack smoke source", fill="#f7f0d0")
    token = secrets.token_hex(16)
    uploads_util.uploads_dir().mkdir(parents=True, exist_ok=True)
    image.save(uploads_util.uploads_dir() / f"{token}.png", format="PNG")
    return token


async def main() -> None:
    model = os.environ.get("MODEL", "wan2.2-ti2v-5b")
    family = family_for_model(model)
    mode = os.environ.get("MODE", "i2v" if family is ModelFamily.HUNYUAN_VIDEO else "t2v")
    w = int(os.environ.get("W", "480" if family is ModelFamily.HUNYUAN_VIDEO else "832"))
    h = int(os.environ.get("H", "832" if family is ModelFamily.HUNYUAN_VIDEO else "480"))
    frames = int(os.environ.get("FRAMES", "91" if family is ModelFamily.HUNYUAN_VIDEO else "25"))
    steps = int(os.environ.get("STEPS", "8"))

    settings.stub_mode = False

    path = settings.video_models_dir / model
    desc = ModelDescriptor(id=model, name=model, family=family, path=path, size_bytes=0, quant=settings.video_quant)
    backend = DiffusersVideoBackend(desc)

    print(f"=== probe model={model} mode={mode} {w}x{h} frames={frames} steps={steps} ===")
    print(f"[pre-load ] {vram()}")
    t0 = time.time()
    await backend.load()
    torch.cuda.reset_peak_memory_stats()
    print(f"[loaded {time.time()-t0:5.1f}s] {vram()}")

    params = {
        "prompt": "a cinematic shot of a paper boat sailing down a rain puddle, soft light",
        "negative": "blurry, low quality",
        "mode": mode,
        "width": w, "height": h, "frames": frames, "steps": steps,
    }
    if mode == "i2v":
        params["init_image"] = source_token(w, h)

    last = {"t": time.time()}

    async def progress(frac: float, note: str | None) -> None:
        now = time.time()
        print(f"  {frac*100:5.1f}% {note or '':28s} | {vram()} | +{now-last['t']:.1f}s")
        last["t"] = now

    t1 = time.time()
    try:
        rec = await backend.generate(params, progress)
        print(f"[done {time.time()-t1:5.1f}s] peak={gb(torch.cuda.max_memory_allocated())} GB -> {rec['path']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAILED {time.time()-t1:5.1f}s] {type(exc).__name__}: {exc}")
        print(f"[at-fail ] {vram()}")
        raise
    finally:
        await backend.unload()


if __name__ == "__main__":
    asyncio.run(main())
