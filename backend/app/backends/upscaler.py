"""Arbiter-managed image upscaler backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
import random
from typing import Any

from PIL import Image as PILImage

from ..config import settings
from ..core.enums import ModelFamily
from ..services import accelerator_runtime
from ..util import imaging
from .base import GenerationCancelled, ModelDescriptor, ProgressCb, UpscaleBackend


class ImageUpscalerBackend(UpscaleBackend):
    def __init__(self, descriptor: ModelDescriptor) -> None:
        super().__init__(descriptor)
        self._accelerator: accelerator_runtime.AcceleratorRuntime | None = None
        self._upsampler: Any = None
        self._mode = "pillow"
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    async def load(self) -> None:
        if self._loaded:
            return
        self._stop = False
        if settings.stub_mode:
            await asyncio.sleep(0.1)
            self._mode = "stub"
            self._loaded = True
            self._load_report = {"upscaler": {"mode": self._mode, "stub": True}}
            return
        await asyncio.to_thread(self._load_sync)
        self._loaded = True

    def _load_sync(self) -> None:
        import torch  # noqa: PLC0415

        self._accelerator = accelerator_runtime.current()
        report: dict[str, Any] = {
            "upscaler": {
                "requested": self.descriptor.name,
                "weights": str(self.descriptor.path),
                "accelerator": self._accelerator.public(),
            }
        }
        try:
            self._accelerator.require_available(torch)
            self._upsampler = self._load_realesrgan(torch)
            self._mode = "realesrgan"
        except Exception as exc:  # noqa: BLE001 - optional fast path
            self._upsampler = None
            self._mode = "pillow"
            report["upscaler"]["fallback"] = f"{type(exc).__name__}: {exc}"
        report["upscaler"]["mode"] = self._mode
        self._load_report = report

    def _load_realesrgan(self, torch):
        if not self.descriptor.path.exists():
            raise FileNotFoundError(self.descriptor.path)
        from basicsr.archs.rrdbnet_arch import RRDBNet  # noqa: PLC0415
        from realesrgan import RealESRGANer  # noqa: PLC0415

        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_grow_ch=32,
            scale=4,
        )
        runtime = self._accelerator or accelerator_runtime.current()
        return RealESRGANer(
            scale=4,
            model_path=str(self.descriptor.path),
            model=model,
            tile=0,
            tile_pad=10,
            pre_pad=0,
            half=runtime.cuda_family and hasattr(torch, "float16"),
        )

    async def unload(self) -> None:
        self._upsampler = None
        self._loaded = False
        self._warm = False
        self._accelerator = None
        self._mode = "pillow"

    async def upscale(self, params: dict[str, Any], progress: ProgressCb) -> list[dict[str, Any]]:
        source = params.get("_source_path") or params.get("source_path")
        if not isinstance(source, str) or not source:
            raise ValueError("upscale source image is missing")
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        scale = _scale(params)
        await progress(0.05, f"upscale {scale}x")
        img = await asyncio.to_thread(self._upscale_sync, source_path, scale)
        if self._stop:
            raise GenerationCancelled()
        await progress(1.0, "upscale done")
        width, height = img.size
        meta = {
            **{k: v for k, v in params.items() if not k.startswith("_")},
            "model": self.descriptor.name,
            "family": ModelFamily.UPSCALER.value,
            "upscale": {"scale": scale, "mode": self._mode},
            "width": width,
            "height": height,
        }
        return [self._persist(img, meta, width, height)]

    def _upscale_sync(self, source_path: Path, scale: int):
        img = PILImage.open(source_path).convert("RGB")
        if self._upsampler is not None:
            import numpy as np  # noqa: PLC0415

            bgr = np.array(img)[:, :, ::-1]
            out, _ = self._upsampler.enhance(bgr, outscale=scale)
            return PILImage.fromarray(out[:, :, ::-1]).convert("RGB")
        return img.resize((img.width * scale, img.height * scale), PILImage.Resampling.LANCZOS)

    def _persist(self, img, meta: dict[str, Any], width: int, height: int) -> dict[str, Any]:
        out_dir = imaging.day_dir(settings.outputs_dir)
        stem = f"upscale_{random.randint(100000, 999999)}"
        png_path = out_dir / f"{stem}.png"
        thumb_path = out_dir / f"{stem}.thumb.webp"
        imaging.save_png(img, png_path, meta)
        imaging.make_thumbnail(img, thumb_path)
        return {
            "path": str(png_path),
            "thumb_path": str(thumb_path),
            "seed": None,
            "width": width,
            "height": height,
            "family": meta["family"],
            "params": meta,
        }


def _scale(params: dict[str, Any]) -> int:
    try:
        value = int(params.get("scale", 2))
    except (TypeError, ValueError):
        value = 2
    return 4 if value >= 4 else 2
