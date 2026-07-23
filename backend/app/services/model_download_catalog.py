"""Hugging Face repository browsing and normalized search results."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

HF_SEARCH_LIMIT_MAX = 50
HF_SORTS = {
    "downloads": "downloads",
    "likes": "likes",
    "updated": "last_modified",
    "trending": "trending_score",
    "created": "created_at",
}
WEIGHT_RE = re.compile(
    r"\.(safetensors|gguf|pt|pth|bin|ckpt|onnx)$",
    re.IGNORECASE,
)


def hf_list_files(
    repo: str,
    *,
    hub_available: bool,
) -> list[dict[str, Any]]:
    """List model-repository files with sizes."""
    repo = (repo or "").strip()
    if not repo:
        raise ValueError("Enter a HuggingFace repo id, e.g. owner/model.")
    _require_hub(hub_available)

    from huggingface_hub import HfApi  # noqa: PLC0415
    from huggingface_hub.utils import (  # noqa: PLC0415
        HfHubHTTPError,
    )

    try:
        info = HfApi().model_info(repo, files_metadata=True)
    except HfHubHTTPError as exc:
        raise ValueError(f"Could not read '{repo}': {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not read '{repo}': {type(exc).__name__}: {exc}") from exc

    files: list[dict[str, Any]] = []
    for sibling in getattr(info, "siblings", None) or []:
        name = getattr(sibling, "rfilename", None)
        if not name:
            continue
        files.append(
            {
                "path": name,
                "size_bytes": int(getattr(sibling, "size", None) or 0),
            }
        )
    files.sort(key=lambda item: item["path"].lower())
    return files


def hf_search_models(
    query: str,
    *,
    limit: int = 24,
    sort: str = "downloads",
    filter_tags: list[str] | None = None,
    hub_available: bool,
) -> dict[str, Any]:
    """Search and normalize Hugging Face model repositories."""
    query = (query or "").strip()
    try:
        limit = max(1, min(int(limit), HF_SEARCH_LIMIT_MAX))
    except (TypeError, ValueError):
        limit = 24
    sort_key = HF_SORTS.get(
        (sort or "").strip().lower(),
        "downloads",
    )
    filters = [tag.strip() for tag in (filter_tags or []) if tag.strip()]
    _require_hub(hub_available)

    from huggingface_hub import HfApi  # noqa: PLC0415
    from huggingface_hub.utils import (  # noqa: PLC0415
        HfHubHTTPError,
    )

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
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not search Hugging Face: {type(exc).__name__}: {exc}") from exc

    results: list[dict[str, Any]] = []
    for model in models:
        repo_id = str(getattr(model, "modelId", None) or getattr(model, "id", "") or "")
        if not repo_id:
            continue
        tags = [str(tag) for tag in (getattr(model, "tags", None) or []) if tag]
        siblings = getattr(model, "siblings", None) or []
        paths = [
            str(getattr(sibling, "rfilename", ""))
            for sibling in siblings
            if getattr(sibling, "rfilename", "")
        ]
        formats = _weight_formats(paths)
        pipeline_tag = getattr(model, "pipeline_tag", None)
        results.append(
            {
                "id": repo_id,
                "author": getattr(model, "author", None),
                "sha": getattr(model, "sha", None),
                "downloads": int(getattr(model, "downloads", None) or 0),
                "likes": int(getattr(model, "likes", None) or 0),
                "last_modified": _iso(
                    getattr(model, "last_modified", None) or getattr(model, "lastModified", None)
                ),
                "created_at": _iso(getattr(model, "created_at", None)),
                "pipeline_tag": pipeline_tag,
                "library_name": getattr(
                    model,
                    "library_name",
                    None,
                ),
                "tags": tags[:30],
                "license": _license_from_tags(tags),
                "gated": bool(getattr(model, "gated", False)),
                "private": bool(getattr(model, "private", False)),
                "weight_count": sum(1 for path in paths if WEIGHT_RE.search(path)),
                "file_count": len(paths),
                "weight_formats": formats,
                "suggested_kind": _infer_kind(
                    repo_id,
                    pipeline_tag,
                    tags,
                    paths,
                ),
                "url": f"https://huggingface.co/{repo_id}",
            }
        )
    return {
        "query": query,
        "sort": sort,
        "limit": limit,
        "filters": filters,
        "results": results,
    }


def _require_hub(available: bool) -> None:
    if available:
        return
    raise ValueError(
        "huggingface_hub is not installed in this environment. "
        "Run the accelerator setup (setup ... real) or "
        "`pip install huggingface_hub`."
    )


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
        if suffix and WEIGHT_RE.search(path):
            formats.add(suffix)
    return sorted(formats)


def _infer_kind(
    repo_id: str,
    pipeline_tag: str | None,
    tags: list[str],
    paths: list[str],
) -> str | None:
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
    if pipeline_tag in {"text-to-video", "image-to-video"}:
        return "video"
    if pipeline_tag in {"text-to-image", "image-to-image"} or "diffusers" in tagset:
        return "image"
    if pipeline_tag in {
        "image-text-to-text",
        "visual-question-answering",
    }:
        return "vision"
    return None
