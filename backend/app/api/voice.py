"""Local voice-changer workspace (P6, RVC w-okada-style).

P6.1 is the model-gated *shell*: it scans ``models/voice`` for RVC voice models
(a ``.pth`` weight, optionally paired with a same-stem ``.index`` retrieval file)
and reports whether the inference dependencies are importable. The actual RVC
conversion engine is wired in a later step; until then ``/convert`` returns a
clear 503 instead of pretending to work. Like the TTS/Vision tabs it is
CPU-first by default so an offline conversion does not bypass the GPU arbiter.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings

router = APIRouter(prefix="/api/voice", tags=["voice"])

ALLOWED_EXTS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}

# Candidate modules an RVC inference stack needs. We don't pin a single package
# name yet (the engine is wired in P6.2); presence of torch + one RVC-style
# module is what flips the tab from "shell" to "ready".
_RVC_MODULES = ("rvc", "infer", "fairseq")


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _id(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or uuid.uuid4().hex


def _models() -> list[dict[str, Any]]:
    root = settings.voice_models_dir
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.pth")):
        if not path.is_file():
            continue
        index = path.with_suffix(".index")
        out.append({
            "id": _id(path),
            "name": path.stem,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "has_index": index.exists(),
            "index_path": str(index) if index.exists() else None,
        })
    return out


def _engine() -> dict[str, bool]:
    return {
        "torch": _has("torch"),
        "rvc": any(_has(m) for m in _RVC_MODULES),
    }


def _engine_ready(engine: dict[str, bool]) -> bool:
    return engine["torch"] and engine["rvc"]


@router.get("/status")
async def voice_status() -> dict:
    engine = _engine()
    models = _models()
    return {
        "engine": "rvc",
        "models_dir": str(settings.voice_models_dir),
        "models": models,
        "deps": engine,
        "device": settings.voice_device,
        "max_upload_mb": settings.voice_max_upload_mb,
        # ready = an inference stack is importable AND at least one voice exists.
        "ready": _engine_ready(engine) and bool(models),
        "realtime": False,  # P6.2
    }


@router.post("/convert")
async def voice_convert(
    file: UploadFile = File(...),  # noqa: ARG001 - accepted now, used once the engine is wired
    model_id: str = Form(...),
    pitch: int = Form(0),  # noqa: ARG001
) -> dict:
    """Offline file -> file conversion. Gated until the RVC engine is wired."""
    model = next((m for m in _models() if m["id"] == model_id), None)
    if not model:
        raise HTTPException(404, "voice model not found")
    if not _engine_ready(_engine()):
        raise HTTPException(
            503,
            "RVC inference engine is not installed yet (P6.2). Drop an RVC .pth "
            "(+ .index) into models/voice and install the engine to enable conversion.",
        )
    # The real conversion is wired in P6.2; refuse rather than fake a result.
    raise HTTPException(501, "voice conversion is not implemented yet (P6.2)")
