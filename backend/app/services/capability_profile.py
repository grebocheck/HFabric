"""Runtime capability profile built from the shared hardware/install resolver.

Installer and launcher decisions live in ``scripts/install_profiles.py``. The
backend imports that resolver by file path so runtime/API decisions stay aligned
without turning ``scripts`` into an installed package.
"""

from __future__ import annotations

from copy import deepcopy
from functools import cache, lru_cache
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from ..config import ROOT, settings

CUDA_FEATURES = {
    "nunchaku_cuda",
    "cuda_llama_binaries",
    "onnxruntime_cuda",
    "realtime_cuda_voice",
}


def get_capability_profile(*, refresh: bool = False) -> dict[str, Any]:
    """Return the active runtime capability profile for this process."""
    if refresh:
        _hardware_profile.cache_clear()
    return build_capability_profile(_hardware_profile())


def build_capability_profile(resolved: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an API-safe profile from a resolved install profile.

    Tests pass ``resolved`` directly. Production callers use the cached hardware
    probe + resolver through :func:`get_capability_profile`.
    """
    resolved = deepcopy(resolved or _hardware_profile())
    selected_profile = str(resolved.get("selected_profile") or "cpu-safe")
    selected_defaults = dict(resolved.get("runtime_defaults") or {})
    configured_stub = bool(settings.stub_mode)
    effective_stub = configured_stub or selected_profile == "cpu-safe"

    active_profile = "cpu-safe" if effective_stub else selected_profile
    active_defaults = _active_defaults(selected_defaults, effective_stub)
    backend = str(active_defaults.get("backend") or "cpu")
    disabled_features = _disabled_features(resolved, active_defaults, effective_stub)
    features = _features(resolved, active_defaults, disabled_features)
    warnings = _warnings(resolved, configured_stub, effective_stub, selected_profile)

    return {
        "schema_version": 1,
        "selected_profile": selected_profile,
        "active_profile": active_profile,
        "label": resolved.get("label"),
        "backend": backend,
        "configured_stub_mode": configured_stub,
        "effective_stub_mode": effective_stub,
        "confidence": resolved.get("confidence"),
        "reason": resolved.get("reason"),
        "hardware_tier": resolved.get("hardware_tier") or "unknown",
        "primary_gpu": resolved.get("primary_gpu"),
        "runtime_defaults": active_defaults,
        "features": features,
        "disabled_features": disabled_features,
        "model_policy": resolved.get("model_policy") or {},
        "warnings": warnings,
        "candidates": resolved.get("candidates") or [],
        "sources": resolved.get("sources") or {},
    }


def _active_defaults(defaults: dict[str, Any], effective_stub: bool) -> dict[str, Any]:
    active = dict(defaults)
    if effective_stub:
        active.update({
            "backend": "cpu",
            "stub_mode": True,
            "torch_compile": False,
            "attention_backend": "math",
            "allow_nunchaku": False,
            "blackwell_fast_paths": False,
            "prefer_cpu_offload": True,
        })
    return active


def _features(
    resolved: dict[str, Any],
    defaults: dict[str, Any],
    disabled_features: list[str],
) -> dict[str, bool]:
    backend = str(defaults.get("backend") or "cpu")
    optional = set(resolved.get("optional_features") or [])
    disabled = set(disabled_features)

    return {
        "cuda": backend == "cuda",
        "rocm": backend == "rocm",
        "cpu_safe": backend == "cpu",
        "torch_compile": bool(defaults.get("torch_compile")) and "torch_compile" not in disabled,
        "nunchaku_cuda": (
            backend == "cuda"
            and bool(defaults.get("allow_nunchaku"))
            and "nunchaku_cuda" in optional
            and "nunchaku_cuda" not in disabled
        ),
        "cuda_llama_binaries": (
            backend == "cuda"
            and "cuda_llama_binaries" in optional
            and "cuda_llama_binaries" not in disabled
        ),
        "onnxruntime_cuda": (
            backend == "cuda"
            and "onnxruntime_cuda" in optional
            and "onnxruntime_cuda" not in disabled
        ),
        "realtime_cuda_voice": backend == "cuda" and "realtime_cuda_voice" not in disabled,
        "blackwell_fast_paths": bool(defaults.get("blackwell_fast_paths")),
        "prefer_cpu_offload": bool(defaults.get("prefer_cpu_offload")),
    }


def _disabled_features(
    resolved: dict[str, Any],
    defaults: dict[str, Any],
    effective_stub: bool,
) -> list[str]:
    disabled = set(resolved.get("disabled_features") or [])
    backend = str(defaults.get("backend") or "cpu")

    if effective_stub:
        disabled.update(_cpu_safe_disabled_features())
    if backend != "cuda":
        disabled.update(CUDA_FEATURES)
        disabled.add("blackwell_fast_paths")
    if not defaults.get("allow_nunchaku"):
        disabled.add("nunchaku_cuda")
    if not defaults.get("torch_compile"):
        disabled.add("torch_compile")

    return sorted(disabled)


def _warnings(
    resolved: dict[str, Any],
    configured_stub: bool,
    effective_stub: bool,
    selected_profile: str,
) -> list[str]:
    warnings = list(resolved.get("warnings") or [])
    if configured_stub and selected_profile != "cpu-safe":
        warnings.append("STUB mode is enabled; accelerator features are disabled for this process.")
    elif effective_stub and selected_profile == "cpu-safe":
        warnings.append("CPU-safe profile is active; heavy GPU features are disabled.")
    return warnings


@lru_cache(maxsize=1)
def _hardware_profile() -> dict[str, Any]:
    report = _hardware_probe_module().collect_report(settings.root)
    return _install_profiles_module().resolve_profile(report)


@lru_cache(maxsize=1)
def _cpu_safe_disabled_features() -> tuple[str, ...]:
    profile_defs = _install_profiles_module().PROFILE_DEFS
    return tuple(profile_defs["cpu-safe"]["disabled_features"])


@cache
def _script_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hardware_probe_module() -> ModuleType:
    return _script_module("_hfabric_hardware_probe", ROOT / "scripts" / "hardware_probe.py")


def _install_profiles_module() -> ModuleType:
    return _script_module("_hfabric_install_profiles", ROOT / "scripts" / "install_profiles.py")
