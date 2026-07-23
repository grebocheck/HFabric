"""In-app model download manager.

Turns ``scripts/fetch_models.py`` into a UI: a curated catalog of verified
starter models annotated with size, license, target dir, whether the file is
already present, and whether it is recommended for the detected hardware. A
background download with file-level progress mirrors the llama.cpp runtime
manager (``llama_manager``); the UI polls status.

The catalog and the recommendation logic come from the same ``fetch_models``
module the installer uses, so the in-app manager and ``setup … all`` never
diverge. Downloads land in the exact ``models/<kind>/`` folders the registry
scans, so a fetched file is usable without copying.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import threading
import time
from typing import Any

from ..config import ROOT
from ..config import settings as settings
from . import (
    capability_profile,
    model_download_catalog,
    model_download_transport,
    model_download_validation,
)
from .model_download_transport import socket as socket

_MB = 1024 * 1024
# Refuse a batch unless this fraction of headroom over the estimate stays free.
_DISK_HEADROOM = 1.15

_status: dict[str, Any] = {
    "state": "idle",  # idle | running | done | error
    "message": "",
    "current": None,
    "progress": {"done": 0, "total": 0},
    "failed": [],
    "updated_at": 0.0,
}
_status_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Status helpers
# --------------------------------------------------------------------------- #
def get_status() -> dict[str, Any]:
    with _status_lock:
        return dict(_status)


def _set_status(**fields: Any) -> None:
    with _status_lock:
        _status.update(fields)
        _status["updated_at"] = time.time()


def is_downloading() -> bool:
    with _status_lock:
        return _status["state"] == "running"


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def _models_root() -> Path:
    root = ROOT / "models"
    return root if root.exists() else ROOT


def _all_jobs() -> list[Any]:
    fm = capability_profile.fetch_models_module()
    return [
        *fm.STARTER_IMAGE_JOBS,
        *getattr(fm, "ADVANCED_IMAGE_JOBS", []),
        *getattr(fm, "VIDEO_JOBS", []),
        *fm.COMMON_JOBS,
    ]


def _recommended_keys(*, refresh: bool = False) -> set[tuple[str, str]]:
    fm = capability_profile.fetch_models_module()
    resolved = capability_profile.resolved_install_profile(refresh=refresh)
    return {(job.repo, _job_filename(job)) for job in fm.plan_for_profile(resolved)}


def _job_key(repo: str, filename: str) -> str:
    return f"{repo}/{filename}"


def _job_filename(job: Any) -> str:
    if hasattr(job, "display_filename"):
        return str(job.display_filename())
    return str(job.filename)


def _job_target_dir(job: Any) -> Path:
    if hasattr(job, "target_dir"):
        return job.target_dir()
    return job.dest


def _job_present(job: Any) -> bool:
    if hasattr(job, "is_present"):
        return bool(job.is_present())
    return (job.dest / job.filename).exists()


def catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    """The full curated catalog, annotated for the detected hardware."""
    recommended = _recommended_keys(refresh=refresh)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for job in _all_jobs():
        filename = _job_filename(job)
        target_dir = _job_target_dir(job)
        ident = (job.repo, filename)
        if ident in seen:
            continue
        seen.add(ident)
        present = _job_present(job)
        items.append(
            {
                "key": _job_key(job.repo, filename),
                "repo": job.repo,
                "filename": filename,
                "dest": target_dir.relative_to(ROOT).as_posix(),
                "label": job.label,
                "reason": job.reason,
                "feature": job.feature,
                "source": getattr(job, "source", "hf-file"),
                "approx_size_mb": job.approx_size_mb,
                "license": job.license,
                "repo_url": f"https://huggingface.co/{job.repo}",
                "present": present,
                "recommended": ident in recommended,
            }
        )
    return items


def disk_status() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(_models_root())
        free_mb = usage.free // _MB
    except OSError:
        free_mb = None
    return {"free_mb": free_mb, "models_root": str(_models_root().relative_to(ROOT))}


def state(*, refresh: bool = False) -> dict[str, Any]:
    """Full payload for the download-manager UI."""
    return {
        "catalog": catalog(refresh=refresh),
        "disk": disk_status(),
        "status": get_status(),
        "available": _hub_available(),
    }


def _hub_available() -> bool:
    import importlib.util  # noqa: PLC0415

    return importlib.util.find_spec("huggingface_hub") is not None


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def _jobs_for_keys(keys: list[str]) -> list[Any]:
    wanted = set(keys)
    return [job for job in _all_jobs() if _job_key(job.repo, _job_filename(job)) in wanted]


def _required_mb(jobs: list[Any]) -> int:
    return sum(job.approx_size_mb for job in jobs if not _job_present(job))


def preflight(keys: list[str]) -> tuple[list[Any], str | None]:
    """Resolve keys to jobs and check disk budget. Returns (jobs, error)."""
    jobs = _jobs_for_keys(keys)
    if not jobs:
        return [], "No matching downloads were selected."
    if not _hub_available():
        return jobs, (
            "huggingface_hub is not installed in this environment. Run the "
            "accelerator setup (setup … real) or `pip install huggingface_hub`."
        )
    required = _required_mb(jobs)
    free = disk_status()["free_mb"]
    if free is not None and required and free < required * _DISK_HEADROOM:
        return jobs, (
            f"Not enough free disk: this set needs about {required} MB plus headroom, "
            f"but only {free} MB is free on the models drive. Free space or pick fewer models."
        )
    return jobs, None


def start(keys: list[str]) -> dict[str, Any]:
    """Begin a background download of the selected catalog keys."""
    with _status_lock:
        if _status["state"] == "running":
            return dict(_status)
    jobs, error = preflight(keys)
    if error:
        raise ValueError(error)
    pending = [job for job in jobs if not _job_present(job)]
    if not pending:
        _set_status(
            state="done",
            message="All selected models are already present.",
            current=None,
            progress={"done": 0, "total": 0},
            failed=[],
        )
        return get_status()
    _set_status(
        state="running",
        message="Starting download…",
        current=None,
        progress={"done": 0, "total": len(pending)},
        failed=[],
    )
    return get_status()


def run_blocking(keys: list[str]) -> dict[str, Any]:
    """Download the selected jobs. Runs in a worker thread; updates status."""
    from huggingface_hub import hf_hub_download, snapshot_download  # noqa: PLC0415

    jobs = [job for job in _jobs_for_keys(keys) if not _job_present(job)]
    total = len(jobs)
    failed: list[dict[str, str]] = []
    for index, job in enumerate(jobs):
        filename = _job_filename(job)
        target_dir = _job_target_dir(job)
        _set_status(
            current={"label": job.label, "filename": filename},
            message=f"Downloading {job.label}…",
            progress={"done": index, "total": total},
        )
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if getattr(job, "source", "hf-file") == "hf-repo":
                snapshot_download(
                    repo_id=job.repo,
                    local_dir=str(target_dir),
                    allow_patterns=list(getattr(job, "include_patterns", ())) or None,
                    ignore_patterns=list(getattr(job, "exclude_patterns", ())) or None,
                )
            else:
                hf_hub_download(repo_id=job.repo, filename=job.filename, local_dir=str(target_dir))
        except Exception as exc:  # noqa: BLE001 - report each failure to the UI
            failed.append({"label": job.label, "error": f"{type(exc).__name__}: {exc}"})

    done = total - len(failed)
    if failed:
        names = ", ".join(item["label"] for item in failed)
        message = f"Downloaded {done}/{total}; failed: {names}"
        _set_status(
            state="error",
            message=message,
            current=None,
            progress={"done": total, "total": total},
            failed=failed,
        )
    else:
        _set_status(
            state="done",
            message=f"Downloaded {done} model file(s).",
            current=None,
            progress={"done": total, "total": total},
            failed=[],
        )
    return get_status()


# --------------------------------------------------------------------------- #
# Custom downloads (any source)
# --------------------------------------------------------------------------- #
def _kind_dir(kind: str) -> Path | None:
    return model_download_validation.kind_dir(kind)


def hf_list_files(repo: str) -> list[dict[str, Any]]:
    return model_download_catalog.hf_list_files(
        repo,
        hub_available=_hub_available(),
    )


def hf_search_models(
    query: str,
    *,
    limit: int = 24,
    sort: str = "downloads",
    filter_tags: list[str] | None = None,
) -> dict[str, Any]:
    return model_download_catalog.hf_search_models(
        query,
        limit=limit,
        sort=sort,
        filter_tags=filter_tags,
        hub_available=_hub_available(),
    )


def validate_custom(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    return model_download_validation.validate_custom(items)


def start_custom(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate + flip status to running for a custom (any-source) download batch."""
    with _status_lock:
        if _status["state"] == "running":
            return dict(_status)
    clean, error = validate_custom(items)
    if error:
        raise ValueError(error)
    if any(spec["source"] in ("hf", "hf-repo") for spec in clean) and not _hub_available():
        raise ValueError(
            "huggingface_hub is not installed in this environment. Run the "
            "accelerator setup (setup … real) or `pip install huggingface_hub`."
        )
    _set_status(
        state="running",
        message="Starting download…",
        current=None,
        progress={"done": 0, "total": len(clean)},
        failed=[],
    )
    return get_status()


