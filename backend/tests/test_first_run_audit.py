from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from first_run_audit import (  # noqa: E402
    _managed_npm_path,
    clean_checkout_status,
    collect_audit,
    render_markdown,
)


def test_clean_checkout_status_flags_bootstrap_paths(tmp_path):
    clean = clean_checkout_status(tmp_path)
    assert clean["clean"] is True

    (tmp_path / ".venv").mkdir()
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
    dirty = clean_checkout_status(tmp_path)

    assert dirty["clean"] is False
    assert dirty["present_bootstrap_paths"] == [".venv", "frontend/node_modules"]


def test_collect_audit_without_hardware_is_side_effect_light(tmp_path, monkeypatch):
    monkeypatch.setattr("first_run_audit.git_status", lambda _root: {"head": "abc123", "dirty": False})
    report = collect_audit(tmp_path, phase="pre", include_hardware=False)

    assert report["phase"] == "pre"
    assert report["clean_checkout"]["clean"] is True
    assert "hardware_profile" not in report
    assert "setup.bat" in report["next_commands"]


def test_managed_npm_path_finds_versioned_windows_node(tmp_path, monkeypatch):
    monkeypatch.setattr("first_run_audit.platform.system", lambda: "Windows")
    npm = tmp_path / ".tools" / "node-v24.17.0-win-x64" / "npm.cmd"
    npm.parent.mkdir(parents=True)
    npm.write_text("", encoding="utf-8")

    assert _managed_npm_path(tmp_path) == npm


def test_render_markdown_includes_profile_and_bootstrap_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("first_run_audit.git_status", lambda _root: {"head": "abc123", "dirty": True})
    report = collect_audit(tmp_path, phase="post-setup", include_hardware=False)
    report["hardware_profile"] = {
        "profile": {
            "selected_profile": "amd-rocm-linux",
            "backend": "rocm",
            "hardware_tier": "large_24gb_plus",
            "gpu": {"name": "Radeon RX 7900 XTX"},
            "video_policy": {"recommended": ["cogvideo"], "hidden": ["ltx-video"]},
        }
    }

    text = render_markdown(report)

    assert "First-Run Audit Snapshot" in text
    assert "amd-rocm-linux / rocm" in text
    assert "cogvideo" in text
    assert "`frontend/node_modules`" in text
