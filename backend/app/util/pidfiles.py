"""Pidfile helpers for managed external server processes."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any

import psutil

from ..config import settings

LLAMA_SERVER_PID = "llama-server.pid"
PIDFILE_VERSION = 1


def llama_server_pidfile() -> Path:
    return settings.runtime_dir / LLAMA_SERVER_PID


def write_pidfile(path: Path, pid: int) -> None:
    """Persist enough process identity to make later cleanup safe.

    A numeric PID alone is not ownership proof: operating systems reuse PIDs.
    The start time, executable and command line let a later process distinguish
    the exact child it launched from an unrelated process with the same PID.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "version": PIDFILE_VERSION,
        "pid": pid,
        "project_root": str(settings.root.resolve()),
        "create_time": None,
        "name": None,
        "executable": None,
        "cmdline": None,
    }
    try:
        proc = psutil.Process(pid)
        record.update(_process_identity(proc))
    except (psutil.Error, OSError):
        # A child can exit between spawn and pidfile creation. Keep the PID so
        # the next startup can discard the dead record, but never treat this
        # incomplete identity as permission to terminate a live process.
        pass

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_pidfile(path: Path) -> None:
    path.unlink(missing_ok=True)


def reap_pidfile(path: Path, expected_name: str, logger: logging.Logger) -> bool:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        remove_pidfile(path)
        return False
    if not isinstance(record, dict) or record.get("version") != PIDFILE_VERSION:
        # Legacy PID-only files cannot distinguish a stale child from PID reuse.
        remove_pidfile(path)
        return False
    pid = record.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        remove_pidfile(path)
        return False

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        remove_pidfile(path)
        return False

    try:
        name = proc.name()
    except (psutil.Error, OSError):
        return False
    if expected_name.casefold() not in name.casefold():
        return False
    if not _matches_record(proc, record):
        logger.warning(
            "event=process.reap_refused pid=%s name=%s pidfile=%s reason=identity_mismatch",
            pid,
            name,
            path,
        )
        return False

    logger.warning(
        "event=process.reap pid=%s name=%s pidfile=%s expected=%s",
        pid,
        name,
        path,
        expected_name,
    )
    _terminate(proc)
    remove_pidfile(path)
    return True


def reap_known_pidfiles(logger: logging.Logger) -> None:
    reap_pidfile(llama_server_pidfile(), "llama-server", logger)


def _process_identity(proc: psutil.Process) -> dict[str, Any]:
    return {
        "create_time": proc.create_time(),
        "name": proc.name(),
        "executable": proc.exe(),
        "cmdline": proc.cmdline(),
    }


def _normalise_path(value: str) -> str:
    try:
        resolved = str(Path(value).resolve(strict=False))
    except (OSError, ValueError):
        resolved = value
    return os.path.normcase(resolved)


def _matches_record(proc: psutil.Process, record: dict[str, Any]) -> bool:
    """Return true only when the live process is the exact recorded child."""

    expected_root = record.get("project_root")
    if not isinstance(expected_root, str) or _normalise_path(expected_root) != _normalise_path(str(settings.root)):
        return False

    recorded_start = record.get("create_time")
    recorded_name = record.get("name")
    recorded_executable = record.get("executable")
    recorded_cmdline = record.get("cmdline")
    if (
        not isinstance(recorded_start, (int, float))
        or isinstance(recorded_start, bool)
        or not isinstance(recorded_name, str)
        or not isinstance(recorded_executable, str)
        or not isinstance(recorded_cmdline, list)
        or not all(isinstance(part, str) for part in recorded_cmdline)
    ):
        return False

    try:
        live = _process_identity(proc)
    except (psutil.Error, OSError):
        return False
    return (
        abs(float(live["create_time"]) - float(recorded_start)) <= 0.01
        and str(live["name"]).casefold() == recorded_name.casefold()
        and _normalise_path(str(live["executable"])) == _normalise_path(recorded_executable)
        and list(live["cmdline"]) == recorded_cmdline
    )


def _terminate(proc: psutil.Process, timeout: float = 5.0) -> None:
    try:
        children = proc.children(recursive=True)
    except psutil.Error:
        children = []
    targets = [*children, proc]
    for target in targets:
        try:
            target.terminate()
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(targets, timeout=timeout)
    if alive:
        for target in alive:
            try:
                target.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=timeout)
    # Give Windows a short moment to release process handles before the caller
    # starts a replacement server on the same port.
    if not gone:
        time.sleep(0.1)