def _assert_public_download_url(url: str) -> None:
    model_download_transport.assert_public_download_url(url)


def _download_url(url: str, dest_path: Path, headers: dict[str, str] | None = None) -> None:
    model_download_transport.download_url(
        url,
        dest_path,
        headers,
    )


def _verify_sha256(path: Path, expected: str) -> None:
    model_download_transport.verify_sha256(path, expected)


def run_blocking_custom(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Download user-supplied models. Runs in a worker thread; updates status."""
    clean, error = validate_custom(items)
    if error:
        _set_status(state="error", message=error, current=None, progress={"done": 0, "total": 0}, failed=[])
        return get_status()

    total = len(clean)
    failed: list[dict[str, str]] = []
    for index, spec in enumerate(clean):
        _set_status(
            current={"label": spec["label"], "filename": spec["filename"]},
            message=f"Downloading {spec['label']}…",
            progress={"done": index, "total": total},
        )
        try:
            kind_dir = _kind_dir(spec["kind"])
            if kind_dir is None:
                raise ValueError(f"unknown kind {spec['kind']}")
            if spec["source"] == "hf-repo":
                from huggingface_hub import snapshot_download  # noqa: PLC0415

                dest = kind_dir / spec["subdir"]
                dest.mkdir(parents=True, exist_ok=True)
                snapshot_download(repo_id=spec["repo"], local_dir=str(dest))
            elif spec["source"] == "hf":
                from huggingface_hub import hf_hub_download  # noqa: PLC0415

                dest = kind_dir / spec["subdir"] if spec.get("subdir") else kind_dir
                dest.mkdir(parents=True, exist_ok=True)
                hf_hub_download(repo_id=spec["repo"], filename=spec["filename"], local_dir=str(dest))
            elif spec["source"] == "civitai":
                import httpx  # noqa: PLC0415

                from . import civitai_auth  # noqa: PLC0415

                kind_dir.mkdir(parents=True, exist_ok=True)
                dest_path = kind_dir / spec["filename"]
                # API key (?token=) is preferred; a saved session cookie is the fallback.
                url, headers = civitai_auth.download_auth(spec["url"])
                try:
                    _download_url(url, dest_path, headers=headers)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (401, 403):
                        raise ValueError(
                            "CivitAI requires an API key or session login to download this model "
                            "(it now gates most downloads, even some public ones). Add your key or "
                            "session cookie in the CivitAI account panel — it is stored locally."
                        ) from exc
                    raise
                if spec.get("sha256"):
                    _verify_sha256(dest_path, spec["sha256"])
            else:
                kind_dir.mkdir(parents=True, exist_ok=True)
                _download_url(spec["url"], kind_dir / spec["filename"])
        except Exception as exc:  # noqa: BLE001 - report each failure to the UI
            failed.append({"label": spec["label"], "error": f"{type(exc).__name__}: {exc}"})

    done = total - len(failed)
    if failed:
        names = ", ".join(item["label"] for item in failed)
        _set_status(
            state="error",
            message=f"Downloaded {done}/{total}; failed: {names}",
            current=None,
            progress={"done": total, "total": total},
            failed=failed,
        )
    else:
        _set_status(
            state="done",
            message=f"Downloaded {done} model file(s).",
            current=None,
            progress={"done": total, "total": total},
            failed=[],
        )
    return get_status()
