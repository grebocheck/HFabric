"""Model Manager: installed inventory + safe deletion + custom-source validation
(P25). Uses the stub app_client whose temp model dirs the conftest seeds.
"""

from __future__ import annotations

from app.config import settings
from app.services import model_download_service as downloads
from app.services import model_storage


async def test_installed_lists_seeded_models_with_sizes(app_client):
    payload = (await app_client.get("/api/models/installed")).json()
    items = payload["items"]
    # The conftest seeds an SDXL image checkpoint and a GGUF LLM.
    image = next(i for i in items if i["kind"] == "image")
    llm = next(i for i in items if i["kind"] == "llm")
    assert image["size_bytes"] > 0
    assert llm["name"] == "stub-llm"
    assert all("path" in i and "in_use" in i for i in items)
    assert payload["total_used_bytes"] >= image["size_bytes"]


async def test_delete_removes_a_model_and_frees_space(app_client):
    extra = settings.llm_models_dir / "scratch-llm.gguf"
    extra.write_bytes(b"GGUF12")  # 6 bytes
    try:
        listed = (await app_client.get("/api/models/installed")).json()["items"]
        target = next(i for i in listed if i["name"] == "scratch-llm")

        res = await app_client.request(
            "DELETE", "/api/models/installed", params={"kind": target["kind"], "path": target["path"]}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["freed_bytes"] == 6
        assert not extra.exists()

        after = (await app_client.get("/api/models/installed")).json()["items"]
        assert not any(i["name"] == "scratch-llm" for i in after)
    finally:
        extra.unlink(missing_ok=True)


async def test_delete_rejects_traversal_and_folder_targets(app_client):
    escape = await app_client.request(
        "DELETE", "/api/models/installed", params={"kind": "llm", "path": "../../.env"}
    )
    assert escape.status_code == 400

    bad_kind = await app_client.request(
        "DELETE", "/api/models/installed", params={"kind": "nope", "path": "x.gguf"}
    )
    assert bad_kind.status_code == 400

    # An empty path would target the kind folder itself; must be refused.
    whole = await app_client.request(
        "DELETE", "/api/models/installed", params={"kind": "llm", "path": "."}
    )
    assert whole.status_code == 400

    missing = await app_client.request(
        "DELETE", "/api/models/installed", params={"kind": "llm", "path": "nope.gguf"}
    )
    assert missing.status_code in (400, 404)


def test_validate_custom_normalizes_hf_and_url_and_rejects_bad_input():
    clean, error = downloads.validate_custom([
        {"source": "hf", "kind": "llm", "repo": "owner/model", "filename": "m.gguf"},
        {"source": "url", "kind": "lora", "url": "https://example.com/path/x.safetensors?dl=1"},
    ])
    assert error is None
    assert clean[0]["label"] == "owner/model/m.gguf"
    assert clean[1]["filename"] == "x.safetensors"  # derived from the URL, query stripped

    _, bad_kind = downloads.validate_custom([{"source": "hf", "kind": "nope", "repo": "a/b", "filename": "x"}])
    assert bad_kind is not None
    _, bad_url = downloads.validate_custom([{"source": "url", "kind": "llm", "url": "ftp://x/y"}])
    assert bad_url is not None
    _, traversal = downloads.validate_custom(
        [{"source": "hf", "kind": "llm", "repo": "a/b", "filename": "../escape.gguf"}]
    )
    assert traversal is not None


def test_model_storage_delete_refuses_in_use(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "resident.gguf"
    weight.write_bytes(b"GGUF")

    try:
        model_storage.delete("llm", "resident.gguf", in_use={weight})
        raise AssertionError("expected ModelInUseError")
    except model_storage.ModelInUseError:
        pass
    assert weight.exists()  # not deleted
