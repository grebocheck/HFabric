"""Image backend built on a custom diffusers pipeline (per the chosen design —
no ComfyUI). Memory strategy is Forge-style frugal:

* SDXL (~6.6 GB) fits fully in 16 GB VRAM -> load straight to the active accelerator.
* FLUX fp8 (~16 GB all-in-one) -> ``enable_model_cpu_offload`` so the text
  encoders / VAE live in RAM and only the transformer holds VRAM during denoise.

In STUB mode (the default for the foundation) no torch is touched: load/unload
just toggle, and ``generate`` renders a labelled placeholder so the queue,
arbiter swap, progress events and gallery can all be exercised today.
"""

from __future__ import annotations

import asyncio
import importlib.util
import random
from typing import Any

from ..config import settings
from ..core.enums import ModelFamily
from ..services import accelerator_runtime
from ..util import imaging
from .base import ImageBackend, ModelDescriptor, ProgressCb
from .image_diffusers_parts import (
    AnimaLoaderMixin,
    DiffusersMemoryMixin,
    DiffusersPipelineMixin,
    Flux2LoaderMixin,
    FluxLoaderMixin,
    ImageEditingMixin,
    LoraRuntimeMixin,
    QwenZLoaderMixin,
    SdxlLoaderMixin,
)
from .image_diffusers_parts.generation import run_real_generation


