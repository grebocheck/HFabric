"""Real image generation dispatch for the Diffusers image backend.

The concrete backend owns lifecycle, metadata, persistence, and all family
helpers. This module keeps the high-churn txt2img/img2img/inpaint/controlnet
branching out of the backend class so mode-specific edits are easier to review.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ...core.enums import ModelFamily
from ..base import GenerationCancelled, ProgressCb


@dataclass(frozen=True)
class RealGenerationResult:
    image: Any
    has_mask: bool
    control_token: Any


@dataclass(frozen=True)
class RealGenerationRequest:
    params: dict[str, Any]
    width: int
    height: int
    steps: int
    seed: int
    index: int
    batch: int
    family: ModelFamily
    init_token: Any
    mask_token: Any
    control_token: Any
    strength: float
    has_mask: bool


def _step_callback(backend: Any, loop, progress: ProgressCb, req: RealGenerationRequest):
    def callback(*args):
        if backend._stop:
            raise GenerationCancelled()
        step = int(args[1] if len(args) >= 4 else args[0])
        frac = (req.index + (step + 1) / req.steps) / req.batch
        asyncio.run_coroutine_threadsafe(
            progress(frac, f"step {step + 1}/{req.steps} (img {req.index + 1}/{req.batch})"),
            loop,
        )
        return args[-1] if args else None

    return callback


def _common_kwargs(backend: Any, torch, req: RealGenerationRequest, callback) -> dict[str, Any]:
    common = {
        "prompt": req.params.get("prompt", ""),
        "num_inference_steps": req.steps,
        "guidance_scale": backend._guidance(req.params),
        "generator": backend._runtime().generator(torch, req.seed),
        "negative_prompt": req.params.get("negative") or None,
        "callback_on_step_end": callback,
    }
    if req.family is ModelFamily.FLUX2:
        common.pop("negative_prompt", None)
    elif req.family in (ModelFamily.QWEN_IMAGE, ModelFamily.QWEN_IMAGE_EDIT):
        common["true_cfg_scale"] = common.pop("guidance_scale")
    return common


def _call_controlnet(backend: Any, torch, req: RealGenerationRequest, common: dict[str, Any]):
    control = backend._load_control_image(req.control_token, req.width, req.height, req.params.get("control_type"))
    control_type = str(req.params.get("control_type") or "canny")
    control_mode = backend._controlnet_mode_kwargs(control_type)
    if req.init_token and req.has_mask:
        src = backend._load_init_image(req.init_token, req.width, req.height, req.params)
        mask = backend._load_mask_image(req.mask_token, req.width, req.height, req.params)
        return backend._sdxl_controlnet_pipe(torch, "inpaint", control_type)(
            image=src,
            mask_image=mask,
            control_image=control,
            width=req.width,
            height=req.height,
            padding_mask_crop=backend._padding_mask_crop(req.params),
            strength=req.strength,
            controlnet_conditioning_scale=backend._control_scale(req.params),
            **control_mode,
            **common,
        )
    if req.init_token:
        src = backend._load_init_image(req.init_token, req.width, req.height, req.params)
        return backend._sdxl_controlnet_pipe(torch, "img2img", control_type)(
            image=src,
            control_image=control,
            width=req.width,
            height=req.height,
            strength=req.strength,
            controlnet_conditioning_scale=backend._control_scale(req.params),
            **control_mode,
            **common,
        )
    return backend._sdxl_controlnet_pipe(torch, "text2img", control_type)(
        image=control,
        width=req.width,
        height=req.height,
        controlnet_conditioning_scale=backend._control_scale(req.params),
        **control_mode,
        **common,
    )


def _call_masked_edit(backend: Any, req: RealGenerationRequest, common: dict[str, Any]):
    src = backend._load_init_image(req.init_token, req.width, req.height, req.params)
    mask = backend._load_mask_image(req.mask_token, req.width, req.height, req.params)
    padding_crop = backend._padding_mask_crop(req.params)
    if req.family is ModelFamily.SDXL:
        return backend._sdxl_inpaint_pipe()(
            image=src,
            mask_image=mask,
            width=req.width,
            height=req.height,
            padding_mask_crop=padding_crop,
            strength=req.strength,
            **common,
        )
    if req.family is ModelFamily.FLUX:
        return backend._flux_inpaint_pipe()(
            image=src,
            mask_image=mask,
            width=req.width,
            height=req.height,
            padding_mask_crop=padding_crop,
            strength=req.strength,
            **common,
        )
    if req.family is ModelFamily.FLUX2:
        return backend._flux2_inpaint_pipe()(
            image=src,
            mask_image=mask,
            width=req.width,
            height=req.height,
            padding_mask_crop=padding_crop,
            strength=req.strength,
            **common,
        )
    if req.family is ModelFamily.QWEN_IMAGE:
        return backend._qwen_inpaint_pipe()(
            image=src,
            mask_image=mask,
            width=req.width,
            height=req.height,
            padding_mask_crop=padding_crop,
            strength=req.strength,
            **common,
        )
    return backend._z_image_inpaint_pipe()(
        image=src,
        mask_image=mask,
        width=req.width,
        height=req.height,
        strength=req.strength,
        **common,
    )


def _call_img2img(backend: Any, req: RealGenerationRequest, common: dict[str, Any]):
    src = backend._load_init_image(req.init_token, req.width, req.height, req.params)
    if req.family in (ModelFamily.QWEN_IMAGE_EDIT, ModelFamily.FLUX_KONTEXT):
        return backend._pipe(image=src, width=req.width, height=req.height, **common)
    if req.family is ModelFamily.SDXL:
        return backend._sdxl_img2img_pipe()(image=src, strength=req.strength, **common)
    if req.family is ModelFamily.FLUX:
        return backend._flux_img2img_pipe()(
            image=src, width=req.width, height=req.height, strength=req.strength, **common
        )
    if req.family is ModelFamily.QWEN_IMAGE:
        return backend._qwen_img2img_pipe()(
            image=src, width=req.width, height=req.height, strength=req.strength, **common
        )
    if req.family is ModelFamily.Z_IMAGE:
        return backend._z_image_img2img_pipe()(
            image=src, width=req.width, height=req.height, strength=req.strength, **common
        )
    if req.family is ModelFamily.ANIMA:
        return backend._pipe(image=src, width=req.width, height=req.height, strength=req.strength, **common)
    # FLUX.2 klein's pipeline accepts a source/reference image but does not
    # expose a denoise-strength knob.
    return backend._pipe(image=src, width=req.width, height=req.height, **common)


def _call_text2img(backend: Any, req: RealGenerationRequest, common: dict[str, Any]):
    return backend._pipe(**common, width=req.width, height=req.height)


async def run_real_generation(
    backend: Any,
    torch,
    params: dict[str, Any],
    *,
    width: int,
    height: int,
    steps: int,
    seed: int,
    i: int,
    batch: int,
    progress: ProgressCb,
) -> RealGenerationResult:
    loop = asyncio.get_running_loop()
    family = backend.descriptor.family
    init_token = params.get("init_image")
    mask_token = params.get("mask_image")
    control_token = params.get("control_image")
    edit_mode = backend._edit_mode(params)
    req = RealGenerationRequest(
        params=params,
        width=width,
        height=height,
        steps=steps,
        seed=seed,
        index=i,
        batch=batch,
        family=family,
        init_token=init_token,
        mask_token=mask_token,
        control_token=control_token,
        strength=backend._resolved_strength(params, steps),
        has_mask=bool(mask_token or edit_mode == "outpaint"),
    )
    callback = _step_callback(backend, loop, progress, req)

    def run():
        backend._apply_runtime_loras(params)
        common = _common_kwargs(backend, torch, req, callback)
        with backend._generation_context(steps), backend._attention_context(torch):
            if control_token:
                output = _call_controlnet(backend, torch, req, common)
            elif init_token and req.has_mask:
                output = _call_masked_edit(backend, req, common)
            elif init_token:
                output = _call_img2img(backend, req, common)
            else:
                output = _call_text2img(backend, req, common)
        return output.images[0]

    image = await asyncio.to_thread(run)
    return RealGenerationResult(image=image, has_mask=req.has_mask, control_token=control_token)
