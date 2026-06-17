"""Installed-model inventory + safe deletion for the Model Manager (P25.2).

Walks every model kind's folder and reports the deletable units the user sees on
disk (a single weight file, or a multi-file repo folder) with sizes, so the UI can
show what's installed and reclaim space. Deletion is path-validated to stay inside
the known model folders and refuses anything currently resident/warm on the GPU.

This is deliberately decoupled from the job-specific ``ModelRegistry`` classifier:
the manager shows *files on disk* per folder (including kinds the registry doesn't
scan, like TTS / transcribe / embed / voice), not runnable descriptors.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from ..config import settings

# File extensions that count as a model weight at the top level of a kind folder.
# Directories are always listed (a multi-file repo); sidecars (.json/.txt/…) are not.
_WEIGHT_EXTS = {".safetensors", ".gguf", ".pt", ".pth", ".bin", ".ckpt", ".onnx"}

# Subfolders that are shared infrastructure, not user-deletable models.
_SKIP_DIRS = {"pretrain"}


class ModelInUseError(Exception):
    """Raised when a delete targets a model that is currently resident/warm on GPU."""


def _kind_dirs() -> dict[str, Path]:
    """kind -> folder, resolved at call time (settings is monkeypatched in tests)."""
    return {
        "image": settings.image_models_dir,
        "llm": settings.llm_models_dir,
        "lora": settings.lora_models_dir,
        "tts": settings.tts_models_dir,
        "transcribe": settings.transcription_models_dir,
        "embed": settings.embed_models_dir,
        "vision": settings.vision_models_dir,
        "voice": settings.voice_models_dir,
    }


KIND_LABELS: dict[str, str] = {
    "image": "Image",
    "llm": "LLM (chat)",
    "lora": "LoRA",
    "tts": "Text-to-speech",
    "transcribe": "Transcription",
    "embed": "Embeddings (RAG)",
    "vision": "Vision (multimodal)",
    "voice": "Voice changer",
}


def _dir_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _entry_size(path: Path) -> int:
    if path.is_dir():
        return _dir_size(path)
    try:
        return path.stat().st_size
    except OSError:
        return 0


def installed(in_use: set[Path] | None = None) -> list[dict[str, Any]]:
    """Every deletable model unit across all kinds, annotated with size + in-use.

    An item's ``path`` is relative to its kind folder (location-independent: the
    kind folders are env-overridable and can live anywhere), and ``kind`` + ``path``
    together are the delete key."""
    in_use_resolved = {p.resolve() for p in (in_use or set())}
    items: list[dict[str, Any]] = []
    for kind, directory in _kind_dirs().items():
        if not directory.exists():
            continue
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or child.name in _SKIP_DIRS:
                continue
            is_dir = child.is_dir()
            if not is_dir and child.suffix.lower() not in _WEIGHT_EXTS:
                continue
            items.append(
                {
                    "kind": kind,
                    "kind_label": KIND_LABELS.get(kind, kind),
                    "name": child.stem if not is_dir else child.name,
                    "path": child.name,
                    "size_bytes": _entry_size(child),
                    "is_dir": is_dir,
                    "in_use": child.resolve() in in_use_resolved,
                }
            )
    return items


def total_used_bytes() -> int:
    return sum(item["size_bytes"] for item in installed())


def _validate_target(kind: str, rel_path: str) -> Path:
    """Resolve a (kind, kind-relative path) to a deletable model unit.

    Guards against traversal and against deleting a kind folder itself: the target
    must live *inside* that kind's folder (but not be the folder)."""
    directory = _kind_dirs().get(kind)
    if directory is None:
        raise ValueError(f"unknown model type: {kind or '(none)'}")
    if not rel_path or rel_path.strip() in {"", ".", "/", "\\"}:
        raise ValueError("a model path is required")
    root = directory.resolve()
    target = (directory / rel_path).resolve()
    if target == root:
        raise ValueError("refusing to delete a whole model folder")
    if not target.is_relative_to(root):
        raise ValueError("path is outside the model folder")
    return target


def delete(kind: str, rel_path: str, *, in_use: set[Path] | None = None) -> dict[str, Any]:
    """Delete one installed model unit (file or repo folder); return freed bytes.

    Refuses an in-use (resident/warm) target — a model file can't be safely removed
    while it's memory-mapped on the GPU; the caller should free the GPU first."""
    target = _validate_target(kind, rel_path)
    if not target.exists():
        raise FileNotFoundError(rel_path)
    if in_use and target.resolve() in {p.resolve() for p in in_use}:
        raise ModelInUseError(rel_path)
    freed = _entry_size(target)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": f"{kind}/{rel_path}", "freed_bytes": freed}
