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
import time

import torch

from app.backends.base import ModelDescriptor
from app.backends.video_diffusers import DiffusersVideoBackend
from app.config import settings
from app.core.enums import ModelFamily

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


async def main() -> None:
    model = os.environ.get("MODEL", "wan2.2-ti2v-5b")
    mode = os.environ.get("MODE", "t2v")
    w = int(os.environ.get("W", "832"))
    h = int(os.environ.get("H", "480"))
    frames = int(os.environ.get("FRAMES", "25"))
    steps = int(os.environ.get("STEPS", "8"))

    settings.stub_mode = False

    family = ModelFamily.WAN_VIDEO if "wan" in model else ModelFamily.LTX_VIDEO
    path = settings.video_models_dir / model
    desc = ModelDescriptor(id=model, name=model, family=family, path=path, size_bytes=0)
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
        params["init_image"] = os.environ["INIT_IMAGE"]  # upload token

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
