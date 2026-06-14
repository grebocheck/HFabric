from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from install_profiles import nvidia_architecture, resolve_profile  # noqa: E402


def report(system: str, gpus: list[dict]) -> dict:
    return {
        "os": {"system": system},
        "gpus": gpus,
        "rocm": {},
    }


def nvidia_report(name: str, vram_mb: int, cap: list[int], system: str = "Linux") -> dict:
    return report(system, [{
        "vendor": "nvidia",
        "name": name,
        "vram_mb": vram_mb,
        "compute_capability_tuple": cap,
    }])


def test_resolves_blackwell_nvidia_cuda_profile():
    result = resolve_profile(report("Windows", [{
        "vendor": "nvidia",
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "vram_mb": 16303,
        "compute_capability_tuple": [12, 0],
    }]))

    assert result["selected_profile"] == "nvidia-cuda"
    assert result["hardware_tier"] == "rich_16gb_plus"
    assert result["install"]["torch"]["index_url"].endswith("/cu128")
    assert result["install"]["requirements"] == ["backend/requirements-gpu.txt"]
    assert result["runtime_defaults"]["backend"] == "cuda"
    assert result["runtime_defaults"]["blackwell_fast_paths"] is True
    assert result["runtime_defaults"]["allow_nunchaku"] is True


def test_resolves_lower_vram_nvidia_with_safe_tier():
    result = resolve_profile(report("Linux", [{
        "vendor": "nvidia",
        "name": "NVIDIA GeForce RTX 4060",
        "vram_mb": 8192,
        "compute_capability_tuple": [8, 9],
    }]))

    assert result["selected_profile"] == "nvidia-cuda"
    assert result["hardware_tier"] == "safe_8gb"
    assert result["runtime_defaults"]["blackwell_fast_paths"] is False
    assert result["runtime_defaults"]["prefer_cpu_offload"] is True


def test_resolves_linux_amd_rocm_profile_when_official_target_visible():
    result = resolve_profile(report("Linux", [{
        "vendor": "amd",
        "name": "AMD Radeon RX 7900 XTX",
        "vram_mb": 24576,
        "rocm": {
            "visible": True,
            "llvm_targets": ["gfx1100"],
            "official_targets": ["gfx1100"],
            "support": "official",
        },
    }]))

    assert result["selected_profile"] == "amd-rocm-linux"
    assert result["hardware_tier"] == "large_24gb_plus"
    assert result["install"]["torch"]["index_url"].endswith("/rocm7.2")
    assert result["install"]["requirements"] == ["backend/requirements-rocm.txt"]
    assert result["runtime_defaults"]["backend"] == "rocm"
    assert result["runtime_defaults"]["torch_device"] == "cuda"
    assert "nunchaku_cuda" in result["disabled_features"]


def test_linux_amd_visible_non_official_target_is_experimental_rocm():
    result = resolve_profile(report("Linux", [{
        "vendor": "amd",
        "name": "AMD Radeon Experimental",
        "vram_mb": 16384,
        "rocm": {
            "visible": True,
            "llvm_targets": ["gfx9999"],
            "official_targets": [],
            "support": "community_experimental",
        },
    }]))

    assert result["selected_profile"] == "amd-rocm-linux"
    assert result["confidence"] == "medium"
    assert any("experimental" in warning.lower() for warning in result["warnings"])


def test_windows_amd_falls_back_to_cpu_safe():
    result = resolve_profile(report("Windows", [{
        "vendor": "amd",
        "name": "AMD Radeon RX 7900 XTX",
        "vram_mb": 24576,
    }]))

    assert result["selected_profile"] == "cpu-safe"
    assert result["runtime_defaults"]["backend"] == "cpu"
    assert "Windows AMD acceleration" in " ".join(result["warnings"])


def test_resolves_apple_silicon_mps_profile():
    result = resolve_profile({
        "os": {"system": "Darwin", "machine": "arm64"},
        "gpus": [{
            "vendor": "apple",
            "name": "Apple Silicon GPU",
            "architecture": "apple-silicon",
            "mps": {"potential": True},
        }],
        "torch": {"installed": True, "mps_available": True},
        "rocm": {},
    })

    assert result["selected_profile"] == "apple-mps"
    assert result["install"]["torch"]["index_url"] is None
    assert result["install"]["requirements"] == ["backend/requirements-mps.txt"]
    assert result["runtime_defaults"]["backend"] == "mps"
    assert result["runtime_defaults"]["torch_device"] == "mps"
    assert "metal_llama_binaries" in result["optional_features"]
    image = result["model_policy"]["image"]
    assert image["recommended"] == ["sdxl"]
    assert {"flux", "flux2", "qwen-image", "z-image"} <= set(image["hidden"])


def test_cpu_only_report_uses_cpu_safe_profile():
    result = resolve_profile(report("Linux", []))

    assert result["selected_profile"] == "cpu-safe"
    assert result["install"]["torch"]["index_url"].endswith("/cpu")
    assert result["runtime_defaults"]["stub_mode"] is True


def test_prefer_rejects_invalid_profile_for_report():
    try:
        resolve_profile(report("Linux", []), prefer="nvidia-cuda")
    except ValueError as exc:
        assert "preferred profile" in str(exc)
    else:
        raise AssertionError("expected invalid preferred profile to fail")


# --- P20.3: NVIDIA beyond Blackwell -----------------------------------------

