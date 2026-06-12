"""Pretrained asset discovery for the native RVC engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import settings


@dataclass(frozen=True)
class RequiredAsset:
    name: str
    filenames: tuple[str, ...]
    subdir: str = ""
    optional: bool = False
    require_all: bool = False


REQUIRED_ASSETS = (
    RequiredAsset("content_vec", ("content_vec_500.onnx", "content_vec_500.fp16.onnx")),
    RequiredAsset("rmvpe", ("rmvpe.pt",)),
)
OPTIONAL_ASSETS = (
    RequiredAsset(
        "denoise_dtln",
        ("dtln_model_1.onnx", "dtln_model_2.onnx"),
        subdir="denoise",
        optional=True,
        require_all=True,
    ),
)


def _candidate_dirs() -> tuple[tuple[str, Path], ...]:
    return (
        ("local", settings.voice_pretrain_dir),
    )


def _find_asset(asset: RequiredAsset) -> dict[str, Any]:
    for source, root in _candidate_dirs():
        base = root / asset.subdir if asset.subdir else root
        paths = [base / filename for filename in asset.filenames]
        if asset.require_all:
            if all(path.is_file() for path in paths):
                return {
                    "name": asset.name,
                    "path": str(base),
                    "found": True,
                    "source": source,
                    "optional": asset.optional,
                    "files": {path.name: str(path) for path in paths},
                }
            continue
        for path in paths:
            if path.is_file():
                return {
                    "name": asset.name,
                    "path": str(path),
                    "found": True,
                    "source": source,
                    "optional": asset.optional,
                }
    return {
        "name": asset.name,
        "path": None,
        "found": False,
        "source": None,
        "optional": asset.optional,
    }


def discover_assets() -> dict[str, Any]:
    """Return required RVC pretrain assets and an overall readiness flag.

    Discovery is pure pathlib work and intentionally does not probe file
    contents.
    """
    required = [_find_asset(asset) for asset in REQUIRED_ASSETS]
    optional = [_find_asset(asset) for asset in OPTIONAL_ASSETS]
    return {
        "ready": all(item["found"] for item in required),
        "assets": [*required, *optional],
    }


def searched_dirs() -> list[str]:
    """Human-readable search roots for precise missing-asset errors."""
    return [str(path) for _, path in _candidate_dirs()]


def denoise_searched_dirs() -> list[str]:
    """Human-readable DTLN search roots for precise missing-asset errors."""
    return [str(path / "denoise") for _, path in _candidate_dirs()]


def dtln_model_paths() -> tuple[Path, Path] | None:
    """Return the two DTLN ONNX paths when the optional pair is complete."""
    found = _find_asset(OPTIONAL_ASSETS[0])
    files = found.get("files")
    if not found["found"] or not isinstance(files, dict):
        return None
    return Path(files["dtln_model_1.onnx"]), Path(files["dtln_model_2.onnx"])
