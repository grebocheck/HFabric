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
import re
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
_HF_SEARCH_LIMIT_MAX = 50
_HF_SORTS = {
    "downloads": "downloads",
    "likes": "likes",
    "updated": "last_modified",
    "trending": "trending_score",
    "created": "created_at",
}
_WEIGHT_RE = re.compile(r"\.(safetensors|gguf|pt|pth|bin|ckpt|onnx)$", re.IGNORECASE)

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
    return [*fm.STARTER_IMAGE_JOBS, *getattr(fm, "ADVANCED_IMAGE_JOBS", []), *fm.COMMON_JOBS]


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
        _set_status(state="done", message="All selected models are already present.",
                    current=None, progress={"done": 0, "total": 0}, failed=[])
        return get_status()
    _set_status(state="running", message="Starting download…", current=None,
                progress={"done": 0, "total": len(pending)}, failed=[])
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


def _safe_subdir(raw: Any) -> str:
    """A traversal-safe relative subfolder (or '') from user input."""
    parts = [p for p in str(raw or "").replace("\\", "/").split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def hf_list_files(repo: str) -> list[dict[str, Any]]:
    """List a HuggingFace model repo's files with sizes so the UI can let the user
    pick specific files or the whole repo (P25). Raises ValueError on failure."""
    repo = (repo or "").strip()
    if not repo:
        raise ValueError("Enter a HuggingFace repo id, e.g. owner/model.")
    if not _hub_available():
        raise ValueError(
            "huggingface_hub is not installed in this environment. Run the "
            "accelerator setup (setup … real) or `pip install huggingface_hub`."
        )
    from huggingface_hub import HfApi  # noqa: PLC0415
    from huggingface_hub.utils import HfHubHTTPError  # noqa: PLC0415

    try:
        info = HfApi().model_info(repo, files_metadata=True)
    except HfHubHTTPError as exc:
        raise ValueError(f"Could not read '{repo}': {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any hub failure becomes a clean message
        raise ValueError(f"Could not read '{repo}': {type(exc).__name__}: {exc}") from exc

    files: list[dict[str, Any]] = []
    for sibling in getattr(info, "siblings", None) or []:
        name = getattr(sibling, "rfilename", None)
        if not name:
            continue
        files.append({"path": name, "size_bytes": int(getattr(sibling, "size", None) or 0)})
    files.sort(key=lambda f: f["path"].lower())
    return files


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _license_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("license:"):
            return tag.split(":", 1)[1] or None
    return None


def _weight_formats(paths: list[str]) -> list[str]:
    formats: set[str] = set()
    for path in paths:
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix and _WEIGHT_RE.search(path):
            formats.add(suffix)
    return sorted(formats)


def _infer_kind(repo_id: str, pipeline_tag: str | None, tags: list[str], paths: list[str]) -> str | None:
    haystack = " ".join([repo_id, pipeline_tag or "", *tags, *paths]).lower()
    tagset = {tag.lower() for tag in tags}
    if "rvc" in haystack or "voice-conversion" in haystack:
        return "voice"
    if "automatic-speech-recognition" in tagset or pipeline_tag == "automatic-speech-recognition":
        return "transcribe"
    if "text-to-speech" in tagset or pipeline_tag == "text-to-speech":
        return "tts"
    if "sentence-transformers" in tagset or pipeline_tag == "feature-extraction":
        return "embed"
    if "lora" in tagset or "adapter" in tagset or "peft" in tagset or "lora" in haystack:
        return "lora"
    if "gguf" in tagset or any(path.lower().endswith(".gguf") for path in paths):
        return "llm"
    if pipeline_tag in {"text-to-image", "image-to-image", "image-to-video"} or "diffusers" in tagset:
        return "image"
    if pipeline_tag in {"image-text-to-text", "visual-question-answering"}:
        return "vision"
    return None


def hf_search_models(
    query: str,
    *,
    limit: int = 24,
    sort: str = "downloads",
    filter_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Search Hugging Face model repos for the in-app catalog browser."""
    query = (query or "").strip()
    try:
        limit = max(1, min(int(limit), _HF_SEARCH_LIMIT_MAX))
    except (TypeError, ValueError):
        limit = 24
    sort_key = _HF_SORTS.get((sort or "").strip().lower(), "downloads")
    filters = [tag.strip() for tag in (filter_tags or []) if tag.strip()]
    if not _hub_available():
        raise ValueError(
            "huggingface_hub is not installed in this environment. Run the "
            "accelerator setup (setup ... real) or `pip install huggingface_hub`."
        )

    from huggingface_hub import HfApi  # noqa: PLC0415
    from huggingface_hub.utils import HfHubHTTPError  # noqa: PLC0415

    try:
        models = list(
            HfApi().list_models(
                search=query or None,
                filter=filters or None,
                sort=sort_key,
                direction=-1,
                limit=limit,
                full=True,
            )
        )
    except HfHubHTTPError as exc:
        raise ValueError(f"Could not search Hugging Face: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any hub failure becomes a clean message
        raise ValueError(f"Could not search Hugging Face: {type(exc).__name__}: {exc}") from exc

    results: list[dict[str, Any]] = []
    for model in models:
        repo_id = str(getattr(model, "modelId", None) or getattr(model, "id", "") or "")
        if not repo_id:
            continue
        tags = [str(tag) for tag in (getattr(model, "tags", None) or []) if tag]
        siblings = getattr(model, "siblings", None) or []
        paths = [str(getattr(sibling, "rfilename", "")) for sibling in siblings if getattr(sibling, "rfilename", "")]
        formats = _weight_formats(paths)
        pipeline_tag = getattr(model, "pipeline_tag", None)
        results.append(
            {
                "id": repo_id,
                "author": getattr(model, "author", None),
                "sha": getattr(model, "sha", None),
                "downloads": int(getattr(model, "downloads", None) or 0),
                "likes": int(getattr(model, "likes", None) or 0),
                "last_modified": _iso(getattr(model, "last_modified", None) or getattr(model, "lastModified", None)),
                "created_at": _iso(getattr(model, "created_at", None)),
                "pipeline_tag": pipeline_tag,
                "library_name": getattr(model, "library_name", None),
                "tags": tags[:30],
                "license": _license_from_tags(tags),
                "gated": bool(getattr(model, "gated", False)),
                "private": bool(getattr(model, "private", False)),
                "weight_count": sum(1 for path in paths if _WEIGHT_RE.search(path)),
                "file_count": len(paths),
                "weight_formats": formats,
                "suggested_kind": _infer_kind(repo_id, pipeline_tag, tags, paths),
                "url": f"https://huggingface.co/{repo_id}",
            }
        )
    return {"query": query, "sort": sort, "limit": limit, "filters": filters, "results": results}


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
                "subdir": _safe_subdir(raw.get("subdir")),
                "label": str(raw.get("label") or f"{repo}/{filename}"),
            })
        elif source == "hf-repo":
            repo = str(raw.get("repo") or "").strip()
            if not repo:
                return [], "A whole-repo download needs a repo id."
            subdir = _safe_subdir(raw.get("subdir")) or repo.split("/")[-1]
            clean.append({
                "source": "hf-repo", "kind": kind, "repo": repo, "subdir": subdir,
                "filename": f"{subdir}/", "label": str(raw.get("label") or repo),
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
    if any(spec["source"] in ("hf", "hf-repo") for spec in clean) and not _hub_available():
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
            else:
                kind_dir.mkdir(parents=True, exist_ok=True)
                _download_url(spec["url"], kind_dir / spec["filename"])
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
