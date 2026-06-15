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
