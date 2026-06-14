"""Install, update, and version-manage the llama.cpp binaries (P20.10).

Wraps the stdlib core in ``scripts/llama_release.py`` with the app's managed
location, the detected accelerator variant, live ``settings`` repointing, and a
small in-memory status object the UI polls during a background download.

Old builds are kept (up to ``KEEP_VERSIONS``) so a broken update can be rolled
back without re-downloading; the active build is never pruned.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import platform
import threading
import time
from types import ModuleType
from typing import Any

from ..config import _EXE, ROOT, settings
from . import capability_profile

MANAGED_ROOT = ROOT / "bin" / "llama"

_status: dict[str, Any] = {
    "state": "idle",          # idle | running | done | error
    "tag": None,
    "variant": None,
    "message": "",
    "asset": None,
    "progress": {"done": 0, "total": 0},
    "version": None,
    "updated_at": 0.0,
}
_status_lock = threading.Lock()
_update_cache: dict[str, Any] = {}


def _llama_release() -> ModuleType:
    mod = getattr(_llama_release, "_mod", None)
    if mod is None:
        path = ROOT / "scripts" / "llama_release.py"
        spec = importlib.util.spec_from_file_location("_hfabric_llama_release", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _llama_release._mod = mod  # type: ignore[attr-defined]
    return mod


def current_variant() -> str:
    """The llama.cpp release variant for this host's active accelerator."""
    try:
        backend = capability_profile.get_capability_profile().get("backend")
    except Exception:  # noqa: BLE001 - detection must not break the manager
        backend = None
    return _llama_release().backend_to_variant(backend, platform.system())


def get_status() -> dict[str, Any]:
    with _status_lock:
        return dict(_status)


def _set_status(**fields: Any) -> None:
    with _status_lock:
        _status.update(fields)
        _status["updated_at"] = time.time()


def is_installing() -> bool:
    with _status_lock:
        return _status["state"] == "running"


def state() -> dict[str, Any]:
    """Full payload for the Settings UI."""
    lr = _llama_release()
    raw = lr.read_state(MANAGED_ROOT)
    active_id = raw.get("active")
    versions = [
        {
            "id": v.get("id"),
            "tag": v.get("tag"),
            "variant": v.get("variant"),
            "installed_at": v.get("installed_at"),
            "size_bytes": v.get("size_bytes"),
            "active": v.get("id") == active_id,
            "binaries": sorted((v.get("binaries") or {}).keys()),
        }
        for v in sorted(raw.get("versions", []), key=lambda v: v.get("installed_at") or "", reverse=True)
    ]
    return {
        "managed_root": str(MANAGED_ROOT),
        "system": platform.system(),
        "machine": platform.machine(),
        "variant": current_variant(),
        "active": active_id,
        "versions": versions,
        "keep_versions": lr.KEEP_VERSIONS,
        "legacy_binary_present": _legacy_present(),
        "install_status": get_status(),
        "update": _update_cache or None,
    }


def _legacy_present() -> bool:
    """A manually-placed binary at the legacy bin/llama path (pre-manager)."""
    return (MANAGED_ROOT / f"llama-server{_EXE}").exists()


def apply_active_to_settings() -> dict[str, str]:
    """Repoint settings.llama_*_bin at the active managed build, if any."""
    lr = _llama_release()
    active = lr.active_version(MANAGED_ROOT)
    if not active:
        return {}
    binaries = active.get("binaries") or {}
    applied: dict[str, str] = {}
    for name, attr in (
        ("llama-server", "llama_server_bin"),
        ("llama-tts", "llama_tts_bin"),
        ("llama-mtmd-cli", "llama_mtmd_bin"),
    ):
        path = binaries.get(name)
        if path and Path(path).exists():
            setattr(settings, attr, Path(path))
            applied[attr] = path
    return applied


def install_blocking(tag: str | None = None, variant: str | None = None) -> dict[str, Any]:
    """Download + register a build. Runs in a worker thread; updates status."""
    with _status_lock:
        if _status["state"] == "running":
            return dict(_status)
        variant = variant or current_variant()
        _status.update({
            "state": "running", "tag": tag, "variant": variant,
            "message": "Resolving release…", "asset": None,
            "progress": {"done": 0, "total": 0}, "version": None, "updated_at": time.time(),
        })

    lr = _llama_release()

    def progress(asset: str, done: int, total: int) -> None:
        _set_status(asset=asset, progress={"done": done, "total": total},
                    message=f"Downloading {asset}")

    try:
        version = lr.install(
            MANAGED_ROOT,
            system=platform.system(),
            machine=platform.machine(),
            variant=variant,
            tag=tag,
            progress_cb=progress,
        )
        apply_active_to_settings()
        note = "" if version.get("variant_matched", True) else f" ({version.get('selection_reason')})"
        _set_status(state="done", version=version, message=f"Installed {version.get('tag')}{note}")
        return version
    except Exception as exc:  # noqa: BLE001 - report download/extract failures to the UI
        _set_status(state="error", message=f"{type(exc).__name__}: {exc}")
        raise


def activate(version_id: str) -> dict[str, Any]:
    lr = _llama_release()
    version = lr.activate(MANAGED_ROOT, version_id)
    apply_active_to_settings()
    return version


def remove(version_id: str) -> None:
    _llama_release().remove_version(MANAGED_ROOT, version_id)


def check_update(variant: str | None = None) -> dict[str, Any]:
    """Query GitHub for the latest release and compare with the active build."""
    lr = _llama_release()
    variant = variant or current_variant()
    release = lr.fetch_latest_release()
    latest_tag = str(release.get("tag_name") or "")
    selection = lr.select_assets(
        release.get("assets") or [], system=platform.system(),
        machine=platform.machine(), variant=variant,
    )
    active = lr.active_version(MANAGED_ROOT)
    active_tag = active.get("tag") if active else None
    result = {
        "latest_tag": latest_tag,
        "active_tag": active_tag,
        "variant": variant,
        "asset_available": bool(selection["primary"]),
        "variant_matched": selection["variant_matched"],
        "selection_reason": selection["reason"],
        "update_available": bool(latest_tag and latest_tag != active_tag and selection["primary"]),
        "checked_at": time.time(),
    }
    _update_cache.clear()
    _update_cache.update(result)
    return result
