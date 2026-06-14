from __future__ import annotations

from app.config import settings
from app.services import capability_profile


def report(system: str, gpus: list[dict]) -> dict:
    return {
        "os": {"system": system},
        "gpus": gpus,
        "rocm": {},
    }


def resolve(system: str, gpus: list[dict]) -> dict:
    return capability_profile._install_profiles_module().resolve_profile(report(system, gpus))


def test_cuda_capability_profile_exposes_active_features(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", False)

    profile = capability_profile.build_capability_profile(resolve("Windows", [{
        "vendor": "nvidia",
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "vram_mb": 16303,
        "compute_capability_tuple": [12, 0],
    }]))

    assert profile["selected_profile"] == "nvidia-cuda"
    assert profile["active_profile"] == "nvidia-cuda"
    assert profile["backend"] == "cuda"
    assert profile["effective_stub_mode"] is False
    assert profile["features"]["cuda"] is True
    assert profile["features"]["nunchaku_cuda"] is True
    assert profile["features"]["blackwell_fast_paths"] is True
    assert "nunchaku_cuda" not in profile["disabled_features"]
    labels = {job["label"] for job in profile["starter_models"]["jobs"]}
    assert "SDXL Lightning 4-step checkpoint" in labels
    assert "FLUX.1 dev Nunchaku fp4" in labels


def test_stub_override_disables_cuda_features_on_cuda_machine(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", True)

    profile = capability_profile.build_capability_profile(resolve("Windows", [{
        "vendor": "nvidia",
        "name": "NVIDIA GeForce RTX 5070 Ti",
        "vram_mb": 16303,
        "compute_capability_tuple": [12, 0],
    }]))

    assert profile["selected_profile"] == "nvidia-cuda"
    assert profile["active_profile"] == "cpu-safe"
    assert profile["backend"] == "cpu"
    assert profile["effective_stub_mode"] is True
    assert profile["features"]["cuda"] is False
    assert profile["features"]["nunchaku_cuda"] is False
    assert "nunchaku_cuda" in profile["disabled_features"]
    assert any("STUB mode" in warning for warning in profile["warnings"])


def test_rocm_capability_profile_disables_cuda_only_features(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", False)

    profile = capability_profile.build_capability_profile(resolve("Linux", [{
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

    assert profile["selected_profile"] == "amd-rocm-linux"
    assert profile["active_profile"] == "amd-rocm-linux"
    assert profile["backend"] == "rocm"
    assert profile["features"]["rocm"] is True
    assert profile["features"]["cuda"] is False
    assert profile["features"]["nunchaku_cuda"] is False
    assert "cuda_llama_binaries" in profile["disabled_features"]
    assert "onnxruntime_cuda" in profile["disabled_features"]


def test_mps_capability_profile_exposes_metal_and_disables_cuda(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", False)

    resolved = capability_profile._install_profiles_module().resolve_profile({
        "os": {"system": "Darwin", "machine": "arm64"},
        "gpus": [{
            "vendor": "apple",
            "name": "Apple Silicon GPU",
            "architecture": "apple-silicon",
            "mps": {"potential": True, "torch_visible": True},
        }],
        "torch": {"installed": True, "mps_available": True},
        "rocm": {},
    })
    profile = capability_profile.build_capability_profile(resolved)

    assert profile["selected_profile"] == "apple-mps"
    assert profile["active_profile"] == "apple-mps"
    assert profile["backend"] == "mps"
    assert profile["features"]["mps"] is True
    assert profile["features"]["metal_llama_binaries"] is True
    assert profile["features"]["cuda"] is False
    assert "nunchaku_cuda" in profile["disabled_features"]
    labels = {job["label"] for job in profile["starter_models"]["jobs"]}
    assert "SDXL Lightning 4-step checkpoint" in labels
    assert "FLUX.1 dev Nunchaku fp4" not in labels


def test_cpu_safe_capability_profile_is_effective_stub_even_when_configured_real(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", False)

    profile = capability_profile.build_capability_profile(resolve("Linux", []))

    assert profile["selected_profile"] == "cpu-safe"
    assert profile["active_profile"] == "cpu-safe"
    assert profile["backend"] == "cpu"
    assert profile["configured_stub_mode"] is False
    assert profile["effective_stub_mode"] is True
    assert profile["features"]["cpu_safe"] is True
    assert "heavy_image_models" in profile["disabled_features"]
    assert profile["starter_models"]["jobs"] == []


async def test_capabilities_endpoint_and_settings_share_profile(monkeypatch, app_client):
    monkeypatch.setattr(settings, "stub_mode", False)
    fake = resolve("Linux", [{
        "vendor": "nvidia",
        "name": "NVIDIA GeForce RTX 4060",
        "vram_mb": 8192,
        "compute_capability_tuple": [8, 9],
    }])
    monkeypatch.setattr(capability_profile, "_hardware_profile", lambda: fake)

    capabilities = (await app_client.get("/api/capabilities")).json()
    runtime = (await app_client.get("/api/settings")).json()

    assert capabilities["selected_profile"] == "nvidia-cuda"
    assert capabilities["hardware_tier"] == "safe_8gb"
    assert capabilities["runtime_defaults"]["prefer_cpu_offload"] is True
    assert runtime["capability"]["selected_profile"] == capabilities["selected_profile"]
    assert runtime["capability"]["hardware_tier"] == capabilities["hardware_tier"]
