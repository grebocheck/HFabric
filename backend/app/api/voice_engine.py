"""Native RVC voice engine API (parallel to the w-okada fallback router)."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
import wave

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..services.voice_engine import assets as asset_discovery
from ..services.voice_engine import devices, storage
from ..services.voice_engine.engine import get_engine
from ..util import uploads as uploads_util

router = APIRouter(prefix="/api/voice/engine", tags=["voice-engine"])

ALLOWED_EXTS = {".wav", ".flac", ".ogg"}


class VoiceEngineSettingsUpdate(BaseModel):
    pitch: int | None = None
    index_ratio: float | None = None
    protect: float | None = None
    f0_detector: str | None = None
    server_input_device_id: int | None = None
    server_output_device_id: int | None = None
    server_monitor_device_id: int | None = None
    server_input_gain: float | None = None
    server_output_gain: float | None = None
    server_monitor_gain: float | None = None


def _asset_error() -> str | None:
    if settings.stub_mode:
        return None
    discovered = asset_discovery.discover_assets()
    missing = [item["name"] for item in discovered["assets"] if not item["found"]]
    if not missing:
        return None
    dirs = ", ".join(asset_discovery.searched_dirs())
    return f"missing required voice pretrain asset(s): {', '.join(missing)}; searched {dirs}"


def _status_payload() -> dict[str, Any]:
    engine = get_engine()
    asset_info = engine.assets()
    models = engine.models()
    ready = True if settings.stub_mode else asset_info["ready"] and bool(models)
    return {
        "engine": "native-rvc",
        "stub": settings.stub_mode,
        "ready": ready,
        "assets": asset_info["assets"],
        "models": models,
        "audio_devices": devices.audio_devices(),
        "device": engine.device,
        "settings": engine.settings_payload(),
        "loaded_model": engine.loaded_model_id,
    }


def _safe_ext(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if ext in ALLOWED_EXTS else ""


async def _write_upload_to_temp(file: UploadFile, ext: str) -> Path:
    max_bytes = settings.voice_max_upload_mb * 1024 * 1024
    storage.output_dir()
    fd, name = tempfile.mkstemp(prefix="voice-upload-", suffix=ext, dir=str(storage.output_dir()))
    path = Path(name)
    try:
        with open(fd, "wb") as handle:
            total = await uploads_util.copy_limited_upload(
                file,
                handle,
                max_bytes=max_bytes,
                label="audio upload",
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if total == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "audio file is empty")
    return path


@router.get("/status")
async def voice_engine_status() -> dict[str, Any]:
    return _status_payload()


@router.post("/settings")
async def voice_engine_settings(body: VoiceEngineSettingsUpdate) -> dict[str, Any]:
    engine = get_engine()
    try:
        engine.update_settings(body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _status_payload()


@router.post("/convert")
async def voice_engine_convert(
    file: UploadFile = File(...),
    model_id: str = Form(...),
    pitch: int | None = Form(None),
    index_ratio: float | None = Form(None),
    protect: float | None = Form(None),
) -> dict[str, Any]:
    engine = get_engine()
    if engine.get_model(model_id) is None:
        raise HTTPException(404, "voice model not found")

    ext = _safe_ext(file.filename)
    if not ext:
        raise HTTPException(415, "unsupported audio container; use wav, flac, or ogg")

    missing = _asset_error()
    if missing is not None:
        raise HTTPException(503, missing)

    input_path = await _write_upload_to_temp(file, ext)
    token = storage.new_token()
    output_path = storage.resolve_output(token)
    assert output_path is not None
    try:
        try:
            result = await engine.convert_file(
                input_path,
                output_path,
                model_id,
                pitch=pitch,
                index_ratio=index_ratio,
                protect=protect,
            )
        except wave.Error as exc:
            raise HTTPException(415, f"unsupported or corrupt WAV input: {exc}") from exc
        except RuntimeError as exc:
            if "missing required voice pretrain asset" in str(exc):
                raise HTTPException(503, str(exc)) from exc
            raise
    finally:
        input_path.unlink(missing_ok=True)

    return {
        "token": token,
        "url": f"/api/voice/engine/file/{token}",
        **result,
    }


@router.get("/file/{token}")
async def voice_engine_file(token: str) -> FileResponse:
    path = storage.resolve_output(token)
    if path is None or not path.exists():
        raise HTTPException(404, "voice output not found")
    return FileResponse(path, media_type="audio/wav")