class DiffusersImageBackend(
    ImageEditingMixin,
    LoraRuntimeMixin,
    AnimaLoaderMixin,
    QwenZLoaderMixin,
    Flux2LoaderMixin,
    FluxLoaderMixin,
    SdxlLoaderMixin,
    DiffusersMemoryMixin,
    DiffusersPipelineMixin,
    ImageBackend,
):
    def __init__(self, descriptor: ModelDescriptor) -> None:
        super().__init__(descriptor)
        self._pipe: Any = None  # diffusers pipeline in real mode
        self._img2img_pipe: Any = None  # lazily-built img2img view sharing _pipe's weights
        self._inpaint_pipe: Any = None  # lazily-built inpaint view sharing _pipe's weights
        self._controlnet_pipe: Any = None
        self._controlnet_model: Any = None
        self._controlnet_pipes: dict[tuple[str, str], Any] = {}
        self._controlnet_models: dict[str, Any] = {}
        self._active_features: dict[str, Any] = {}
        self._loaded_loras: dict[str, str] = {}
        self._loaded_lora_last_used: dict[str, int] = {}
        self._generation_index = 0
        self._accelerator: accelerator_runtime.AcceleratorRuntime | None = None
        self._accelerator_allocated_baseline_gb: float | None = None
        self._stop = False

    def _require_peft_for_lora(self) -> None:
        if importlib.util.find_spec("peft") is not None:
            return
        raise RuntimeError(
            "LoRA support in Diffusers requires the optional Python package 'peft'. "
            "Run setup/update again, or install the accelerator requirements for your "
            "profile, then restart HFabric."
        )

    def _is_z_image_turbo(self) -> bool:
        if self.descriptor.family is not ModelFamily.Z_IMAGE:
            return False
        text = f"{self.descriptor.id} {self.descriptor.name} {self.descriptor.path}".lower()
        return self._is_nunchaku_quant() or "turbo" in text

    def _z_image_default_steps(self) -> int:
        if self._is_z_image_turbo():
            return settings.z_image_default_steps
        return settings.z_image_base_default_steps

    def _z_image_default_guidance(self) -> float:
        if self._is_z_image_turbo():
            return settings.z_image_default_guidance
        return settings.z_image_base_default_guidance

    def request_stop(self) -> None:
        """Ask the denoise loop to abort at the next step (see step callbacks)."""
        self._stop = True

    @property
    def can_keep_warm(self) -> bool:
        return True

    # ----------------------------------------------------------------- load
    async def load(self) -> None:
        if self._loaded:
            return
        if self._warm:
            if settings.stub_mode:
                await asyncio.sleep(0.1)
                self._loaded = True
                self._warm = False
                self._load_report = {"keep_warm": {"resumed": True, "stub": True}}
                return
            if self._pipe is not None:
                await asyncio.to_thread(self._resume_pipeline_sync)
                self._loaded = True
                self._warm = False
                return
        if settings.stub_mode:
            await asyncio.sleep(0.4)  # simulate load latency
            self._loaded = True
            return
        # --- real path (exercised in M0) ---
        await asyncio.to_thread(self._load_pipeline_sync)
        self._loaded = True

    def _load_pipeline_sync(self) -> None:
        # Loaders verified on RTX 5070 Ti (Blackwell) in M0.
        import os  # noqa: PLC0415

        import torch  # noqa: PLC0415  (lazy: only when GPU mode is on)

        self._accelerator = accelerator_runtime.current()
        self._accelerator.require_available(torch)
        self._ensure_runtime_support(self._accelerator)
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        self._active_features = {}
        self._loaded_loras = {}
        self._loaded_lora_last_used = {}
        report: dict[str, Any] = {
            "accelerator": self._accelerator.public(),
            "acceleration": {},
            "memory": {"start": self._memory_snapshot(torch)},
        }

        if self.descriptor.family is ModelFamily.ANIMA:
            pipe = self._load_anima(torch)
        elif self.descriptor.family is ModelFamily.FLUX2 and self._is_nunchaku_quant():
            pipe = self._load_nunchaku_flux2_klein(torch)
        elif self.descriptor.family is ModelFamily.FLUX2:
            pipe = self._load_flux2_klein(torch)
        elif self.descriptor.family is ModelFamily.QWEN_IMAGE_EDIT:
            pipe = self._load_qwen_image_edit(torch)
        elif self.descriptor.family is ModelFamily.FLUX_KONTEXT:
            pipe = self._load_flux_kontext(torch)
        elif self.descriptor.family is ModelFamily.QWEN_IMAGE:
            pipe = self._load_qwen_image(torch)
        elif self.descriptor.family is ModelFamily.Z_IMAGE:
            pipe = self._load_z_image(torch)
        elif self._is_nunchaku_quant():
            pipe = self._load_nunchaku_flux(torch)
        elif self.descriptor.family is ModelFamily.FLUX:
            pipe = self._load_flux(torch)
        else:
            pipe = self._load_sdxl(torch)
        self._pipe = pipe
        self._apply_acceleration(torch, pipe, report)
        report["memory"]["end"] = self._memory_snapshot(torch)
        self._remember_accelerator_baseline(torch)
        self._load_report = report

    # --------------------------------------------------------------- unload

    # ------------------------------------------------------- post-job hygiene

    # ------------------------------------------------------------- generate
    async def generate(self, params: dict[str, Any], progress: ProgressCb) -> list[dict[str, Any]]:
        width = self._dimension(params, "width", settings.default_width, settings.flux2_default_width)
        height = self._dimension(params, "height", settings.default_height, settings.flux2_default_height)
        width, height = self._normalize_dims(width, height)
        steps = self._steps(params)
        batch = int(params.get("batch_size", 1))
        base_seed = params.get("seed")
        if base_seed in (None, -1):
            base_seed = random.randint(0, 2**31 - 1)

        # For img2img/inpainting, a source image steers
        # generation; an optional mask constrains the repaint region.
        if params.get("mask_image") and not params.get("init_image"):
            raise ValueError("inpainting requires an img2img source image")
        edit_families = {
            ModelFamily.ANIMA,
            ModelFamily.SDXL,
            ModelFamily.FLUX,
            ModelFamily.FLUX2,
            ModelFamily.QWEN_IMAGE,
            ModelFamily.QWEN_IMAGE_EDIT,
            ModelFamily.Z_IMAGE,
            ModelFamily.FLUX_KONTEXT,
        }
        if (
            params.get("init_image") or params.get("mask_image")
        ) and self.descriptor.family not in edit_families:
            raise ValueError("this model family does not support latent img2img/inpainting")
        if params.get("mask_image") and self.descriptor.family is ModelFamily.ANIMA:
            raise ValueError("Anima supports img2img but not inpainting")
        if self._edit_mode(params) == "outpaint" and not params.get("init_image"):
            raise ValueError("outpainting requires a source image")
        if self._edit_mode(params) == "outpaint" and self.descriptor.family is ModelFamily.ANIMA:
            raise ValueError("Anima does not support outpainting")
        instruction_families = {ModelFamily.QWEN_IMAGE_EDIT, ModelFamily.FLUX_KONTEXT}
        if self.descriptor.family in instruction_families:
            if not params.get("init_image"):
                raise ValueError("instruction editing requires a source image")
            if params.get("mask_image") or self._edit_mode(params) in {"inpaint", "outpaint"}:
                raise ValueError("instruction-edit models do not use an inpaint mask")
        if params.get("control_image"):
            if self.descriptor.family is not ModelFamily.SDXL:
                raise ValueError("ControlNet is currently supported only for SDXL models")

        self._stop = False
        results: list[dict[str, Any]] = []
        for i in range(batch):
            seed = int(base_seed) + i
            self._generation_index += 1
            if settings.stub_mode:
                rec = await self._generate_stub(params, width, height, steps, seed, i, batch, progress)
            else:
                rec = await self._generate_real(params, width, height, steps, seed, i, batch, progress)
            results.append(rec)
        return results

    async def _generate_stub(self, params, width, height, steps, seed, i, batch, progress) -> dict[str, Any]:
        for s in range(steps):
            await asyncio.sleep(0.03)
            frac = (i + (s + 1) / steps) / batch
            await progress(frac, f"step {s + 1}/{steps} (img {i + 1}/{batch})")
        meta = {
            **self._public_params(params),
            "seed": seed,
            "width": width,
            "height": height,
            "model": self.descriptor.name,
            "family": self.descriptor.family.value,
            "stub": True,
            "acceleration": self._active_features,
        }
        self._add_edit_meta(meta, params, steps)
        if params.get("control_image"):
            meta["controlnet"] = {
                "type": params.get("control_type") or "canny",
                "scale": self._control_scale(params),
            }
        lines = [
            f"[STUB] {self.descriptor.name}",
            f"seed={seed}  {width}x{height}  steps={steps}",
            f"prompt: {params.get('prompt', '')}",
        ]
        if params.get("init_image"):
            if self.descriptor.family is ModelFamily.FLUX2 and not params.get("mask_image"):
                lines.append("FLUX.2 reference conditioning")
            else:
                lines.append(f"img2img strength={self._resolved_strength(params, steps):.2f}")
        if params.get("mask_image"):
            lines.append("inpaint mask: enabled")
        if params.get("control_image"):
            lines.append(
                f"controlnet {params.get('control_type') or 'canny'} scale={self._control_scale(params):.2f}"
            )
        return await asyncio.to_thread(
            self._persist_placeholder,
            lines,
            meta,
            seed,
            width,
            height,
        )

    async def _generate_real(self, params, width, height, steps, seed, i, batch, progress) -> dict[str, Any]:
        import torch  # noqa: PLC0415

        result = await run_real_generation(
            self,
            torch,
            params,
            width=width,
            height=height,
            steps=steps,
            seed=seed,
            i=i,
            batch=batch,
            progress=progress,
        )
        meta = {
            **self._public_params(params),
            "seed": seed,
            "width": width,
            "height": height,
            "steps": steps,
            "guidance": self._guidance(params),
            "model": self.descriptor.name,
            "family": self.descriptor.family.value,
            "acceleration": self._active_features,
        }
        self._add_edit_meta(meta, params, steps)
        if result.has_mask:
            meta["inpaint"] = True
        if result.control_token:
            meta["controlnet"] = {
                "type": params.get("control_type") or "canny",
                "scale": self._control_scale(params),
            }
        return await asyncio.to_thread(
            self._persist,
            result.image,
            meta,
            seed,
            width,
            height,
        )

    def _normalize_dims(self, width: int, height: int) -> tuple[int, int]:
        """Snap a request onto the grid the model actually accepts.

        Anima hard-requires multiples of 64 in [512, 1536]; rather than fail a
        queued job over an off-grid size (a reproduced/preset value, a custom
        entry, or a size carried over from another family), round to the nearest
        valid cell so generation proceeds instead of erroring."""
        if self.descriptor.family is not ModelFamily.ANIMA:
            return width, height

        def snap(value: int) -> int:
            return max(512, min(1536, round(value / 64) * 64))

        return snap(width), snap(height)

    def _dimension(self, params: dict[str, Any], key: str, default: int, flux2_default: int) -> int:
        if key not in params:
            if self.descriptor.family is ModelFamily.ANIMA:
                return settings.anima_default_width if key == "width" else settings.anima_default_height
            if self.descriptor.family is ModelFamily.FLUX2:
                return flux2_default
            if self.descriptor.family in (ModelFamily.QWEN_IMAGE, ModelFamily.QWEN_IMAGE_EDIT):
                return (
                    settings.qwen_image_default_width
                    if key == "width"
                    else settings.qwen_image_default_height
                )
            if self.descriptor.family is ModelFamily.Z_IMAGE:
                return settings.z_image_default_width if key == "width" else settings.z_image_default_height
            if self.descriptor.family is ModelFamily.FLUX_KONTEXT:
                return default
        return int(params.get(key, default))

    def _steps(self, params: dict[str, Any]) -> int:
        steps = int(params.get("steps", settings.default_steps))
        untouched = "steps" not in params or steps == settings.default_steps
        if self._is_sdxl_lightning_checkpoint() and untouched:
            return 4
        if self.descriptor.family is ModelFamily.ANIMA and untouched:
            return settings.anima_default_steps
        if self.descriptor.family is ModelFamily.FLUX2 and untouched:
            return settings.flux2_default_steps
        if self.descriptor.family is ModelFamily.QWEN_IMAGE and untouched:
            return settings.qwen_image_default_steps
        if self.descriptor.family is ModelFamily.QWEN_IMAGE_EDIT and untouched:
            return settings.qwen_image_edit_default_steps
        if self.descriptor.family is ModelFamily.FLUX_KONTEXT and untouched:
            return settings.flux_kontext_default_steps
        if self.descriptor.family is ModelFamily.Z_IMAGE and untouched:
            return self._z_image_default_steps()
        if self._active_features.get("sdxl_turbo_lora") and params.get("turbo", True):
            if untouched:
                return settings.sdxl_turbo_steps
        return steps

    def _guidance(self, params: dict[str, Any]) -> float:
        guidance = float(params.get("guidance", settings.default_guidance))
        untouched = "guidance" not in params or guidance == settings.default_guidance
        if self._is_sdxl_lightning_checkpoint() and untouched:
            return 1.0
        if self.descriptor.family is ModelFamily.ANIMA and untouched:
            return settings.anima_default_guidance
        if self.descriptor.family is ModelFamily.FLUX2 and untouched:
            return settings.flux2_default_guidance
        if self.descriptor.family is ModelFamily.QWEN_IMAGE and untouched:
            return settings.qwen_image_default_guidance
        if self.descriptor.family is ModelFamily.QWEN_IMAGE_EDIT and untouched:
            return settings.qwen_image_edit_default_guidance
        if self.descriptor.family is ModelFamily.FLUX_KONTEXT and untouched:
            return settings.flux_kontext_default_guidance
        if self.descriptor.family is ModelFamily.Z_IMAGE and untouched:
            return self._z_image_default_guidance()
        if self._active_features.get("sdxl_turbo_lora") and params.get("turbo", True):
            if untouched:
                return settings.sdxl_turbo_guidance
        return guidance

    @staticmethod
    def _public_params(params: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in params.items() if not k.startswith("_")}

    def _persist(self, img, meta, seed, width, height) -> dict[str, Any]:
        out_dir = imaging.day_dir(settings.outputs_dir)
        stem = f"{seed}_{random.randint(1000, 9999)}"
        png_path = out_dir / f"{stem}.png"
        thumb_path = out_dir / f"{stem}.thumb.webp"
        imaging.save_png(img, png_path, meta)
        imaging.make_thumbnail(img, thumb_path)
        return {
            "path": str(png_path),
            "thumb_path": str(thumb_path),
            "seed": seed,
            "width": width,
            "height": height,
            "family": meta.get("family"),
            "params": meta,
        }

    def _persist_placeholder(
        self,
        lines: list[str],
        meta: dict[str, Any],
        seed: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        image = imaging.make_placeholder(width, height, lines)
        return self._persist(image, meta, seed, width, height)
