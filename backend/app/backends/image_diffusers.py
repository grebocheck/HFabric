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
from pathlib import Path
import random
from typing import Any

from ..config import settings
from ..core.enums import ModelFamily
from ..services import accelerator_runtime
from ..util import imaging
from .base import GenerationCancelled, ImageBackend, ModelDescriptor, ProgressCb
from .image_diffusers_parts import (
    DiffusersMemoryMixin,
    DiffusersPipelineMixin,
    Flux2LoaderMixin,
    FluxLoaderMixin,
    QwenZLoaderMixin,
    SdxlLoaderMixin,
)


class DiffusersImageBackend(
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
        self._active_features: dict[str, Any] = {}
        self._loaded_loras: dict[str, str] = {}
        self._loaded_lora_last_used: dict[str, int] = {}
        self._generation_index = 0
        self._accelerator: accelerator_runtime.AcceleratorRuntime | None = None
        self._accelerator_allocated_baseline_gb: float | None = None
        self._stop = False

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

        if self.descriptor.family is ModelFamily.FLUX2 and self._is_nunchaku_quant():
            pipe = self._load_nunchaku_flux2_klein(torch)
        elif self.descriptor.family is ModelFamily.FLUX2:
            pipe = self._load_flux2_klein(torch)
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
    async def generate(
        self, params: dict[str, Any], progress: ProgressCb
    ) -> list[dict[str, Any]]:
        width = self._dimension(params, "width", settings.default_width, settings.flux2_default_width)
        height = self._dimension(params, "height", settings.default_height, settings.flux2_default_height)
        steps = self._steps(params)
        batch = int(params.get("batch_size", 1))
        base_seed = params.get("seed")
        if base_seed in (None, -1):
            base_seed = random.randint(0, 2**31 - 1)

        # img2img/inpainting (P13.4/P13.5/P19.1): a source image steers
        # generation; an optional mask constrains the repaint region.
        if params.get("mask_image") and not params.get("init_image"):
            raise ValueError("inpainting requires an img2img source image")
        edit_families = {ModelFamily.SDXL, ModelFamily.FLUX, ModelFamily.FLUX2}
        if (params.get("init_image") or params.get("mask_image")) and self.descriptor.family not in edit_families:
            raise ValueError("img2img/inpainting is currently supported only for SDXL, FLUX, and FLUX.2 models")
        if params.get("control_image"):
            if self.descriptor.family is not ModelFamily.SDXL:
                raise ValueError("ControlNet is currently supported only for SDXL models")
            if params.get("init_image") or params.get("mask_image"):
                raise ValueError("ControlNet cannot be combined with img2img/inpainting yet")

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
        meta = {**self._public_params(params), "seed": seed, "width": width, "height": height,
                "model": self.descriptor.name, "family": self.descriptor.family.value, "stub": True,
                "acceleration": self._active_features}
        self._add_strength_meta(meta, params, steps)
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
            lines.append(f"img2img strength={self._effective_strength(params, steps):.2f}")
        if params.get("mask_image"):
            lines.append("inpaint mask: enabled")
        if params.get("control_image"):
            lines.append(f"controlnet {params.get('control_type') or 'canny'} scale={self._control_scale(params):.2f}")
        img = imaging.make_placeholder(width, height, lines)
        return self._persist(img, meta, seed, width, height)

    async def _generate_real(self, params, width, height, steps, seed, i, batch, progress) -> dict[str, Any]:
        import torch  # noqa: PLC0415

        loop = asyncio.get_running_loop()

        def _step_cb(pipe, step, timestep, kw):
            if self._stop:
                raise GenerationCancelled()
            frac = (i + (step + 1) / steps) / batch
            asyncio.run_coroutine_threadsafe(
                progress(frac, f"step {step + 1}/{steps} (img {i + 1}/{batch})"), loop
            )
            return kw

        def _step_cb_flux2(*cb_args):
            if self._stop:
                raise GenerationCancelled()
            if len(cb_args) == 4:
                _, step, timestep, kw = cb_args
            else:
                step, timestep, kw = cb_args
            frac = (i + (step + 1) / steps) / batch
            asyncio.run_coroutine_threadsafe(
                progress(frac, f"step {step + 1}/{steps} (img {i + 1}/{batch})"), loop
            )
            return kw

        init_token = params.get("init_image")
        mask_token = params.get("mask_image")
        control_token = params.get("control_image")
        strength = self._effective_strength(params, steps)
        family = self.descriptor.family

        def _run():
            gen = self._runtime().generator(torch, seed)
            self._apply_runtime_loras(params)
            callback = (
                _step_cb_flux2
                if family in (ModelFamily.FLUX2, ModelFamily.QWEN_IMAGE, ModelFamily.Z_IMAGE)
                else _step_cb
            )
            common = {
                "prompt": params.get("prompt", ""),
                "num_inference_steps": steps,
                "guidance_scale": self._guidance(params),
                "generator": gen,
                "negative_prompt": params.get("negative") or None,
                "callback_on_step_end": callback,
            }
            if family is ModelFamily.FLUX2:
                common.pop("negative_prompt", None)
            elif family is ModelFamily.QWEN_IMAGE:
                common["true_cfg_scale"] = common.pop("guidance_scale")
            with self._generation_context(steps), self._attention_context(torch):
                if control_token:
                    control = self._load_control_image(control_token, width, height, params.get("control_type"))
                    out = self._sdxl_controlnet_pipe(torch)(
                        image=control,
                        width=width,
                        height=height,
                        controlnet_conditioning_scale=self._control_scale(params),
                        **common,
                    )
                elif init_token and mask_token:
                    src = self._load_init_image(init_token, width, height)
                    mask = self._load_mask_image(mask_token, width, height)
                    if family is ModelFamily.SDXL:
                        out = self._sdxl_inpaint_pipe()(image=src, mask_image=mask, strength=strength, **common)
                    elif family is ModelFamily.FLUX:
                        out = self._flux_inpaint_pipe()(
                            image=src, mask_image=mask, width=width, height=height, strength=strength, **common
                        )
                    else:
                        out = self._flux2_inpaint_pipe()(
                            image=src, mask_image=mask, width=width, height=height, strength=strength, **common
                        )
                elif init_token:
                    src = self._load_init_image(init_token, width, height)
                    if family is ModelFamily.SDXL:
                        out = self._sdxl_img2img_pipe()(image=src, strength=strength, **common)
                    elif family is ModelFamily.FLUX:
                        out = self._flux_img2img_pipe()(
                            image=src, width=width, height=height, strength=strength, **common
                        )
                    else:
                        # FLUX.2 klein's pipeline accepts a source/reference
                        # image but does not expose a denoise-strength knob.
                        out = self._pipe(image=src, width=width, height=height, **common)
                else:
                    call_kwargs = {
                        **common,
                        "width": width,
                        "height": height,
                    }
                    out = self._pipe(**call_kwargs)
            return out.images[0]

        img = await asyncio.to_thread(_run)
        meta = {**self._public_params(params), "seed": seed, "width": width, "height": height,
                "steps": steps, "guidance": self._guidance(params),
                "model": self.descriptor.name, "family": self.descriptor.family.value,
                "acceleration": self._active_features}
        self._add_strength_meta(meta, params, steps)
        if mask_token:
            meta["inpaint"] = True
        if control_token:
            meta["controlnet"] = {
                "type": params.get("control_type") or "canny",
                "scale": self._control_scale(params),
            }
        return self._persist(img, meta, seed, width, height)

    @staticmethod
    def _strength(params: dict[str, Any]) -> float:
        """img2img denoise strength, clamped to a sane range."""
        try:
            value = float(params.get("strength", settings.img2img_default_strength))
        except (TypeError, ValueError):
            value = settings.img2img_default_strength
        return max(0.05, min(1.0, value))

    @classmethod
    def _effective_strength(cls, params: dict[str, Any], steps: int) -> float:
        """Diffusers img2img floors ``steps * strength`` to choose timesteps.
        Keep low-step smoke/tests from producing a zero-length denoise schedule."""
        return max(cls._strength(params), 1.0 / max(1, int(steps)))

    @classmethod
    def _add_strength_meta(cls, meta: dict[str, Any], params: dict[str, Any], steps: int) -> None:
        if not params.get("init_image"):
            return
        requested = cls._strength(params)
        effective = cls._effective_strength(params, steps)
        meta["strength"] = effective
        if effective != requested:
            meta["requested_strength"] = requested

    def _load_init_image(self, token: str, width: int, height: int):
        """Open an uploaded source image and resize it to the requested canvas so
        the img2img output matches the composer's width/height."""
        from PIL import Image as PILImage  # noqa: PLC0415

        from ..util import uploads as uploads_util  # noqa: PLC0415

        path = uploads_util.resolve_upload(token)
        if path is None or not path.exists():
            raise ValueError("img2img source image not found (re-upload it)")
        return PILImage.open(path).convert("RGB").resize((width, height))

    def _load_mask_image(self, token: str, width: int, height: int):
        """Open an uploaded inpaint mask and resize it to the requested canvas.
        White pixels are repainted; black pixels are preserved."""
        from PIL import Image as PILImage  # noqa: PLC0415

        from ..util import uploads as uploads_util  # noqa: PLC0415

        path = uploads_util.resolve_upload(token)
        if path is None or not path.exists():
            raise ValueError("inpainting mask not found (re-upload it)")
        return PILImage.open(path).convert("L").resize((width, height))

    @staticmethod
    def _control_scale(params: dict[str, Any]) -> float:
        try:
            value = float(params.get("control_scale", settings.sdxl_controlnet_default_scale))
        except (TypeError, ValueError):
            value = settings.sdxl_controlnet_default_scale
        return max(0.0, min(2.0, value))

    def _load_control_image(self, token: str, width: int, height: int, control_type: Any):
        from PIL import Image as PILImage  # noqa: PLC0415
        from PIL import ImageFilter, ImageOps  # noqa: PLC0415

        from ..util import uploads as uploads_util  # noqa: PLC0415

        control = str(control_type or "canny").lower().strip()
        if control != "canny":
            raise ValueError("only canny ControlNet is supported")
        path = uploads_util.resolve_upload(token)
        if path is None or not path.exists():
            raise ValueError("ControlNet source image not found (re-upload it)")
        img = PILImage.open(path).convert("RGB").resize((width, height))
        edges = ImageOps.grayscale(img).filter(ImageFilter.FIND_EDGES)
        edges = ImageOps.autocontrast(edges)
        return PILImage.merge("RGB", (edges, edges, edges))



    def _dimension(self, params: dict[str, Any], key: str, default: int, flux2_default: int) -> int:
        if key not in params:
            if self.descriptor.family is ModelFamily.FLUX2:
                return flux2_default
            if self.descriptor.family is ModelFamily.QWEN_IMAGE:
                return (
                    settings.qwen_image_default_width
                    if key == "width"
                    else settings.qwen_image_default_height
                )
            if self.descriptor.family is ModelFamily.Z_IMAGE:
                return (
                    settings.z_image_default_width
                    if key == "width"
                    else settings.z_image_default_height
                )
        return int(params.get(key, default))

    def _steps(self, params: dict[str, Any]) -> int:
        steps = int(params.get("steps", settings.default_steps))
        untouched = "steps" not in params or steps == settings.default_steps
        if self._is_sdxl_lightning_checkpoint() and untouched:
            return 4
        if self.descriptor.family is ModelFamily.FLUX2 and untouched:
            return settings.flux2_default_steps
        if self.descriptor.family is ModelFamily.QWEN_IMAGE and untouched:
            return settings.qwen_image_default_steps
        if self.descriptor.family is ModelFamily.Z_IMAGE and untouched:
            return settings.z_image_default_steps
        if self._active_features.get("sdxl_turbo_lora") and params.get("turbo", True):
            if untouched:
                return settings.sdxl_turbo_steps
        return steps

    def _guidance(self, params: dict[str, Any]) -> float:
        guidance = float(params.get("guidance", settings.default_guidance))
        untouched = "guidance" not in params or guidance == settings.default_guidance
        if self._is_sdxl_lightning_checkpoint() and untouched:
            return 1.0
        if self.descriptor.family is ModelFamily.FLUX2 and untouched:
            return settings.flux2_default_guidance
        if self.descriptor.family is ModelFamily.QWEN_IMAGE and untouched:
            return settings.qwen_image_default_guidance
        if self.descriptor.family is ModelFamily.Z_IMAGE and untouched:
            return settings.z_image_default_guidance
        if self._active_features.get("sdxl_turbo_lora") and params.get("turbo", True):
            if untouched:
                return settings.sdxl_turbo_guidance
        return guidance




    def _apply_runtime_loras(self, params: dict[str, Any]) -> None:
        adapters: list[str] = []
        weights: list[float] = []
        turbo = self._active_features.get("sdxl_turbo_lora")
        if turbo and params.get("turbo", True):
            adapters.append("turbo")
            weights.append(float(turbo["weight"]))

        requests = self._lora_requests(params)
        if requests and not hasattr(self._pipe, "load_lora_weights"):
            raise RuntimeError(f"Pipeline for {self.descriptor.name} does not support LoRA loading")
        for request in requests:
            adapter = self._load_lora_adapter(request["id"], Path(request["path"]))
            adapters.append(adapter)
            weights.append(float(request["weight"]))
            self._loaded_lora_last_used[request["id"]] = self._generation_index

        if adapters:
            if not hasattr(self._pipe, "set_adapters"):
                raise RuntimeError(f"Pipeline for {self.descriptor.name} does not support LoRA adapters")
            self._pipe.set_adapters(adapters, adapter_weights=weights)
            if hasattr(self._pipe, "enable_lora"):
                self._pipe.enable_lora()
        elif hasattr(self._pipe, "disable_lora"):
            self._pipe.disable_lora()

    def _lora_requests(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raw_loras = params.get("loras") or []
        paths = params.get("_lora_paths") or {}
        if not isinstance(raw_loras, list) or not isinstance(paths, dict):
            return []

        requests: list[dict[str, Any]] = []
        for item in raw_loras:
            if not isinstance(item, dict):
                continue
            lora_id = item.get("id")
            if not isinstance(lora_id, str):
                continue
            path = item.get("path") or paths.get(lora_id)
            if not isinstance(path, str):
                raise RuntimeError(f"LoRA {lora_id!r} is missing its validated path")
            requests.append({
                "id": lora_id,
                "path": path,
                "weight": float(item.get("weight", 1.0)),
            })
        return requests

    def _requested_lora_ids(self, params: dict[str, Any]) -> set[str]:
        raw_loras = params.get("loras") or []
        if not isinstance(raw_loras, list):
            return set()
        ids: set[str] = set()
        for item in raw_loras:
            if isinstance(item, str):
                ids.add(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.add(item["id"])
        return ids

    def _load_lora_adapter(self, lora_id: str, path: Path) -> str:
        if lora_id in self._loaded_loras:
            return self._loaded_loras[lora_id]
        if not path.exists():
            raise FileNotFoundError(f"LoRA file not found: {path}")

        adapter = self._lora_adapter_name(lora_id)
        if path.is_dir():
            self._pipe.load_lora_weights(str(path), adapter_name=adapter)
        elif path.suffix.lower() == ".safetensors":
            self._pipe.load_lora_weights(str(path.parent), weight_name=path.name, adapter_name=adapter)
        else:
            self._pipe.load_lora_weights(str(path), adapter_name=adapter)
        self._loaded_loras[lora_id] = adapter
        self._loaded_lora_last_used[lora_id] = self._generation_index
        return adapter

    def _prune_lora_cache(self, keep_ids: set[str]) -> list[str]:
        if not self._loaded_loras:
            return []

        max_cached = int(settings.image_lora_cache_max)
        if max_cached < 0:
            return []

        if max_cached == 0:
            prune_ids = list(self._loaded_loras)
        else:
            ordered = sorted(
                self._loaded_loras,
                key=lambda lora_id: self._loaded_lora_last_used.get(lora_id, -1),
            )
            prune_ids = []
            for lora_id in ordered:
                if len(self._loaded_loras) - len(prune_ids) <= max_cached:
                    break
                if lora_id not in keep_ids:
                    prune_ids.append(lora_id)
        if not prune_ids:
            return []

        adapter_names = [self._loaded_loras[lora_id] for lora_id in prune_ids]
        if hasattr(self._pipe, "delete_adapters"):
            self._pipe.delete_adapters(adapter_names)
        elif len(prune_ids) == len(self._loaded_loras) and not self._active_features.get("sdxl_turbo_lora") and hasattr(self._pipe, "unload_lora_weights"):
            self._pipe.unload_lora_weights()
        else:
            return []

        for lora_id in prune_ids:
            self._loaded_loras.pop(lora_id, None)
            self._loaded_lora_last_used.pop(lora_id, None)
        return prune_ids

    @staticmethod
    def _lora_adapter_name(lora_id: str) -> str:
        body = "".join(ch if ch.isalnum() else "_" for ch in lora_id)[:80]
        return f"lora_{body}"

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
