from __future__ import annotations

from contextlib import nullcontext
import importlib
import importlib.util
from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Any

from ...config import settings
from ...core.enums import ModelFamily
from ...services import accelerator_runtime


class DiffusersPipelineMixin:
    def _runtime(self) -> accelerator_runtime.AcceleratorRuntime:
        if self._accelerator is None:
            self._accelerator = accelerator_runtime.current()
        return self._accelerator

    def _ensure_runtime_support(self, runtime: accelerator_runtime.AcceleratorRuntime) -> None:
        if runtime.cpu:
            raise RuntimeError("CPU-safe profile cannot load real image models; use STUB mode.")
        if self._is_nunchaku_quant() and not runtime.cuda_family:
            raise RuntimeError("Nunchaku image models require the NVIDIA CUDA/Nunchaku profile.")
        if self._is_nunchaku_quant() and find_spec("nunchaku") is None:
            raise RuntimeError(
                "Nunchaku Python package is not installed. Re-run setup.bat -Nunchaku "
                "or restart through run.bat to repair the CUDA fp4 runtime."
            )
        if runtime.backend == "mps" and self.descriptor.family is not ModelFamily.SDXL:
            raise RuntimeError("Apple MPS image loading is currently enabled only for SDXL models.")
        if runtime.backend == "rocm" and self.descriptor.family is not ModelFamily.SDXL:
            raise RuntimeError("ROCm image loading is currently enabled only for SDXL models.")
        if runtime.backend in {"rocm", "mps"} and str(self.descriptor.quant or "").startswith("bnb-"):
            raise RuntimeError(f"bitsandbytes-quantized image models are disabled on {runtime.backend}.")

    @staticmethod
    def _quantized_repo_kwargs(
        torch,
        quant: str,
        env_name: str,
        components_to_quantize: list[str],
    ) -> dict[str, Any]:
        quant = quant.lower().strip()
        if quant not in ("bnb-nf4", "bnb-fp4", "", "none", "bf16"):
            raise ValueError(
                f"{env_name} must be one of: bnb-nf4, bnb-fp4, none "
                f"(got {quant!r})"
            )
        kwargs: dict[str, Any] = {"torch_dtype": torch.bfloat16}
        if quant in ("bnb-nf4", "bnb-fp4"):
            from diffusers import PipelineQuantizationConfig  # noqa: PLC0415

            kwargs["quantization_config"] = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": "nf4" if quant == "bnb-nf4" else "fp4",
                    "bnb_4bit_compute_dtype": torch.bfloat16,
                },
                components_to_quantize=components_to_quantize,
            )
        return kwargs

    def _place_repo_pipeline(self, pipe: Any, offload: str, env_name: str) -> None:
        offload = offload.lower().strip()
        if offload == "sequential":
            self._runtime().enable_sequential_cpu_offload(pipe)
        elif offload in ("", "none"):
            self._runtime().move(pipe)
        elif offload == "model":
            self._runtime().enable_model_cpu_offload(pipe)
        else:
            raise ValueError(
                f"{env_name} must be one of: model, sequential, none "
                f"(got {offload!r})"
            )

    def _import_nunchaku_flux2_transformer(self):
        try:
            from nunchaku import NunchakuFlux2Transformer2DModel  # type: ignore[attr-defined] # noqa: PLC0415

            return NunchakuFlux2Transformer2DModel
        except (ImportError, AttributeError):
            pass
        try:
            module = importlib.import_module("nunchaku.models.transformers.transformer_flux2")
            return module.NunchakuFlux2Transformer2DModel
        except (ImportError, AttributeError):
            return self._import_nunchaku_flux2_sidecar()

    def _using_flux2_sidecar(self) -> bool:
        module = sys.modules.get("nunchaku.models.transformers.transformer_flux2")
        filename = getattr(module, "__file__", "") if module else ""
        return bool(filename and settings.flux2_nunchaku_dir.as_posix() in Path(filename).as_posix())

    def _import_nunchaku_flux2_sidecar(self):
        code_dir = settings.flux2_nunchaku_dir
        transfer_src = code_dir / "torch_transfer_utils.py"
        transformer_src = code_dir / "transformer_flux2.py"
        if not transfer_src.is_file() or not transformer_src.is_file():
            raise RuntimeError(
                "FLUX.2 nunchaku sidecar files are missing. Expected "
                f"{transfer_src} and {transformer_src}."
            )

        self._load_module_from_file("nunchaku.torch_transfer_utils", transfer_src)
        module = self._load_module_from_file(
            "nunchaku.models.transformers.transformer_flux2",
            transformer_src,
        )
        return module.NunchakuFlux2Transformer2DModel

    @staticmethod
    def _load_module_from_file(module_name: str, path: Path):
        existing = sys.modules.get(module_name)
        if existing is not None and getattr(existing, "__file__", None) == str(path):
            return existing
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not import {module_name} from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _is_nunchaku_quant(self) -> bool:
        return bool(self.descriptor.quant and self.descriptor.quant.startswith("nunchaku"))

    def _apply_acceleration(self, torch, pipe: Any, report: dict[str, Any]) -> None:
        self._configure_attention(torch, report)
        self._maybe_apply_flux_step_cache(pipe, report)
        self._maybe_apply_sdxl_turbo_lora(pipe, report)
        self._maybe_compile_transformer(torch, pipe, report)

    def _configure_attention(self, torch, report: dict[str, Any]) -> None:
        mode = settings.attention_backend.lower().strip() or "auto"
        precision = settings.attention_matmul_precision.lower().strip()
        if precision not in ("highest", "high", "medium"):
            raise ValueError(
                "HFAB_ATTENTION_MATMUL_PRECISION must be one of: highest, high, medium "
                f"(got {settings.attention_matmul_precision!r})"
            )
        if hasattr(torch, "set_float32_matmul_precision"):
            torch.set_float32_matmul_precision(precision)

        runtime = self._runtime()
        cuda_available = runtime.cuda_available(torch)
        if cuda_available:
            matmul = getattr(getattr(torch.backends, "cuda", None), "matmul", None)
            if matmul is not None and hasattr(matmul, "allow_tf32"):
                matmul.allow_tf32 = settings.attention_allow_tf32

        attention = getattr(torch.nn, "attention", None)
        sdp_backend = getattr(attention, "SDPBackend", None) if attention else None
        sdpa_kernel = getattr(attention, "sdpa_kernel", None) if attention else None
        native_backends = self._native_sdp_backend_names(sdp_backend)
        backend_map = {
            "flash": "FLASH_ATTENTION",
            "efficient": "EFFICIENT_ATTENTION",
            "math": "MATH",
            "cudnn": "CUDNN_ATTENTION",
        }
        aliases = {"default": "auto", "sdpa": "auto", "native": "auto"}
        mode = aliases.get(mode, mode)
        if mode not in {"auto", *backend_map}:
            raise ValueError(
                "HFAB_ATTENTION_BACKEND must be one of: auto, flash, efficient, math, cudnn "
                f"(got {settings.attention_backend!r})"
            )
        if mode != "auto":
            enum_name = backend_map[mode]
            if sdpa_kernel is None or sdp_backend is None or enum_name not in native_backends:
                raise ValueError(
                    f"HFAB_ATTENTION_BACKEND={mode!r} requires torch.nn.attention."
                    f"SDPBackend.{enum_name}, but this torch build does not expose it."
                )
            if mode in {"flash", "efficient", "cudnn"} and not cuda_available:
                raise ValueError(
                    f"HFAB_ATTENTION_BACKEND={mode!r} requires a CUDA torch build/device."
                )

        feature = {
            "requested": settings.attention_backend,
            "mode": mode,
            "native_sdpa": sdpa_kernel is not None and sdp_backend is not None,
            "native_backends": native_backends,
            "forced_backend": backend_map.get(mode),
            "cuda_available": cuda_available,
            "external_flash_attn": find_spec("flash_attn") is not None,
            "xformers": find_spec("xformers") is not None,
            "float8_dtypes": self._torch_float8_dtypes(torch),
            "allow_tf32": settings.attention_allow_tf32,
            "matmul_precision": precision,
            "backend": runtime.backend,
            "torch_device": runtime.torch_device,
        }
        self._active_features["attention"] = feature
        report["acceleration"]["attention"] = feature

    @staticmethod
    def _native_sdp_backend_names(sdp_backend: Any) -> list[str]:
        if sdp_backend is None:
            return []
        return [
            name
            for name in ("FLASH_ATTENTION", "EFFICIENT_ATTENTION", "MATH", "CUDNN_ATTENTION")
            if hasattr(sdp_backend, name)
        ]

    @staticmethod
    def _torch_float8_dtypes(torch) -> list[str]:
        return sorted(name for name in dir(torch) if name.startswith("float8_"))

    def _maybe_compile_transformer(self, torch, pipe: Any, report: dict[str, Any]) -> None:
        if not settings.torch_compile:
            return
        if not hasattr(pipe, "transformer"):
            report["acceleration"]["torch_compile"] = {"skipped": "pipeline has no transformer"}
            return

        compile_report: dict[str, Any] = {
            "mode": settings.torch_compile_mode,
            "before": self._memory_snapshot(torch),
        }
        original_transformer = pipe.transformer
        try:
            self._runtime().reset_peak_memory_stats(torch)
            pipe.transformer = torch.compile(pipe.transformer, mode=settings.torch_compile_mode)
            compile_report["after_wrap"] = self._memory_snapshot(torch)

            if settings.torch_compile_warmup:
                self._warmup_pipeline(torch, pipe)
                compile_report["after_warmup"] = self._memory_snapshot(torch)
                compile_report.update(self._runtime().peak_memory(torch))
        except Exception as exc:
            import gc  # noqa: PLC0415

            pipe.transformer = original_transformer
            compile_report["failed"] = repr(exc)
            compile_report["after_rollback"] = self._memory_snapshot(torch)
            gc.collect()
            self._runtime().empty_cache(torch)
            report["acceleration"]["torch_compile"] = compile_report
            return

        self._active_features["torch_compile"] = {"mode": settings.torch_compile_mode}
        report["acceleration"]["torch_compile"] = compile_report

    def _warmup_pipeline(self, torch, pipe: Any) -> None:
        size = int(settings.torch_compile_warmup_size)
        size = max(256, (size // 64) * 64)
        kwargs = {
            "prompt": "warmup",
            "width": size,
            "height": size,
            "num_inference_steps": 1,
            "guidance_scale": settings.default_guidance,
            "generator": self._runtime().generator(torch, 0),
        }
        with torch.inference_mode(), self._attention_context(torch):
            pipe(**kwargs)

    def _attention_context(self, torch):
        forced_backend = (self._active_features.get("attention") or {}).get("forced_backend")
        if not forced_backend:
            return nullcontext()

        attention = getattr(torch.nn, "attention", None)
        if attention is None:
            return nullcontext()
        sdpa_kernel = getattr(attention, "sdpa_kernel", None)
        sdp_backend = getattr(attention, "SDPBackend", None)
        if sdpa_kernel is None or sdp_backend is None or not hasattr(sdp_backend, forced_backend):
            return nullcontext()
        return sdpa_kernel([getattr(sdp_backend, forced_backend)])

    def _sdxl_img2img_pipe(self):
        """A SDXL Img2Img pipeline sharing the resident text2img pipeline's
        weights (built once, no extra VRAM). GPU-smoke validated on Blackwell."""
        if self._img2img_pipe is None:
            from diffusers import StableDiffusionXLImg2ImgPipeline  # noqa: PLC0415

            self._img2img_pipe = StableDiffusionXLImg2ImgPipeline(**self._pipe.components)
        return self._img2img_pipe

    def _sdxl_inpaint_pipe(self):
        """A SDXL Inpaint pipeline sharing the resident text2img pipeline's
        weights (built once, no extra VRAM). GPU-smoke validated on Blackwell."""
        if self._inpaint_pipe is None:
            from diffusers import StableDiffusionXLInpaintPipeline  # noqa: PLC0415

            self._inpaint_pipe = StableDiffusionXLInpaintPipeline(**self._pipe.components)
        return self._inpaint_pipe

    def _flux_img2img_pipe(self):
        if self._img2img_pipe is None:
            from diffusers import FluxImg2ImgPipeline  # noqa: PLC0415

            self._img2img_pipe = FluxImg2ImgPipeline(**self._pipe.components)
        return self._img2img_pipe

    def _flux_inpaint_pipe(self):
        if self._inpaint_pipe is None:
            from diffusers import FluxInpaintPipeline  # noqa: PLC0415

            self._inpaint_pipe = FluxInpaintPipeline(**self._pipe.components)
        return self._inpaint_pipe

    def _flux2_inpaint_pipe(self):
        if self._inpaint_pipe is None:
            from diffusers import Flux2KleinInpaintPipeline  # noqa: PLC0415

            self._inpaint_pipe = Flux2KleinInpaintPipeline(**self._pipe.components)
        return self._inpaint_pipe

    def _sdxl_controlnet_pipe(self, torch):
        if self._controlnet_pipe is None:
            repo = settings.sdxl_controlnet_canny_repo
            if not repo:
                raise RuntimeError("SDXL ControlNet canny repo is not configured.")
            from diffusers import ControlNetModel, StableDiffusionXLControlNetPipeline  # noqa: PLC0415

            dtype = getattr(getattr(self._pipe, "unet", None), "dtype", torch.float16)
            before = self._memory_snapshot(torch)
            controlnet = ControlNetModel.from_pretrained(repo, torch_dtype=dtype)
            self._runtime().move(controlnet)
            components = dict(self._pipe.components)
            components["controlnet"] = controlnet
            self._controlnet_model = controlnet
            self._controlnet_pipe = StableDiffusionXLControlNetPipeline(**components)
            after = self._memory_snapshot(torch)
            feature = {
                "type": "canny",
                "repo": repo,
                "memory": {
                    "before": before.get(self._runtime().memory_key),
                    "after": after.get(self._runtime().memory_key),
                },
            }
            self._active_features["sdxl_controlnet"] = feature
            if isinstance(self._load_report, dict):
                self._load_report.setdefault("acceleration", {})["sdxl_controlnet"] = feature
                self._load_report.setdefault("memory", {})["end"] = after
        return self._controlnet_pipe
