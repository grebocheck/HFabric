from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.config import settings
from app.services import civitai_auth, settings_overrides
from app.services.atomic_json import AtomicJSONStore, persistence_warnings
from app.services.voice_engine import presets as voice_presets


def test_store_upgrades_legacy_data_keeps_backup_and_quarantines_corruption(
    tmp_path,
):
    path = tmp_path / "state.json"
    path.write_text('{"legacy": 1}', encoding="utf-8")
    store = AtomicJSONStore(path, schema="test.state", max_bytes=1024)

    assert store.read({}) == {"legacy": 1}
    store.write({"current": 2})

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == {
        "schema": "test.state",
        "version": 1,
        "data": {"current": 2},
    }
    assert json.loads(store.backup_path.read_text(encoding="utf-8")) == {
        "legacy": 1
    }

    path.write_text("{broken", encoding="utf-8")
    assert store.read({"safe": True}) == {"safe": True}
    assert not path.exists()
    quarantined = list(tmp_path.glob("state.corrupt-*.json"))
    assert len(quarantined) == 1
    warning = persistence_warnings(path)[0]
    assert warning["file"] == "state.json"
    assert warning["quarantined_as"] == quarantined[0].name
    assert "JSONDecodeError" in warning["reason"]


def test_store_rejects_oversized_payload_without_replacing_current(tmp_path):
    path = tmp_path / "small.json"
    store = AtomicJSONStore(path, schema="test.small", max_bytes=128)
    store.write({"ok": True})
    before = path.read_bytes()

    with pytest.raises(ValueError, match="persistence limit"):
        store.write({"large": "x" * 500})

    assert path.read_bytes() == before


def test_store_serializes_concurrent_read_modify_write(tmp_path):
    path = tmp_path / "counter.json"
    store = AtomicJSONStore(path, schema="test.counter")

    def increment(_index: int) -> None:
        AtomicJSONStore(path, schema="test.counter").update(
            {"count": 0},
            lambda data: {"count": data["count"] + 1},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(40)))

    assert store.read({}) == {"count": 40}


def test_corrupt_settings_are_quarantined_and_do_not_block_startup(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    path = settings_overrides.overrides_path()
    path.write_text('{"default_steps":', encoding="utf-8")

    assert settings_overrides.load() == set()
    assert not path.exists()
    assert list(tmp_path.glob("settings-overrides.corrupt-*.json"))
    warning = settings_overrides.payload()["persistence_warnings"][0]
    assert warning["file"] == "settings-overrides.json"


def test_settings_runtime_is_not_mutated_when_durable_write_fails(monkeypatch):
    monkeypatch.setattr(settings, "default_steps", 22)

    class FailingStore:
        def write(self, _data) -> None:
            raise OSError("disk full")

    monkeypatch.setattr(settings_overrides, "_store", FailingStore)

    with pytest.raises(OSError, match="disk full"):
        settings_overrides.save({"default_steps": 44})

    assert settings.default_steps == 22


def test_secret_store_is_versioned_and_only_exposes_redacted_status(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(civitai_auth.settings, "data_dir", tmp_path)
    civitai_auth.set_key("secret-key")
    civitai_auth.set_cookie("secret-cookie")

    raw = json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))
    assert raw["schema"] == "hfabric.local-secrets"
    assert raw["version"] == 1
    assert raw["data"]["civitai_api_key"] == "secret-key"
    assert civitai_auth.redacted_status() == {
        "api_key": "<redacted>",
        "session_cookie": "<redacted>",
        "storage": "atomic-user-file",
        "protection": civitai_auth.SECRET_STORAGE_DECISION,
    }
    assert not (tmp_path / "secrets.json.bak").exists()


def test_voice_presets_read_legacy_format_and_upgrade_on_write(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(voice_presets.settings, "data_dir", tmp_path)
    legacy = [{
        "id": "legacy",
        "name": "Legacy",
        "model_id": None,
        "settings": {"pitch": 2},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }]
    path = tmp_path / voice_presets.VOICE_PRESETS_FILE
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert voice_presets.list_presets()[0]["id"] == "legacy"
    voice_presets.create_preset("New", {"pitch": 3})

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema"] == "hfabric.voice-presets"
    assert persisted["version"] == 1
    assert {item["id"] for item in persisted["data"]} >= {"legacy"}
