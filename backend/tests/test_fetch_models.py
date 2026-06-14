from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_models  # noqa: E402


def profile(profile_id: str, *, optional: list[str] | None = None) -> dict:
    return {
        "selected_profile": profile_id,
        "hardware_tier": "rich_16gb_plus",
        "optional_features": optional or [],
    }


def labels(jobs: list[fetch_models.FetchJob]) -> set[str]:
    return {job.label for job in jobs}


def test_mps_plan_includes_sdxl_starter_not_cuda_flux():
    jobs = fetch_models.plan_for_profile(profile("apple-mps"))

    got = labels(jobs)
    assert "SDXL Lightning 4-step checkpoint" in got
    assert "FLUX.1 dev Nunchaku fp4" not in got
    assert "Gemma 3 12B GGUF" in got


def test_rocm_plan_uses_same_safe_sdxl_starter():
    jobs = fetch_models.plan_for_profile(profile("amd-rocm-linux"))

    got = labels(jobs)
    assert "SDXL Lightning 4-step checkpoint" in got
    assert "FLUX.1 dev Nunchaku fp4" not in got


def test_cuda_plan_adds_nunchaku_flux_only_when_feature_is_available():
    without = labels(fetch_models.plan_for_profile(profile("nvidia-cuda")))
    with_feature = labels(
        fetch_models.plan_for_profile(
            profile("nvidia-cuda", optional=["nunchaku_cuda"]),
        )
    )

    assert "FLUX.1 dev Nunchaku fp4" not in without
    assert "FLUX.1 dev Nunchaku fp4" in with_feature


def test_cpu_safe_plan_has_no_real_model_downloads():
    assert fetch_models.plan_for_profile(profile("cpu-safe")) == []


def test_synthetic_dry_run_profile_can_show_cross_device_plan():
    jobs = fetch_models.plan_for_profile(fetch_models.synthetic_profile("apple-mps"))

    got = labels(jobs)
    assert "SDXL Lightning 4-step checkpoint" in got
    assert "FLUX.1 dev Nunchaku fp4" not in got
