"""Local Diffusers video backend (P27).

The STUB path deliberately depends only on the foundation stack. The real path
loads local LTX/Wan repositories lazily, quantizes their heavy components while
streaming the shards, enables VAE tiling, and remains the arbiter's sole heavy
resident just like an image pipeline.
"""

from __future__ import annotations

import asyncio
import gc
import json
from pathlib import Path
import random
from typing import Any

from PIL import Image as PILImage

from ..config import settings
from ..core.enums import ModelFamily
from ..services import accelerator_runtime
from ..util import imaging, sysmon
from ..util import uploads as uploads_util
from .base import GenerationCancelled, ModelDescriptor, ProgressCb, VideoBackend

# Per-family generation defaults. The arbiter keeps a single heavy resident, so
# these mirror each model's validated recipe rather than one global compromise.
# Frame rate matters most: LTX-Video conditions the transformer on it and the
# model card calls for 24-30 fps, so the old global 16 fps default sat below the
# trained range and produced temporal artifacts. Wan 2.2 TI2V-5B is likewise a
# 24 fps model and prefers stronger guidance than LTX.
_FAMILY_GEN_DEFAULTS: dict[ModelFamily, dict[str, Any]] = {
    ModelFamily.LTX_VIDEO: {"width": 704, "height": 512, "frames": 49, "fps": 24, "steps": 30, "guidance": 3.0},
    ModelFamily.WAN_VIDEO: {"width": 832, "height": 480, "frames": 49, "fps": 24, "steps": 30, "guidance": 5.0},
    ModelFamily.HUNYUAN_VIDEO: {
        "width": 480,
        "height": 832,
        "frames": 91,
        "fps": 30,
        "steps": 30,
        "guidance": 9.0,
        "latent_window_size": 9,
    },
}


def family_video_default(family: ModelFamily, key: str, fallback: Any) -> Any:
    return _FAMILY_GEN_DEFAULTS.get(family, {}).get(key, fallback)


