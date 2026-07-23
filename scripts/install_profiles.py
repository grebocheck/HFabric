"""Resolve an HFabric install profile from a hardware probe report.

The profile is advisory and machine-readable: setup scripts can consume it to
choose package indexes and defaults, while the UI can explain the decision in
plain language.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "backend" / "dependency-profiles.json"


def _load_dependency_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load dependency profile manifest {path}: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise RuntimeError(
            f"unsupported dependency profile manifest schema: {manifest.get('schema_version')!r}"
        )
    required_sections = {"resolver", "torch", "locks", "profiles"}
    missing = sorted(required_sections - manifest.keys())
    if missing:
        raise RuntimeError(f"dependency profile manifest is missing: {', '.join(missing)}")
    return manifest


DEPENDENCY_MANIFEST = _load_dependency_manifest()
PYTORCH_VERSION = str(DEPENDENCY_MANIFEST["torch"]["torch"])
TORCHVISION_VERSION = str(DEPENDENCY_MANIFEST["torch"]["torchvision"])
TORCHAUDIO_VERSION = str(DEPENDENCY_MANIFEST["torch"]["torchaudio"])

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

VIDEO_FAMILIES = (
    "ltx-video",
    "wan-video",
    "hunyuan-video",
    "cogvideo",
    "animatediff",
)

CUDA_VIDEO_FAMILIES = {
    "ltx-video": {"min_tier": "safe_8gb", "recommended": True},
    "wan-video": {"min_tier": "rich_16gb_plus", "recommended": False},
    "hunyuan-video": {"min_tier": "rich_16gb_plus", "recommended": False},
    "cogvideo": {"min_tier": "safe_8gb", "recommended": False},
}

VIDEO_FALLBACK_CANDIDATES = ("cogvideo", "animatediff")

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

def _profile_definitions() -> dict[str, dict[str, Any]]:
    torch_packages = [
        f"torch=={PYTORCH_VERSION}",
        f"torchvision=={TORCHVISION_VERSION}",
        f"torchaudio=={TORCHAUDIO_VERSION}",
    ]
    definitions: dict[str, dict[str, Any]] = {}
    locks = DEPENDENCY_MANIFEST["locks"]
    for profile_id, raw in DEPENDENCY_MANIFEST["profiles"].items():
        profile = deepcopy(raw)
        profile["torch_packages"] = list(torch_packages)
        # Compatibility keys remain available to the capability service and
        # third-party scripts, but are derived from the manifest rather than
        # maintained as a second source of truth.
        targets = profile.get("targets") or []
        profile["torch_index_url"] = targets[0].get("torch_index_url") if targets else None
        profile["requirements"] = [
            locks[target["lock"]]["output"]
            for target in targets
            if target.get("lock")
        ]
        definitions[profile_id] = profile
    return definitions


PROFILE_DEFS = _profile_definitions()


def _install_target(profile_id: str, report: dict[str, Any]) -> dict[str, Any] | None:
    profile = PROFILE_DEFS[profile_id]
    os_info = report.get("os") or {}
    system = str(os_info.get("system") or "").lower()
    machine = str(os_info.get("machine") or "").lower()
    fallback: dict[str, Any] | None = None
    for target in profile.get("targets") or []:
        systems = {str(value).lower() for value in target.get("systems") or []}
        machines = {str(value).lower() for value in target.get("machines") or []}
        if not systems:
            fallback = target
            continue
        if system not in systems:
            continue
        # Older probe fixtures did not include machine. Treat an unknown
        # architecture as the profile's documented default, but reject an
        # explicitly unsupported architecture.
        if machine and machines and machine not in machines:
            continue
        return target
    return fallback


def resolve_profile(report: dict[str, Any], prefer: str | None = None) -> dict[str, Any]:
    candidates = _candidate_profiles(report)
    if prefer:
        selected = next((candidate for candidate in candidates if candidate["id"] == prefer), None)
        if selected is None:
            raise ValueError(f"preferred profile {prefer!r} is not valid for this hardware report")
    else:
        selected = candidates[0]

    profile = deepcopy(PROFILE_DEFS[selected["id"]])
    target = _install_target(selected["id"], report)
    if target is None:
        raise ValueError(f"profile {selected['id']!r} has no supported install target for this host")
    lock_id = target.get("lock")
    requirements = (
        [str(DEPENDENCY_MANIFEST["locks"][lock_id]["output"])]
        if lock_id
        else []
    )
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
            "target": target["id"],
            "foundation_lock": DEPENDENCY_MANIFEST["locks"]["foundation"]["output"],
            "torch": {
                "packages": profile["torch_packages"],
                "backend": target.get("torch_backend"),
                "index_url": target.get("torch_index_url"),
            },
            "requirements": requirements,
            "hashes_required": bool(requirements),
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
            "pytorch_mps": "https://pytorch.org/docs/stable/notes/mps.html",
        },
    }


def _candidate_profiles(report: dict[str, Any]) -> list[dict[str, Any]]:
    os_name = str((report.get("os") or {}).get("system") or "").lower()
    gpus = report.get("gpus") or []
    candidates: list[dict[str, Any]] = []

    nvidia = _best_gpu(gpus, "nvidia")
    nvidia_target = _install_target("nvidia-cuda", report)
    if nvidia and nvidia_target is not None:
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
        rocm_target = _install_target("amd-rocm-linux", report)
        if rocm_target is not None and rocm_support in {"official", "community_experimental", "visible"}:
            warnings = ["CUDA-only acceleration is disabled on ROCm; expect feature parity work to continue."]
            if rocm_support != "official":
                warnings.append(
                    "ROCm sees this AMD target, but it is not in the official support list; treating it as experimental."
                )
            candidates.append({
                "id": "amd-rocm-linux",
                "confidence": "high" if rocm_support == "official" else "medium",
                "reason": (
                    "AMD GPU with official ROCm support detected on Linux."
                    if rocm_support == "official"
                    else "AMD GPU is visible to ROCm on Linux; experimental ROCm profile selected."
                ),
                "gpu": amd,
                "warnings": warnings,
            })
        elif rocm_target is not None:
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

    apple = _best_gpu(gpus, "apple")
    machine = str((report.get("os") or {}).get("machine") or "").lower()
    if (
        _install_target("apple-mps", report) is not None
        and (apple or machine in {"arm64", "aarch64"})
    ):
        torch_info = report.get("torch") or {}
        mps_available = bool(torch_info.get("mps_available"))
        candidates.append({
            "id": "apple-mps",
            "confidence": "high" if mps_available else "medium",
            "reason": (
                "Apple Silicon detected; PyTorch MPS is the recommended accelerator path."
            ),
            "gpu": apple or {
                "vendor": "apple",
                "name": "Apple Silicon GPU",
                "architecture": "apple-silicon",
                "mps": {"potential": True},
            },
            "warnings": [] if mps_available else [
                "PyTorch MPS visibility will be verified after installing the standard PyPI torch wheels."
            ],
        })

    if not candidates:
        reason = "No supported GPU accelerator detected."
        if os_name == "darwin":
            reason = "macOS Intel or non-MPS machine detected; using CPU-safe mode."
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
    if support in {"community_experimental", "community_or_unknown"}:
        return "community_experimental"
    if rocm.get("visible"):
        return "community_experimental"
    global_rocm = report.get("rocm") or {}
    if global_rocm.get("official_targets"):
        return "official"
    if global_rocm.get("llvm_targets"):
        return "community_experimental"
    return "unsupported"


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
            "torch_device": "cuda",
            "architecture": nvidia_architecture(cap),
            "torch_compile": viable,
            "attention_backend": "auto" if ampere_plus else "math",
            "allow_nunchaku": viable,
            # First-block step cache relies on the same fp4 fast path nunchaku uses.
            "flux_step_cache": "fb" if viable else "off",
            "blackwell_fast_paths": bool(cap and cap >= (12, 0)),
            # LTX's fp8-optimized lane is an Ada/Blackwell-class video path.
            # Keep it separate from blackwell_fast_paths so RTX 40-series cards
            # can advertise fp8 video without enabling sm_120-only toggles.
            "video_fp8_fast_paths": bool(cap and cap >= (8, 9) and tier not in {"low_vram", "unknown"}),
            "video_light_fallback": False,
        })
    elif profile_id == "amd-rocm-linux":
        defaults.update({
            "backend": "rocm",
            "torch_device": "cuda",
            "architecture": "rocm",
            "torch_compile": False,
            "attention_backend": "auto",
            "allow_nunchaku": False,
            "flux_step_cache": "off",
            "blackwell_fast_paths": False,
            "video_fp8_fast_paths": False,
            "video_light_fallback": True,
        })
    elif profile_id == "apple-mps":
        defaults.update({
            "backend": "mps",
            "torch_device": "mps",
            "architecture": "apple-silicon",
            "torch_compile": False,
            "attention_backend": "math",
            "allow_nunchaku": False,
            "flux_step_cache": "off",
            "blackwell_fast_paths": False,
            "video_fp8_fast_paths": False,
            "video_light_fallback": True,
            "prefer_cpu_offload": False,
        })
    else:
        defaults.update({
            "backend": "cpu",
            "torch_device": "cpu",
            "architecture": "cpu",
            "torch_compile": False,
            "attention_backend": "math",
            "allow_nunchaku": False,
            "flux_step_cache": "off",
            "blackwell_fast_paths": False,
            "video_fp8_fast_paths": False,
            "video_light_fallback": False,
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
    tier, while ``hidden`` cannot run on this hardware path and is omitted from
    the download manager.
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
    elif backend == "mps":
        recommended = ["sdxl"]
        hidden = [family for family in IMAGE_FAMILY_POLICY if family != "sdxl"]
        notes.append("Apple MPS is conservative: SDXL is enabled; fp4/large image families wait for real-Mac validation.")
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
        "video": _video_policy(defaults, tier, notes),
        "llm": {
            "max_recommended_params_b": LLM_RECOMMENDED_PARAMS_B.get(tier, 8),
        },
        "notes": notes,
    }


def _video_policy(defaults: dict[str, Any], tier: str, notes: list[str]) -> dict[str, Any]:
    """Bucket runnable video families separately from planned fallback candidates.

    The registry can recognize CogVideoX/AnimateDiff repos. CogVideoX-2B is the
    light fallback path for ROCm/MPS; AnimateDiff stays hidden until its SDXL
    adapter composition is implemented and validated.
    """
    backend = str(defaults.get("backend") or "cpu")
    tier_rank = TIER_RANK.get(tier, 0)
    recommended: list[str] = []
    advanced: list[str] = []
    hidden: list[str] = []

    if backend != "cuda":
        if backend in {"rocm", "mps"} and defaults.get("video_light_fallback"):
            recommended = ["cogvideo"]
            hidden = [family for family in VIDEO_FAMILIES if family not in recommended]
            notes.append(
                "ROCm/MPS video exposes CogVideoX-2B as the light T2V fallback; "
                "LTX/Wan/FramePack remain CUDA-only and real-machine fallback smoke is still required."
            )
        else:
            hidden = list(VIDEO_FAMILIES)
            notes.append("CPU-safe/STUB mode hides real video models; use STUB output or an accelerator profile.")
        return {
            "recommended": recommended,
            "advanced": advanced,
            "hidden": hidden,
            "fallback_candidates": list(VIDEO_FALLBACK_CANDIDATES),
        }

    if tier in {"unknown", "low_vram"}:
        hidden = list(VIDEO_FAMILIES)
        notes.append("Real video generation is hidden below the 8 GB VRAM safety floor.")
        return {
            "recommended": recommended,
            "advanced": advanced,
            "hidden": hidden,
            "fallback_candidates": list(VIDEO_FALLBACK_CANDIDATES),
        }

    for family, rule in CUDA_VIDEO_FAMILIES.items():
        if tier_rank >= TIER_RANK[rule["min_tier"]] and rule["recommended"]:
            recommended.append(family)
        else:
            advanced.append(family)

    hidden = [family for family in VIDEO_FAMILIES if family not in recommended and family not in advanced]
    notes.append(
        "CUDA video policy: LTX is the default; Wan and FramePack are advanced tiers with per-job RAM/VRAM guards."
    )
    if defaults.get("video_fp8_fast_paths"):
        notes.append("Ada/Blackwell fp8 video fast paths are enabled for compatible LTX loaders.")
    if defaults.get("blackwell_fast_paths"):
        notes.append("Blackwell-only fast paths are enabled for sm_120+ kernels.")
    return {
        "recommended": recommended,
        "advanced": advanced,
        "hidden": hidden,
        "fallback_candidates": list(VIDEO_FALLBACK_CANDIDATES),
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
        "architecture": (
            nvidia_architecture(cap)
            if str(gpu.get("vendor")).lower() == "nvidia"
            else gpu.get("architecture")
        ),
        "rocm": gpu.get("rocm"),
        "mps": gpu.get("mps"),
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "confidence": candidate["confidence"],
        "reason": candidate["reason"],
        "gpu": _public_gpu(candidate.get("gpu")),
        "warnings": candidate.get("warnings", []),
    }


LOCK_FINGERPRINT_RE = re.compile(r"^# hfabric-lock-input-sha256: ([0-9a-f]{64})$", re.MULTILINE)


def lock_fingerprint(
    lock_id: str,
    *,
    manifest: dict[str, Any] = DEPENDENCY_MANIFEST,
    root: Path = ROOT,
) -> str:
    """Hash every source and resolver option that can affect a compiled lock."""
    try:
        spec = manifest["locks"][lock_id]
    except KeyError as exc:
        raise ValueError(f"unknown dependency lock {lock_id!r}") from exc
    payload = {
        "schema_version": manifest["schema_version"],
        "python_version": manifest["python_version"],
        "resolver": manifest["resolver"],
        "torch": manifest["torch"],
        "lock_id": lock_id,
        "spec": spec,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    for relative in spec.get("source_files") or []:
        path = root / relative
        digest.update(b"\0path\0")
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0content\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_lock_fingerprint(path: Path) -> str | None:
    match = LOCK_FINGERPRINT_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _find_uv() -> Path:
    executable = "uv.exe" if os.name == "nt" else "uv"
    adjacent = Path(sys.executable).with_name(executable)
    if adjacent.is_file():
        return adjacent
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise RuntimeError(
        "uv is required to compile dependency locks; install backend/requirements-dev.lock first"
    )


def _assert_uv_version(uv: Path) -> None:
    expected = str(DEPENDENCY_MANIFEST["resolver"]["version"])
    result = subprocess.run(
        [str(uv), "--version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", result.stdout)
    actual = match.group(1) if match else result.stdout.strip()
    if actual != expected:
        raise RuntimeError(f"dependency locks require uv {expected}; found {actual or 'unknown'}")


def _normalise_compiled_lock(
    text: str,
    *,
    lock_id: str,
    replacements: dict[str, str],
) -> str:
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
        text = text.replace(source.replace("\\", "/"), replacement)
    marker = f"# hfabric-lock-input-sha256: {lock_fingerprint(lock_id)}"
    lines = text.splitlines()
    lines = [line for line in lines if not line.startswith("# hfabric-lock-input-sha256:")]
    return "\n".join([marker, *lines]) + "\n"


def compile_dependency_locks(
    lock_ids: list[str] | tuple[str, ...] | None = None,
    *,
    check: bool = False,
) -> list[str]:
    """Compile or compare deterministic, platform-specific hashed locks.

    All requested outputs are staged first, so a resolver failure cannot leave
    the repository with a partially refreshed lock set.
    """
    locks: dict[str, dict[str, Any]] = DEPENDENCY_MANIFEST["locks"]
    requested = list(lock_ids or locks)
    unknown = sorted(set(requested) - locks.keys())
    if unknown:
        raise ValueError(f"unknown dependency lock(s): {', '.join(unknown)}")
    # Preserve manifest order, both for stable output and so development can
    # constrain against the freshly staged foundation lock during a full run.
    requested_set = set(requested)
    ordered = [lock_id for lock_id in locks if lock_id in requested_set]
    uv = _find_uv()
    _assert_uv_version(uv)
    resolver = DEPENDENCY_MANIFEST["resolver"]
    python_version = str(DEPENDENCY_MANIFEST["python_version"])
    command_label = str(resolver["command"])
    stale: list[str] = []

    temp_parent = ROOT / ".tmp"
    temp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dependency-locks-", dir=temp_parent) as temp_name:
        temp_root = Path(temp_name)
        staged: dict[str, Path] = {}
        for lock_id in ordered:
            spec = locks[lock_id]
            stage = temp_root / f"{lock_id}.lock"
            args = [
                str(uv),
                "pip",
                "compile",
                str(spec["input"]),
                "--output-file",
                str(stage),
                "--python-version",
                python_version,
                "--generate-hashes",
                "--custom-compile-command",
                command_label,
                "--exclude-newer",
                str(resolver["exclude_newer"]),
                "--quiet",
            ]
            if spec.get("universal"):
                args.append("--universal")
            if spec.get("python_platform"):
                args.extend(["--python-platform", str(spec["python_platform"])])
            if spec.get("torch_backend"):
                args.extend(["--torch-backend", str(spec["torch_backend"])])
            for package in spec.get("omit_packages") or []:
                args.extend(["--no-emit-package", str(package)])

            replacements: dict[str, str] = {}
            constraint_id = spec.get("constraint_lock")
            if constraint_id:
                constraint_path = staged.get(constraint_id)
                if constraint_path is None:
                    constraint_path = ROOT / locks[constraint_id]["output"]
                args.extend(["--constraint", str(constraint_path)])
                canonical = str(locks[constraint_id]["output"]).replace("\\", "/")
                replacements[str(constraint_path)] = canonical
                try:
                    replacements[str(constraint_path.relative_to(ROOT))] = canonical
                except ValueError:
                    pass

            result = subprocess.run(
                args,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"failed to compile {lock_id}: {details}")

            normalised = _normalise_compiled_lock(
                stage.read_text(encoding="utf-8"),
                lock_id=lock_id,
                replacements=replacements,
            )
            stage.write_text(normalised, encoding="utf-8", newline="\n")
            staged[lock_id] = stage

        for lock_id in ordered:
            target = ROOT / locks[lock_id]["output"]
            generated = staged[lock_id].read_text(encoding="utf-8")
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if check:
                if current != generated:
                    stale.append(lock_id)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged[lock_id], target)
            print(f"compiled {lock_id}: {target.relative_to(ROOT)}")
    return stale


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
    parser = argparse.ArgumentParser(
        description="Resolve an HFabric install profile or compile its dependency locks."
    )
    lock_actions = parser.add_mutually_exclusive_group()
    lock_actions.add_argument(
        "--compile-locks",
        action="store_true",
        help="Compile manifest-declared hashed lock files atomically with the pinned uv resolver.",
    )
    lock_actions.add_argument(
        "--check-locks",
        action="store_true",
        help="Resolve locks into a temporary directory and fail if committed outputs differ.",
    )
    parser.add_argument(
        "--lock",
        action="append",
        choices=sorted(DEPENDENCY_MANIFEST["locks"]),
        help="Limit --compile-locks/--check-locks to one lock (repeatable).",
    )
    parser.add_argument("--probe", help="Path to a hardware_probe.py JSON report. If omitted, probe now.")
    parser.add_argument("--prefer", choices=sorted(PROFILE_DEFS), help="Require a specific valid profile.")
    parser.add_argument("--output", "-o", help="Write JSON to this file instead of stdout.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    args = parser.parse_args(argv)

    if args.lock and not (args.compile_locks or args.check_locks):
        parser.error("--lock requires --compile-locks or --check-locks")
    if args.compile_locks or args.check_locks:
        if args.probe or args.prefer or args.output or args.pretty:
            parser.error("profile-resolution options cannot be combined with lock actions")
        try:
            stale = compile_dependency_locks(args.lock, check=args.check_locks)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"dependency lock error: {exc}", file=sys.stderr)
            return 1
        if stale:
            print(
                "dependency locks are stale: "
                + ", ".join(stale)
                + "; run "
                + str(DEPENDENCY_MANIFEST["resolver"]["command"]),
                file=sys.stderr,
            )
            return 1
        if args.check_locks:
            print("dependency locks match the canonical profile inputs")
        return 0

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
