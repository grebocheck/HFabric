from __future__ import annotations

import json

from app.config import settings
from app.services.voice_engine import assets, slots


def test_asset_discovery_prefers_local(monkeypatch, tmp_path):
    local = tmp_path / "local-pretrain"
    local.mkdir()
    (local / "content_vec_500.onnx").write_bytes(b"onnx")
    (local / "rmvpe.pt").write_bytes(b"pt")
    monkeypatch.setattr(settings, "voice_pretrain_dir", local)

    found = assets.discover_assets()

    assert found["ready"] is True
    by_name = {item["name"]: item for item in found["assets"]}
    assert {name: by_name[name]["source"] for name in ("content_vec", "rmvpe")} == {
        "content_vec": "local",
        "rmvpe": "local",
    }
    assert by_name["denoise_dtln"]["found"] is False
    assert by_name["denoise_dtln"]["optional"] is True


def test_asset_discovery_missing_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "voice_pretrain_dir", tmp_path / "missing-local")

    found = assets.discover_assets()

    assert found["ready"] is False
    assert [item["found"] for item in found["assets"]] == [False, False, False]


def test_optional_dtln_asset_missing_does_not_break_ready(monkeypatch, tmp_path):
    local = tmp_path / "local-pretrain"
    local.mkdir()
    (local / "content_vec_500.onnx").write_bytes(b"onnx")
    (local / "rmvpe.pt").write_bytes(b"pt")
    monkeypatch.setattr(settings, "voice_pretrain_dir", local)

    found = assets.discover_assets()
    by_name = {item["name"]: item for item in found["assets"]}

    assert found["ready"] is True
    assert by_name["denoise_dtln"]["found"] is False
    assert by_name["denoise_dtln"]["path"] is None


def test_fetch_specs_targets_missing_required_into_pretrain(monkeypatch, tmp_path):
    # Only content_vec present -> rmvpe is the one missing required asset to fetch.
    local = tmp_path / "local-pretrain"
    local.mkdir()
    (local / "content_vec_500.onnx").write_bytes(b"onnx")
    monkeypatch.setattr(settings, "voice_pretrain_dir", local)

    assert assets.missing_required_names() == ["rmvpe"]
    specs = assets.fetch_specs()
    assert len(specs) == 1
    spec = specs[0]
    assert spec["filename"] == "rmvpe.pt"
    assert spec["source"] == "url" and spec["kind"] == "voice" and spec["subdir"] == "pretrain"
    assert spec["url"].startswith("https://")


def test_fetch_specs_explicit_names_cover_both_assets():
    specs = assets.fetch_specs(["content_vec", "rmvpe"])
    assert [s["filename"] for s in specs] == ["vec-768-layer-12.onnx", "rmvpe.pt"]
    assert all(s["kind"] == "voice" and s["subdir"] == "pretrain" for s in specs)


def test_fetch_optional_specs_cover_dtln_pair():
    specs = assets.fetch_optional_specs(["denoise_dtln"])
    assert [s["filename"] for s in specs] == ["dtln_model_1.onnx", "dtln_model_2.onnx"]
    assert all(s["kind"] == "voice" and s["subdir"] == "pretrain/denoise" for s in specs)
    assert all(s["url"].startswith("https://") for s in specs)


def test_slot_discovery_params_bare_and_zip_ignored(monkeypatch, tmp_path):
    local = tmp_path / "voice"
    local.mkdir()

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

    (local / "not-a-model.zip").write_bytes(b"zip")

    monkeypatch.setattr(settings, "voice_models_dir", local)

    found = slots.discover_slots()
    by_id = {item["id"]: item for item in found}

    assert set(by_id) == {"bare", "slot-a"}
    assert by_id["slot-a"]["name"] == "Display Voice"
    assert by_id["slot-a"]["has_index"] is True
    assert by_id["slot-a"]["sampling_rate"] == 48000
    assert by_id["slot-a"]["f0"] is True
    assert by_id["bare"]["version"] == ""
