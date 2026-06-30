"""Per-model compatibility checks derived from the active capability profile."""

from __future__ import annotations

import importlib.util
from typing import Any

from ..backends.base import ModelDescriptor
from ..config import settings
from ..core.enums import JobType, ModelFamily
from ..util import sysmon
from . import capability_profile


def compatibility_for_model(
    desc: ModelDescriptor,
    *,
    profile: dict[str, Any] | None = None,
    estimated_vram_gb: float | None = None,
) -> dict[str, Any]:
    """Return queue/UI compatibility metadata for one discovered model."""
    if estimated_vram_gb is None:
        estimated_vram_gb = sysmon.estimate_vram_need_gb(desc.family, desc.size_bytes, desc.quant, desc.id)

    profile = profile or capability_profile.get_capability_profile()
    if profile.get("effective_stub_mode"):
        return {
            "available": True,
            "runtime_mode": "stub",
            "unavailable_reason": None,
            "compatibility_warnings": ["Runs through the STUB pipeline in this process."],
            "recommendation": "neutral",
        }

    backend = str(profile.get("backend") or "cpu")
    disabled = set(profile.get("disabled_features") or [])
    warnings: list[str] = []

    if desc.job_type is JobType.IMAGE:
        unavailable = _image_unavailable_reason(desc, profile, backend, disabled)
        if unavailable:
            return {
                "available": False,
                "runtime_mode": "disabled",
                "unavailable_reason": unavailable,
                "compatibility_warnings": warnings,
                "recommendation": "hidden",
            }
        if desc.family is ModelFamily.ANIMA:
            warnings.append(
                "Anima model weights and derivatives are non-commercial; the model card permits "
                "commercial use of generated outputs."
            )
        # VRAM alone no longer blocks an image model: every diffusers family streams
        # weights from RAM via CPU offload, so exceeding the card's VRAM means
        # "slower", not "impossible". Surface it as a warning and let it run.
        gpu_vram_gb = _primary_gpu_vram_gb(profile)
        if estimated_vram_gb and gpu_vram_gb and estimated_vram_gb > gpu_vram_gb + 0.5:
            warnings.append(
                f"Needs ~{estimated_vram_gb:.1f} GB VRAM but the GPU has "
                f"{gpu_vram_gb:.1f} GB — runs with CPU offload to RAM (slower) "
                f"rather than being blocked."
            )
        if backend == "rocm" and desc.family in {
            ModelFamily.FLUX,
            ModelFamily.FLUX2,
            ModelFamily.QWEN_IMAGE,
            ModelFamily.QWEN_IMAGE_EDIT,
            ModelFamily.Z_IMAGE,
            ModelFamily.FLUX_KONTEXT,
        }:
            warnings.append("This image family is not fully validated on ROCm yet.")

    if desc.job_type is JobType.LLM and backend == "rocm" and "cuda_llama_binaries" in disabled:
        warnings.append(
            "ROCm disables CUDA llama binaries; use a CPU/ROCm-safe llama build or lower GPU layers."
        )

    if desc.job_type is JobType.VIDEO:
        unavailable = _video_unavailable_reason(desc, profile, backend, disabled)
        if unavailable:
            return {
                "available": False,
                "runtime_mode": "disabled",
                "unavailable_reason": unavailable,
                "compatibility_warnings": warnings,
                "recommendation": "hidden",
            }
        warnings.append("Video generation can take several minutes; only one heavy model stays resident.")
        if desc.family is ModelFamily.WAN_VIDEO:
            warnings.append("Wan 2.2 5B is the quality tier and may take roughly minutes per clip.")
        if desc.family is ModelFamily.HUNYUAN_VIDEO:
            warnings.append("FramePack Hunyuan is image-to-video only; upload a first frame before queueing.")
            if not (desc.quant or "").startswith("bnb-"):
                warnings.append("FramePack bf16 can exceed this machine's RAM; bnb 4-bit is the validated path.")

    return {
        "available": True,
        "runtime_mode": "real",
        "unavailable_reason": None,
        "compatibility_warnings": warnings,
        "recommendation": _recommendation(desc, profile),
    }


def _recommendation(desc: ModelDescriptor, profile: dict[str, Any]) -> str:
    """Hardware-fit hint for an available model: recommended / advanced / neutral.

    Derived from the capability profile's per-family `model_policy` (P20.3). LLMs
    have no per-family policy yet, so they stay neutral.
    """
    if desc.job_type is JobType.VIDEO:
        video_policy = ((profile.get("model_policy") or {}).get("video")) or {}
        family = desc.family.value
        if family in (video_policy.get("recommended") or []):
            return "recommended"
        if family in (video_policy.get("advanced") or []):
            return "advanced"
        if not video_policy:
            return "recommended" if desc.family is ModelFamily.LTX_VIDEO else "advanced"
        return "neutral"
    if desc.job_type is not JobType.IMAGE:
        return "neutral"
    image_policy = ((profile.get("model_policy") or {}).get("image")) or {}
    family = desc.family.value
    if family in (image_policy.get("recommended") or []):
        return "recommended"
    if family in (image_policy.get("advanced") or []):
        return "advanced"
    return "neutral"


