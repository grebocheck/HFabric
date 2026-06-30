from __future__ import annotations

from pathlib import Path

from app.backends.base import ModelDescriptor
from app.config import settings
from app.core.enums import ModelFamily
from app.services import model_compatibility


def desc(
    family: ModelFamily = ModelFamily.SDXL,
    *,
    quant: str | None = None,
    size_bytes: int = 0,
) -> ModelDescriptor:
    return ModelDescriptor(
        id="m",
        name="M",
        family=family,
        path=Path("m.safetensors"),
        size_bytes=size_bytes,
        quant=quant,
    )


def profile(
    *,
    backend: str = "cuda",
    effective_stub: bool = False,
    disabled: list[str] | None = None,
    vram_mb: int | None = 16384,
    model_policy: dict | None = None,
) -> dict:
    return {
        "backend": backend,
        "effective_stub_mode": effective_stub,
        "disabled_features": disabled or [],
        "primary_gpu": {"vram_mb": vram_mb} if vram_mb else None,
        "model_policy": model_policy or {},
    }


def test_stub_profile_keeps_models_queueable():
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX, quant="nunchaku-fp4"),
        profile=profile(effective_stub=True, disabled=["nunchaku_cuda"]),
        estimated_vram_gb=99,
    )

    assert compat["available"] is True
    assert compat["runtime_mode"] == "stub"
    assert compat["unavailable_reason"] is None


def test_nunchaku_requires_cuda_feature_in_real_mode():
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX, quant="nunchaku-fp4"),
        profile=profile(backend="rocm", disabled=["nunchaku_cuda"]),
        estimated_vram_gb=8,
    )

    assert compat["available"] is False
    assert "Nunchaku" in compat["unavailable_reason"]


def test_anima_requires_its_companion_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "anima_text_encoder_path", tmp_path / "missing-te.safetensors")
    monkeypatch.setattr(settings, "anima_qwen_config_dir", tmp_path / "missing-qwen")
    monkeypatch.setattr(settings, "anima_t5_tokenizer_dir", tmp_path / "missing-t5")
    monkeypatch.setattr(settings, "anima_vae_dir", tmp_path / "missing-vae")
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.ANIMA),
        profile=profile(backend="cuda"),
        estimated_vram_gb=None,
    )

    assert compat["available"] is False
    assert compat["runtime_mode"] == "disabled"
    assert "support assets" in compat["unavailable_reason"]
    assert "fetch_anima_support.py" in compat["unavailable_reason"]


def test_anima_is_available_with_native_support_assets(monkeypatch, tmp_path):
    text_encoder = tmp_path / "qwen.safetensors"
    qwen_dir = tmp_path / "qwen"
    t5_dir = tmp_path / "t5"
    vae_dir = tmp_path / "vae"
    for path in (
        qwen_dir / "config.json",
        t5_dir / "tokenizer_config.json",
        vae_dir / "config.json",
        vae_dir / "diffusion_pytorch_model.safetensors",
        text_encoder,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(settings, "anima_text_encoder_path", text_encoder)
    monkeypatch.setattr(settings, "anima_qwen_config_dir", qwen_dir)
    monkeypatch.setattr(settings, "anima_t5_tokenizer_dir", t5_dir)
    monkeypatch.setattr(settings, "anima_vae_dir", vae_dir)
    monkeypatch.setattr(model_compatibility.sysmon, "ram_stats", lambda: {"total_gb": 32.0})

    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.ANIMA, size_bytes=4_182_218_328),
        profile=profile(backend="cuda"),
        estimated_vram_gb=12.0,
    )

    assert compat["available"] is True
    assert compat["runtime_mode"] == "real"
    assert any("non-commercial" in warning for warning in compat["compatibility_warnings"])


def test_nunchaku_requires_python_package_in_real_mode(monkeypatch):
    monkeypatch.setattr(model_compatibility, "_nunchaku_runtime_available", lambda: False)

    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.Z_IMAGE, quant="nunchaku-fp4"),
        profile=profile(backend="cuda"),
        estimated_vram_gb=8,
    )

    assert compat["available"] is False
    assert "Nunchaku Python package" in compat["unavailable_reason"]


def test_rocm_blocks_bitsandbytes_quantized_image_models():
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.QWEN_IMAGE, quant="bnb-nf4"),
        profile=profile(backend="rocm"),
        estimated_vram_gb=12,
    )

    assert compat["available"] is False
    assert "bitsandbytes" in compat["unavailable_reason"]


