"""Report the real VRAM footprint of each Wan/LTX submodel + VAE dtype/tiling.

No generation — just load and introspect, so it's fast. Answers: how big is the
text encoder we'd offload, and what does the VAE decode start from.
"""

from __future__ import annotations

import asyncio
import os

import torch

from app.backends.base import ModelDescriptor
from app.backends.video_diffusers import DiffusersVideoBackend
from app.config import settings
from app.core.enums import ModelFamily


def comp_bytes(module) -> float:
    if module is None:
        return 0.0
    total = 0
    for p in module.parameters():
        total += p.numel() * p.element_size()
    for b in module.buffers():
        total += b.numel() * b.element_size()
    return total / 1024**3


async def main() -> None:
    model = os.environ.get("MODEL", "wan2.2-ti2v-5b")
    settings.stub_mode = False
    lowered = model.lower()
    if "framepack" in lowered or "hunyuan" in lowered:
        family = ModelFamily.HUNYUAN_VIDEO
    elif "wan" in lowered:
        family = ModelFamily.WAN_VIDEO
    else:
        family = ModelFamily.LTX_VIDEO
    desc = ModelDescriptor(
        id=model,
        name=model,
        family=family,
        path=settings.video_models_dir / model,
        size_bytes=0,
        quant=settings.video_quant,
    )
    backend = DiffusersVideoBackend(desc)
    await backend.load()
    pipe = backend._pipe

    def dev_dtype(m):
        if m is None:
            return "—"
        p = next(m.parameters(), None)
        return f"{p.device}/{p.dtype}" if p is not None else "?"

    print(f"=== {model} component footprint ===")
    print(f"total CUDA alloc: {round(torch.cuda.memory_allocated()/1024**3,2)} GB")
    for name in ("text_encoder", "text_encoder_2", "image_encoder", "transformer", "transformer_2", "vae"):
        m = getattr(pipe, name, None)
        print(f"  {name:14s} {comp_bytes(m):6.2f} GB  [{dev_dtype(m)}]")
    vae = pipe.vae
    print(f"vae tiling enabled: {getattr(vae, 'use_tiling', '?')} | slicing: {getattr(vae, 'use_slicing', '?')}")
    for attr in ("tile_sample_min_height", "tile_sample_min_width",
                 "tile_sample_min_num_frames", "tile_sample_stride_height",
                 "tile_sample_stride_width"):
        if hasattr(vae, attr):
            print(f"  vae.{attr} = {getattr(vae, attr)}")
    await backend.unload()


if __name__ == "__main__":
    asyncio.run(main())