def test_architecture_map_covers_generations():
    assert nvidia_architecture([12, 0]) == "blackwell"
    assert nvidia_architecture([8, 9]) == "ada"
    assert nvidia_architecture([8, 6]) == "ampere"
    assert nvidia_architecture([7, 5]) == "turing"
    assert nvidia_architecture([6, 1]) == "pascal"
    assert nvidia_architecture(None) is None


def test_pre_ampere_nvidia_drops_nunchaku_and_fast_paths():
    # GTX 1080 Ti: real CUDA card, but no fp4 kernels and no flash-attention-2.
    result = resolve_profile(nvidia_report("NVIDIA GeForce GTX 1080 Ti", 11264, [6, 1]))

    assert result["selected_profile"] == "nvidia-cuda"
    defaults = result["runtime_defaults"]
    assert defaults["allow_nunchaku"] is False
    assert defaults["attention_backend"] == "math"
    assert defaults["flux_step_cache"] == "off"
    assert defaults["blackwell_fast_paths"] is False
    assert defaults["architecture"] == "pascal"
    # Installer must not fetch the CUDA nunchaku wheel it could never use.
    assert "nunchaku_cuda" not in result["optional_features"]
    # No nunchaku-only image family is recommended or even allowed.
    image = result["model_policy"]["image"]
    assert set(image["recommended"] + image["advanced"]) == {"sdxl"}
    assert {"flux", "flux2", "qwen-image", "z-image"} <= set(image["hidden"])


def test_turing_keeps_cuda_but_no_fp4():
    result = resolve_profile(nvidia_report("NVIDIA GeForce RTX 2080 Ti", 11264, [7, 5]))

    defaults = result["runtime_defaults"]
    assert defaults["allow_nunchaku"] is False
    assert defaults["attention_backend"] == "math"
    assert "nunchaku_cuda" not in result["optional_features"]


def test_ampere_30xx_enables_fp4_fast_paths_but_not_blackwell():
    # RTX 3090: 24 GB Ampere — full fp4 path, blackwell-only flags stay off.
    result = resolve_profile(nvidia_report("NVIDIA GeForce RTX 3090", 24576, [8, 6]))

    defaults = result["runtime_defaults"]
    assert defaults["allow_nunchaku"] is True
    assert defaults["attention_backend"] == "auto"
    assert defaults["flux_step_cache"] == "fb"
    assert defaults["blackwell_fast_paths"] is False
    assert defaults["architecture"] == "ampere"
    assert "nunchaku_cuda" in result["optional_features"]
    image = result["model_policy"]["image"]
    assert {"flux", "flux2", "qwen-image", "z-image"} <= set(image["recommended"])
    assert not image["hidden"]


def test_ada_40xx_12gb_recommends_flux_but_clamps_heavy_families():
    # RTX 4070: 12 GB Ada — flux fits, but flux2/qwen/z stay in the advanced bucket.
    result = resolve_profile(nvidia_report("NVIDIA GeForce RTX 4070", 12288, [8, 9]))

    defaults = result["runtime_defaults"]
    assert defaults["allow_nunchaku"] is True
    assert defaults["architecture"] == "ada"
    image = result["model_policy"]["image"]
    assert "sdxl" in image["recommended"]
    assert "flux" in image["recommended"]
    assert {"flux2", "qwen-image", "z-image"} <= set(image["advanced"])
    assert not image["hidden"]


def test_low_vram_nvidia_keeps_sdxl_only_and_disables_fast_paths():
    # RTX 3050 6 GB: Ampere capability but below the 8 GB safe floor.
    result = resolve_profile(nvidia_report("NVIDIA GeForce RTX 3050", 6144, [8, 6]))

    assert result["hardware_tier"] == "low_vram"
    defaults = result["runtime_defaults"]
    assert defaults["allow_nunchaku"] is False
    assert defaults["torch_compile"] is False
    assert defaults["prefer_cpu_offload"] is True
    assert "nunchaku_cuda" not in result["optional_features"]
    image = result["model_policy"]["image"]
    assert {"flux", "flux2", "qwen-image", "z-image"} <= set(image["hidden"])


def test_resolver_never_recommends_impossible_image_path():
    # Across capabilities, a recommended/advanced family must be installable:
    # nunchaku families only when the nunchaku wheel is actually offered.
    caps = [[6, 1], [7, 5], [8, 0], [8, 6], [8, 9], [9, 0], [12, 0]]
    nunchaku_families = {"flux", "flux2", "qwen-image", "z-image"}
    for cap in caps:
        for vram in (6144, 8192, 12288, 16303, 24576):
            result = resolve_profile(nvidia_report("synthetic", vram, cap))
            image = result["model_policy"]["image"]
            offered = set(image["recommended"] + image["advanced"])
            if offered & nunchaku_families:
                assert "nunchaku_cuda" in result["optional_features"], (cap, vram)
            # Hidden + offered must partition the known families with no overlap.
            assert not (offered & set(image["hidden"]))


def test_llm_param_recommendation_scales_with_tier():
    small = resolve_profile(nvidia_report("RTX 4060", 8192, [8, 9]))
    big = resolve_profile(nvidia_report("RTX 5090", 32768, [12, 0]))
    assert small["model_policy"]["llm"]["max_recommended_params_b"] < (
        big["model_policy"]["llm"]["max_recommended_params_b"]
    )
