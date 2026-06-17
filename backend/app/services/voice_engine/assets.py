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

# Canonical upstream sources for the shared RVC pretrain assets so the in-app
# "Download voice assets" action, scripts/fetch_voice_assets.py, and the docs all
# agree on one place. These weights keep their upstream licenses (RVC-Project, MIT).
# content_vec is required by every conversion; rmvpe is the quality F0 path (FCPE,
# the default detector, bundles its own weights, so rmvpe matters for the RMVPE
# presets). Each lands in models/voice/pretrain/ via the custom-download path
# (kind=voice, subdir=pretrain).
ASSET_SOURCES: dict[str, dict[str, str]] = {
    "content_vec": {
        "filename": "content_vec_500.onnx",
        "url": "https://huggingface.co/NaruseMioShirakana/MoeSS-SUBModel/resolve/main/contentvec/content_vec_500.onnx",
        "approx_mb": "190",
    },
    "rmvpe": {
        "filename": "rmvpe.pt",
        "url": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt",
        "approx_mb": "181",
    },
}


def missing_required_names() -> list[str]:
    """Names of required assets not present on disk (what to fetch)."""
    return [a["name"] for a in discover_assets()["assets"] if not a["found"] and not a.get("optional")]


def fetch_specs(names: list[str] | None = None) -> list[dict[str, str]]:
    """Custom-download specs (for ``model_download_service.start_custom``) that place
    the shared RVC assets into ``models/voice/pretrain``. Defaults to the missing
    required ones; assets without a known source are skipped."""
    wanted = names if names is not None else missing_required_names()
    specs: list[dict[str, str]] = []
    for name in wanted:
        src = ASSET_SOURCES.get(name)
        if not src:
            continue
        specs.append({
            "source": "url",
            "kind": "voice",
            "subdir": "pretrain",
            "url": src["url"],
            "filename": src["filename"],
            "label": f"voice asset · {src['filename']}",
        })
    return specs


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
