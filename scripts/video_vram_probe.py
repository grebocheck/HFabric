"""Direct VRAM/perf probe for the local video backend.

Loads the real Wan/LTX/FramePack/CogVideo Diffusers pipeline (no FastAPI), runs
one generation, and reports peak VRAM + timing for each stage. Parameterised by
env so the same script can A/B the text-encoder offload and resolutions as
separate processes (VRAM only fully resets across processes).

    REQUIRE_BACKEND=cuda|rocm|mps
    MODEL=wan2.2-ti2v-5b|ltx-video|cogvideo-2b  MODE=t2v|i2v
    W=832 H=480 FRAMES=25 STEPS=8  python scripts/video_vram_probe.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import secrets
import sys
import time

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.backends.base import ModelDescriptor  # noqa: E402
from app.backends.video_diffusers import DiffusersVideoBackend  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.enums import ModelFamily  # noqa: E402
from app.services import accelerator_runtime  # noqa: E402
from app.util import uploads as uploads_util  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def gb(n: float) -> float:
    return round(n / 1024**3, 2)


def accel_mem(runtime: accelerator_runtime.AcceleratorRuntime) -> str:
    import torch  # noqa: PLC0415 - hardware-only dependency, keep module importable in STUB CI

    if runtime.cuda_available(torch):
        free, total = torch.cuda.mem_get_info()
        return (
            f"alloc={gb(torch.cuda.memory_allocated())} "
            f"peak={gb(torch.cuda.max_memory_allocated())} "
            f"reserved={gb(torch.cuda.memory_reserved())} "
            f"device_free={gb(free)}/{gb(total)}"
        )
    if runtime.mps and hasattr(torch, "mps"):
        parts = []
        if hasattr(torch.mps, "current_allocated_memory"):
            parts.append(f"alloc={gb(torch.mps.current_allocated_memory())}")
        if hasattr(torch.mps, "driver_allocated_memory"):
            parts.append(f"reserved={gb(torch.mps.driver_allocated_memory())}")
        return " ".join(parts) or "mps_mem=unavailable"
    return "accelerator_mem=unavailable"


def family_for_model(model: str) -> ModelFamily:
    lowered = model.lower()
    if "framepack" in lowered or "hunyuan" in lowered:
        return ModelFamily.HUNYUAN_VIDEO
    if "cogvideo" in lowered:
        return ModelFamily.COGVIDEO
    if "wan" in lowered:
        return ModelFamily.WAN_VIDEO
    return ModelFamily.LTX_VIDEO


def require_backend(runtime: accelerator_runtime.AcceleratorRuntime, expected: str | None) -> None:
    if not expected:
        return
    normalized = expected.strip().lower()
    if normalized and runtime.backend != normalized:
        raise RuntimeError(
            f"REQUIRE_BACKEND={normalized!r} but active backend is {runtime.backend!r}; "
            "stop rather than accepting the wrong hardware path as a smoke pass."
        )


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
    import torch  # noqa: PLC0415 - only the real hardware entrypoint needs PyTorch

    model = os.environ.get("MODEL", "wan2.2-ti2v-5b")
    family = family_for_model(model)
    mode = os.environ.get("MODE", "i2v" if family is ModelFamily.HUNYUAN_VIDEO else "t2v")
    w = int(os.environ.get("W", "480" if family is ModelFamily.HUNYUAN_VIDEO else ("704" if family is ModelFamily.COGVIDEO else "832")))
    h = int(os.environ.get("H", "832" if family is ModelFamily.HUNYUAN_VIDEO else "480"))
    frames = int(os.environ.get("FRAMES", "91" if family is ModelFamily.HUNYUAN_VIDEO else "25"))
    steps = int(os.environ.get("STEPS", "8"))

    settings.stub_mode = False
    runtime = accelerator_runtime.current()
    require_backend(runtime, os.environ.get("REQUIRE_BACKEND"))

    path = settings.video_models_dir / model
    desc = ModelDescriptor(id=model, name=model, family=family, path=path, size_bytes=0, quant=settings.video_quant)
    backend = DiffusersVideoBackend(desc)

    print(
        f"=== probe model={model} family={family.value} mode={mode} "
        f"backend={runtime.backend} device={runtime.torch_device} {w}x{h} frames={frames} steps={steps} ==="
    )
    print(f"[pre-load ] {accel_mem(runtime)}")
    t0 = time.time()
    await backend.load()
    runtime.reset_peak_memory_stats(torch)
    print(f"[loaded {time.time()-t0:5.1f}s] {accel_mem(runtime)}")

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
        print(f"  {frac*100:5.1f}% {note or '':28s} | {accel_mem(runtime)} | +{now-last['t']:.1f}s")
        last["t"] = now

    t1 = time.time()
    try:
        rec = await backend.generate(params, progress)
        peak = runtime.peak_memory(torch).get("peak_allocated_gb")
        peak_text = f"peak={peak} GB" if peak is not None else accel_mem(runtime)
        print(f"[done {time.time()-t1:5.1f}s] {peak_text} -> {rec['path']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAILED {time.time()-t1:5.1f}s] {type(exc).__name__}: {exc}")
        print(f"[at-fail ] {accel_mem(runtime)}")
        raise
    finally:
        await backend.unload()


if __name__ == "__main__":
    asyncio.run(main())
