"""Durable JSON persistence with process-local concurrency safety.

The store deliberately targets settings/metadata rather than large documents:
payloads are size-bounded, wrapped in a schema/version envelope, written through
a same-directory temporary file, flushed to disk, and atomically replaced.
Legacy unwrapped JSON remains readable and is upgraded on the next write.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_MAX_BYTES = 1024 * 1024

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_WARNINGS_LOCK = threading.Lock()
_WARNINGS: dict[str, dict[str, Any]] = {}


def _path_key(path: Path) -> str:
    value = str(path.absolute())
    return value.casefold() if os.name == "nt" else value


def _path_lock(path: Path) -> threading.RLock:
    key = _path_key(path)
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def persistence_warnings(path: Path | None = None) -> list[dict[str, Any]]:
    """Return sanitized persistence warnings suitable for diagnostics payloads."""
    with _WARNINGS_LOCK:
        if path is not None:
            warning = _WARNINGS.get(_path_key(path))
            return [dict(warning)] if warning else []
        return [dict(item) for item in _WARNINGS.values()]


def persistence_warnings_under(directory: Path) -> list[dict[str, Any]]:
    """Return sanitized warnings for stores located below one runtime root."""
    root = Path(_path_key(directory))
    with _WARNINGS_LOCK:
        return [
            dict(warning)
            for key, warning in _WARNINGS.items()
            if Path(key).is_relative_to(root)
        ]


def clear_persistence_warnings(path: Path | None = None) -> None:
    """Clear warning state after a successful repair/write (also useful in tests)."""
    with _WARNINGS_LOCK:
        if path is None:
            _WARNINGS.clear()
        else:
            _WARNINGS.pop(_path_key(path), None)


def _record_warning(path: Path, reason: str, quarantine: Path | None) -> None:
    warning = {
        "file": path.name,
        "reason": reason[:240],
        "quarantined_as": quarantine.name if quarantine is not None else None,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with _WARNINGS_LOCK:
        _WARNINGS[_path_key(path)] = warning


class AtomicJSONStore:
    """A schema-versioned atomic JSON file with corruption quarantine."""

    def __init__(
        self,
        path: Path,
        *,
        schema: str,
        version: int = 1,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup: bool = True,
        mode: int = 0o600,
    ) -> None:
        if not schema.strip():
            raise ValueError("JSON store schema is required")
        if version < 1:
            raise ValueError("JSON store version must be positive")
        if max_bytes < 1:
            raise ValueError("JSON store size limit must be positive")
        self.path = Path(path)
        self.schema = schema
        self.version = version
        self.max_bytes = max_bytes
        self.backup = backup
        self.mode = mode
        self._lock = _path_lock(self.path)

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.bak")

    def read(
        self,
        default: T,
        *,
        validator: Callable[[Any], T] | None = None,
    ) -> T:
        """Read and validate data, quarantining malformed/oversized files."""
        with self._lock:
            return self._read_unlocked(default, validator)

    def write(self, data: T) -> None:
        """Durably replace the current payload."""
        with self._lock:
            self._write_unlocked(data)

    def update(
        self,
        default: T,
        updater: Callable[[T], T],
        *,
        validator: Callable[[Any], T] | None = None,
    ) -> T:
        """Atomically perform a process-local read/modify/write transaction."""
        with self._lock:
            current = self._read_unlocked(default, validator)
            updated = updater(deepcopy(current))
            self._write_unlocked(updated)
            return updated

    def _read_unlocked(
        self,
        default: T,
        validator: Callable[[Any], T] | None,
    ) -> T:
        if not self.path.exists():
            return deepcopy(default)
        try:
            raw_bytes = self.path.read_bytes()
            if len(raw_bytes) > self.max_bytes:
                raise ValueError(
                    f"file exceeds the {self.max_bytes}-byte persistence limit"
                )
            raw = json.loads(raw_bytes.decode("utf-8"))
            data = self._unwrap(raw)
            return validator(data) if validator is not None else data
        except (json.JSONDecodeError, UnicodeError, OSError, TypeError, ValueError) as exc:
            quarantine = self._quarantine_unlocked()
            _record_warning(
                self.path,
                f"{type(exc).__name__}: {exc}",
                quarantine,
            )
            return deepcopy(default)

    def _unwrap(self, raw: Any) -> Any:
        envelope_keys = {"schema", "version", "data"}
        if not isinstance(raw, dict) or not (envelope_keys & raw.keys()):
            return raw
        missing = envelope_keys - raw.keys()
        if missing:
            raise ValueError(
                f"incomplete persistence envelope; missing: {', '.join(sorted(missing))}"
            )
        if raw["schema"] != self.schema:
            raise ValueError(
                f"expected schema {self.schema!r}, got {raw['schema']!r}"
            )
        if raw["version"] != self.version:
            raise ValueError(
                f"unsupported {self.schema} version {raw['version']!r}"
            )
        return raw["data"]

    def _write_unlocked(self, data: Any) -> None:
        envelope = {
            "schema": self.schema,
            "version": self.version,
            "data": data,
        }
        try:
            encoded = (
                json.dumps(
                    envelope,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload is not valid JSON: {exc}") from exc
        if len(encoded) > self.max_bytes:
            raise ValueError(
                f"serialized payload exceeds the {self.max_bytes}-byte persistence limit"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.backup and self.path.is_file():
            previous = self.path.read_bytes()
            if len(previous) <= self.max_bytes:
                self._atomic_replace_bytes(self.backup_path, previous)
        self._atomic_replace_bytes(self.path, encoded)
        clear_persistence_warnings(self.path)

    def _atomic_replace_bytes(self, destination: Path, payload: bytes) -> None:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                tmp_path.chmod(self.mode)
            except OSError:
                pass
            os.replace(tmp_path, destination)
            tmp_path = None
            try:
                destination.chmod(self.mode)
            except OSError:
                pass
            self._fsync_parent()
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _quarantine_unlocked(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        quarantine = self.path.with_name(
            f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}"
        )
        try:
            os.replace(self.path, quarantine)
            self._fsync_parent()
            return quarantine
        except OSError:
            return None

    def _fsync_parent(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(self.path.parent, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
