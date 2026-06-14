"""Resolve an HFabric install profile from a hardware probe report.

The profile is advisory and machine-readable: setup scripts can consume it to
choose package indexes and defaults, while the UI can explain the decision in
plain language.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
import sys
from typing import Any

PYTORCH_VERSION = "2.11.0"
TORCHVISION_VERSION = "0.26.0"
TORCHAUDIO_VERSION = "2.11.0"

# Ordered worst -> best so recommendations can compare tiers by rank.
TIER_ORDER = (
    "unknown",
    "low_vram",
    "safe_8gb",
    "balanced_12gb",
    "rich_16gb_plus",
    "large_24gb_plus",
)
TIER_RANK = {name: rank for rank, name in enumerate(TIER_ORDER)}

# Practical first-choice path per image family + the tier where it stops being a
# stretch. nunchaku-quantized families need an Ampere-or-newer CUDA GPU; SDXL is
# the universal floor that still runs (with offload) on 8 GB cards.
IMAGE_FAMILY_POLICY: dict[str, dict[str, Any]] = {
    "sdxl": {"min_tier": "safe_8gb", "needs_nunchaku": False},
    "flux": {"min_tier": "balanced_12gb", "needs_nunchaku": True},
    "flux2": {"min_tier": "rich_16gb_plus", "needs_nunchaku": True},
    "qwen-image": {"min_tier": "rich_16gb_plus", "needs_nunchaku": True},
    "z-image": {"min_tier": "rich_16gb_plus", "needs_nunchaku": True},
}

# Largest LLM (in billions of params) worth preselecting per tier. Lower tiers
# still *allow* bigger quantized models, but the resolver won't recommend them.
LLM_RECOMMENDED_PARAMS_B = {
    "unknown": 8,
    "low_vram": 4,
    "safe_8gb": 8,
    "balanced_12gb": 14,
    "rich_16gb_plus": 24,
    "large_24gb_plus": 70,
}

PROFILE_DEFS: dict[str, dict[str, Any]] = {
    "nvidia-cuda": {
        "label": "NVIDIA CUDA",
        "torch_index_url": "https://download.pytorch.org/whl/cu128",
        "torch_packages": [
            f"torch=={PYTORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
            f"torchaudio=={TORCHAUDIO_VERSION}",
        ],
        "requirements": ["backend/requirements-gpu.txt"],
        "verify": "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))",
        "optional_features": ["nunchaku_cuda", "cuda_llama_binaries", "onnxruntime_cuda"],
        "disabled_features": [],
    },
    "amd-rocm-linux": {
        "label": "AMD ROCm (Linux)",
        "torch_index_url": "https://download.pytorch.org/whl/rocm7.2",
        "torch_packages": [
            f"torch=={PYTORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
            f"torchaudio=={TORCHAUDIO_VERSION}",
        ],
        "requirements": ["backend/requirements-rocm.txt"],
        "verify": "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0), torch.version.hip)",
        "optional_features": [],
        "disabled_features": ["nunchaku_cuda", "cuda_llama_binaries", "onnxruntime_cuda"],
    },
    "cpu-safe": {
        "label": "CPU-safe",
        "torch_index_url": "https://download.pytorch.org/whl/cpu",
        "torch_packages": [
            f"torch=={PYTORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
            f"torchaudio=={TORCHAUDIO_VERSION}",
        ],
        "requirements": [],
        "verify": "import torch; print(torch.__version__)",
        "optional_features": [],
        "disabled_features": [
            "heavy_image_models",
            "nunchaku_cuda",
            "cuda_llama_binaries",
            "onnxruntime_cuda",
            "realtime_cuda_voice",
        ],
    },
}


def resolve_profile(report: dict[str, Any], prefer: str | None = None) -> dict[str, Any]:
    candidates = _candidate_profiles(report)
    if prefer:
        selected = next((candidate for candidate in candidates if candidate["id"] == prefer), None)
        if selected is None:
            raise ValueError(f"preferred profile {prefer!r} is not valid for this hardware report")
    else:
        selected = candidates[0]

    profile = deepcopy(PROFILE_DEFS[selected["id"]])
    primary_gpu = selected.get("gpu")
    tier = hardware_tier(primary_gpu)
    runtime_defaults = _runtime_defaults(selected["id"], primary_gpu, tier)
    optional_features = _optional_features(profile, runtime_defaults)
    model_policy = _model_policy(selected["id"], runtime_defaults, tier)

    return {
        "schema_version": 1,
        "selected_profile": selected["id"],
        "label": profile["label"],
        "confidence": selected["confidence"],
        "reason": selected["reason"],
        "hardware_tier": tier,
        "primary_gpu": _public_gpu(primary_gpu),
        "candidates": [_public_candidate(candidate) for candidate in candidates],
        "install": {
            "torch": {
                "packages": profile["torch_packages"],
                "index_url": profile["torch_index_url"],
            },
            "requirements": profile["requirements"],
            "verify": profile["verify"],
        },
        "runtime_defaults": runtime_defaults,
        "optional_features": optional_features,
        "disabled_features": profile["disabled_features"],
        "model_policy": model_policy,
        "warnings": selected.get("warnings", []),
        "sources": {
            "pytorch_install": "https://pytorch.org/get-started/locally/",
            "pytorch_previous_versions": "https://pytorch.org/get-started/previous-versions/",
            "nvidia_compute_capability": "https://developer.nvidia.com/cuda/gpus",
            "amd_rocm_system_requirements": "https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html",
            "amd_rocm_pytorch": "https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/3rd-party/pytorch-install.html",
        },
    }


def _candidate_profiles(report: dict[str, Any]) -> list[dict[str, Any]]:
    os_name = str((report.get("os") or {}).get("system") or "").lower()
    gpus = report.get("gpus") or []
    candidates: list[dict[str, Any]] = []

    nvidia = _best_gpu(gpus, "nvidia")
    if nvidia and os_name != "darwin":
        warnings = []
        vram = _vram_mb(nvidia)
        if vram is not None and vram < 8192:
            warnings.append("NVIDIA GPU has less than 8 GB VRAM; use small models and CPU offload.")
        candidates.append({
            "id": "nvidia-cuda",
            "confidence": "high" if _compute_cap(nvidia) or (vram and vram >= 8192) else "medium",
            "reason": "NVIDIA GPU detected; CUDA PyTorch wheels are the recommended accelerator path.",
            "gpu": nvidia,
            "warnings": warnings,
        })

    amd = _best_gpu(gpus, "amd")
    if amd:
        rocm_support = _amd_rocm_support(amd, report)
        if os_name == "linux" and rocm_support in {"official", "visible"}:
            candidates.append({
                "id": "amd-rocm-linux",
                "confidence": "high" if rocm_support == "official" else "medium",
                "reason": "AMD GPU with ROCm support detected on Linux.",
                "gpu": amd,
                "warnings": [
                    "CUDA-only acceleration is disabled on ROCm; expect feature parity work to continue."
                ],
            })
        elif os_name == "linux":
            candidates.append({
                "id": "cpu-safe",
                "confidence": "medium",
                "reason": "AMD GPU detected, but ROCm visibility/support was not confirmed.",
                "gpu": amd,
                "warnings": ["Install ROCm for a supported AMD GPU before selecting the ROCm profile."],
            })
        else:
            candidates.append({
                "id": "cpu-safe",
                "confidence": "high",
                "reason": "AMD GPU detected, but the supported PyTorch ROCm path is Linux-first.",
                "gpu": amd,
                "warnings": ["Windows AMD acceleration is not auto-selected yet; CPU-safe mode is used."],
            })

    if not candidates:
        reason = "No supported GPU accelerator detected."
        if os_name == "darwin":
            reason = "macOS has no CUDA/ROCm path in this app; using CPU-safe mode."
        candidates.append({
            "id": "cpu-safe",
            "confidence": "high",
            "reason": reason,
            "gpu": None,
            "warnings": [],
        })

    if not any(candidate["id"] == "cpu-safe" for candidate in candidates):
        candidates.append({
            "id": "cpu-safe",
            "confidence": "fallback",
            "reason": "Always available fallback when accelerator setup fails.",
            "gpu": None,
            "warnings": [],
        })

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for candidate in candidates:
        key = candidate["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _best_gpu(gpus: list[dict[str, Any]], vendor: str) -> dict[str, Any] | None:
    matches = [gpu for gpu in gpus if str(gpu.get("vendor")).lower() == vendor]
    if not matches:
        return None
    return sorted(matches, key=lambda gpu: _vram_mb(gpu) or 0, reverse=True)[0]


def _vram_mb(gpu: dict[str, Any] | None) -> int | None:
    if not gpu:
        return None
    value = gpu.get("vram_mb")
    if value is None and isinstance(gpu.get("torch"), dict):
        value = gpu["torch"].get("total_memory_mb")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compute_cap(gpu: dict[str, Any] | None) -> tuple[int, int] | None:
    if not gpu:
        return None
    value = gpu.get("compute_capability_tuple")
    if isinstance(value, list) and len(value) >= 2:
        return int(value[0]), int(value[1])
    raw = str(gpu.get("compute_capability") or "")
    if "." in raw:
        major, _, minor = raw.partition(".")
        try:
            return int(major), int(minor)
        except ValueError:
            return None
    return None


def _amd_rocm_support(gpu: dict[str, Any], report: dict[str, Any]) -> str:
    rocm = gpu.get("rocm") if isinstance(gpu.get("rocm"), dict) else {}
    support = str(rocm.get("support") or "")
    if support == "official":
        return "official"
    if rocm.get("visible"):
        return "visible"
    global_rocm = report.get("rocm") or {}
    if global_rocm.get("official_targets"):
        return "official"
    if global_rocm.get("llvm_targets"):
        return "visible"
    return "not_visible"


def hardware_tier(gpu: dict[str, Any] | None) -> str:
    vram = _vram_mb(gpu)
    if vram is None:
        return "unknown"
    # Vendor tools report MiB and often reserve a slice of nominal VRAM, so use
    # marketing-friendly thresholds (8/12/16/24 GB) instead of exact GiB values.
    if vram >= 24000:
        return "large_24gb_plus"
    if vram >= 16000:
        return "rich_16gb_plus"
    if vram >= 12000:
        return "balanced_12gb"
    if vram >= 8000:
        return "safe_8gb"
    return "low_vram"


def _runtime_defaults(profile_id: str, gpu: dict[str, Any] | None, tier: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "stub_mode": profile_id == "cpu-safe",
        "profile_id": profile_id,
        "image_recommendation_tier": tier,
        "prefer_cpu_offload": tier in {"low_vram", "safe_8gb", "unknown"},
    }
    if profile_id == "nvidia-cuda":
        cap = _compute_cap(gpu)
        # Ampere (8.0) is the floor for flash-attention-2 and the nunchaku fp4
        # kernels. Pre-Ampere CUDA cards (Pascal 6.x, Turing/Volta 7.x) still run
        # SDXL, but only on the math/SDPA attention path with no fp4 fast lane.
        ampere_plus = bool(cap and cap >= (8, 0))
        viable = ampere_plus and tier not in {"low_vram", "unknown"}
        defaults.update({
            "backend": "cuda",
            "architecture": nvidia_architecture(cap),
            "torch_compile": viable,
            "attention_backend": "auto" if ampere_plus else "math",
            "allow_nunchaku": viable,
            # First-block step cache relies on the same fp4 fast path nunchaku uses.
            "flux_step_cache": "fb" if viable else "off",
            "blackwell_fast_paths": bool(cap and cap >= (12, 0)),
        })
    elif profile_id == "amd-rocm-linux":
        defaults.update({
            "backend": "rocm",
            "architecture": "rocm",
            "torch_compile": False,
            "attention_backend": "auto",
            "allow_nunchaku": False,
            "flux_step_cache": "off",
            "blackwell_fast_paths": False,
        })
    else:
        defaults.update({
            "backend": "cpu",
            "architecture": "cpu",
            "torch_compile": False,
            "attention_backend": "math",
            "allow_nunchaku": False,
            "flux_step_cache": "off",
            "blackwell_fast_paths": False,
        })
    return defaults


def nvidia_architecture(cap: tuple[int, int] | None) -> str | None:
    """Map an NVIDIA compute capability to a marketing architecture name."""
    if cap is None:
        return None
    major, minor = cap
    if major >= 10:
        return "blackwell"
    if major == 9:
        return "hopper"
    if major == 8:
        return "ada" if minor == 9 else "ampere"
    if major == 7:
        return "turing" if minor == 5 else "volta"
    if major == 6:
        return "pascal"
    if major == 5:
        return "maxwell"
    return "legacy"


def _optional_features(profile: dict[str, Any], defaults: dict[str, Any]) -> list[str]:
    """Drop install-time features the active GPU can't actually use.

    The installer pip-installs each entry (e.g. the CUDA nunchaku wheel), so a
    pre-Ampere NVIDIA card must not advertise ``nunchaku_cuda`` or setup would
    fetch a wheel whose fp4 kernels never load.
    """
    features = list(profile["optional_features"])
    if "nunchaku_cuda" in features and not defaults.get("allow_nunchaku"):
        features.remove("nunchaku_cuda")
    return features


def _model_policy(profile_id: str, defaults: dict[str, Any], tier: str) -> dict[str, Any]:
    """Bucket image families into recommended / advanced / hidden for this GPU.

    ``recommended`` is preselected UX, ``advanced`` runs but is a stretch at this
    tier, ``hidden`` cannot run on this hardware path at all (P20.7 wires this to
    the download manager).
    """
    backend = str(defaults.get("backend") or "cpu")
    allow_nunchaku = bool(defaults.get("allow_nunchaku"))
    tier_rank = TIER_RANK.get(tier, 0)
    notes: list[str] = []

    recommended: list[str] = []
    advanced: list[str] = []
    hidden: list[str] = []

    if backend == "cpu":
        # CPU-safe/STUB renders placeholders; no real image family is recommended.
        hidden = list(IMAGE_FAMILY_POLICY)
        notes.append("CPU-safe/STUB mode renders placeholder images; real model paths are hidden.")
    else:
        for family, rule in IMAGE_FAMILY_POLICY.items():
            if rule["needs_nunchaku"] and not allow_nunchaku:
                hidden.append(family)
            elif tier_rank >= TIER_RANK[rule["min_tier"]]:
                recommended.append(family)
            else:
                advanced.append(family)
        if backend == "rocm" and hidden:
            notes.append("nunchaku fp4 families need a CUDA GPU; not available on ROCm.")
        elif hidden:
            notes.append("nunchaku fp4 families need an Ampere-or-newer NVIDIA GPU.")

    return {
        "tier": tier,
        "image": {
            "recommended": recommended,
            "advanced": advanced,
            "hidden": hidden,
        },
        "llm": {
            "max_recommended_params_b": LLM_RECOMMENDED_PARAMS_B.get(tier, 8),
        },
        "notes": notes,
    }


def _public_gpu(gpu: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gpu:
        return None
    cap = _compute_cap(gpu)
    return {
        "vendor": gpu.get("vendor"),
        "name": gpu.get("name"),
        "vram_mb": _vram_mb(gpu),
        "compute_capability_tuple": list(cap or ()),
        "architecture": nvidia_architecture(cap) if str(gpu.get("vendor")).lower() == "nvidia" else None,
        "rocm": gpu.get("rocm"),
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "confidence": candidate["confidence"],
        "reason": candidate["reason"],
        "gpu": _public_gpu(candidate.get("gpu")),
        "warnings": candidate.get("warnings", []),
    }


def _load_report(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    try:
        from hardware_probe import collect_report
    except ImportError:
        from scripts.hardware_probe import collect_report  # type: ignore[no-redef]
    return collect_report(os.getcwd())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve HFabric install profile JSON.")
    parser.add_argument("--probe", help="Path to a hardware_probe.py JSON report. If omitted, probe now.")
    parser.add_argument("--prefer", choices=sorted(PROFILE_DEFS), help="Require a specific valid profile.")
    parser.add_argument("--output", "-o", help="Write JSON to this file instead of stdout.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    args = parser.parse_args(argv)

    result = resolve_profile(_load_report(args.probe), args.prefer)
    data = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(data)
    else:
        sys.stdout.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
