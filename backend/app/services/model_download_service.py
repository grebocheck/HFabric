"""In-app model download manager (P18.4).

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

from ..config import ROOT, settings
from . import capability_profile

# Custom downloads (P25.3): a user-supplied model from any source, dropped into the
# right kind folder. Kept deliberately small — HuggingFace repo+file and direct URL.
_CUSTOM_KINDS = ("image", "llm", "lora", "tts", "transcribe", "embed", "vision", "voice")

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
    return [*fm.STARTER_IMAGE_JOBS, *fm.COMMON_JOBS]


def _recommended_keys(*, refresh: bool = False) -> set[tuple[str, str]]:
    fm = capability_profile.fetch_models_module()
    resolved = capability_profile.resolved_install_profile(refresh=refresh)
    return {(job.repo, job.filename) for job in fm.plan_for_profile(resolved)}


def _job_key(repo: str, filename: str) -> str:
    return f"{repo}/{filename}"


def catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    """The full curated catalog, annotated for the detected hardware."""
    recommended = _recommended_keys(refresh=refresh)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for job in _all_jobs():
        ident = (job.repo, job.filename)
        if ident in seen:
            continue
        seen.add(ident)
        present = (job.dest / job.filename).exists()
        items.append(
            {
                "key": _job_key(job.repo, job.filename),
                "repo": job.repo,
                "filename": job.filename,
                "dest": job.dest.relative_to(ROOT).as_posix(),
                "label": job.label,
                "reason": job.reason,
                "feature": job.feature,
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
    return [job for job in _all_jobs() if _job_key(job.repo, job.filename) in wanted]


def _required_mb(jobs: list[Any]) -> int:
    return sum(job.approx_size_mb for job in jobs if not (job.dest / job.filename).exists())


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
    pending = [job for job in jobs if not (job.dest / job.filename).exists()]
    if not pending:
        _set_status(state="done", message="All selected models are already present.",
                    current=None, progress={"done": 0, "total": 0}, failed=[])
        return get_status()
    _set_status(state="running", message="Starting download…", current=None,
                progress={"done": 0, "total": len(pending)}, failed=[])
    return get_status()


def run_blocking(keys: list[str]) -> dict[str, Any]:
    """Download the selected jobs. Runs in a worker thread; updates status."""
    from huggingface_hub import hf_hub_download  # noqa: PLC0415

    jobs = [job for job in _jobs_for_keys(keys) if not (job.dest / job.filename).exists()]
    total = len(jobs)
    failed: list[dict[str, str]] = []
    for index, job in enumerate(jobs):
        _set_status(
            current={"label": job.label, "filename": job.filename},
            message=f"Downloading {job.label}…",
            progress={"done": index, "total": total},
        )
        try:
            job.dest.mkdir(parents=True, exist_ok=True)
            hf_hub_download(repo_id=job.repo, filename=job.filename, local_dir=str(job.dest))
        except Exception as exc:  # noqa: BLE001 - report each failure to the UI
            failed.append({"label": job.label, "error": f"{type(exc).__name__}: {exc}"})

    done = total - len(failed)
    if failed:
        names = ", ".join(item["label"] for item in failed)
        message = f"Downloaded {done}/{total}; failed: {names}"
        _set_status(state="error", message=message, current=None,
                    progress={"done": total, "total": total}, failed=failed)
    else:
        _set_status(state="done", message=f"Downloaded {done} model file(s).", current=None,
                    progress={"done": total, "total": total}, failed=[])
    return get_status()


# --------------------------------------------------------------------------- #
# Custom downloads (any source)
# --------------------------------------------------------------------------- #
def _kind_dir(kind: str) -> Path | None:
    mapping = {
        "image": settings.image_models_dir,
        "llm": settings.llm_models_dir,
        "lora": settings.lora_models_dir,
        "tts": settings.tts_models_dir,
        "transcribe": settings.transcription_models_dir,
        "embed": settings.embed_models_dir,
        "vision": settings.vision_models_dir,
        "voice": settings.voice_models_dir,
    }
    return mapping.get(kind)


def validate_custom(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize user-supplied download specs. Returns (clean_specs, error)."""
    if not items:
        return [], "No models to download were provided."
    clean: list[dict[str, Any]] = []
    for raw in items:
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in _CUSTOM_KINDS:
            return [], f"Unknown model type: {kind or '(none)'}."
        source = str(raw.get("source") or "").strip().lower()
        if source == "hf":
            repo = str(raw.get("repo") or "").strip()
            filename = str(raw.get("filename") or "").strip()
            if not repo or not filename:
                return [], "A HuggingFace download needs both a repo id and a file name."
            if ".." in filename.replace("\\", "/").split("/"):
                return [], "Invalid file name."
            clean.append({
                "source": "hf", "kind": kind, "repo": repo, "filename": filename,
                "label": str(raw.get("label") or f"{repo}/{filename}"),
            })
        elif source == "url":
            url = str(raw.get("url") or "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                return [], "A direct download needs an http(s) URL."
            given = str(raw.get("filename") or "").strip()
            filename = Path(given).name if given else Path(url.split("?")[0]).name
            if not filename:
                return [], "Could not determine a file name from the URL; provide one."
            clean.append({
                "source": "url", "kind": kind, "url": url, "filename": filename,
                "label": str(raw.get("label") or filename),
            })
        else:
            return [], f"Unknown source: {source or '(none)'}."
    return clean, None


def start_custom(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate + flip status to running for a custom (any-source) download batch."""
    with _status_lock:
        if _status["state"] == "running":
            return dict(_status)
    clean, error = validate_custom(items)
    if error:
        raise ValueError(error)
    if any(spec["source"] == "hf" for spec in clean) and not _hub_available():
        raise ValueError(
            "huggingface_hub is not installed in this environment. Run the "
            "accelerator setup (setup … real) or `pip install huggingface_hub`."
        )
    _set_status(state="running", message="Starting download…", current=None,
                progress={"done": 0, "total": len(clean)}, failed=[])
    return get_status()


def _download_url(url: str, dest_path: Path) -> None:
    """Stream a direct URL to disk via a ``.part`` file, then atomically rename."""
    import httpx  # noqa: PLC0415

    tmp = dest_path.with_name(dest_path.name + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=None) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=_MB):
                handle.write(chunk)
    tmp.replace(dest_path)


def run_blocking_custom(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Download user-supplied models. Runs in a worker thread; updates status."""
    clean, error = validate_custom(items)
    if error:
        _set_status(state="error", message=error, current=None,
                    progress={"done": 0, "total": 0}, failed=[])
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
            dest = _kind_dir(spec["kind"])
            if dest is None:
                raise ValueError(f"unknown kind {spec['kind']}")
            dest.mkdir(parents=True, exist_ok=True)
            if spec["source"] == "hf":
                from huggingface_hub import hf_hub_download  # noqa: PLC0415

                hf_hub_download(repo_id=spec["repo"], filename=spec["filename"], local_dir=str(dest))
            else:
                _download_url(spec["url"], dest / spec["filename"])
        except Exception as exc:  # noqa: BLE001 - report each failure to the UI
            failed.append({"label": spec["label"], "error": f"{type(exc).__name__}: {exc}"})

    done = total - len(failed)
    if failed:
        names = ", ".join(item["label"] for item in failed)
        _set_status(state="error", message=f"Downloaded {done}/{total}; failed: {names}",
                    current=None, progress={"done": total, "total": total}, failed=failed)
    else:
        _set_status(state="done", message=f"Downloaded {done} model file(s).", current=None,
                    progress={"done": total, "total": total}, failed=[])
    return get_status()