def framepack_sections(frames: int, latent_window_size: int = 9) -> int:
    window_frames = (latent_window_size - 1) * 4 + 1
    return max(1, (max(1, frames) + window_frames - 1) // window_frames)


def framepack_output_frames(frames: int, latent_window_size: int = 9) -> int:
    return framepack_sections(frames, latent_window_size) * latent_window_size * 4 + 1


# The heavy work does not stop at the last denoise step: a (fp32, tiled) VAE
# decode and the mp4 encode follow, and neither emits step callbacks. Wan's
# decode alone can run minutes. Reserve progress headroom so sampling fills the
# bar up to _DENOISE_END and the decode/encode phases stay visible afterwards
# instead of the bar sitting frozen at 100%.
_DENOISE_END = 0.9
_ENCODE_START = 0.97


class DiffusersVideoBackend(VideoBackend):
    def __init__(self, descriptor: ModelDescriptor) -> None:
        super().__init__(descriptor)
        self._pipe: Any = None
        self._i2v_pipe: Any = None
        self._accelerator: accelerator_runtime.AcceleratorRuntime | None = None
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    async def load(self) -> None:
        if self._loaded:
            return
        if settings.stub_mode:
            await asyncio.sleep(0.25)
            self._loaded = True
            self._load_report = {"stub": True}
            return
        await asyncio.to_thread(self._load_pipeline_sync)
        self._loaded = True

    def _load_pipeline_sync(self) -> None:
        from diffusers import PipelineQuantizationConfig  # noqa: PLC0415
        import torch  # noqa: PLC0415

        self._accelerator = accelerator_runtime.current()
        self._accelerator.require_available(torch)
        if self._accelerator.backend != "cuda":
            raise RuntimeError("Diffusers video generation currently requires an NVIDIA CUDA profile")

        start = self._memory_snapshot(torch)
        quant = settings.video_quant.lower().strip()
        if quant not in {"bnb-nf4", "bnb-fp4", "", "none", "bf16"}:
            raise ValueError(
                "HFAB_VIDEO_QUANT must be one of: bnb-nf4, bnb-fp4, none "
                f"(got {settings.video_quant!r})"
            )
        use_bnb = quant in {"bnb-nf4", "bnb-fp4"}
        def pipeline_kwargs(components: list[str]) -> dict[str, Any]:
            kwargs: dict[str, Any] = {"torch_dtype": torch.bfloat16, "local_files_only": True}
            if use_bnb:
                kwargs["quantization_config"] = PipelineQuantizationConfig(
                    quant_backend="bitsandbytes_4bit",
                    quant_kwargs={
                        "load_in_4bit": True,
                        "bnb_4bit_quant_type": "nf4" if quant == "bnb-nf4" else "fp4",
                        "bnb_4bit_compute_dtype": torch.bfloat16,
                    },
                    components_to_quantize=components,
                )
            return kwargs

        def bnb_model_config():
            from diffusers import BitsAndBytesConfig  # noqa: PLC0415

            return BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4" if quant == "bnb-nf4" else "fp4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        path = str(self.descriptor.path)
        if self.descriptor.family is ModelFamily.LTX_VIDEO:
            from diffusers import LTXPipeline  # noqa: PLC0415

            pipe = LTXPipeline.from_pretrained(path, **pipeline_kwargs(["transformer", "text_encoder"]))
        elif self.descriptor.family is ModelFamily.WAN_VIDEO:
            from diffusers import AutoencoderKLWan, WanPipeline  # noqa: PLC0415

            vae = AutoencoderKLWan.from_pretrained(
                path,
                subfolder="vae",
                torch_dtype=torch.float32,
                local_files_only=True,
            )
            pipe = WanPipeline.from_pretrained(path, vae=vae, **pipeline_kwargs(["transformer", "text_encoder"]))
        elif self.descriptor.family is ModelFamily.HUNYUAN_VIDEO:
            from diffusers import (  # noqa: PLC0415
                HunyuanVideoFramepackPipeline,
                HunyuanVideoFramepackTransformer3DModel,
            )
            from transformers import SiglipImageProcessor, SiglipVisionModel  # noqa: PLC0415

            layout = self._framepack_layout(Path(path))
            if layout is None:
                pipe = HunyuanVideoFramepackPipeline.from_pretrained(
                    path,
                    **pipeline_kwargs(["transformer", "text_encoder", "text_encoder_2"]),
                )
            else:
                transformer_kwargs: dict[str, Any] = {
                    "torch_dtype": torch.bfloat16,
                    "local_files_only": True,
                }
                if use_bnb:
                    transformer_kwargs["quantization_config"] = bnb_model_config()
                transformer = HunyuanVideoFramepackTransformer3DModel.from_pretrained(
                    str(layout["transformer"]),
                    **transformer_kwargs,
                )
                feature_extractor = SiglipImageProcessor.from_pretrained(
                    str(layout["redux"]),
                    subfolder="feature_extractor",
                    local_files_only=True,
                )
                image_encoder = SiglipVisionModel.from_pretrained(
                    str(layout["redux"]),
                    subfolder="image_encoder",
                    torch_dtype=torch.float16,
                    local_files_only=True,
                )
                pipe = HunyuanVideoFramepackPipeline.from_pretrained(
                    str(layout["base"]),
                    transformer=transformer,
                    feature_extractor=feature_extractor,
                    image_encoder=image_encoder,
                    **pipeline_kwargs(["text_encoder", "text_encoder_2"]),
                )
        else:
            raise ValueError(f"video family {self.descriptor.family.value!r} is not implemented yet")

        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
        if hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()

        offload = settings.video_offload.lower().strip()
        if use_bnb:
            # The big win on 16 GB: model offload keeps only the active submodel on
            # the GPU. Wan 5B's text encoder is ~7 GB of *unquantized* bf16 and is
            # used once; with everything resident the fp32 VAE decode had no room
            # and spilled to shared RAM (or OOMed at 720p). Per-submodel offload
            # drops the peak from ~14.5 GB to ~7.8 GB. The old "bnb can't be moved"
            # worry only applies to a bulk pipe.to() — model-offload's hooks work
            # fine with the 4-bit transformer (verified on diffusers 0.38).
            if offload == "sequential":
                self._accelerator.enable_sequential_cpu_offload(pipe)
                placement = "bnb+sequential-offload"
            else:
                self._accelerator.enable_model_cpu_offload(pipe)
                placement = "bnb+model-offload"
        else:
            if offload == "sequential":
                self._accelerator.enable_sequential_cpu_offload(pipe)
            elif offload in {"", "none"}:
                self._accelerator.move(pipe)
            else:
                self._accelerator.enable_model_cpu_offload(pipe)
            placement = offload or "none"

        self._pipe = pipe
        self._load_report = {
            "accelerator": self._accelerator.public(),
            "video": {
                "quant": quant or "bf16",
                "placement": placement,
                "vae_tiling": True,
            },
            "memory": {"start": start, "end": self._memory_snapshot(torch)},
        }

    @staticmethod
    def _framepack_layout(path: Path) -> dict[str, Path] | None:
        base = path / "base"
        transformer = path / "transformer"
        redux = path / "redux"
        if (
            (base / "model_index.json").is_file()
            and (transformer / "config.json").is_file()
            and (redux / "feature_extractor" / "preprocessor_config.json").is_file()
            and (redux / "image_encoder" / "config.json").is_file()
        ):
            return {"base": base, "transformer": transformer, "redux": redux}
        return None

    async def unload(self) -> None:
        if not self._loaded:
            return
        try:
            if not settings.stub_mode:
                await asyncio.to_thread(self._free_pipeline_sync)
        finally:
            self._pipe = None
            self._i2v_pipe = None
            self._accelerator = None
            self._loaded = False
            self._warm = False

    def _free_pipeline_sync(self) -> None:
        import torch  # noqa: PLC0415

        if self._pipe is not None and hasattr(self._pipe, "maybe_free_model_hooks"):
            self._pipe.maybe_free_model_hooks()
        self._i2v_pipe = None
        self._pipe = None
        gc.collect()
        self._runtime().empty_cache(torch)

    async def after_job(
        self, job_id: str, params: dict[str, Any], *, failed: bool = False
    ) -> dict[str, Any] | None:
        if settings.stub_mode or self._pipe is None:
            return None
        return await asyncio.to_thread(self._cleanup_after_job, failed)

    def _cleanup_after_job(self, failed: bool) -> dict[str, Any]:
        import torch  # noqa: PLC0415

        if hasattr(self._pipe, "maybe_free_model_hooks"):
            self._pipe.maybe_free_model_hooks()
        gc.collect()
        self._runtime().empty_cache(torch, reset_peak=True)
        return {"backend": self.resident_key, "family": self.descriptor.family.value, "failed": failed}

    async def generate(
        self, params: dict[str, Any], progress: ProgressCb
    ) -> dict[str, Any]:
        width, height = self._dimensions(params)
        frames = self._frames(params)
        fps = self._bounded_int(params.get("fps"), self._gen_default("fps", settings.video_default_fps), 4, 30)
        steps = self._bounded_int(params.get("steps"), self._gen_default("steps", settings.video_default_steps), 1, 80)
        guidance = self._bounded_float(
            params.get("guidance"), self._gen_default("guidance", settings.video_default_guidance), 0.0, 20.0
        )
        seed = self._bounded_int(params.get("seed"), -1, -1, 2**31 - 1)
        if seed < 0:
            seed = random.randint(0, 2**31 - 1)
        mode = "i2v" if params.get("init_image") or params.get("mode") == "i2v" else "t2v"
        if self.descriptor.family is ModelFamily.HUNYUAN_VIDEO and mode != "i2v":
            raise ValueError("FramePack Hunyuan video is image-to-video only; upload a source frame")
        if mode == "i2v" and not params.get("init_image"):
            raise ValueError("image-to-video requires a source image")

        self._stop = False
        if settings.stub_mode:
            return await self._generate_stub(
                params, progress, width=width, height=height, frames=frames,
                fps=fps, steps=steps, guidance=guidance, seed=seed, mode=mode,
            )
        return await self._generate_real(
            params, progress, width=width, height=height, frames=frames,
            fps=fps, steps=steps, guidance=guidance, seed=seed, mode=mode,
        )

    def _gen_default(self, key: str, fallback: Any) -> Any:
        return family_video_default(self.descriptor.family, key, fallback)

    async def _generate_stub(
        self,
        params: dict[str, Any],
        progress: ProgressCb,
        *,
        width: int,
        height: int,
        frames: int,
        fps: int,
        steps: int,
        guidance: float,
        seed: int,
        mode: str,
    ) -> dict[str, Any]:
        for step in range(steps):
            if self._stop:
                raise GenerationCancelled()
            await asyncio.sleep(0.025)
            await progress(_DENOISE_END * (step + 1) / steps, f"step {step + 1}/{steps}")
        await progress(_ENCODE_START, "encoding video…")

        # Keep CI/dev output tiny while still producing a real seekable mp4.
        actual_frames = min(frames, 24)
        rendered = []
        for index in range(actual_frames):
            rendered.append(imaging.make_placeholder(width, height, [
                f"[STUB VIDEO] {self.descriptor.name}",
                f"{mode.upper()}  frame {index + 1}/{actual_frames}  seed={seed}",
                str(params.get("prompt") or ""),
            ]))
        meta = self._metadata(
            params, width=width, height=height, frames=actual_frames,
            requested_frames=frames, fps=fps, steps=steps, guidance=guidance, seed=seed, mode=mode,
        )
        meta["stub"] = True
        return await asyncio.to_thread(self._persist, rendered, meta)

    async def _generate_real(
        self,
        params: dict[str, Any],
        progress: ProgressCb,
        *,
        width: int,
        height: int,
        frames: int,
        fps: int,
        steps: int,
        guidance: float,
        seed: int,
        mode: str,
    ) -> dict[str, Any]:
        import torch  # noqa: PLC0415

        loop = asyncio.get_running_loop()
        latent_window_size = self._bounded_int(
            params.get("latent_window_size"),
            self._gen_default("latent_window_size", 9),
            3,
            17,
        )
        total_steps = steps
        if self.descriptor.family is ModelFamily.HUNYUAN_VIDEO:
            total_steps *= framepack_sections(frames, latent_window_size)
        denoise = {"done": 0}

        def callback(*args):
            if self._stop:
                raise GenerationCancelled()
            denoise["done"] = min(total_steps, denoise["done"] + 1)
            done = denoise["done"]
            if done >= total_steps:
                # Final step end — sampling is over and the slow VAE decode begins
                # with no callbacks of its own; label it so the bar isn't a frozen 100%.
                frac, note = _DENOISE_END, "decoding frames (VAE)…"
            else:
                frac, note = _DENOISE_END * done / total_steps, f"step {done}/{total_steps}"
            asyncio.run_coroutine_threadsafe(progress(frac, note), loop)
            return args[-1] if args and isinstance(args[-1], dict) else None

        def run():
            pipe = self._pipeline_for_mode(mode)
            kwargs: dict[str, Any] = {
                "prompt": str(params.get("prompt") or ""),
                "negative_prompt": str(params.get("negative") or "") or None,
                "width": width,
                "height": height,
                "num_frames": frames,
                "num_inference_steps": steps,
                "guidance_scale": guidance,
                "generator": self._runtime().generator(torch, seed),
                "callback_on_step_end": callback,
            }
            if self.descriptor.family is ModelFamily.LTX_VIDEO:
                kwargs["frame_rate"] = fps
            elif self.descriptor.family is ModelFamily.HUNYUAN_VIDEO:
                kwargs["latent_window_size"] = latent_window_size
                if params.get("negative"):
                    kwargs["true_cfg_scale"] = self._bounded_float(
                        params.get("true_cfg_scale"), 1.0, 1.0, 20.0
                    )
            if mode == "i2v":
                kwargs["image"] = self._source_image(str(params["init_image"]), width, height)
                if self.descriptor.family is ModelFamily.HUNYUAN_VIDEO and params.get("last_image"):
                    kwargs["last_image"] = self._source_image(str(params["last_image"]), width, height)
            output = pipe(**kwargs)
            return list(output.frames[0])

        rendered = await asyncio.to_thread(run)
        await progress(_ENCODE_START, "encoding video…")
        meta = self._metadata(
            params, width=width, height=height, frames=len(rendered),
            requested_frames=frames, fps=fps, steps=steps, guidance=guidance, seed=seed, mode=mode,
        )
        return await asyncio.to_thread(self._persist, rendered, meta)

    def _pipeline_for_mode(self, mode: str):
        if mode != "i2v":
            return self._pipe
        if self.descriptor.family is ModelFamily.HUNYUAN_VIDEO:
            return self._pipe
        if self._i2v_pipe is None:
            if self.descriptor.family is ModelFamily.LTX_VIDEO:
                from diffusers import LTXImageToVideoPipeline  # noqa: PLC0415
                import torch  # noqa: PLC0415

                self._i2v_pipe = LTXImageToVideoPipeline.from_pipe(self._pipe)
                # Diffusers 0.38 builds the LTX I2V image tensor as bf16 from the
                # parent pipe, while from_pipe can leave the VAE encode path in
                # fp32. Keep the VAE on bf16 so image conditioning does not fail
                # with "input bf16, bias float" during the first conv3d.
                self._i2v_pipe.vae.to(dtype=torch.bfloat16)
            elif self.descriptor.family is ModelFamily.WAN_VIDEO:
                from diffusers import WanImageToVideoPipeline  # noqa: PLC0415
                from diffusers.utils import is_ftfy_available  # noqa: PLC0415

                # diffusers 0.38's Wan i2v prompt cleaner calls ftfy.fix_text
                # without the availability guard the t2v path has, so a missing
                # ftfy otherwise surfaces as a cryptic mid-run NameError.
                if not is_ftfy_available():
                    raise RuntimeError(
                        "Wan image-to-video needs the 'ftfy' package — install it with "
                        "`pip install ftfy` (already pinned in requirements-gpu.txt)."
                    )
                self._i2v_pipe = WanImageToVideoPipeline.from_pipe(self._pipe)
            else:
                raise ValueError("this video model does not support image-to-video")
        return self._i2v_pipe

    def _persist(self, frames: list[Any], meta: dict[str, Any]) -> dict[str, Any]:
        import imageio.v2 as imageio  # foundation dependency; no Diffusers import in STUB
        import numpy as np  # noqa: PLC0415

        pil_frames = [self._to_pil(frame) for frame in frames]
        if not pil_frames:
            raise RuntimeError("video pipeline returned no frames")
        out_dir = imaging.day_dir(settings.outputs_dir)
        stem = f"video_{meta['seed']}_{random.randint(1000, 9999)}"
        video_path = out_dir / f"{stem}.mp4"
        poster_path = out_dir / f"{stem}.poster.webp"
        thumb_path = out_dir / f"{stem}.thumb.webp"

        with imageio.get_writer(
            video_path,
            fps=int(meta["fps"]),
            codec="libx264",
            quality=7,
            macro_block_size=16,
            pixelformat="yuv420p",  # imageio injects -pix_fmt itself; passing it again warns
            ffmpeg_params=["-movflags", "+faststart"],
        ) as writer:
            for frame in pil_frames:
                writer.append_data(np.asarray(frame))

        poster = pil_frames[0].copy()
        poster.thumbnail((768, 768))
        poster.save(poster_path, format="WEBP", quality=84)
        sample_count = min(12, len(pil_frames))
        indexes = [round(i * (len(pil_frames) - 1) / max(1, sample_count - 1)) for i in range(sample_count)]
        thumbs = []
        for index in indexes:
            thumb = pil_frames[index].copy()
            thumb.thumbnail((384, 384))
            thumbs.append(thumb)
        thumbs[0].save(
            thumb_path,
            format="WEBP",
            save_all=True,
            append_images=thumbs[1:],
            duration=max(40, round(1000 / int(meta["fps"]))),
            loop=0,
            quality=72,
        )
        video_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "path": str(video_path),
            "poster_path": str(poster_path),
            "thumb_path": str(thumb_path),
            "seed": meta["seed"],
            "width": meta["width"],
            "height": meta["height"],
            "frames": meta["frames"],
            "fps": meta["fps"],
            "duration_s": meta["duration_s"],
            "family": meta["family"],
            "params": meta,
        }

    def _metadata(self, params: dict[str, Any], **resolved: Any) -> dict[str, Any]:
        public = {key: value for key, value in params.items() if not key.startswith("_")}
        frames = int(resolved["frames"])
        fps = int(resolved["fps"])
        return {
            **public,
            **resolved,
            "duration_s": round(frames / fps, 3),
            "model": self.descriptor.name,
            "family": self.descriptor.family.value,
            "quant": self.descriptor.quant,
            "vae_tiling": True,
        }

    def _runtime(self) -> accelerator_runtime.AcceleratorRuntime:
        if self._accelerator is None:
            self._accelerator = accelerator_runtime.current()
        return self._accelerator

    def _memory_snapshot(self, torch) -> dict[str, Any]:
        snap = sysmon.snapshot()
        process = self._runtime().process_memory(torch)
        if process:
            snap["accelerator_process"] = process
            if self._runtime().memory_key == "cuda_process":
                snap["cuda_process"] = process
        return snap

    def _dimensions(self, params: dict[str, Any]) -> tuple[int, int]:
        width = self._bounded_int(
            params.get("width"), self._gen_default("width", settings.video_default_width), 256, settings.video_max_width
        )
        height = self._bounded_int(
            params.get("height"),
            self._gen_default("height", settings.video_default_height),
            256,
            settings.video_max_height,
        )
        # Both implemented families accept 32-aligned canvases; normalization is
        # deterministic and keeps encoders/ffmpeg on friendly dimensions.
        return max(256, width // 32 * 32), max(256, height // 32 * 32)

    def _frames(self, params: dict[str, Any]) -> int:
        frames = self._bounded_int(
            params.get("frames"), self._gen_default("frames", settings.video_default_frames), 9, settings.video_max_frames
        )
        if self.descriptor.family is ModelFamily.HUNYUAN_VIDEO:
            return frames
        temporal = 8 if self.descriptor.family is ModelFamily.LTX_VIDEO else 4
        return max(temporal + 1, (frames - 1) // temporal * temporal + 1)

    @staticmethod
    def _source_image(token: str, width: int, height: int) -> PILImage.Image:
        from PIL import ImageOps  # noqa: PLC0415

        path = uploads_util.resolve_upload(token)
        if path is None or not path.is_file():
            raise ValueError("image-to-video source image not found (re-upload it)")
        image = PILImage.open(path).convert("RGB")
        return ImageOps.fit(image, (width, height), method=PILImage.Resampling.LANCZOS)

    @staticmethod
    def _to_pil(frame: Any) -> PILImage.Image:
        import numpy as np  # noqa: PLC0415

        if isinstance(frame, PILImage.Image):
            return frame.convert("RGB")
        array = np.asarray(frame)
        if array.dtype.kind == "f":
            array = np.clip(array, 0.0, 1.0) * 255
        return PILImage.fromarray(array.astype("uint8")).convert("RGB")

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
