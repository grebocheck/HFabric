"""Installed-model inventory and safe deletion for the Model Manager.

Walks every model kind's folder and reports the deletable units the user sees on
disk (a single weight file, or a multi-file repo folder) with sizes, so the UI can
show what's installed and reclaim space. Deletion is path-validated to stay inside
the known model folders and refuses anything currently resident/warm on the GPU.

This is deliberately decoupled from the job-specific ``ModelRegistry`` classifier:
the manager shows *files on disk* per folder (including kinds the registry doesn't
scan, like TTS / transcribe / embed / voice), not runnable descriptors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
import time
from typing import Any
import uuid

from ..config import settings

# File extensions that count as a model weight at the top level of a kind folder.
# Directories are always listed (a multi-file repo); sidecars (.json/.txt/…) are not.
_WEIGHT_EXTS = {".safetensors", ".gguf", ".pt", ".pth", ".bin", ".ckpt", ".onnx"}

# Subfolders that are shared infrastructure, not user-deletable models.
_SKIP_DIRS = {"pretrain"}
_DELETE_LOCK = threading.RLock()
_RESERVED_PATHS: set[Path] = set()
_SIZE_CACHE_LOCK = threading.RLock()
_SIZE_CACHE_TTL_SECONDS = 30.0
_SIZE_CACHE_MAX_ENTRIES = 512
_SIZE_CACHE: dict[Path, tuple[tuple[int, int], float, int]] = {}
_INVENTORY_SCAN_SLOTS = threading.BoundedSemaphore(2)

BusyPaths = Iterable[Path] | Callable[[], Iterable[Path]]


class ModelInUseError(Exception):
    """Raised when a delete targets a model that is currently resident/warm on GPU."""


class ModelDeleteError(Exception):
    """Raised when the OS cannot complete or safely roll back a deletion."""


class ModelInventoryError(ModelDeleteError):
    """Deletion completed, but the in-memory registry could not be refreshed."""


def _kind_dirs() -> dict[str, Path]:
    """kind -> folder, resolved at call time (settings is monkeypatched in tests)."""
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
    }


KIND_LABELS: dict[str, str] = {
    "image": "Image",
    "video": "Video",
    "llm": "LLM (chat)",
    "lora": "LoRA",
    "tts": "Text-to-speech",
    "transcribe": "Transcription",
    "embed": "Embeddings (RAG)",
    "vision": "Vision (multimodal)",
    "voice": "Voice changer",
}


def _dir_size(path: Path) -> int:
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_ctime_ns)
        cache_key = path.resolve(strict=False)
    except OSError:
        return 0
    now = time.monotonic()
    with _SIZE_CACHE_LOCK:
        cached = _SIZE_CACHE.get(cache_key)
        if (
            cached is not None
            and cached[0] == signature
            and now - cached[1] <= _SIZE_CACHE_TTL_SECONDS
        ):
            return cached[2]

    total = 0
    for dirpath, _, filenames in os.walk(path):
        directory = Path(dirpath)
        for filename in filenames:
            try:
                total += (directory / filename).stat().st_size
            except OSError:
                continue
    try:
        final_stat = path.stat()
        final_signature = (final_stat.st_mtime_ns, final_stat.st_ctime_ns)
    except OSError:
        return total
    if final_signature == signature:
        with _SIZE_CACHE_LOCK:
            if len(_SIZE_CACHE) >= _SIZE_CACHE_MAX_ENTRIES:
                oldest = min(_SIZE_CACHE, key=lambda key: _SIZE_CACHE[key][1])
                _SIZE_CACHE.pop(oldest, None)
            _SIZE_CACHE[cache_key] = (signature, now, total)
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
    in_use_resolved = _resolve_paths(in_use or set())
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
                    "in_use": any(
                        paths_overlap(child, busy)
                        for busy in in_use_resolved
                    ),
                }
            )
    return items


async def installed_async(
    in_use: set[Path] | None = None,
) -> list[dict[str, Any]]:
    """Build the recursive inventory without occupying the application loop."""
    return await asyncio.to_thread(_installed_bounded, in_use)


def _installed_bounded(in_use: set[Path] | None) -> list[dict[str, Any]]:
    # Keep cancellation/repeated refreshes from filling the filesystem with
    # dozens of simultaneous recursive walks.
    with _INVENTORY_SCAN_SLOTS:
        return installed(in_use)


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

    normalized = PurePosixPath(rel_path.strip().replace("\\", "/"))
    if (
        normalized.is_absolute()
        or len(normalized.parts) != 1
        or normalized.parts[0] in {"", ".", ".."}
    ):
        raise ValueError("model path must identify one top-level installed item")

    root = directory.resolve()
    candidate = directory / normalized.parts[0]
    if candidate.is_symlink() or _is_junction(candidate):
        raise ValueError("refusing to delete a symlink or junction model entry")
    target = candidate.resolve(strict=False)
    if target == root:
        raise ValueError("refusing to delete a whole model folder")
    if not target.is_relative_to(root):
        raise ValueError("path is outside the model folder")
    return target


def paths_overlap(left: Path, right: Path) -> bool:
    """True for same, ancestor, or descendant paths (case-normalized by resolve)."""
    try:
        a = left.resolve(strict=False)
        b = right.resolve(strict=False)
    except OSError:
        a = left.absolute()
        b = right.absolute()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def reserved_paths() -> set[Path]:
    """Public snapshot for loaders/downloaders that choose to honor reservations."""
    with _DELETE_LOCK:
        return set(_RESERVED_PATHS)


def _resolve_paths(paths: Iterable[Path]) -> set[Path]:
    resolved: set[Path] = set()
    for path in paths:
        try:
            resolved.add(Path(path).resolve(strict=False))
        except OSError:
            resolved.add(Path(path).absolute())
    return resolved


def _busy_snapshot(in_use: BusyPaths | None) -> set[Path]:
    if in_use is None:
        return set()
    paths = in_use() if callable(in_use) else in_use
    return _resolve_paths(paths)


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except OSError:
        return True


def _remove_staged(staged: Path) -> None:
    if staged.is_dir():
        shutil.rmtree(staged)
    else:
        staged.unlink()


def _invalidate_size_cache(path: Path) -> None:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    with _SIZE_CACHE_LOCK:
        for cached_path in tuple(_SIZE_CACHE):
            if paths_overlap(cached_path, resolved):
                _SIZE_CACHE.pop(cached_path, None)


def delete(
    kind: str,
    rel_path: str,
    *,
    in_use: BusyPaths | None = None,
    after_delete: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Delete one installed model unit (file or repo folder); return freed bytes.

    Refuses an in-use (resident/warm) target — a model file can't be safely removed
    while it's memory-mapped on the GPU; the caller should free the GPU first."""
    with _DELETE_LOCK:
        # Reserve under one lock so two API calls cannot both pass validation
        # for overlapping targets. Slow removal runs without blocking readers.
        target = _validate_target(kind, rel_path)
        if any(paths_overlap(target, reserved) for reserved in _RESERVED_PATHS):
            raise ModelInUseError(f"{rel_path} is already reserved")
        if not target.exists():
            raise FileNotFoundError(rel_path)

        busy = _busy_snapshot(in_use)
        if any(paths_overlap(target, path) for path in busy):
            raise ModelInUseError(rel_path)

        _RESERVED_PATHS.add(target)

    try:
        # A same-directory rename is atomic and exposes Windows mmap/handle
        # conflicts before recursive deletion starts.
        staged = target.with_name(
            f".{target.name}.deleting-{uuid.uuid4().hex}"
        )
        freed = _entry_size(target)
        try:
            os.replace(target, staged)
        except OSError as exc:
            raise ModelDeleteError(
                f"could not reserve '{target.name}' for deletion; "
                f"the model may be locked by another process: {exc}"
            ) from exc

        try:
            _remove_staged(staged)
        except OSError as exc:
            rollback_error: OSError | None = None
            restored = target.exists()
            if staged.exists():
                try:
                    os.replace(staged, target)
                    restored = True
                except OSError as rollback_exc:
                    rollback_error = rollback_exc
            if rollback_error is not None:
                detail = f"; rollback also failed: {rollback_error}"
            elif restored:
                detail = "; the remaining visible model path was restored"
            else:
                detail = "; deletion state is uncertain; run a model rescan"
            raise ModelDeleteError(
                f"could not delete '{target.name}': {exc}{detail}"
            ) from exc

        _invalidate_size_cache(target)
        if after_delete is not None:
            try:
                after_delete()
            except Exception as exc:
                raise ModelInventoryError(
                    f"'{target.name}' was deleted, but the model inventory refresh "
                    f"failed; run Rescan Models: {exc}"
                ) from exc
        return {
            "deleted": f"{kind}/{rel_path}",
            "freed_bytes": freed,
        }
    finally:
        with _DELETE_LOCK:
            _RESERVED_PATHS.discard(target)


async def delete_async(
    kind: str,
    rel_path: str,
    *,
    in_use: BusyPaths | None = None,
    after_delete: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Reserve and delete a model in the filesystem worker pool."""
    return await asyncio.to_thread(
        delete,
        kind,
        rel_path,
        in_use=in_use,
        after_delete=after_delete,
    )
