from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.backends.image_diffusers_parts import generation
from app.core.enums import ModelFamily


class _Runtime:
    def generator(self, torch, seed: int) -> str:
        return f"gen:{seed}"


class _Pipe:
    def __init__(self, name: str, calls: list[tuple[str, dict]]) -> None:
        self.name = name
        self.calls = calls

    def __call__(self, **kwargs):
        callback = kwargs.get("callback_on_step_end")
        if callback is not None:
            callback(None, 0, None, {"latents": "ok"})
        self.calls.append((self.name, kwargs))
        return SimpleNamespace(images=[f"image:{self.name}"])


class _Backend:
    def __init__(self, family: ModelFamily) -> None:
        self.descriptor = SimpleNamespace(family=family)
        self._stop = False
        self.calls: list[tuple[str, dict]] = []
        self._pipe = _Pipe("base", self.calls)

    def _runtime(self) -> _Runtime:
        return _Runtime()

    def _guidance(self, params: dict) -> float:
        return 7.5

    def _apply_runtime_loras(self, params: dict) -> None:
        self.calls.append(("loras", dict(params)))

    def _generation_context(self, steps: int):
        return nullcontext()

    def _attention_context(self, torch):
        return nullcontext()

    def _edit_mode(self, params: dict) -> str:
        return str(params.get("edit_mode") or ("inpaint" if params.get("mask_image") else "img2img"))

    def _resolved_strength(self, params: dict, steps: int) -> float:
        return 0.42

    def _load_init_image(self, token, width: int, height: int, params: dict):
        return f"src:{token}:{width}x{height}"

    def _load_mask_image(self, token, width: int, height: int, params: dict):
        return f"mask:{token}:{width}x{height}"

    def _load_control_image(self, token, width: int, height: int, control_type):
        return f"control:{token}:{control_type}:{width}x{height}"

    def _padding_mask_crop(self, params: dict) -> int:
        return 12

    def _control_scale(self, params: dict) -> float:
        return 0.8

    def _controlnet_mode_kwargs(self, control_type: str) -> dict:
        return {"control_mode": control_type}

    def _sdxl_img2img_pipe(self):
        return _Pipe("sdxl-img2img", self.calls)

    def _flux_img2img_pipe(self):
        return _Pipe("flux-img2img", self.calls)

    def _qwen_img2img_pipe(self):
        return _Pipe("qwen-img2img", self.calls)

    def _z_image_img2img_pipe(self):
        return _Pipe("z-img2img", self.calls)

    def _sdxl_inpaint_pipe(self):
        return _Pipe("sdxl-inpaint", self.calls)

    def _flux_inpaint_pipe(self):
        return _Pipe("flux-inpaint", self.calls)

    def _flux2_inpaint_pipe(self):
        return _Pipe("flux2-inpaint", self.calls)

    def _qwen_inpaint_pipe(self):
        return _Pipe("qwen-inpaint", self.calls)

    def _z_image_inpaint_pipe(self):
        return _Pipe("z-inpaint", self.calls)

    def _sdxl_controlnet_pipe(self, torch, mode: str, control_type: str):
        return _Pipe(f"control-{mode}-{control_type}", self.calls)


async def _run(family: ModelFamily, params: dict):
    backend = _Backend(family)
    events: list[tuple[float, str | None]] = []

    async def progress(frac: float, note: str | None) -> None:
        events.append((frac, note))

    result = await generation.run_real_generation(
        backend,
        torch=object(),
        params=params,
        width=320,
        height=256,
        steps=2,
        seed=123,
        i=0,
        batch=1,
        progress=progress,
    )
    await asyncio.sleep(0)
    return backend, result, events


@pytest.mark.parametrize(
    ("family", "params", "expected_pipe"),
    [
        (ModelFamily.SDXL, {"prompt": "p", "negative": "n"}, "base"),
        (ModelFamily.SDXL, {"prompt": "p", "init_image": "i"}, "sdxl-img2img"),
        (ModelFamily.FLUX, {"prompt": "p", "init_image": "i"}, "flux-img2img"),
        (ModelFamily.QWEN_IMAGE, {"prompt": "p", "init_image": "i"}, "qwen-img2img"),
        (ModelFamily.Z_IMAGE, {"prompt": "p", "init_image": "i"}, "z-img2img"),
        (ModelFamily.ANIMA, {"prompt": "p", "init_image": "i"}, "base"),
        (ModelFamily.FLUX2, {"prompt": "p", "init_image": "i", "negative": "ignored"}, "base"),
    ],
)
async def test_real_generation_dispatches_text_and_img2img_modes(family, params, expected_pipe):
    backend, result, events = await _run(family, params)

    pipe_name, kwargs = backend.calls[-1]
    assert pipe_name == expected_pipe
    assert result.image == f"image:{expected_pipe}"
    assert result.has_mask is False
    assert result.control_token is None
    assert kwargs["generator"] == "gen:123"
    assert events and events[0][1] == "step 1/2 (img 1/1)"

    if family is ModelFamily.QWEN_IMAGE:
        assert kwargs["true_cfg_scale"] == 7.5
        assert "guidance_scale" not in kwargs
    if family is ModelFamily.FLUX2:
        assert "negative_prompt" not in kwargs


@pytest.mark.parametrize(
    ("family", "expected_pipe"),
    [
        (ModelFamily.SDXL, "sdxl-inpaint"),
        (ModelFamily.FLUX, "flux-inpaint"),
        (ModelFamily.FLUX2, "flux2-inpaint"),
        (ModelFamily.QWEN_IMAGE, "qwen-inpaint"),
        (ModelFamily.Z_IMAGE, "z-inpaint"),
    ],
)
async def test_real_generation_dispatches_masked_edit_modes(family, expected_pipe):
    backend, result, _events = await _run(
        family,
        {"prompt": "p", "init_image": "i", "mask_image": "m"},
    )

    pipe_name, kwargs = backend.calls[-1]
    assert pipe_name == expected_pipe
    assert result.image == f"image:{expected_pipe}"
    assert result.has_mask is True
    assert kwargs["image"] == "src:i:320x256"
    assert kwargs["mask_image"] == "mask:m:320x256"
    assert kwargs["strength"] == 0.42


@pytest.mark.parametrize(
    ("params", "expected_pipe"),
    [
        ({"prompt": "p", "control_image": "c"}, "control-text2img-union-pose"),
        ({"prompt": "p", "init_image": "i", "control_image": "c"}, "control-img2img-union-pose"),
        (
            {"prompt": "p", "init_image": "i", "mask_image": "m", "control_image": "c"},
            "control-inpaint-union-pose",
        ),
    ],
)
async def test_real_generation_dispatches_controlnet_modes(params, expected_pipe):
    params = {**params, "control_type": "union-pose"}
    backend, result, _events = await _run(ModelFamily.SDXL, params)

    pipe_name, kwargs = backend.calls[-1]
    assert pipe_name == expected_pipe
    assert result.image == f"image:{expected_pipe}"
    assert result.control_token == "c"
    image_key = "image" if "text2img" in expected_pipe else "control_image"
    assert kwargs[image_key] == "control:c:union-pose:320x256"
    assert kwargs["controlnet_conditioning_scale"] == 0.8
    assert kwargs["control_mode"] == "union-pose"
