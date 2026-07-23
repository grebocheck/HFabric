"""Destination policy and normalization for user-supplied model downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import settings

CUSTOM_KINDS = (
    "image",
    "video",
    "llm",
    "lora",
    "tts",
    "transcribe",
    "embed",
    "vision",
    "voice",
)


def kind_dir(kind: str) -> Path | None:
    return {
        "image": settings.image_models_dir,
        "video": settings.video_models_dir,
        "llm": settings.llm_models_dir,
        "lora": settings.lora_models_dir,
        "tts": settings.tts_models_dir,
        "transcribe": settings.transcription_models_dir,
        "embed": settings.embed_models_dir,
        "vision": settings.vision_models_dir,
        "voice": settings.voice_models_dir,
    }.get(kind)


def safe_subdir(raw: Any) -> str:
    """Return a traversal-safe relative subfolder from user input."""
    parts = [
        part for part in str(raw or "").replace("\\", "/").split("/") if part and part not in (".", "..")
    ]
    return "/".join(parts)


def validate_custom(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize user-supplied download specs."""
    if not items:
        return [], "No models to download were provided."
    clean: list[dict[str, Any]] = []
    for raw in items:
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in CUSTOM_KINDS:
            return [], f"Unknown model type: {kind or '(none)'}."
        source = str(raw.get("source") or "").strip().lower()
        if source == "hf":
            repo = str(raw.get("repo") or "").strip()
            filename = str(raw.get("filename") or "").strip()
            if not repo or not filename:
                return (
                    [],
                    "A HuggingFace download needs both a repo id and a file name.",
                )
            if ".." in filename.replace("\\", "/").split("/"):
                return [], "Invalid file name."
            clean.append(
                {
                    "source": "hf",
                    "kind": kind,
                    "repo": repo,
                    "filename": filename,
                    "subdir": safe_subdir(raw.get("subdir")),
                    "label": str(raw.get("label") or f"{repo}/{filename}"),
                }
            )
        elif source == "hf-repo":
            repo = str(raw.get("repo") or "").strip()
            if not repo:
                return [], "A whole-repo download needs a repo id."
            subdir = safe_subdir(raw.get("subdir")) or repo.split("/")[-1]
            clean.append(
                {
                    "source": "hf-repo",
                    "kind": kind,
                    "repo": repo,
                    "subdir": subdir,
                    "filename": f"{subdir}/",
                    "label": str(raw.get("label") or repo),
                }
            )
        elif source == "url":
            url = str(raw.get("url") or "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                return [], "A direct download needs an http(s) URL."
            given = str(raw.get("filename") or "").strip()
            filename = Path(given).name if given else Path(url.split("?")[0]).name
            if not filename:
                return (
                    [],
                    "Could not determine a file name from the URL; provide one.",
                )
            clean.append(
                {
                    "source": "url",
                    "kind": kind,
                    "url": url,
                    "filename": filename,
                    "label": str(raw.get("label") or filename),
                }
            )
        elif source == "civitai":
            url = str(raw.get("url") or "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                return (
                    [],
                    "A CivitAI download needs the file's download URL.",
                )
            given = str(raw.get("filename") or "").strip()
            filename = Path(given).name if given else Path(url.split("?")[0]).name
            if not filename:
                return [], "A CivitAI download needs a file name."
            sha256 = str(raw.get("sha256") or "").strip().lower() or None
            clean.append(
                {
                    "source": "civitai",
                    "kind": kind,
                    "url": url,
                    "filename": filename,
                    "sha256": sha256,
                    "label": str(raw.get("label") or filename),
                }
            )
        else:
            return [], f"Unknown source: {source or '(none)'}."
    return clean, None
