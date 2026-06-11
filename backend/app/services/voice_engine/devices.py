"""Audio device enumeration for the native voice engine."""

from __future__ import annotations

from typing import Any

from ...config import settings


def _stub_devices() -> dict[str, list[dict[str, Any]]]:
    inputs = [
        {
            "id": "0",
            "index": 0,
            "name": "Stub microphone 1",
            "host_api": "stub",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_sample_rate": 48000,
        },
        {
            "id": "1",
            "index": 1,
            "name": "Stub microphone 2",
            "host_api": "stub",
            "max_input_channels": 2,
            "max_output_channels": 0,
            "default_sample_rate": 44100,
        },
    ]
    outputs = [
        {
            "id": "2",
            "index": 2,
            "name": "Stub speakers 1",
            "host_api": "stub",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_sample_rate": 48000,
        },
        {
            "id": "3",
            "index": 3,
            "name": "Stub speakers 2",
            "host_api": "stub",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_sample_rate": 44100,
        },
    ]
    return {"inputs": inputs, "outputs": outputs}


def _host_api_name(host_apis: list[dict[str, Any]], index: int | None) -> str:
    if index is None or index < 0 or index >= len(host_apis):
        return ""
    return str(host_apis[index].get("name") or "")


def _device(index: int, raw: dict[str, Any], host_apis: list[dict[str, Any]]) -> dict[str, Any]:
    default_rate = raw.get("default_samplerate")
    try:
        default_rate = int(float(default_rate)) if default_rate is not None else None
    except (TypeError, ValueError):
        default_rate = None
    host_api_index = raw.get("hostapi")
    try:
        host_api_index = int(host_api_index)
    except (TypeError, ValueError):
        host_api_index = None
    return {
        "id": str(index),
        "index": index,
        "name": str(raw.get("name") or f"Device {index}"),
        "host_api": _host_api_name(host_apis, host_api_index),
        "max_input_channels": int(raw.get("max_input_channels") or 0),
        "max_output_channels": int(raw.get("max_output_channels") or 0),
        "default_sample_rate": default_rate,
    }


def audio_devices() -> dict[str, list[dict[str, Any]]]:
    if settings.stub_mode:
        return _stub_devices()

    import sounddevice as sd  # noqa: PLC0415

    raw_devices = sd.query_devices()
    raw_host_apis = sd.query_hostapis()
    devices = [
        _device(index, dict(raw), [dict(api) for api in raw_host_apis])
        for index, raw in enumerate(raw_devices)
    ]
    return {
        "inputs": [item for item in devices if item["max_input_channels"] > 0],
        "outputs": [item for item in devices if item["max_output_channels"] > 0],
    }
