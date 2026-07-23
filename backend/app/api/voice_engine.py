"""Native RVC voice engine API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from pathlib import Path
import tempfile
from typing import Any
import wave

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..core.arbiter import GpuArbiter
from ..core.enums import EventType
from ..core.events import EventBus
from ..core.scheduler import Worker
from ..services import model_download_service as downloads
from ..services.voice_engine import assets as asset_discovery
from ..services.voice_engine import devices, presets, realtime, storage
from ..services.voice_engine.engine import get_engine
from ..util import uploads as uploads_util
from .contracts import (
    ERROR_RESPONSES,
    DeleteOut,
    VoiceConvertOut,
    VoiceEnginePresetOut,
    VoiceEngineStatusOut,
    VoiceRecordingMetadataOut,
    binary_response,
)
from .deps import get_arbiter, get_bus, get_worker

router = APIRouter(
    prefix="/api/voice/engine",
    tags=["voice-engine"],
    responses=ERROR_RESPONSES,
)

ALLOWED_EXTS = {".wav", ".flac", ".ogg", ".mp3"}
_VOICE_LOCK_ATTR = "_voice_api_lifecycle_lock"
logger = logging.getLogger("hfabric")


def _voice_lifecycle_lock(arbiter: GpuArbiter) -> asyncio.Lock:
    """Keep start/stop serialized per app/arbiter (and therefore per event loop)."""
    lock = getattr(arbiter, _VOICE_LOCK_ATTR, None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(arbiter, _VOICE_LOCK_ATTR, lock)
    return lock


def _voice_idle_guard(worker: Worker) -> Callable[[], str | None]:
    def guard() -> str | None:
        job_id = worker.running_job_id
        if job_id is None:
            return None
        return f"GPU job is still running ({job_id}); wait or stop it first"

    return guard


async def shutdown_voice_session(
    arbiter: GpuArbiter,
    worker: Worker,
    bus: EventBus,
) -> bool:
    """Stop realtime/recording and always release the Voice GPU reservation."""
    async with _voice_lifecycle_lock(arbiter):
        was_active = realtime.session_active()
        stopped = False
        try:
            stopped = await asyncio.to_thread(realtime.stop_session)
            return stopped
        finally:
            # realtime.stop_session clears its singleton in its own finally. The
            # arbiter lane must have the same guarantee if audio teardown raises.
            await arbiter.deactivate_lane("voice")
            if was_active or stopped:
                bus.emit(EventType.VOICE_SESSION_STOPPED, engine="native-rvc")
            worker.notify()


async def _rollback_voice_handoff(
    arbiter: GpuArbiter,
    previous: Any,
) -> None:
    try:
        await arbiter.rollback_lane("voice", previous)
    except Exception:  # noqa: BLE001 - preserve the original device/start failure
        logger.exception("event=voice.handoff.rollback_failed")


class VoiceEngineSettingsUpdate(BaseModel):
    pitch: int | None = None
    speaker_id: int | None = None
    index_ratio: float | None = None
    protect: float | None = None
    noise_scale: float | None = None
    f0_smoothing: float | None = None
    f0_detector: str | None = None
    input_highpass_hz: int | str | None = None
    input_gate_db: float | str | None = None
    input_formant: float | None = None
    input_denoise: str | None = None
    input_denoise_mix: float | None = None
    silence_threshold_db: float | str | None = None
    silence_hold_ms: float | None = None
    server_input_device_id: int | None = None
    server_output_device_id: int | None = None
    server_monitor_device_id: int | None = None
    server_input_gain: float | None = None
    server_output_gain: float | None = None
    server_monitor_gain: float | None = None
    server_audio_sample_rate: int | None = None
    server_read_chunk_size: int | None = None
    cross_fade_overlap_size: float | None = None
    extra_convert_size: float | None = None
    pass_through: bool | None = None


class VoiceEnginePresetCreate(BaseModel):
    name: str
    settings: VoiceEngineSettingsUpdate
    model_id: str | None = None


class VoiceEnginePresetUpdate(BaseModel):
    name: str | None = None
    settings: VoiceEngineSettingsUpdate | None = None
    model_id: str | None = None


class VoiceSessionStart(BaseModel):
    model_id: str


class VoiceAssetFetchRequest(BaseModel):
    names: list[str] | None = None
    include_optional: bool = False


def _asset_error(input_denoise: str | None = None) -> str | None:
    if settings.stub_mode:
        return None
    discovered = asset_discovery.discover_assets()
    missing = [item["name"] for item in discovered["assets"] if not item["found"] and not item.get("optional")]
    if not missing:
        mode = str(input_denoise or get_engine().input_denoise).strip().lower()
        if mode == "dtln" and asset_discovery.dtln_model_paths() is None:
            dirs = ", ".join(asset_discovery.denoise_searched_dirs())
            return f"missing required DTLN denoise asset(s): denoise_dtln; searched {dirs}"
        return None
    dirs = ", ".join(asset_discovery.searched_dirs())
    return f"missing required voice pretrain asset(s): {', '.join(missing)}; searched {dirs}"


def _device_id_set(items: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for item in items:
        for key in ("id", "index"):
            try:
                ids.add(int(item[key]))
            except (KeyError, TypeError, ValueError):
                continue
    return ids


def _device_missing(settings_payload: dict[str, Any], audio_devices: dict[str, list[dict[str, Any]]]) -> dict[str, bool]:
    input_ids = _device_id_set(audio_devices["inputs"])
    output_ids = _device_id_set(audio_devices["outputs"])

    def missing(value: object, ids: set[int], *, off_ok: bool = False) -> bool:
        if value is None:
            return False
        try:
            n = int(value)
        except (TypeError, ValueError):
            return True
        if off_ok and n < 0:
            return False
        return n not in ids

    return {
        "input": missing(settings_payload.get("server_input_device_id"), input_ids),
        "output": missing(settings_payload.get("server_output_device_id"), output_ids),
        "monitor": missing(settings_payload.get("server_monitor_device_id"), output_ids, off_ok=True),
    }


async def _status_payload() -> VoiceEngineStatusOut:
    engine = get_engine()
    asset_info, models, audio_devices = await asyncio.gather(
        engine.assets_async(),
        engine.models_async(),
        asyncio.to_thread(devices.audio_devices),
    )
    ready = True if settings.stub_mode else asset_info["ready"] and bool(models)
    session = realtime.current_session()
    settings_payload = engine.settings_payload()
    settings_payload["device_missing"] = _device_missing(settings_payload, audio_devices)
    return {
        "engine": "native-rvc",
        "stub": settings.stub_mode,
        "ready": ready,
        "assets": asset_info["assets"],
        "asset_download": downloads.get_status(),
        "models": models,
        "audio_devices": audio_devices,
        "device": engine.device,
        "settings": settings_payload,
        "loaded_model": engine.loaded_model_id,
        "live": session is not None,
        "session_config": session.session_config() if session is not None else None,
        "session_error": session.error if session is not None else None,
        "recording": realtime.recording_status(),
        "metrics": session.metrics() if session is not None else {
            "input_vu": 0.0,
            "output_vu": 0.0,
            "output_peak": 0.0,
            "output_peak_dbfs": None,
            "limiter_reduction_db": 0.0,
            "timings_ms": {},
            "total_ms": None,
            "total_p95_ms": None,
            "chunk_ms": None,
            "latency_headroom_ms": None,
            "latency_warning": None,
            "provider_health": engine.provider_health(),
            "overruns": 0,
            "underruns": 0,
            "squelched": False,
        },
    }


def _safe_ext(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if ext in ALLOWED_EXTS else ""


def _mp3_url(token: str) -> str:
    return f"/api/voice/engine/file/{token}/mp3"


def _wav_url(token: str) -> str:
    return f"/api/voice/engine/file/{token}"


def _ensure_mp3(token: str) -> Path:
    wav_path = storage.resolve_output(token)
    mp3_path = storage.resolve_mp3(token)
    if wav_path is None or mp3_path is None or not wav_path.exists():
        raise HTTPException(404, "voice output not found")
    if mp3_path.exists() and mp3_path.stat().st_mtime >= wav_path.stat().st_mtime:
        return mp3_path
    try:
        import soundfile as sf  # noqa: PLC0415

        audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        sf.write(str(mp3_path), audio, sr, format="MP3")
    except Exception as exc:  # noqa: BLE001 - surface local codec failures clearly
        mp3_path.unlink(missing_ok=True)
        raise HTTPException(503, f"MP3 export is not available in this runtime: {exc}") from exc
    return mp3_path


def _ensure_metadata(token: str) -> Path:
    path = storage.resolve_metadata(token)
    if path is None or not path.exists():
        raise HTTPException(404, "voice recording metadata not found")
    return path


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


@router.get("/status", response_model=VoiceEngineStatusOut)
async def voice_engine_status() -> VoiceEngineStatusOut:
    return await _status_payload()


@router.post("/assets/fetch", response_model=VoiceEngineStatusOut)
async def voice_engine_fetch_assets(
    body: VoiceAssetFetchRequest | None = None,
) -> VoiceEngineStatusOut:
    """Download the missing shared RVC pretrain assets (ContentVec + RMVPE) into
    models/voice/pretrain so a voice model the user dropped in actually runs — no
    manual hunting for files. Reuses the background download machinery; the Voice
    tab shows progress via the ``asset_download`` field of the status payload."""
    if downloads.is_downloading():
        raise HTTPException(409, "a model download is already running; wait for it to finish")
    names = body.names if body is not None else None
    specs = await asyncio.to_thread(asset_discovery.fetch_specs, names)
    if body is not None and body.include_optional:
        specs.extend(
            await asyncio.to_thread(asset_discovery.fetch_optional_specs, names)
        )
    if not specs:
        return await _status_payload()  # nothing missing (or no known source)
    try:
        await asyncio.to_thread(downloads.start_custom, specs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if downloads.is_downloading():
        asyncio.create_task(asyncio.to_thread(downloads.run_blocking_custom, specs))
        await asyncio.sleep(0)  # let the task start before we report
    return await _status_payload()


@router.post("/settings", response_model=VoiceEngineStatusOut)
async def voice_engine_settings(
    body: VoiceEngineSettingsUpdate,
) -> VoiceEngineStatusOut:
    engine = get_engine()
    try:
        await engine.update_settings_async(body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await _status_payload()


@router.get("/presets", response_model=list[VoiceEnginePresetOut])
async def voice_engine_presets() -> list[VoiceEnginePresetOut]:
    return await asyncio.to_thread(presets.list_presets)


@router.post("/presets", response_model=VoiceEnginePresetOut)
async def voice_engine_preset_create(
    body: VoiceEnginePresetCreate,
) -> VoiceEnginePresetOut:
    try:
        preset = await asyncio.to_thread(
            presets.create_preset,
            body.name,
            body.settings.model_dump(exclude_unset=True),
            body.model_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return preset


@router.patch(
    "/presets/{preset_id}",
    response_model=VoiceEnginePresetOut,
)
async def voice_engine_preset_update(
    preset_id: str,
    body: VoiceEnginePresetUpdate,
) -> VoiceEnginePresetOut:
    fields = body.model_fields_set
    kwargs: dict[str, Any] = {}
    if "name" in fields:
        kwargs["name"] = body.name
    if "settings" in fields:
        kwargs["preset_settings"] = body.settings.model_dump(exclude_unset=True) if body.settings is not None else {}
    if "model_id" in fields:
        kwargs["model_id"] = body.model_id
    try:
        preset = await asyncio.to_thread(
            presets.update_preset,
            preset_id,
            **kwargs,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if preset is None:
        raise HTTPException(404, "voice preset not found")
    return preset


@router.delete("/presets/{preset_id}", response_model=DeleteOut)
async def voice_engine_preset_delete(preset_id: str) -> DeleteOut:
    if not await asyncio.to_thread(presets.delete_preset, preset_id):
        raise HTTPException(404, "voice preset not found")
    return {"deleted": preset_id}


@router.post("/convert", response_model=VoiceConvertOut)
async def voice_engine_convert(
    file: UploadFile = File(...),
    model_id: str = Form(...),
    pitch: int | None = Form(None),
    speaker_id: int | None = Form(None),
    index_ratio: float | None = Form(None),
    protect: float | None = Form(None),
    noise_scale: float | None = Form(None),
    f0_smoothing: float | None = Form(None),
    input_highpass_hz: str | None = Form(None),
    input_gate_db: str | None = Form(None),
    input_formant: float | None = Form(None),
    input_denoise: str | None = Form(None),
    input_denoise_mix: float | None = Form(None),
) -> VoiceConvertOut:
    engine = get_engine()
    if await engine.get_model_async(model_id) is None:
        raise HTTPException(404, "voice model not found")

    ext = _safe_ext(file.filename)
    if not ext:
        raise HTTPException(415, "unsupported audio container; use wav, flac, ogg, or mp3")

    missing = await asyncio.to_thread(_asset_error, input_denoise)
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
                speaker_id=speaker_id,
                index_ratio=index_ratio,
                protect=protect,
                noise_scale=noise_scale,
                f0_smoothing=f0_smoothing,
                input_highpass_hz=input_highpass_hz,
                input_gate_db=input_gate_db,
                input_formant=input_formant,
                input_denoise=input_denoise,
                input_denoise_mix=input_denoise_mix,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except wave.Error as exc:
            raise HTTPException(415, f"unsupported or corrupt WAV input: {exc}") from exc
        except RuntimeError as exc:
            if "missing required voice pretrain asset" in str(exc):
                raise HTTPException(503, str(exc)) from exc
            raise
    finally:
        await asyncio.to_thread(input_path.unlink, missing_ok=True)

    return {
        "token": token,
        "url": _wav_url(token),
        "mp3_url": _mp3_url(token),
        **result,
    }


@router.post("/session/start", response_model=VoiceEngineStatusOut)
async def voice_engine_session_start(
    body: VoiceSessionStart,
    arbiter: GpuArbiter = Depends(get_arbiter),
    worker: Worker = Depends(get_worker),
    bus: EventBus = Depends(get_bus),
) -> VoiceEngineStatusOut:
    """Atomically hand the GPU from the arbiter to a live Voice session."""
    async with _voice_lifecycle_lock(arbiter):
        engine = get_engine()
        if await engine.get_model_async(body.model_id) is None:
            raise HTTPException(404, "voice model not found")
        if realtime.session_active():
            raise HTTPException(409, "a voice session is already live")
        missing = await asyncio.to_thread(_asset_error, engine.input_denoise)
        if missing is not None:
            raise HTTPException(503, missing)

        # Reservation and resident unload happen under one arbiter lock. The
        # worker guard is re-evaluated inside that lock, closing the start race.
        previous = await arbiter.activate_lane(
            "voice",
            "voice session",
            exclusive=True,
            unload_resident=True,
            idle_guard=_voice_idle_guard(worker),
        )
        try:
            await asyncio.to_thread(realtime.start_session, engine, body.model_id)
        except asyncio.CancelledError:
            await _rollback_voice_handoff(arbiter, previous)
            worker.notify()
            raise
        except RuntimeError as exc:
            await _rollback_voice_handoff(arbiter, previous)
            worker.notify()
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface device/model failures clearly
            await _rollback_voice_handoff(arbiter, previous)
            worker.notify()
            raise HTTPException(500, f"could not start the voice session: {exc}") from exc

        bus.emit(
            EventType.VOICE_SESSION_STARTED,
            engine="native-rvc",
            model_id=body.model_id,
        )
        return await _status_payload()


@router.post("/session/stop", response_model=VoiceEngineStatusOut)
async def voice_engine_session_stop(
    arbiter: GpuArbiter = Depends(get_arbiter),
    worker: Worker = Depends(get_worker),
    bus: EventBus = Depends(get_bus),
) -> VoiceEngineStatusOut:
    try:
        await shutdown_voice_session(arbiter, worker, bus)
    except Exception as exc:  # noqa: BLE001 - lane cleanup already completed
        raise HTTPException(500, f"could not stop the voice session: {exc}") from exc
    return await _status_payload()


@router.post("/recording/start", response_model=VoiceEngineStatusOut)
async def voice_engine_recording_start() -> VoiceEngineStatusOut:
    if not realtime.session_active():
        raise HTTPException(409, "start a live voice session before recording")
    try:
        await asyncio.to_thread(realtime.start_recording)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await _status_payload()


@router.post("/recording/stop", response_model=VoiceEngineStatusOut)
async def voice_engine_recording_stop() -> VoiceEngineStatusOut:
    if not realtime.session_active():
        raise HTTPException(409, "start a live voice session before recording")
    try:
        result = await asyncio.to_thread(realtime.stop_recording)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    status = await _status_payload()
    return {
        **status,
        "recording_result": {**result, "mp3_url": _mp3_url(str(result["token"]))},
    }


@router.get(
    "/file/{token}/mp3",
    response_class=FileResponse,
    responses=binary_response("audio/mpeg", "Converted voice MP3"),
)
async def voice_engine_mp3_file(token: str) -> FileResponse:
    path = await asyncio.to_thread(_ensure_mp3, token)
    return FileResponse(path, media_type="audio/mpeg", filename=f"{token}.mp3")


@router.get(
    "/file/{token}/json",
    response_class=FileResponse,
    responses={
        200: {
            "model": VoiceRecordingMetadataOut,
            "description": "Voice recording metadata",
            "content": {"application/json": {}},
        }
    },
)
async def voice_engine_metadata_file(token: str) -> FileResponse:
    path = await asyncio.to_thread(_ensure_metadata, token)
    return FileResponse(path, media_type="application/json", filename=f"{token}.json")


@router.get(
    "/file/{token}",
    response_class=FileResponse,
    responses=binary_response("audio/wav", "Converted voice WAV"),
)
async def voice_engine_file(token: str) -> FileResponse:
    path = storage.resolve_output(token)
    if path is None or not path.exists():
        raise HTTPException(404, "voice output not found")
    return FileResponse(path, media_type="audio/wav", filename=f"{token}.wav")
