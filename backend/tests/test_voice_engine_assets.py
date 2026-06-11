from __future__ import annotations

import json

from app.config import settings
from app.services.voice_engine import assets, slots


def test_asset_discovery_prefers_local(monkeypatch, tmp_path):
    local = tmp_path / "local-pretrain"
    wokada = tmp_path / "wokada"
    local.mkdir()
    (local / "content_vec_500.onnx").write_bytes(b"onnx")
    (local / "rmvpe.pt").write_bytes(b"pt")
    monkeypatch.setattr(settings, "voice_pretrain_dir", local)
    monkeypatch.setattr(settings, "voice_wokada_dir", wokada)

    found = assets.discover_assets()

    assert found["ready"] is True
    assert {item["name"]: item["source"] for item in found["assets"]} == {
        "content_vec": "local",
        "rmvpe": "local",
    }


def test_asset_discovery_falls_back_to_wokada(monkeypatch, tmp_path):
    local = tmp_path / "local-pretrain"
    wokada = tmp_path / "wokada"
    pretrain = wokada / "pretrain"
    local.mkdir()
    pretrain.mkdir(parents=True)
    (pretrain / "content_vec_500.fp16.onnx").write_bytes(b"onnx")
    (pretrain / "rmvpe.pt").write_bytes(b"pt")
    monkeypatch.setattr(settings, "voice_pretrain_dir", local)
    monkeypatch.setattr(settings, "voice_wokada_dir", wokada)

    found = assets.discover_assets()

    assert found["ready"] is True
    assert {item["name"]: item["source"] for item in found["assets"]} == {
        "content_vec": "wokada",
        "rmvpe": "wokada",
    }


def test_asset_discovery_missing_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "voice_pretrain_dir", tmp_path / "missing-local")
    monkeypatch.setattr(settings, "voice_wokada_dir", tmp_path / "missing-wokada")

    found = assets.discover_assets()

    assert found["ready"] is False
    assert [item["found"] for item in found["assets"]] == [False, False]


def test_slot_discovery_params_bare_wokada_and_zip_ignored(monkeypatch, tmp_path):
    local = tmp_path / "voice"
    wokada = tmp_path / "wokada"
    model_dir = wokada / "model_dir"
    local.mkdir()
    model_dir.mkdir(parents=True)

    params_slot = local / "slot-a"
    params_slot.mkdir()
    (params_slot / "voice.pth").write_bytes(b"pth")
    (params_slot / "voice.index").write_bytes(b"index")
    (params_slot / "params.json").write_text(
        json.dumps({
            "name": "Display Voice",
            "voiceChangerType": "RVC",
            "version": "v2",
            "samplingRate": 48000,
            "f0": True,
            "indexFile": "voice.index",
        }),
        encoding="utf-8",
    )

    bare = local / "bare"
    bare.mkdir()
    (bare / "bare.pth").write_bytes(b"pth")

    fallback = model_dir / "wokada-slot"
    fallback.mkdir()
    (fallback / "model.safetensors").write_bytes(b"st")

    (model_dir / "not-a-model.zip").write_bytes(b"zip")

    monkeypatch.setattr(settings, "voice_models_dir", local)
    monkeypatch.setattr(settings, "voice_wokada_dir", wokada)

    found = slots.discover_slots()
    by_id = {item["id"]: item for item in found}

    assert set(by_id) == {"bare", "slot-a", "wokada-slot"}
    assert by_id["slot-a"]["name"] == "Display Voice"
    assert by_id["slot-a"]["has_index"] is True
    assert by_id["slot-a"]["sampling_rate"] == 48000
    assert by_id["slot-a"]["f0"] is True
    assert by_id["bare"]["version"] == ""
    assert by_id["wokada-slot"]["source"] == "wokada"
