"""Diagnostics: bundle logs + hardware/capability + version stamps into a zip.

For bug reports — the zip is produced on demand and downloaded locally only; it is
**never** uploaded anywhere. Secrets (the API token and secret-ish keys) are
redacted before anything is written, so a tester can attach it to an issue safely.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import platform
import tempfile
from typing import Any
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import __version__
from ..config import settings
from ..services import capability_profile, settings_overrides
from ..util import security, sysmon
from ..util.logging import BACKUP_COUNT, LOG_FILE_NAME

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

_SECRET_HINTS = ("token", "secret", "password", "passwd", "apikey", "api_key")
_REDACTED = "***REDACTED***"


def _scrub_text(text: str) -> str:
    """Redact the live API token wherever it appears in free text (e.g. logs)."""
    token = getattr(settings, "api_token", None)
    if isinstance(token, str) and token:
        text = text.replace(token, _REDACTED)
    return text


def _scrub_mapping(obj: Any) -> Any:
    """Recursively redact values under secret-ish keys in dicts/lists."""
    if isinstance(obj, Mapping):
        scrubbed: dict[str, Any] = {}
        for key, value in obj.items():
            name = str(key)
            if any(hint in name.lower() for hint in _SECRET_HINTS):
                scrubbed[name] = _REDACTED
            else:
                scrubbed[name] = _scrub_mapping(value)
        return scrubbed
    if isinstance(obj, (list, tuple)):
        return [_scrub_mapping(item) for item in obj]
    return obj


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _add_json(zf: zipfile.ZipFile, name: str, producer: Callable[[], Any]) -> None:
    """Write one JSON section best-effort; a failure becomes a side note, not a 500."""
    try:
        zf.writestr(name, _dumps(producer()))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail wholesale
        zf.writestr(f"{name}.error.txt", f"{type(exc).__name__}: {exc}")


def _add_logs(zf: zipfile.ZipFile) -> None:
    names = [LOG_FILE_NAME] + [f"{LOG_FILE_NAME}.{i}" for i in range(1, BACKUP_COUNT + 1)]
    found = False
    for name in names:
        path = settings.logs_dir / name
        if not path.exists():
            continue
        found = True
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            zf.writestr(f"logs/{name}", _scrub_text(text))
        except Exception as exc:  # noqa: BLE001
            zf.writestr(f"logs/{name}.error.txt", f"{type(exc).__name__}: {exc}")
    if not found:
        zf.writestr("logs/NO_LOGS.txt", "No hfabric.log files found in logs_dir.\n")


@router.get("/export")
async def export_diagnostics(request: Request) -> FileResponse:
    now = datetime.now(UTC)

    def manifest() -> dict[str, Any]:
        return {
            "generated_at": now.isoformat(),
            "app_version": __version__,
            "stub_mode": settings.stub_mode,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_version": platform.python_version(),
            },
            "note": (
                "Secrets (API token, secret-ish keys) are redacted. "
                "Produced locally and downloaded by you; nothing is uploaded."
            ),
        }

    def health() -> dict[str, Any]:
        arbiter = getattr(request.app.state, "arbiter", None)
        return {
            "version": __version__,
            "stub_mode": settings.stub_mode,
            "gpu": arbiter.status() if arbiter is not None else None,
            "mem": sysmon.snapshot(),
            "security": security.security_posture(),
        }

    def settings_view() -> dict[str, Any]:
        data: dict[str, Any] = {"overrides": settings_overrides.payload()}
        try:
            data["settings"] = settings.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - fall back to plain dump
            data["settings"] = settings.model_dump()
        return _scrub_mapping(data)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        zip_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            _add_json(zf, "manifest.json", manifest)
            _add_json(zf, "health.json", health)
            _add_json(zf, "capability.json", capability_profile.get_capability_profile)
            _add_json(zf, "settings.json", settings_view)
            _add_logs(zf)
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"hfabric-diagnostics-{__version__}-{now.date().isoformat()}.zip",
        background=BackgroundTask(lambda: zip_path.unlink(missing_ok=True)),
    )
