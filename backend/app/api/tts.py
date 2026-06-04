"""TTS workspace readiness.

Generation is intentionally not exposed until a local TTS GGUF exists under
models/tts. This keeps the workspace honest and avoids hidden downloads.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import settings

router = APIRouter(prefix="/api/tts", tags=["tts"])


def _models() -> list[dict]:
    root = settings.tts_models_dir
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob("*.gguf")):
        out.append({
            "id": path.stem.lower().replace(" ", "-"),
            "name": path.stem,
            "path": str(path),
            "size_bytes": path.stat().st_size,
        })
    return out


@router.get("/status")
async def tts_status() -> dict:
    models = _models()
    return {
        "binary": str(settings.llama_tts_bin),
        "binary_exists": settings.llama_tts_bin.exists(),
        "models_dir": str(settings.tts_models_dir),
        "models": models,
        "ready": settings.llama_tts_bin.exists() and bool(models),
    }
