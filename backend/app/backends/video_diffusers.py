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
import random
from typing import Any

from PIL import Image as PILImage

from ..config import settings
from ..core.enums import ModelFamily
from ..services import accelerator_runtime
from ..util import imaging, sysmon
from ..util import uploads as uploads_util
from .base import GenerationCancelled, ModelDescriptor, ProgressCb, VideoBackend


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
            raise RuntimeError("LTX/Wan video generation currently requires an NVIDIA CUDA profile")

        start = self._memory_snapshot(torch)
        quant = settings.video_quant.lower().strip()
        if quant not in {"bnb-nf4", "bnb-fp4", "", "none", "bf16"}:
            raise ValueError(
                "HFAB_VIDEO_QUANT must be one of: bnb-nf4, bnb-fp4, none "
                f"(got {settings.video_quant!r})"
            )
        use_bnb = quant in {"bnb-nf4", "bnb-fp4"}
        kwargs: dict[str, Any] = {"torch_dtype": torch.bfloat16, "local_files_only": True}
        if use_bnb:
            kwargs["quantization_config"] = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": "nf4" if quant == "bnb-nf4" else "fp4",
                    "bnb_4bit_compute_dtype": torch.bfloat16,
                },
                components_to_quantize=["transformer", "text_encoder"],
            )

        path = str(self.descriptor.path)
        if self.descriptor.family is ModelFamily.LTX_VIDEO:
            from diffusers import LTXPipeline  # noqa: PLC0415

            pipe = LTXPipeline.from_pretrained(path, **kwargs)
        elif self.descriptor.family is ModelFamily.WAN_VIDEO:
            from diffusers import AutoencoderKLWan, WanPipeline  # noqa: PLC0415

            vae = AutoencoderKLWan.from_pretrained(
                path,
                subfolder="vae",
                torch_dtype=torch.float32,
                local_files_only=True,
            )
            pipe = WanPipeline.from_pretrained(path, vae=vae, **kwargs)
        else:
            raise ValueError(f"video family {self.descriptor.family.value!r} is not implemented yet")

        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
        if hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()

        if use_bnb:
            # Quantized components are placed by the Diffusers bnb loader. Moving
            # the whole pipeline afterwards can touch meta tensors, so only place
            # the compact tiled VAE on CUDA.
            self._accelerator.move(pipe.vae)
            placement = "bnb-loader+tiled-vae"
        else:
            offload = settings.video_offload.lower().strip()
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
        fps = self._bounded_int(params.get("fps"), settings.video_default_fps, 4, 30)
        steps = self._bounded_int(params.get("steps"), settings.video_default_steps, 1, 80)
        seed = self._bounded_int(params.get("seed"), -1, -1, 2**31 - 1)
        if seed < 0:
            seed = random.randint(0, 2**31 - 1)
        mode = "i2v" if params.get("init_image") or params.get("mode") == "i2v" else "t2v"
        if mode == "i2v" and not params.get("init_image"):
            raise ValueError("image-to-video requires a source image")

        self._stop = False
        if settings.stub_mode:
            return await self._generate_stub(
                params, progress, width=width, height=height, frames=frames,
                fps=fps, steps=steps, seed=seed, mode=mode,
            )
        return await self._generate_real(
            params, progress, width=width, height=height, frames=frames,
            fps=fps, steps=steps, seed=seed, mode=mode,
        )

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
        seed: int,
        mode: str,
    ) -> dict[str, Any]:
        for step in range(steps):
            if self._stop:
                raise GenerationCancelled()
            await asyncio.sleep(0.025)
            await progress((step + 1) / steps, f"step {step + 1}/{steps}")

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
            requested_frames=frames, fps=fps, steps=steps, seed=seed, mode=mode,
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
        seed: int,
        mode: str,
    ) -> dict[str, Any]:
        import torch  # noqa: PLC0415

        loop = asyncio.get_running_loop()

        def callback(*args):
            if self._stop:
                raise GenerationCancelled()
            step = int(args[-3] if len(args) >= 4 else args[0])
            asyncio.run_coroutine_threadsafe(
                progress((step + 1) / steps, f"step {step + 1}/{steps}"), loop
            )
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
                "guidance_scale": self._bounded_float(
                    params.get("guidance"), settings.video_default_guidance, 0.0, 20.0
                ),
                "generator": self._runtime().generator(torch, seed),
                "callback_on_step_end": callback,
            }
            if self.descriptor.family is ModelFamily.LTX_VIDEO:
                kwargs["frame_rate"] = fps
            if mode == "i2v":
                kwargs["image"] = self._source_image(str(params["init_image"]), width, height)
            output = pipe(**kwargs)
            return list(output.frames[0])

        rendered = await asyncio.to_thread(run)
        meta = self._metadata(
            params, width=width, height=height, frames=len(rendered),
            requested_frames=frames, fps=fps, steps=steps, seed=seed, mode=mode,
        )
        return await asyncio.to_thread(self._persist, rendered, meta)

    def _pipeline_for_mode(self, mode: str):
        if mode != "i2v":
            return self._pipe
        if self._i2v_pipe is None:
            if self.descriptor.family is ModelFamily.LTX_VIDEO:
                from diffusers import LTXImageToVideoPipeline  # noqa: PLC0415

                self._i2v_pipe = LTXImageToVideoPipeline.from_pipe(self._pipe)
            elif self.descriptor.family is ModelFamily.WAN_VIDEO:
                from diffusers import WanImageToVideoPipeline  # noqa: PLC0415

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
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
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
            params.get("width"), settings.video_default_width, 256, settings.video_max_width
        )
        height = self._bounded_int(
            params.get("height"), settings.video_default_height, 256, settings.video_max_height
        )
        # Both implemented families accept 32-aligned canvases; normalization is
        # deterministic and keeps encoders/ffmpeg on friendly dimensions.
        return max(256, width // 32 * 32), max(256, height // 32 * 32)

    def _frames(self, params: dict[str, Any]) -> int:
        frames = self._bounded_int(
            params.get("frames"), settings.video_default_frames, 9, settings.video_max_frames
        )
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
