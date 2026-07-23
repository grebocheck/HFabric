from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_dependency_consistency import check  # noqa: E402
from install_profiles import (  # noqa: E402
    DEPENDENCY_MANIFEST,
    lock_fingerprint,
    read_lock_fingerprint,
)


def test_dependency_profiles_and_shared_pins_are_consistent():
    assert check() == []


def test_every_manifest_lock_has_current_source_fingerprint_and_hashes():
    for lock_id, spec in DEPENDENCY_MANIFEST["locks"].items():
        path = ROOT / spec["output"]
        assert read_lock_fingerprint(path) == lock_fingerprint(lock_id)
        text = path.read_text(encoding="utf-8")
        assert "--hash=sha256:" in text


def test_profile_manifest_is_machine_readable_and_references_platform_locks():
    manifest = json.loads((ROOT / "backend" / "dependency-profiles.json").read_text(encoding="utf-8"))
    targets = {
        (profile_id, target["id"]): target
        for profile_id, profile in manifest["profiles"].items()
        for target in profile["targets"]
    }

    assert targets[("nvidia-cuda", "windows-x86_64")]["lock"] == "cuda-windows-x86_64"
    assert targets[("nvidia-cuda", "linux-x86_64")]["lock"] == "cuda-linux-x86_64"
    assert targets[("amd-rocm-linux", "linux-x86_64")]["lock"] == "rocm-linux-x86_64"
    assert targets[("apple-mps", "macos-arm64")]["lock"] == "mps-macos-arm64"
    rocm = manifest["locks"]["rocm-linux-x86_64"]
    assert rocm["torch_preinstalled_backend"] == "rocm7.2"
    assert set(rocm["omit_packages"]) == {"torch", "torchvision", "torchaudio"}


def test_fingerprint_changes_when_a_declared_source_changes(tmp_path):
    source = tmp_path / "requirements.txt"
    source.write_text("demo==1.0\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "python_version": "3.12",
        "resolver": {"tool": "uv", "version": "0.11.31"},
        "torch": {},
        "locks": {
            "demo": {
                "input": "requirements.txt",
                "output": "demo.lock",
                "source_files": ["requirements.txt"],
            }
        },
    }
    before = lock_fingerprint("demo", manifest=manifest, root=tmp_path)
    source.write_text("demo==1.1\n", encoding="utf-8")

    assert lock_fingerprint("demo", manifest=manifest, root=tmp_path) != before
