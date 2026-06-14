from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from install_smoke import ERROR, OK, WARN, evaluate  # noqa: E402


def status_of(result: dict, name: str) -> str:
    return next(c["status"] for c in result["checks"] if c["name"] == name)


def report(system: str, gpus: list[dict], torch: dict | None = None) -> dict:
    return {
        "os": {"system": system},
        "python": {"version": "3.12.0"},
        "gpus": gpus,
        "rocm": {},
        "torch": torch or {},
    }


def test_nvidia_cuda_torch_match_passes():
    result = evaluate(
        report(
            "Linux",
            [{"vendor": "nvidia", "name": "RTX 5070 Ti", "vram_mb": 16303, "compute_capability_tuple": [12, 0]}],
            torch={"installed": True, "cuda_available": True, "torch_hip_version": None},
        ),
        run_verify=False,
    )
    assert result["ok"] is True
    assert status_of(result, "torch_visible") == OK
    assert status_of(result, "feature_sanity") == OK


def test_nvidia_profile_with_rocm_torch_build_fails():
    # CUDA profile but torch is a HIP build -> mismatched install, must fail.
    result = evaluate(
        report(
            "Linux",
            [{"vendor": "nvidia", "name": "RTX 4090", "vram_mb": 24576, "compute_capability_tuple": [8, 9]}],
            torch={"installed": True, "cuda_available": True, "torch_hip_version": "6.2"},
        ),
        run_verify=False,
    )
    assert result["ok"] is False
    assert status_of(result, "torch_visible") == ERROR


def test_cuda_profile_without_visible_accelerator_fails():
    result = evaluate(
        report(
            "Linux",
            [{"vendor": "nvidia", "name": "RTX 3090", "vram_mb": 24576, "compute_capability_tuple": [8, 6]}],
            torch={"installed": True, "cuda_available": False, "torch_hip_version": None},
        ),
        run_verify=False,
    )
    assert result["ok"] is False
    assert status_of(result, "torch_visible") == ERROR


def test_rocm_profile_matches_hip_build():
    result = evaluate(
        report(
            "Linux",
            [{
                "vendor": "amd",
                "name": "Radeon RX 7900 XTX",
                "vram_mb": 24576,
                "rocm": {"visible": True, "official_targets": ["gfx1100"], "support": "official"},
            }],
            torch={"installed": True, "cuda_available": True, "torch_hip_version": "6.2"},
        ),
        run_verify=False,
    )
    assert result["profile"]["selected_profile"] == "amd-rocm-linux"
    assert result["ok"] is True
    assert status_of(result, "torch_visible") == OK


def test_torch_not_installed_is_a_warning_not_a_failure():
    result = evaluate(
        report(
            "Linux",
            [{"vendor": "nvidia", "name": "RTX 4070", "vram_mb": 12288, "compute_capability_tuple": [8, 9]}],
            torch={"installed": False, "error": "No module named 'torch'"},
        ),
        run_verify=False,
    )
    assert result["ok"] is True
    assert status_of(result, "torch_visible") == WARN


def test_cpu_safe_with_no_accelerator_passes():
    result = evaluate(report("Linux", [], torch={"installed": True, "cuda_available": False}), run_verify=False)
    assert result["profile"]["selected_profile"] == "cpu-safe"
    assert result["ok"] is True
    assert status_of(result, "torch_visible") == OK


def test_pre_ampere_nvidia_does_not_offer_nunchaku():
    # GTX 1080 Ti: feature_sanity must pass *because* nunchaku was dropped.
    result = evaluate(
        report(
            "Linux",
            [{"vendor": "nvidia", "name": "GTX 1080 Ti", "vram_mb": 11264, "compute_capability_tuple": [6, 1]}],
            torch={"installed": True, "cuda_available": True, "torch_hip_version": None},
        ),
        run_verify=False,
    )
    assert "nunchaku_cuda" not in result["profile"]["optional_features"]
    assert status_of(result, "feature_sanity") == OK
    assert result["ok"] is True
