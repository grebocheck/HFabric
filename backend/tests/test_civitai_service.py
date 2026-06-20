"""Tests for the CivitAI browse service + the civitai custom-download source.

No network: the httpx client is replaced with a fake that returns canned API
payloads, and the download loop runs against a stubbed ``_download_url``.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path

import pytest

from app.services import civitai_auth
from app.services import civitai_service as cs
from app.services import model_download_service as dl


# --------------------------------------------------------------------------- #
# Fake httpx client
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, routes: dict[str, dict]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict | None = None) -> _FakeResponse:
        self.calls.append((path, params or {}))
        return _FakeResponse(self.routes[path])


@contextmanager
def _fake_client_cm(client: _FakeClient):
    yield client


# --------------------------------------------------------------------------- #
# infer_kind
# --------------------------------------------------------------------------- #
def test_infer_kind_maps_known_types() -> None:
    assert cs.infer_kind("Checkpoint") == "image"
    assert cs.infer_kind("LORA") == "lora"
    assert cs.infer_kind("LoCon") == "lora"
    assert cs.infer_kind("VAE") is None
    assert cs.infer_kind(None) is None


# --------------------------------------------------------------------------- #
# search_models
# --------------------------------------------------------------------------- #
def test_search_normalizes_results_and_picks_host(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "items": [
            {
                "id": 42,
                "name": "Cool LoRA",
                "type": "LORA",
                "nsfw": False,
                "creator": {"username": "alice"},
                "stats": {"downloadCount": 1234, "thumbsUpCount": 56},
                "tags": ["anime", "style"],
                "modelVersions": [
                    {
                        "id": 100,
                        "name": "v1",
                        "baseModel": "SDXL 1.0",
                        "images": [{"url": "https://img/x.png", "nsfwLevel": 1, "width": 8, "height": 8}],
                    },
                    {"id": 99, "name": "v0", "baseModel": "SD 1.5", "images": []},
                ],
            }
        ],
        "metadata": {"totalPages": 3, "nextPage": 2},
    }
    fake = _FakeClient({"/models": payload})
    monkeypatch.setattr(cs, "_client", lambda nsfw, token=None: _fake_client_cm(fake))

    out = cs.search_models("cool", types=["LORA"], sort="downloads", nsfw=False, limit=10)

    assert out["total_pages"] == 3
    assert out["next_page"] == 2
    (result,) = out["results"]
    assert result["id"] == 42
    assert result["suggested_kind"] == "lora"
    assert result["base_model"] == "SDXL 1.0"
    assert result["preview"]["url"] == "https://img/x.png"
    assert result["version_count"] == 2
    assert result["url"].startswith(cs.HOST_SFW)
    # query params forwarded
    _, params = fake.calls[0]
    assert params["sort"] == "Most Downloaded"
    assert params["nsfw"] == "false"
    assert params["types"] == ["LORA"]


def test_search_nsfw_uses_red_host(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_client(nsfw, token=None):
        captured["nsfw"] = nsfw
        return _fake_client_cm(_FakeClient({"/models": {"items": [], "metadata": {}}}))

    monkeypatch.setattr(cs, "_client", fake_client)
    out = cs.search_models("x", nsfw=True)
    assert captured["nsfw"] is True
    assert out["results"] == []


# --------------------------------------------------------------------------- #
# version_files
# --------------------------------------------------------------------------- #
def test_version_files_sorts_primary_first(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "id": 100,
        "name": "v1",
        "modelId": 42,
        "model": {"id": 42, "name": "Cool LoRA", "type": "LORA"},
        "baseModel": "SDXL 1.0",
        "trainedWords": ["coolstyle"],
        "files": [
            {
                "id": 2,
                "name": "extra.safetensors",
                "sizeKB": 1000,
                "primary": False,
                "metadata": {"format": "SafeTensor"},
                "downloadUrl": "https://civitai.com/api/download/models/100?type=extra",
                "hashes": {"SHA256": "ABC123"},
            },
            {
                "id": 1,
                "name": "main.safetensors",
                "sizeKB": 2000,
                "primary": True,
                "metadata": {"format": "SafeTensor"},
                "downloadUrl": "https://civitai.com/api/download/models/100",
                "hashes": {"SHA256": "DEF456"},
            },
        ],
    }
    fake = _FakeClient({"/model-versions/100": payload})
    monkeypatch.setattr(cs, "_client", lambda nsfw, token=None: _fake_client_cm(fake))

    out = cs.version_files(100)
    assert out["trained_words"] == ["coolstyle"]
    assert out["suggested_kind"] == "lora"
    assert [f["name"] for f in out["files"]] == ["main.safetensors", "extra.safetensors"]
    assert out["files"][0]["sha256"] == "def456"  # lower-cased


# --------------------------------------------------------------------------- #
# civitai custom download source
# --------------------------------------------------------------------------- #
def test_validate_custom_accepts_civitai_source() -> None:
    clean, error = dl.validate_custom(
        [
            {
                "source": "civitai",
                "kind": "lora",
                "url": "https://civitai.com/api/download/models/100",
                "filename": "main.safetensors",
                "sha256": "DEADBEEF",
            }
        ]
    )
    assert error is None
    assert clean[0]["source"] == "civitai"
    assert clean[0]["sha256"] == "deadbeef"


def test_validate_custom_civitai_requires_url() -> None:
    _, error = dl.validate_custom([{"source": "civitai", "kind": "lora", "filename": "x.safetensors"}])
    assert error and "download URL" in error


def test_run_civitai_download_verifies_sha256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"weights-bytes"
    good = hashlib.sha256(body).hexdigest()
    lora_dir = tmp_path / "lora"
    monkeypatch.setattr(dl.settings, "lora_models_dir", lora_dir)

    def fake_download(url: str, dest_path: Path, headers: dict | None = None) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(body)

    monkeypatch.setattr(dl, "_download_url", fake_download)

    ok = dl.run_blocking_custom(
        [{"source": "civitai", "kind": "lora", "url": "https://x/y", "filename": "m.safetensors", "sha256": good}]
    )
    assert ok["state"] == "done"
    assert (lora_dir / "m.safetensors").read_bytes() == body


def test_run_civitai_download_rejects_bad_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lora_dir = tmp_path / "lora"
    monkeypatch.setattr(dl.settings, "lora_models_dir", lora_dir)

    def fake_download(url: str, dest_path: Path, headers: dict | None = None) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"login-html-page")

    monkeypatch.setattr(dl, "_download_url", fake_download)

    out = dl.run_blocking_custom(
        [{"source": "civitai", "kind": "lora", "url": "https://x/y", "filename": "m.safetensors", "sha256": "00" * 32}]
    )
    assert out["state"] == "error"
    assert out["failed"]
    assert not (lora_dir / "m.safetensors").exists()  # corrupt download removed


# --------------------------------------------------------------------------- #
# civitai_auth secret store
# --------------------------------------------------------------------------- #
def test_secret_store_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(civitai_auth.settings, "data_dir", tmp_path)
    assert civitai_auth.has_key() is False
    assert civitai_auth.get_key() is None

    civitai_auth.set_key("  my-secret  ")
    assert civitai_auth.get_key() == "my-secret"  # trimmed
    assert civitai_auth.has_key() is True
    assert (tmp_path / "secrets.json").exists()

    civitai_auth.clear_key()
    assert civitai_auth.has_key() is False


def test_set_empty_key_clears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(civitai_auth.settings, "data_dir", tmp_path)
    civitai_auth.set_key("abc")
    civitai_auth.set_key("")
    assert civitai_auth.get_key() is None


def test_cookie_store_normalizes_and_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(civitai_auth.settings, "data_dir", tmp_path)
    assert civitai_auth.has_cookie() is False
    # Accept a pasted "name=value; other=…" cookie string and keep only our value.
    civitai_auth.set_cookie("__Secure-civitai-token=abc.def.ghi; Path=/; Secure")
    assert civitai_auth.get_cookie() == "abc.def.ghi"
    assert civitai_auth.has_cookie() is True
    # Bare value is accepted too.
    civitai_auth.set_cookie("plain-value")
    assert civitai_auth.get_cookie() == "plain-value"
    civitai_auth.clear_cookie()
    assert civitai_auth.has_cookie() is False


def test_download_auth_prefers_key_then_cookie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(civitai_auth.settings, "data_dir", tmp_path)
    base = "https://civitai.com/api/download/models/100"

    # No creds → anonymous, URL unchanged.
    url, headers = civitai_auth.download_auth(base)
    assert url == base and headers is None

    # Cookie only → Cookie header, URL unchanged.
    civitai_auth.set_cookie("cook-val")
    url, headers = civitai_auth.download_auth(base)
    assert url == base
    assert headers == {"Cookie": "__Secure-civitai-token=cook-val"}

    # Key present → key wins: ?token= appended + bearer header.
    civitai_auth.set_key("k-123")
    url, headers = civitai_auth.download_auth(base)
    assert url == f"{base}?token=k-123"
    assert headers == {"Authorization": "Bearer k-123"}


def test_civitai_download_sends_bearer_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lora_dir = tmp_path / "lora"
    monkeypatch.setattr(dl.settings, "lora_models_dir", lora_dir)
    monkeypatch.setattr(civitai_auth, "get_key", lambda: "tok-123")

    captured: dict = {}

    def fake_download(url: str, dest_path: Path, headers: dict | None = None) -> None:
        captured["headers"] = headers
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"data")

    monkeypatch.setattr(dl, "_download_url", fake_download)

    out = dl.run_blocking_custom(
        [{"source": "civitai", "kind": "lora", "url": "https://x/y", "filename": "m.safetensors"}]
    )
    assert out["state"] == "done"
    assert captured["headers"] == {"Authorization": "Bearer tok-123"}
