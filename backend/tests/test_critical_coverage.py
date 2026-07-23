"""Behavioral regression coverage for critical persistence and safety paths."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.websockets import WebSocket

from app.config import settings
from app.services import atomic_json, model_storage, settings_overrides
from app.services.atomic_json import (
    AtomicJSONStore,
    clear_persistence_warnings,
    persistence_warnings,
    persistence_warnings_under,
)
from app.util import security


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"schema": ""}, "schema is required"),
        ({"schema": "test", "version": 0}, "version must be positive"),
        ({"schema": "test", "max_bytes": 0}, "size limit must be positive"),
    ],
)
def test_atomic_store_rejects_invalid_configuration(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        AtomicJSONStore(tmp_path / "state.json", **kwargs)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"schema": "test.state"}, "incomplete persistence envelope"),
        (
            {"schema": "other.state", "version": 1, "data": {}},
            "expected schema",
        ),
        (
            {"schema": "test.state", "version": 2, "data": {}},
            "unsupported test.state version",
        ),
        ({"valid_json": "wrong shape"}, "validator rejected payload"),
    ],
)
def test_atomic_store_quarantines_incompatible_or_rejected_data(
    tmp_path,
    raw,
    reason,
):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    store = AtomicJSONStore(path, schema="test.state")

    def validate(value):
        if value == raw and "valid_json" in raw:
            raise ValueError("validator rejected payload")
        return value

    assert store.read({"safe": True}, validator=validate) == {"safe": True}
    assert not path.exists()
    warning = persistence_warnings(path)[0]
    assert reason in warning["reason"]
    assert warning["quarantined_as"]


def test_atomic_store_quarantines_an_oversized_existing_file(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b"x" * 129)
    store = AtomicJSONStore(path, schema="test.oversized", max_bytes=128)

    assert store.read({"safe": True}) == {"safe": True}
    assert not path.exists()
    assert "persistence limit" in persistence_warnings(path)[0]["reason"]


@pytest.mark.parametrize(
    "invalid_payload",
    [{"not": {"a", "json", "value"}}, {"not": float("nan")}],
)
def test_atomic_store_rejects_non_json_payload_without_replacing_current(
    tmp_path,
    invalid_payload,
):
    path = tmp_path / "state.json"
    store = AtomicJSONStore(path, schema="test.state")
    store.write({"stable": True})
    before = path.read_bytes()

    with pytest.raises(ValueError, match="payload is not valid JSON"):
        store.write(invalid_payload)

    assert path.read_bytes() == before


def test_atomic_store_cleans_temporary_file_when_replace_fails(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = AtomicJSONStore(path, schema="test.state")

    def fail_replace(_source, _destination):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(atomic_json.os, "replace", fail_replace)

    with pytest.raises(PermissionError, match="read-only filesystem"):
        store.write({"value": 1})

    assert not path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_store_keeps_corrupt_file_when_quarantine_rename_fails(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = AtomicJSONStore(path, schema="test.state")

    monkeypatch.setattr(
        atomic_json.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
    )

    assert store.read({"safe": True}) == {"safe": True}
    assert path.exists()
    assert persistence_warnings(path)[0]["quarantined_as"] is None


def test_atomic_store_skips_unsafe_backup_and_tolerates_chmod_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    path.write_bytes(b"x" * 300)
    store = AtomicJSONStore(path, schema="test.state", max_bytes=256)

    monkeypatch.setattr(
        Path,
        "chmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    store.write({"replacement": True})

    assert store.read({}) == {"replacement": True}
    assert not store.backup_path.exists()


def test_atomic_store_can_disable_backups_and_manage_warning_snapshots(tmp_path):
    inside = tmp_path / "runtime" / "inside.json"
    outside = tmp_path / "outside.json"
    inside.parent.mkdir()
    inside.write_text("{broken", encoding="utf-8")
    outside.write_text("{broken", encoding="utf-8")
    inside_store = AtomicJSONStore(inside, schema="test.inside", backup=False)
    outside_store = AtomicJSONStore(outside, schema="test.outside", backup=False)

    clear_persistence_warnings()
    inside_store.read({})
    outside_store.read({})
    all_warnings = persistence_warnings()
    under_runtime = persistence_warnings_under(tmp_path / "runtime")

    assert {warning["file"] for warning in all_warnings} == {
        "inside.json",
        "outside.json",
    }
    assert [warning["file"] for warning in under_runtime] == ["inside.json"]

    clear_persistence_warnings(inside)
    assert persistence_warnings(inside) == []
    assert persistence_warnings(outside)
    outside_store.write({"repaired": True})
    outside_store.write({"repaired": "again"})
    assert not outside_store.backup_path.exists()
    assert persistence_warnings() == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "must be a JSON object"),
        ({"host": "0.0.0.0"}, "unsupported keys: host"),
    ],
)
def test_settings_load_quarantines_invalid_persisted_shape(
    isolated_runtime,
    raw,
    message,
):
    path = settings_overrides.overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert settings_overrides.load() == set()
    assert not path.exists()
    assert message in persistence_warnings(path)[0]["reason"]


def test_settings_load_applies_valid_persisted_values(isolated_runtime):
    path = settings_overrides.overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "default_steps": "31",
                "keep_warm_models": "off",
            }
        ),
        encoding="utf-8",
    )

    assert settings_overrides.load() == {
        "default_steps",
        "keep_warm_models",
    }
    assert settings.default_steps == 31
    assert settings.keep_warm_models is False


def test_settings_save_normalizes_every_user_facing_value_kind(tmp_path):
    result = settings_overrides.save(
        {
            "keep_warm_models": " YES ",
            "default_width": 769,
            "default_guidance": -3,
            "image_edit_resize_mode": " pad ",
            "llama_host": "  localhost  ",
            "sdxl_controlnet_canny_repo": " ",
            "image_models_dir": f"  {tmp_path / 'models'}  ",
            "not_a_setting": "ignored",
        }
    )

    assert settings.keep_warm_models is True
    assert settings.default_width == 768
    assert settings.default_guidance == 0
    assert settings.image_edit_resize_mode == "pad"
    assert settings.llama_host == "localhost"
    assert settings.sdxl_controlnet_canny_repo is None
    assert settings.image_models_dir == tmp_path / "models"
    assert "not_a_setting" not in result["values"]
    assert result["values"]["image_models_dir"] == str(tmp_path / "models")


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"keep_warm_models": "sometimes"}, "expected boolean"),
        ({"default_steps": "many"}, "expected integer"),
        ({"default_guidance": object()}, "expected numeric"),
        ({"image_edit_resize_mode": "diagonal"}, "must be one of"),
        ({"llama_host": " "}, "cannot be empty"),
        ({"image_models_dir": " "}, "cannot be empty"),
    ],
)
def test_settings_reject_invalid_values_before_touching_durable_state(
    patch,
    message,
):
    settings_overrides.save({})
    path = settings_overrides.overrides_path()
    before = path.read_bytes()

    with pytest.raises(ValueError, match=message):
        settings_overrides.save(patch)

    assert path.read_bytes() == before


async def test_model_inventory_filters_noise_caches_directories_and_deletes_async(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "image-models"
    root.mkdir()
    (root / ".partial.gguf").write_bytes(b"partial")
    (root / "pretrain").mkdir()
    (root / "notes.txt").write_text("not a model", encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"weights")
    repo = root / "repo"
    repo.mkdir()
    (repo / "config.json").write_bytes(b"config")
    (repo / "weights.bin").write_bytes(b"repo-weights")
    monkeypatch.setattr(settings, "image_models_dir", root)
    model_storage._SIZE_CACHE.clear()

    first = await model_storage.installed_async()
    second = await model_storage.installed_async()
    image_items = [item for item in first if item["kind"] == "image"]

    assert {item["path"] for item in image_items} == {"model.safetensors", "repo"}
    assert second == first
    assert model_storage.total_used_bytes() >= sum(
        item["size_bytes"] for item in image_items
    )

    refreshed = []
    result = await model_storage.delete_async(
        "image",
        "repo",
        after_delete=lambda: refreshed.append(True),
    )

    assert result["freed_bytes"] == len(b"configrepo-weights")
    assert refreshed == [True]
    assert not repo.exists()


def test_model_delete_accepts_callable_busy_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "busy.gguf"
    weight.write_bytes(b"GGUF")

    with pytest.raises(model_storage.ModelInUseError):
        model_storage.delete("llm", weight.name, in_use=lambda: [weight])

    assert weight.exists()


def test_model_delete_reports_atomic_reservation_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "locked.gguf"
    weight.write_bytes(b"GGUF")

    monkeypatch.setattr(
        model_storage.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("sharing violation")),
    )

    with pytest.raises(model_storage.ModelDeleteError, match="could not reserve"):
        model_storage.delete("llm", weight.name)

    assert weight.exists()
    assert model_storage.reserved_paths() == set()


def test_model_delete_reports_failed_rollback_and_releases_reservation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "rollback.gguf"
    weight.write_bytes(b"GGUF")
    real_replace = os.replace

    def fail_rollback(source, destination):
        source_path = Path(source)
        if source_path.name.startswith(".rollback.gguf.deleting-"):
            raise PermissionError("rollback blocked")
        return real_replace(source, destination)

    monkeypatch.setattr(model_storage.os, "replace", fail_rollback)
    monkeypatch.setattr(
        model_storage,
        "_remove_staged",
        lambda _staged: (_ for _ in ()).throw(PermissionError("delete blocked")),
    )

    with pytest.raises(model_storage.ModelDeleteError, match="rollback also failed"):
        model_storage.delete("llm", weight.name)

    assert not weight.exists()
    assert model_storage.reserved_paths() == set()
    staged = list(tmp_path.glob(".rollback.gguf.deleting-*"))
    assert len(staged) == 1
    staged[0].unlink()


def test_model_delete_reports_uncertain_state_after_partial_removal(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "partial.gguf"
    weight.write_bytes(b"GGUF")

    def remove_then_fail(staged):
        staged.unlink()
        raise PermissionError("directory sync failed")

    monkeypatch.setattr(model_storage, "_remove_staged", remove_then_fail)

    with pytest.raises(model_storage.ModelDeleteError, match="deletion state is uncertain"):
        model_storage.delete("llm", weight.name)

    assert not weight.exists()
    assert model_storage.reserved_paths() == set()


def _request(
    *,
    method: str = "GET",
    path: str = "/api/models",
    client_host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers or [],
            "client": (client_host, 12345),
            "server": ("test", 80),
        }
    )


def _websocket(*, client_host: str = "127.0.0.1") -> WebSocket:
    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_message):
        return None

    return WebSocket(
        {
            "type": "websocket",
            "path": "/ws",
            "raw_path": b"/ws",
            "query_string": b"",
            "headers": [],
            "client": (client_host, 12345),
            "server": ("test", 80),
            "scheme": "ws",
            "subprotocols": [],
        },
        receive,
        send,
    )


@pytest.mark.parametrize(
    "candidate",
    [None, "", "123", "é.abc", "not-a-time.signature", "1000.signature"],
)
def test_asset_session_rejects_missing_or_malformed_values(
    monkeypatch,
    candidate,
):
    monkeypatch.setattr(settings, "api_token", "secret")

    assert not security.asset_session_matches(candidate, now=1_000)


def test_security_helpers_cover_open_mode_and_remote_denials(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "allow_insecure_lan", False)

    with pytest.raises(RuntimeError, match="API token is not configured"):
        security.create_asset_session()

    assert security.asset_session_matches("irrelevant")
    assert security.token_matches(None)
    assert security.request_is_authorized(_request())
    assert not security.request_is_authorized(
        _request(client_host="192.168.1.10")
    )
    assert security.websocket_is_authorized(_websocket())
    assert not security.websocket_is_authorized(
        _websocket(client_host="192.168.1.10")
    )