def test_mps_allows_sdxl_but_blocks_large_image_families():
    sdxl = model_compatibility.compatibility_for_model(
        desc(ModelFamily.SDXL),
        profile=profile(backend="mps", vram_mb=None),
        estimated_vram_gb=8,
    )
    flux = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX),
        profile=profile(backend="mps", vram_mb=None),
        estimated_vram_gb=10,
    )

    assert sdxl["available"] is True
    assert flux["available"] is False
    assert "MPS" in flux["unavailable_reason"]


def test_hidden_policy_bucket_blocks_queueing_even_before_load():
    policy = {"image": {"recommended": ["sdxl"], "advanced": [], "hidden": ["flux"]}}
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX),
        profile=profile(backend="cuda", model_policy=policy),
        estimated_vram_gb=8,
    )

    assert compat["available"] is False
    assert "hidden" in compat["unavailable_reason"]


def test_vram_excess_offloads_to_ram_instead_of_blocking(monkeypatch):
    # FLUX dev (~17 GB) on a 16 GB card: it streams weights from RAM via CPU
    # offload, so it stays available with a "slower" warning rather than disabled.
    from app.util import sysmon

    monkeypatch.setattr(sysmon, "estimate_ram_need_gb", lambda *a, **k: 22.0)
    monkeypatch.setattr(sysmon, "ram_stats", lambda: {"total_gb": 32.0, "available_gb": 24.0})

    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX),
        profile=profile(backend="cuda", vram_mb=16384),
        estimated_vram_gb=17.1,
    )

    assert compat["available"] is True
    assert compat["runtime_mode"] == "real"
    assert any("offload" in w.lower() for w in compat["compatibility_warnings"])


def test_blocks_only_when_even_ram_offload_cannot_hold_the_model(monkeypatch):
    # bf16 model whose RAM need exceeds the whole machine: offload can't save it,
    # so it is genuinely unavailable (the runtime guard would refuse anyway).
    from app.util import sysmon

    monkeypatch.setattr(sysmon, "estimate_ram_need_gb", lambda *a, **k: 64.0)
    monkeypatch.setattr(sysmon, "ram_stats", lambda: {"total_gb": 32.0, "available_gb": 24.0})

    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.QWEN_IMAGE),
        profile=profile(backend="cuda", vram_mb=16384),
        estimated_vram_gb=15,
    )

    assert compat["available"] is False
    assert "RAM" in compat["unavailable_reason"]


def test_recommendation_reflects_model_policy_buckets(monkeypatch):
    monkeypatch.setattr(model_compatibility, "_nunchaku_runtime_available", lambda: True)
    policy = {"image": {"recommended": ["sdxl"], "advanced": ["flux"], "hidden": []}}
    rec = profile(backend="cuda", model_policy=policy)

    sdxl = model_compatibility.compatibility_for_model(
        desc(ModelFamily.SDXL),
        profile=rec,
        estimated_vram_gb=8,
    )
    flux = model_compatibility.compatibility_for_model(
        desc(ModelFamily.FLUX, quant="nunchaku-fp4"),
        profile=rec,
        estimated_vram_gb=10,
    )
    assert sdxl["recommendation"] == "recommended"
    assert flux["recommendation"] == "advanced"


def test_recommendation_is_neutral_for_llm_and_stub():
    policy = {"image": {"recommended": ["sdxl"], "advanced": [], "hidden": []}}
    llm = model_compatibility.compatibility_for_model(
        desc(ModelFamily.GGUF),
        profile=profile(backend="cuda", model_policy=policy),
    )
    stub = model_compatibility.compatibility_for_model(
        desc(ModelFamily.SDXL),
        profile=profile(effective_stub=True, model_policy=policy),
    )
    assert llm["recommendation"] == "neutral"
    assert stub["recommendation"] == "neutral"


def test_framepack_video_warns_that_it_is_i2v_only():
    compat = model_compatibility.compatibility_for_model(
        desc(ModelFamily.HUNYUAN_VIDEO, quant="bnb-nf4"),
        profile=profile(backend="cuda"),
        estimated_vram_gb=13,
    )

    assert compat["available"] is True
    assert compat["recommendation"] == "advanced"
    assert any("image-to-video only" in warning for warning in compat["compatibility_warnings"])


async def test_create_jobs_rejects_unavailable_model(monkeypatch, app_client):
    def reject(_desc):
        raise ValueError("blocked by capability profile")

    monkeypatch.setattr(model_compatibility, "require_model_available", reject)
    models = (await app_client.get("/api/models")).json()
    img = next(model for model in models if model["job_type"] == "image")

    response = await app_client.post(
        "/api/jobs",
        json=[
            {
                "type": "image",
                "model_id": img["id"],
                "params": {"prompt": "blocked", "steps": 1},
            }
        ],
    )

    assert response.status_code == 409
    assert "blocked by capability profile" in response.text
