"""Writable runtime settings overrides for the safe local subset.

Only the fields in ``WRITABLE_KEYS`` may be persisted. Memory guard knobs stay
environment-only so the UI cannot accidentally weaken the pagefile protection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings

WRITABLE_KEYS = frozenset({
    "default_steps",
    "default_guidance",
    "default_width",
    "default_height",
    "keep_warm_models",
    "keep_warm_max_models",
})


def overrides_path() -> Path:
    return settings.data_dir / "settings-overrides.json"


def current_values() -> dict[str, int | float | bool]:
    return {
        "default_steps": int(settings.default_steps),
        "default_guidance": float(settings.default_guidance),
        "default_width": int(settings.default_width),
        "default_height": int(settings.default_height),
        "keep_warm_models": bool(settings.keep_warm_models),
        "keep_warm_max_models": int(settings.keep_warm_max_models),
    }


def payload() -> dict[str, Any]:
    return {
        "values": current_values(),
        "writable_keys": sorted(WRITABLE_KEYS),
        "path": str(overrides_path()),
    }


def load() -> None:
    path = overrides_path()
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("settings overrides must be a JSON object")
    unknown = sorted(set(raw) - WRITABLE_KEYS)
    if unknown:
        raise ValueError(f"settings overrides contain unsupported keys: {', '.join(unknown)}")
    _apply(_sanitize(raw))


def save(patch: dict[str, Any]) -> dict[str, Any]:
    values = {**current_values(), **_sanitize(patch)}
    _apply(values)
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload()


def _apply(values: dict[str, int | float | bool]) -> None:
    for key, value in values.items():
        setattr(settings, key, value)


def _sanitize(raw: dict[str, Any]) -> dict[str, int | float | bool]:
    out: dict[str, int | float | bool] = {}
    for key, value in raw.items():
        if key == "default_steps":
            out[key] = _clamp_int(value, 1, 150)
        elif key == "default_guidance":
            out[key] = _clamp_float(value, 0.0, 30.0)
        elif key in {"default_width", "default_height"}:
            out[key] = _round64(_clamp_int(value, 256, 2048))
        elif key == "keep_warm_models":
            out[key] = _as_bool(value)
        elif key == "keep_warm_max_models":
            out[key] = _clamp_int(value, 0, 8)
    return out


def _clamp_int(value: Any, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected integer setting, got {value!r}") from exc
    return max(low, min(high, n))


def _clamp_float(value: Any, low: float, high: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected numeric setting, got {value!r}") from exc
    return max(low, min(high, n))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "on"}:
            return True
        if clean in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"expected boolean setting, got {value!r}")


def _round64(value: int) -> int:
    return max(64, int(round(value / 64) * 64))
