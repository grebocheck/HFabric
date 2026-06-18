"""Tests for the in-app model download manager (P18.4).

No network and no huggingface_hub dependency: the catalog, recommendation,
disk-budget, and status transitions are exercised against fake jobs in a temp
models tree, and the download loop runs against a stub ``huggingface_hub``.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from app.services import model_download_service as dl

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_models  # noqa: E402


def _fake_jobs(models: Path) -> tuple[list, list]:
    image = [
        fetch_models.FetchJob(
            "vendor/sdxl", "sdxl.safetensors", models / "image",
            "SDXL starter", "safe image starter", approx_size_mb=10, license="OpenRAIL++",
        ),
        fetch_models.FetchJob(
            "vendor/flux-fp4", "flux-fp4.safetensors", models / "image",
            "FLUX fp4", "cuda-only fast path", approx_size_mb=20, license="non-commercial",
            profiles=("nvidia-cuda",), feature="nunchaku_cuda",
        ),
    ]
    common = [
        fetch_models.FetchJob(
            "vendor/gguf", "chat.gguf", models / "llm",
            "Chat GGUF", "starter chat model", approx_size_mb=30, license="Apache-2.0",
        ),
    ]
    return image, common


@pytest.fixture
def fake_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    models = tmp_path / "models"
    (models / "image").mkdir(parents=True)
    (models / "llm").mkdir(parents=True)
    image, common = _fake_jobs(models)
    module = types.SimpleNamespace(
        STARTER_IMAGE_JOBS=image,
        ADVANCED_IMAGE_JOBS=[],
        COMMON_JOBS=common,
        plan_for_profile=lambda resolved, **k: (
            [image[0], common[0]]
            + ([image[1]] if "nunchaku_cuda" in (resolved.get("optional_features") or []) else [])
        ),
    )
    monkeypatch.setattr(dl, "ROOT", tmp_path)
    monkeypatch.setattr(dl.capability_profile, "fetch_models_module", lambda: module)
    monkeypatch.setattr(
        dl.capability_profile, "resolved_install_profile",
        lambda **k: {"selected_profile": "nvidia-cuda", "optional_features": []},
    )
    # default status back to idle so tests don't bleed into one another
    monkeypatch.setattr(dl, "_status", {"state": "idle", "message": "", "current": None,
                                        "progress": {"done": 0, "total": 0}, "failed": [],
                                        "updated_at": 0.0})
    return models


def test_catalog_annotates_present_recommended_and_metadata(fake_catalog: Path):
    (fake_catalog / "image" / "sdxl.safetensors").write_bytes(b"x")  # already downloaded

    items = {item["key"]: item for item in dl.catalog()}

    sdxl = items["vendor/sdxl/sdxl.safetensors"]
    assert sdxl["present"] is True
    assert sdxl["recommended"] is True
    assert sdxl["approx_size_mb"] == 10
    assert sdxl["license"] == "OpenRAIL++"
    assert sdxl["repo_url"] == "https://huggingface.co/vendor/sdxl"

    # CUDA-only FLUX is in the catalog but not recommended (feature off in profile).
    flux = items["vendor/flux-fp4/flux-fp4.safetensors"]
    assert flux["present"] is False
    assert flux["recommended"] is False


def test_recommendation_follows_optional_features(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        dl.capability_profile, "resolved_install_profile",
        lambda **k: {"selected_profile": "nvidia-cuda", "optional_features": ["nunchaku_cuda"]},
    )
    items = {item["key"]: item for item in dl.catalog()}
    assert items["vendor/flux-fp4/flux-fp4.safetensors"]["recommended"] is True


def test_preflight_rejects_when_disk_too_small(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dl, "_hub_available", lambda: True)
    monkeypatch.setattr(dl, "disk_status", lambda: {"free_mb": 5, "models_root": "models"})

    _jobs, error = dl.preflight(["vendor/gguf/chat.gguf"])  # needs ~30 MB
    assert error and "disk" in error.lower()


def test_preflight_passes_with_room(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dl, "_hub_available", lambda: True)
    monkeypatch.setattr(dl, "disk_status", lambda: {"free_mb": 10_000, "models_root": "models"})

    jobs, error = dl.preflight(["vendor/gguf/chat.gguf"])
    assert error is None
    assert [j.filename for j in jobs] == ["chat.gguf"]


def test_preflight_requires_known_keys(fake_catalog: Path):
    _jobs, error = dl.preflight(["nope/none.bin"])
    assert error and "selected" in error.lower()


def test_start_short_circuits_when_all_present(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dl, "_hub_available", lambda: True)
    monkeypatch.setattr(dl, "disk_status", lambda: {"free_mb": 10_000, "models_root": "models"})
    (fake_catalog / "llm" / "chat.gguf").write_bytes(b"x")

    status = dl.start(["vendor/gguf/chat.gguf"])
    assert status["state"] == "done"
    assert dl.is_downloading() is False


def test_run_blocking_downloads_and_reports(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    def fake_download(*, repo_id: str, filename: str, local_dir: str) -> str:
        calls.append((repo_id, filename))
        path = Path(local_dir) / filename
        path.write_bytes(b"downloaded")
        return str(path)

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(hf_hub_download=fake_download, snapshot_download=lambda **_: "snapshot"))

    status = dl.run_blocking(["vendor/gguf/chat.gguf"])

    assert calls == [("vendor/gguf", "chat.gguf")]
    assert status["state"] == "done"
    assert status["progress"] == {"done": 1, "total": 1}
    assert (fake_catalog / "llm" / "chat.gguf").exists()


def test_run_blocking_records_failures(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(**_kwargs):
        raise RuntimeError("404 not found")

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(hf_hub_download=boom, snapshot_download=lambda **_: "snapshot"))

    status = dl.run_blocking(["vendor/gguf/chat.gguf"])

    assert status["state"] == "error"
    assert status["failed"] and status["failed"][0]["label"] == "Chat GGUF"


def test_run_blocking_downloads_snapshot_jobs(fake_catalog: Path, monkeypatch: pytest.MonkeyPatch):
    repo_job = fetch_models.FetchJob(
        "vendor/full-repo",
        "",
        fake_catalog / "image",
        "Full repo",
        "advanced whole repo",
        approx_size_mb=40,
        license="see model card",
        source="hf-repo",
        local_subdir="full-repo",
        exclude_patterns=("assets/*",),
    )
    module = types.SimpleNamespace(
        STARTER_IMAGE_JOBS=[],
        ADVANCED_IMAGE_JOBS=[repo_job],
        COMMON_JOBS=[],
        plan_for_profile=lambda resolved, **k: [],
    )
    calls: list[dict] = []
    monkeypatch.setattr(dl.capability_profile, "fetch_models_module", lambda: module)
    monkeypatch.setattr(dl, "_hub_available", lambda: True)

    def fake_snapshot(**kwargs):
        calls.append(kwargs)
        target = Path(kwargs["local_dir"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_index.json").write_text("{}", encoding="utf-8")
        return str(target)

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(hf_hub_download=lambda **_: "file", snapshot_download=fake_snapshot))

    key = "vendor/full-repo/full-repo/"
    status = dl.run_blocking([key])

    assert status["state"] == "done"
    assert calls and calls[0]["repo_id"] == "vendor/full-repo"
    assert calls[0]["ignore_patterns"] == ["assets/*"]
    assert (fake_catalog / "image" / "full-repo" / "model_index.json").exists()
