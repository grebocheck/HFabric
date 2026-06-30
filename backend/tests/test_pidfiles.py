from __future__ import annotations

import logging
import os

import psutil

from app.util import pidfiles
from app.util.pidfiles import reap_known_pidfiles, reap_pidfile, remove_pidfile, write_pidfile


def test_missing_and_invalid_pidfiles_are_safe(tmp_path):
    missing = tmp_path / "missing.pid"
    assert reap_pidfile(missing, "llama-server", logging.getLogger("test")) is False

    invalid = tmp_path / "bad.pid"
    invalid.write_text("not-a-pid", encoding="utf-8")
    assert reap_pidfile(invalid, "llama-server", logging.getLogger("test")) is False
    assert not invalid.exists()


def test_dead_pidfile_is_cleaned(tmp_path):
    path = tmp_path / "llama-server.pid"
    dead_pid = max(psutil.pids()) + 100_000
    write_pidfile(path, dead_pid)

    assert reap_pidfile(path, "llama-server", logging.getLogger("test")) is False
    assert not path.exists()


def test_alive_wrong_name_pidfile_is_left_alone(tmp_path):
    path = tmp_path / "llama-server.pid"
    write_pidfile(path, os.getpid())

    assert reap_pidfile(path, "llama-server", logging.getLogger("test")) is False
    assert path.exists()


def test_remove_pidfile_and_known_pidfile_path(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    path = pidfiles.llama_server_pidfile()
    write_pidfile(path, 123)
    remove_pidfile(path)

    assert path.name == pidfiles.LLAMA_SERVER_PID
    assert not path.exists()

    called: list[tuple[str, str]] = []
    monkeypatch.setattr(pidfiles, "reap_pidfile", lambda p, name, logger: called.append((p.name, name)))
    reap_known_pidfiles(logging.getLogger("test"))
    assert called == [(pidfiles.LLAMA_SERVER_PID, "llama-server")]


def test_reap_matching_process_terminates_children_and_removes_pidfile(tmp_path, monkeypatch):
    path = tmp_path / "llama-server.pid"
    write_pidfile(path, 1234)
    events: list[str] = []

    class FakeProc:
        def __init__(self, pid: int, name: str = "llama-server") -> None:
            self.pid = pid
            self._name = name

        def name(self) -> str:
            return self._name

        def children(self, recursive: bool = False):
            events.append(f"children:{recursive}")
            return [FakeProc(4321, "child")]

        def terminate(self) -> None:
            events.append(f"terminate:{self.pid}")

        def kill(self) -> None:
            events.append(f"kill:{self.pid}")

    def fake_wait_procs(targets, timeout):
        events.append(f"wait:{','.join(str(t.pid) for t in targets)}:{timeout}")
        if len(targets) == 2:
            return [], targets
        return targets, []

    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProc(pid))
    monkeypatch.setattr(psutil, "wait_procs", fake_wait_procs)
    monkeypatch.setattr(pidfiles.time, "sleep", lambda seconds: events.append(f"sleep:{seconds}"))

    assert reap_pidfile(path, "llama-server", logging.getLogger("test")) is True

    assert not path.exists()
    assert events == [
        "children:True",
        "terminate:4321",
        "terminate:1234",
        "wait:4321,1234:5.0",
        "kill:4321",
        "kill:1234",
        "wait:4321,1234:5.0",
        "sleep:0.1",
    ]


def test_terminate_ignores_missing_children_and_names_that_cannot_be_read(tmp_path, monkeypatch):
    path = tmp_path / "llama-server.pid"
    write_pidfile(path, 5678)

    class UnreadableName:
        def name(self) -> str:
            raise psutil.AccessDenied(pid=5678)

    monkeypatch.setattr(psutil, "Process", lambda pid: UnreadableName())
    assert reap_pidfile(path, "llama-server", logging.getLogger("test")) is False
    assert path.exists()

    events: list[str] = []

    class MissingChildProc:
        def children(self, recursive: bool = False):
            raise psutil.AccessDenied(pid=1)

        def terminate(self) -> None:
            raise psutil.NoSuchProcess(pid=1)

    monkeypatch.setattr(psutil, "wait_procs", lambda targets, timeout: (targets, []))
    monkeypatch.setattr(pidfiles.time, "sleep", lambda seconds: events.append(f"sleep:{seconds}"))
    pidfiles._terminate(MissingChildProc())

    assert events == []


def test_terminate_ignores_process_that_exits_before_kill(monkeypatch):
    class ExitsBeforeKill:
        def children(self, recursive: bool = False):
            return []

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            raise psutil.NoSuchProcess(pid=2)

    monkeypatch.setattr(psutil, "wait_procs", lambda targets, timeout: ([], targets))

    pidfiles._terminate(ExitsBeforeKill())
