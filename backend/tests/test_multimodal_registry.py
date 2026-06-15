from __future__ import annotations

from app.backends.registry import ModelRegistry
from app.config import settings


def test_registry_detects_vision_gguf_mmproj_pair(monkeypatch, tmp_path):
    image_dir = tmp_path / "image"
    llm_dir = tmp_path / "llm"
    vision_dir = tmp_path / "vision"
    lora_dir = tmp_path / "lora"
    for path in (image_dir, llm_dir, vision_dir, lora_dir):
        path.mkdir()
    model = vision_dir / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
    projector = vision_dir / "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
    model.write_bytes(b"GGUF-model")
    projector.write_bytes(b"GGUF-projector")

    monkeypatch.setattr(settings, "image_models_dir", image_dir)
    monkeypatch.setattr(settings, "llm_models_dir", llm_dir)
    monkeypatch.setattr(settings, "vision_models_dir", vision_dir)
    monkeypatch.setattr(settings, "lora_models_dir", lora_dir)
    monkeypatch.setattr(settings, "upscaler_model_path", tmp_path / "upscale.pth")

    registry = ModelRegistry()
    registry.scan()

    llms = [d for d in registry.descriptors() if d.job_type.value == "llm"]
    assert [d.path for d in llms] == [model]
    assert llms[0].multimodal is True
    assert llms[0].mmproj_path == projector
    assert llms[0].mmproj_size_bytes == projector.stat().st_size
    assert llms[0].size_bytes == model.stat().st_size + projector.stat().st_size


def test_stray_projector_does_not_attach_to_unrelated_text_models(monkeypatch, tmp_path):
    """A projector for one vision model must not get bolted onto the unrelated
    text models sharing the folder — that would launch them with a mismatched
    --mmproj and break/slow generation."""
    llm_dir = tmp_path / "llm"
    for sub in ("image", "vision", "lora"):
        (tmp_path / sub).mkdir()
    llm_dir.mkdir()
    text_a = llm_dir / "gemma-3-12b-it-Q4_K_M.gguf"
    text_b = llm_dir / "gpt-oss-20b-MXFP4.gguf"
    vl_model = llm_dir / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
    projector = llm_dir / "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
    for path in (text_a, text_b, vl_model, projector):
        path.write_bytes(b"GGUF")

    monkeypatch.setattr(settings, "image_models_dir", tmp_path / "image")
    monkeypatch.setattr(settings, "llm_models_dir", llm_dir)
    monkeypatch.setattr(settings, "vision_models_dir", tmp_path / "vision")
    monkeypatch.setattr(settings, "lora_models_dir", tmp_path / "lora")
    monkeypatch.setattr(settings, "upscaler_model_path", tmp_path / "upscale.pth")

    registry = ModelRegistry()
    registry.scan()
    by_path = {d.path: d for d in registry.descriptors() if d.job_type.value == "llm"}

    assert by_path[text_a].multimodal is False
    assert by_path[text_b].multimodal is False
    # the projector still pairs with the model it actually matches by name
    assert by_path[vl_model].mmproj_path == projector