def _nunchaku_runtime_available() -> bool:
    return importlib.util.find_spec("nunchaku") is not None


def require_model_available(desc: ModelDescriptor) -> None:
    """Raise ``ValueError`` when a model should not be queued in this runtime."""
    compat = compatibility_for_model(desc)
    if not compat["available"]:
        raise ValueError(str(compat["unavailable_reason"] or "model is unavailable in this runtime"))


def _image_unavailable_reason(
    desc: ModelDescriptor,
    profile: dict[str, Any],
    backend: str,
    disabled: set[str],
) -> str | None:
    quant = desc.quant or ""
    if desc.family is ModelFamily.ANIMA:
        if backend != "cuda":
            return "The native Anima runtime currently requires an NVIDIA CUDA profile."
        required = {
            "Qwen3 0.6B text encoder": settings.anima_text_encoder_path,
            "Qwen3 config/tokenizer": settings.anima_qwen_config_dir / "config.json",
            "T5 tokenizer": settings.anima_t5_tokenizer_dir / "tokenizer_config.json",
            "Qwen-Image VAE": settings.anima_vae_dir / "diffusion_pytorch_model.safetensors",
            "Qwen-Image VAE config": settings.anima_vae_dir / "config.json",
        }
        missing = [label for label, path in required.items() if not path.is_file()]
        if missing:
            return (
                f"Anima support assets are missing: {', '.join(missing)}. "
                "Run: python scripts/fetch_anima_support.py"
            )
    if quant.startswith("nunchaku") and (backend != "cuda" or "nunchaku_cuda" in disabled):
        return "Nunchaku image models require the NVIDIA CUDA/Nunchaku profile."
    if quant.startswith("nunchaku") and not _nunchaku_runtime_available():
        return (
            "Nunchaku Python package is not installed. Re-run setup.bat -Nunchaku "
            "or restart through run.bat to repair the CUDA fp4 runtime."
        )

    if backend == "rocm" and quant.startswith("bnb-"):
        return "bitsandbytes-quantized image models are not enabled for the ROCm profile yet."

    if backend == "mps" and desc.family is not ModelFamily.SDXL:
        return "Apple MPS currently enables SDXL only; larger image families need real-Mac validation first."

    hidden = set((((profile.get("model_policy") or {}).get("image")) or {}).get("hidden") or [])
    if desc.family.value in hidden:
        return "This image family is hidden by the active hardware profile."

    if backend == "cpu":
        return "Real image model loading requires an accelerator profile; use STUB/CPU-safe mode instead."

    # Refuse only when even CPU offload can't hold the model: with offload the
    # weights live in system RAM, so the hard limit is total RAM, not VRAM. The
    # per-load RAM guard (sysmon.ram_budget) still refuses at runtime if free RAM
    # is momentarily too low; here we only hide what this machine can never run.
    ram_need_gb = sysmon.estimate_ram_need_gb(desc.family, desc.size_bytes, desc.quant, desc.id)
    total_ram_gb = sysmon.ram_stats().get("total_gb")
    if total_ram_gb and ram_need_gb > total_ram_gb:
        return (
            f"Needs ~{ram_need_gb:.1f} GB system RAM to run with CPU offload, but this "
            f"machine has {total_ram_gb:.1f} GB."
        )

    return None


def _video_unavailable_reason(
    desc: ModelDescriptor,
    profile: dict[str, Any],
    backend: str,
    disabled: set[str],
) -> str | None:
    video_policy = ((profile.get("model_policy") or {}).get("video")) or {}
    hidden = set(video_policy.get("hidden") or [])
    fallback_candidates = set(video_policy.get("fallback_candidates") or [])

    if backend != "cuda":
        if desc.family.value in fallback_candidates:
            return (
                f"{desc.family.value} is tracked as the light video fallback for non-NVIDIA profiles, "
                "but that backend path still needs implementation and real ROCm/MPS validation."
            )
        return "The installed video generation path currently requires NVIDIA CUDA."

    implemented_cuda = {
        ModelFamily.LTX_VIDEO,
        ModelFamily.WAN_VIDEO,
        ModelFamily.HUNYUAN_VIDEO,
    }
    if desc.family not in implemented_cuda:
        return "This video family is detected on disk, but its Diffusers loader is not implemented yet."

    if "video_diffusers_cuda" in disabled:
        return "CUDA video generation is disabled by the active hardware profile."

    if desc.family.value in hidden:
        return "This video family is hidden by the active hardware profile."

    return None


def _primary_gpu_vram_gb(profile: dict[str, Any]) -> float | None:
    gpu = profile.get("primary_gpu") if isinstance(profile.get("primary_gpu"), dict) else None
    if not gpu:
        return None
    try:
        value = gpu.get("vram_mb")
        return float(value) / 1024 if value else None
    except (TypeError, ValueError):
        return None
