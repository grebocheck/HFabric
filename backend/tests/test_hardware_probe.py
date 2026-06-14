from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hardware_probe  # noqa: E402


def test_attach_rocm_marks_community_experimental_target():
    gpus = [{"vendor": "amd", "name": "Radeon", "vram_mb": 16384}]
    hardware_probe._attach_rocm(gpus, {
        "llvm_targets": ["gfx9999"],
        "official_targets": [],
    })

    assert gpus[0]["rocm"]["support"] == "community_experimental"


def test_probe_apple_silicon_from_platform(monkeypatch):
    monkeypatch.setattr(hardware_probe.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware_probe.platform, "machine", lambda: "arm64")

    gpus = hardware_probe.probe_apple_silicon()

    assert gpus[0]["vendor"] == "apple"
    assert gpus[0]["mps"]["potential"] is True
