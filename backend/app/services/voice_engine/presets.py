"""Named presets for native voice-engine settings."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

from ...config import settings

VOICE_PRESETS_FILE = "voice-presets.json"
PRESET_SETTING_KEYS = {
    "pitch",
    "speaker_id",
    "index_ratio",
    "protect",
    "noise_scale",
    "f0_smoothing",
    "f0_detector",
    "input_highpass_hz",
    "input_gate_db",
    "input_formant",
    "input_denoise",
    "silence_threshold_db",
    "silence_hold_ms",
    "server_audio_sample_rate",
    "server_read_chunk_size",
    "cross_fade_overlap_size",
    "extra_convert_size",
    "server_input_gain",
    "server_output_gain",
    "server_monitor_gain",
}


def _path() -> Path:
    return settings.data_dir / VOICE_PRESETS_FILE


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean_name(name: str) -> str:
    cleaned = " ".join(str(name or "").split())
    if not cleaned:
        raise ValueError("preset name is required")
    return cleaned[:80]


def _clean_settings(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(data or {}).items() if key in PRESET_SETTING_KEYS and value is not None}


def _read() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    presets: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        preset_id = item.get("id")
        preset_settings = item.get("settings")
        if not isinstance(name, str) or not isinstance(preset_id, str) or not isinstance(preset_settings, dict):
            continue
        presets.append({
            "id": preset_id,
            "name": name,
            "settings": _clean_settings(preset_settings),
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or item.get("created_at") or ""),
        })
    return presets


def _write(presets: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(presets, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def list_presets() -> list[dict[str, Any]]:
    return sorted(_read(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def create_preset(name: str, preset_settings: dict[str, Any]) -> dict[str, Any]:
    cleaned_settings = _clean_settings(preset_settings)
    if not cleaned_settings:
        raise ValueError("preset settings are empty")
    now = _now()
    preset = {
        "id": uuid.uuid4().hex,
        "name": _clean_name(name),
        "settings": cleaned_settings,
        "created_at": now,
        "updated_at": now,
    }
    presets = _read()
    presets.append(preset)
    _write(presets)
    return preset


def delete_preset(preset_id: str) -> bool:
    presets = _read()
    kept = [preset for preset in presets if preset.get("id") != preset_id]
    if len(kept) == len(presets):
        return False
    _write(kept)
    return True
