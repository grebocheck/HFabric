"""Model Manager: installed inventory + safe deletion + custom-source validation
(P25). Uses the stub app_client whose temp model dirs the conftest seeds.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from app.api import models as models_api
from app.config import settings
from app.core.enums import JobStatus, JobType
from app.db.models import Job
from app.db.session import session_scope
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


async def test_hf_search_route_passes_query_params(app_client, monkeypatch):
    captured: dict = {}

    def fake_search(q: str, **kwargs):
        captured["q"] = q
        captured.update(kwargs)
        return {"query": q, "sort": kwargs["sort"], "limit": kwargs["limit"], "filters": kwargs["filter_tags"], "results": []}

    monkeypatch.setattr(downloads, "hf_search_models", fake_search)

    res = await app_client.get(
        "/api/downloads/hf/search",
        params={"q": "qwen", "sort": "likes", "limit": 3, "filter": "gguf,lora"},
    )

    assert res.status_code == 200
    assert captured == {"q": "qwen", "limit": 3, "sort": "likes", "filter_tags": ["gguf", "lora"]}
    assert res.json()["filters"] == ["gguf", "lora"]


def test_validate_custom_normalizes_hf_and_url_and_rejects_bad_input():
    clean, error = downloads.validate_custom([
        {"source": "hf", "kind": "llm", "repo": "owner/model", "filename": "m.gguf"},
        {"source": "url", "kind": "lora", "url": "https://example.com/path/x.safetensors?dl=1"},
    ])
    assert error is None
    assert clean[0]["label"] == "owner/model/m.gguf"
    assert clean[1]["filename"] == "x.safetensors"  # derived from the URL, query stripped


def test_validate_custom_handles_subdir_and_whole_repo():
    # A file with a repo subpath is placed under a (sanitized) subdir.
    clean, error = downloads.validate_custom([
        {"source": "hf", "kind": "image", "repo": "owner/diff", "filename": "transformer/m.safetensors",
         "subdir": "../weird//diff"},
    ])
    assert error is None
    assert clean[0]["subdir"] == "weird/diff"  # traversal + empty segments stripped

    # Whole-repo defaults the subdir to the repo's last path segment.
    clean, error = downloads.validate_custom([{"source": "hf-repo", "kind": "image", "repo": "owner/My-Repo"}])
    assert error is None
    assert clean[0]["source"] == "hf-repo"
    assert clean[0]["subdir"] == "My-Repo"

    _, missing = downloads.validate_custom([{"source": "hf-repo", "kind": "image"}])
    assert missing is not None

    _, bad_kind = downloads.validate_custom([{"source": "hf", "kind": "nope", "repo": "a/b", "filename": "x"}])
    assert bad_kind is not None
    _, bad_url = downloads.validate_custom([{"source": "url", "kind": "llm", "url": "ftp://x/y"}])
    assert bad_url is not None
    _, traversal = downloads.validate_custom(
        [{"source": "hf", "kind": "llm", "repo": "a/b", "filename": "../escape.gguf"}]
    )
    assert traversal is not None


def test_direct_download_ssrf_policy_rejects_private_and_mixed_dns(monkeypatch):
    for url in (
        "http://127.0.0.1/model.gguf",
        "http://[::1]/model.gguf",
        "http://169.254.169.254/latest/meta-data",
        "http://service.internal/model.gguf",
        "http://user:pass@example.com/model.gguf",
    ):
        with pytest.raises(ValueError):
            downloads._assert_public_download_url(url)

    monkeypatch.setattr(
        downloads.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (downloads.socket.AF_INET, downloads.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (downloads.socket.AF_INET, downloads.socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443)),
        ],
    )
    with pytest.raises(ValueError, match="local or private"):
        downloads._assert_public_download_url("https://models.example/model.gguf")

    monkeypatch.setattr(
        downloads.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (downloads.socket.AF_INET, downloads.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )
    downloads._assert_public_download_url("https://models.example/model.gguf")


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


def test_model_storage_busy_check_covers_ancestors_and_descendants(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "image_models_dir", tmp_path)
    repo = tmp_path / "repo"
    nested_weight = repo / "transformer" / "model.safetensors"
    nested_weight.parent.mkdir(parents=True)
    nested_weight.write_bytes(b"weights")

    listed = model_storage.installed(in_use={nested_weight})
    assert next(item for item in listed if item["path"] == "repo")["in_use"] is True

    with pytest.raises(model_storage.ModelInUseError):
        model_storage.delete("image", "repo", in_use={nested_weight})
    with pytest.raises(model_storage.ModelInUseError):
        model_storage.delete("image", "repo", in_use={tmp_path})
    assert repo.exists()


def test_model_storage_refuses_symlink_entries(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"GGUF")
    link = root / "linked.gguf"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    monkeypatch.setattr(settings, "llm_models_dir", root)

    with pytest.raises(ValueError, match="symlink or junction"):
        model_storage.delete("llm", "linked.gguf")
    assert outside.exists()


def test_model_storage_rolls_back_visible_path_on_locked_delete(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "locked.gguf"
    weight.write_bytes(b"GGUF")

    def fail_remove(_staged: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(model_storage, "_remove_staged", fail_remove)
    with pytest.raises(
        model_storage.ModelDeleteError,
        match="remaining visible model path was restored",
    ):
        model_storage.delete("llm", "locked.gguf")

    assert weight.exists()
    assert model_storage.reserved_paths() == set()


def test_model_storage_reservation_blocks_parallel_delete(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "parallel.gguf"
    weight.write_bytes(b"GGUF")
    removal_started = threading.Event()
    allow_removal = threading.Event()
    real_remove = model_storage._remove_staged

    def paused_remove(staged: Path) -> None:
        removal_started.set()
        assert allow_removal.wait(timeout=5)
        real_remove(staged)

    monkeypatch.setattr(model_storage, "_remove_staged", paused_remove)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(model_storage.delete, "llm", "parallel.gguf")
        assert removal_started.wait(timeout=5)
        assert any(
            model_storage.paths_overlap(path, weight)
            for path in model_storage.reserved_paths()
        )
        with pytest.raises(model_storage.ModelInUseError):
            model_storage.delete("llm", "parallel.gguf")
        allow_removal.set()
        assert future.result()["freed_bytes"] == 4

    assert model_storage.reserved_paths() == set()


def test_model_storage_reports_rescan_failure_after_completed_delete(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "llm_models_dir", tmp_path)
    weight = tmp_path / "rescan-error.gguf"
    weight.write_bytes(b"GGUF")

    def fail_rescan() -> None:
        raise RuntimeError("registry failed")

    with pytest.raises(
        model_storage.ModelInventoryError,
        match="was deleted.*Rescan Models",
    ):
        model_storage.delete(
            "llm",
            weight.name,
            after_delete=fail_rescan,
        )

    assert not weight.exists()
    assert model_storage.reserved_paths() == set()


def test_related_registry_paths_protects_mmproj_companion(tmp_path):
    model = tmp_path / "chat.gguf"
    projector = tmp_path / "mmproj-chat.gguf"
    descriptor = SimpleNamespace(
        path=model,
        mmproj_path=projector,
        job_type=SimpleNamespace(value="llm"),
    )
    registry = SimpleNamespace(descriptors=lambda: [descriptor], loras=lambda: [])

    protected = models_api._related_registry_paths(registry, {model})

    assert protected == {model, projector}


def test_related_registry_paths_protects_warm_adapter_cache(tmp_path):
    model = tmp_path / "image.safetensors"
    lora = tmp_path / "style.safetensors"
    descriptor = SimpleNamespace(
        path=model,
        mmproj_path=None,
        job_type=SimpleNamespace(value="image"),
    )
    registry = SimpleNamespace(
        descriptors=lambda: [descriptor],
        loras=lambda: [SimpleNamespace(path=lora)],
    )

    protected = models_api._related_registry_paths(registry, {model})

    assert protected == {model, lora}


async def test_delete_blocks_queued_model_and_active_download(
    app_client,
    monkeypatch,
):
    weight = settings.llm_models_dir / "queued-guard.gguf"
    weight.write_bytes(b"GGUF")
    try:
        await app_client.post("/api/models/rescan")
        models = (await app_client.get("/api/models")).json()
        model_id = next(item["id"] for item in models if item["name"] == "queued-guard")
        async with session_scope() as session:
            session.add(
                Job(
                    id="queued-delete-guard",
                    type=JobType.LLM,
                    status=JobStatus.QUEUED,
                    model_id=model_id,
                    params={},
                )
            )

        queued = await app_client.request(
            "DELETE",
            "/api/models/installed",
            params={"kind": "llm", "path": weight.name},
        )
        assert queued.status_code == 409
        assert weight.exists()

        async with session_scope() as session:
            job = await session.get(Job, "queued-delete-guard")
            if job is not None:
                await session.delete(job)
        monkeypatch.setattr(downloads, "is_downloading", lambda: True)
        downloading = await app_client.request(
            "DELETE",
            "/api/models/installed",
            params={"kind": "llm", "path": weight.name},
        )
        assert downloading.status_code == 409
        assert weight.exists()
    finally:
        weight.unlink(missing_ok=True)
