"""Writable runtime settings overrides for local user-facing knobs.

Server binding and authentication stay environment-only. The rest of the
day-to-day tuning surface is described in ``settings_specs`` so the Settings
tab can render typed controls and persist values to ``data/settings-overrides.json``.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from ..config import settings
from .atomic_json import AtomicJSONStore, persistence_warnings_under
from .settings_specs import GROUPS, SPECS, SettingSpec, SettingValue

SPEC_BY_KEY = {spec.key: spec for spec in SPECS}
WRITABLE_KEYS = frozenset(SPEC_BY_KEY)
_SCHEMA = "hfabric.settings-overrides"
_RUNTIME_LOCK = threading.RLock()


def overrides_path() -> Path:
    return settings.data_dir / "settings-overrides.json"


def _store() -> AtomicJSONStore:
    return AtomicJSONStore(
        overrides_path(),
        schema=_SCHEMA,
        max_bytes=512 * 1024,
    )


def current_values() -> dict[str, SettingValue]:
    values: dict[str, SettingValue] = {}
    for spec in SPECS:
        value = getattr(settings, spec.key)
        values[spec.key] = str(value) if isinstance(value, Path) else value
    return values


def payload() -> dict[str, Any]:
    return {
        "values": current_values(),
        "writable_keys": sorted(WRITABLE_KEYS),
        "groups": list(GROUPS),
        "schema": [spec.payload() for spec in SPECS],
        "path": str(overrides_path()),
        "persistence_warnings": persistence_warnings_under(settings.data_dir),
    }


def load() -> set[str]:
    """Apply the persisted override file and return the keys it set (if any)."""
    with _RUNTIME_LOCK:
        sanitized = _store().read({}, validator=_validate_persisted)
        _apply(sanitized)
        return set(sanitized)


def _validate_persisted(raw: Any) -> dict[str, SettingValue]:
    if not isinstance(raw, dict):
        raise ValueError("settings overrides must be a JSON object")
    unknown = sorted(set(raw) - WRITABLE_KEYS)
    if unknown:
        raise ValueError(f"settings overrides contain unsupported keys: {', '.join(unknown)}")
    return _sanitize(raw)


def save(patch: dict[str, Any]) -> dict[str, Any]:
    sanitized_patch = _sanitize(patch)
    with _RUNTIME_LOCK:
        values = {**current_values(), **sanitized_patch}
        # Runtime state must never get ahead of its durable representation.
        _store().write(values)
        _apply(values)
    return payload()


def _apply(values: dict[str, SettingValue]) -> None:
    for key, value in values.items():
        spec = SPEC_BY_KEY[key]
        setattr(settings, key, _runtime_value(spec, value))


def _runtime_value(spec: SettingSpec, value: SettingValue) -> Any:
    if spec.kind == "path":
        return Path(str(value))
    return value


def _sanitize(raw: dict[str, Any]) -> dict[str, SettingValue]:
    out: dict[str, SettingValue] = {}
    for key, value in raw.items():
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            continue
        out[key] = _sanitize_value(spec, value)
    return out


def _sanitize_value(spec: SettingSpec, value: Any) -> SettingValue:
    if spec.kind == "boolean":
        return _as_bool(value)
    if spec.kind == "integer":
        n = _clamp_int(value, spec.minimum, spec.maximum)
        if spec.multiple_of:
            n = _round_to(n, spec.multiple_of)
            n = _clamp_int(n, spec.minimum, spec.maximum)
        return n
    if spec.kind == "number":
        return _clamp_float(value, spec.minimum, spec.maximum)
    if spec.kind == "choice":
        clean = str(value).strip()
        allowed = {choice for choice, _label in spec.choices}
        if clean not in allowed:
            raise ValueError(f"{spec.key} must be one of: {', '.join(sorted(allowed))}")
        return clean
    if spec.kind == "text":
        clean = str(value).strip()
        if spec.nullable and clean == "":
            return None
        if not spec.nullable and clean == "":
            raise ValueError(f"{spec.key} cannot be empty")
        return clean
    if spec.kind == "path":
        clean = str(value).strip()
        if not clean:
            raise ValueError(f"{spec.key} cannot be empty")
        return clean
    raise ValueError(f"unsupported setting kind for {spec.key}: {spec.kind}")


def _clamp_int(value: Any, low: float | None, high: float | None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected integer setting, got {value!r}") from exc
    if low is not None:
        n = max(int(low), n)
    if high is not None:
        n = min(int(high), n)
    return n


def _clamp_float(value: Any, low: float | None, high: float | None) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected numeric setting, got {value!r}") from exc
    if low is not None:
        n = max(low, n)
    if high is not None:
        n = min(high, n)
    return n


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


def _round_to(value: int, multiple: int) -> int:
    return max(multiple, int(round(value / multiple) * multiple))
