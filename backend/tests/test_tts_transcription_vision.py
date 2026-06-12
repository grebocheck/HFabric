from __future__ import annotations


async def test_tts_validation_no_binary_and_no_model_paths(app_client, monkeypatch, tmp_path):
    from app.config import settings

    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setattr(settings, "tts_models_dir", tts_dir)
    monkeypatch.setattr(settings, "llama_tts_bin", tmp_path / "missing-llama-tts")

    status = (await app_client.get("/api/tts/status")).json()
    assert status["ready"] is False
    assert status["models"] == []
    assert status["binary_exists"] is False

    invalid = await app_client.post("/api/tts/generate", json={"model_id": "voice", "text": ""})
    assert invalid.status_code == 422

    no_binary = await app_client.post("/api/tts/generate", json={"model_id": "voice", "text": "hello"})
    assert no_binary.status_code == 503
    assert "llama-tts binary not found" in no_binary.text

    fake_bin = tmp_path / "llama-tts"
    fake_bin.write_bytes(b"")
    monkeypatch.setattr(settings, "llama_tts_bin", fake_bin)
    no_model = await app_client.post("/api/tts/generate", json={"model_id": "voice", "text": "hello"})
    assert no_model.status_code == 404
    assert "TTS model not found" in no_model.text

    (tts_dir / "voice.gguf").write_bytes(b"GGUF")
    no_vocoder = await app_client.post(
        "/api/tts/generate",
        json={"model_id": "voice", "vocoder_id": "missing", "text": "hello"},
    )
    assert no_vocoder.status_code == 404
    assert "TTS vocoder model not found" in no_vocoder.text

    missing_file = await app_client.get("/api/tts/audio/not-a-token/file")
    assert missing_file.status_code == 404


async def test_transcription_validation_no_model_and_missing_engine(app_client, monkeypatch, tmp_path):
    from app.api import transcription as transcription_api
    from app.config import settings

    models_dir = tmp_path / "transcribe"
    models_dir.mkdir()
    monkeypatch.setattr(settings, "transcription_models_dir", models_dir)

    status = (await app_client.get("/api/transcription/status")).json()
    assert status["models"] == []
    assert status["ready"] is False

    invalid_task = await app_client.post(
        "/api/transcription/transcribe",
        data={"model_id": "tiny", "task": "summarize"},
        files={"file": ("tone.wav", b"RIFF....WAVE", "audio/wav")},
    )
    assert invalid_task.status_code == 422
    assert "task must be transcribe or translate" in invalid_task.text

    no_model = await app_client.post(
        "/api/transcription/transcribe",
        data={"model_id": "tiny"},
        files={"file": ("tone.wav", b"RIFF....WAVE", "audio/wav")},
    )
    assert no_model.status_code == 404
    assert "transcription model not found" in no_model.text

    tiny = models_dir / "tiny"
    tiny.mkdir()
    (tiny / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(transcription_api, "_has", lambda _module: False)

    missing_engine = await app_client.post(
        "/api/transcription/transcribe",
        data={"model_id": "tiny"},
        files={"file": ("tone.wav", b"RIFF....WAVE", "audio/wav")},
    )
    assert missing_engine.status_code == 503
    assert "faster-whisper is not installed" in missing_engine.text

    metadata = await app_client.get("/api/transcription/result/not-a-token/metadata")
    assert metadata.status_code == 404


async def test_vision_validation_no_binary_model_projector_and_metadata(app_client, monkeypatch, tmp_path):
    from app.config import settings

    models_dir = tmp_path / "vision"
    models_dir.mkdir()
    monkeypatch.setattr(settings, "vision_models_dir", models_dir)
    monkeypatch.setattr(settings, "llama_mtmd_bin", tmp_path / "missing-mtmd")

    status = (await app_client.get("/api/vision/status")).json()
    assert status["ready"] is False
    assert status["models"] == []
    assert status["projectors"] == []
    assert status["binary_exists"] is False

    no_binary = await app_client.post(
        "/api/vision/analyze",
        data={"model_id": "vision", "projector_id": "mmproj-vision", "prompt": "describe"},
        files={"file": ("img.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert no_binary.status_code == 503
    assert "llama-mtmd-cli binary not found" in no_binary.text

    fake_bin = tmp_path / "llama-mtmd-cli"
    fake_bin.write_bytes(b"")
    monkeypatch.setattr(settings, "llama_mtmd_bin", fake_bin)

    empty_prompt = await app_client.post(
        "/api/vision/analyze",
        data={"model_id": "vision", "projector_id": "mmproj-vision", "prompt": "   "},
        files={"file": ("img.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert empty_prompt.status_code == 422
    assert "prompt is empty" in empty_prompt.text

    no_model = await app_client.post(
        "/api/vision/analyze",
        data={"model_id": "vision", "projector_id": "mmproj-vision", "prompt": "describe"},
        files={"file": ("img.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert no_model.status_code == 404
    assert "vision model not found" in no_model.text

    (models_dir / "vision.gguf").write_bytes(b"GGUF")
    no_projector = await app_client.post(
        "/api/vision/analyze",
        data={"model_id": "vision", "projector_id": "mmproj-vision", "prompt": "describe"},
        files={"file": ("img.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert no_projector.status_code == 404
    assert "vision projector not found" in no_projector.text

    metadata = await app_client.get("/api/vision/result/not-a-token/metadata")
    assert metadata.status_code == 404
