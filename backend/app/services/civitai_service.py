"""CivitAI browse service for the in-app model browser.

Read-only: search models and list a version's files so the unified Models tab can
show CivitAI alongside Hugging Face. The actual file download reuses the custom
download pipeline in ``model_download_service`` (source ``"civitai"``), so status,
progress, disk-budget and registry rescan are shared with every other source.

Domain split (effective 2026-04-15): ``civitai.com`` shows SFW only while
``civitai.red`` also shows NSFW. The same account/database backs both — only
visibility differs — so we pick the host + ``nsfw`` flag from the caller's toggle.
Models that moved to Red are not visible through the ``.com`` host, hence the
host switch rather than the ``nsfw`` query param alone.
"""

from __future__ import annotations

from typing import Any

# civitai.com = SFW front door, civitai.red = SFW + NSFW (see module docstring).
HOST_SFW = "https://civitai.com"
HOST_NSFW = "https://civitai.red"

_TIMEOUT = 30.0
_SEARCH_LIMIT_MAX = 50

# CivitAI ``type`` -> our models/<kind>/ folder. Only the unambiguous ones are
# mapped; anything else returns None and the UI lets the user pick the folder
# (mirrors the Hugging Face browser's suggested-kind behaviour).
_TYPE_TO_KIND: dict[str, str] = {
    "Checkpoint": "image",
    "LORA": "lora",
    "LoCon": "lora",
    "DoRA": "lora",
    "LyCORIS": "lora",
}

# CivitAI sort labels accepted by the public API, keyed by our short UI value.
_SORTS = {
    "downloads": "Most Downloaded",
    "rated": "Highest Rated",
    "newest": "Newest",
}
_PERIODS = {"AllTime", "Year", "Month", "Week", "Day"}


def _host(nsfw: bool) -> str:
    return HOST_NSFW if nsfw else HOST_SFW


def infer_kind(model_type: str | None) -> str | None:
    return _TYPE_TO_KIND.get((model_type or "").strip())


def _client(nsfw: bool, headers: dict[str, str] | None = None):
    import httpx  # noqa: PLC0415

    return httpx.Client(
        base_url=f"{_host(nsfw)}/api/v1",
        headers={"User-Agent": "ImageFabric/CivitAI-Browser", **(headers or {})},
        timeout=_TIMEOUT,
    )


def _err(prefix: str, exc: Exception) -> ValueError:
    from httpx import HTTPStatusError  # noqa: PLC0415

    if isinstance(exc, HTTPStatusError):
        return ValueError(f"{prefix}: {exc.response.status_code} {exc.response.reason_phrase}")
    return ValueError(f"{prefix}: {type(exc).__name__}: {exc}")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_preview(version: dict[str, Any]) -> dict[str, Any] | None:
    for image in version.get("images") or []:
        url = image.get("url")
        if url:
            return {
                "url": url,
                "nsfw_level": image.get("nsfwLevel"),
                "width": image.get("width"),
                "height": image.get("height"),
                "type": image.get("type", "image"),
            }
    return None


def _normalize_model(item: dict[str, Any], nsfw: bool) -> dict[str, Any]:
    versions = item.get("modelVersions") or []
    first = versions[0] if versions else {}
    stats = item.get("stats") or {}
    creator = item.get("creator") or {}
    model_type = item.get("type")
    return {
        "id": _int(item.get("id")),
        "name": str(item.get("name") or ""),
        "type": model_type,
        "nsfw": bool(item.get("nsfw")),
        "creator": creator.get("username"),
        "downloads": _int(stats.get("downloadCount")),
        "likes": _int(stats.get("thumbsUpCount") or stats.get("favoriteCount")),
        "base_model": first.get("baseModel"),
        "tags": [str(t) for t in (item.get("tags") or [])][:20],
        "preview": _first_preview(first),
        "suggested_kind": infer_kind(model_type),
        "version_count": len(versions),
        "versions": [
            {
                "id": _int(v.get("id")),
                "name": str(v.get("name") or ""),
                "base_model": v.get("baseModel"),
            }
            for v in versions
        ],
        "url": f"{_host(nsfw)}/models/{_int(item.get('id'))}",
    }


def search_models(
    query: str,
    *,
    types: list[str] | None = None,
    sort: str = "downloads",
    period: str = "AllTime",
    base_models: list[str] | None = None,
    nsfw: bool = False,
    limit: int = 24,
    page: int = 1,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Search CivitAI models for the in-app browser. Raises ValueError on failure."""
    query = (query or "").strip()
    try:
        limit = max(1, min(int(limit), _SEARCH_LIMIT_MAX))
    except (TypeError, ValueError):
        limit = 24
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    sort_label = _SORTS.get((sort or "").strip().lower(), _SORTS["downloads"])
    period_label = period if period in _PERIODS else "AllTime"

    params: dict[str, Any] = {
        "limit": limit,
        "page": page,
        "sort": sort_label,
        "period": period_label,
        "nsfw": "true" if nsfw else "false",
    }
    if query:
        params["query"] = query
    if types:
        params["types"] = [t for t in types if t]
    if base_models:
        params["baseModels"] = [b for b in base_models if b]

    try:
        with _client(nsfw, headers) as client:
            response = client.get("/models", params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - any failure becomes a clean message
        raise _err("Could not search CivitAI", exc) from exc

    items = payload.get("items") or []
    meta = payload.get("metadata") or {}
    return {
        "query": query,
        "sort": sort,
        "nsfw": nsfw,
        "limit": limit,
        "page": page,
        "total_pages": _int(meta.get("totalPages")) or None,
        "next_page": _int(meta.get("nextPage")) or None,
        "results": [_normalize_model(item, nsfw) for item in items],
    }


def version_files(
    version_id: int, *, nsfw: bool = False, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """List a model version's downloadable files + trigger words. Raises ValueError."""
    try:
        vid = int(version_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("A numeric model-version id is required.") from exc

    try:
        with _client(nsfw, headers) as client:
            response = client.get(f"/model-versions/{vid}")
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        raise _err(f"Could not read CivitAI version {vid}", exc) from exc

    model = data.get("model") or {}
    model_type = model.get("type")
    files: list[dict[str, Any]] = []
    for f in data.get("files") or []:
        meta = f.get("metadata") or {}
        hashes = f.get("hashes") or {}
        files.append(
            {
                "id": _int(f.get("id")),
                "name": str(f.get("name") or ""),
                "size_kb": float(f.get("sizeKB") or 0.0),
                "type": f.get("type"),
                "format": meta.get("format"),
                "fp": meta.get("fp"),
                "size": meta.get("size"),
                "primary": bool(f.get("primary")),
                "download_url": f.get("downloadUrl"),
                "sha256": (hashes.get("SHA256") or "").lower() or None,
            }
        )
    files.sort(key=lambda f: (not f["primary"], f["name"].lower()))
    return {
        "version_id": vid,
        "name": str(data.get("name") or ""),
        "model_id": _int(model.get("id")) or _int(data.get("modelId")),
        "model_name": model.get("name"),
        "model_type": model_type,
        "base_model": data.get("baseModel"),
        "trained_words": [str(w) for w in (data.get("trainedWords") or [])],
        "suggested_kind": infer_kind(model_type),
        "files": files,
    }
