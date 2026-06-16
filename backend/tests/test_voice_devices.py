from __future__ import annotations

import sys

from app.config import settings
from app.services.voice_engine import devices


def test_audio_devices_stub_mode_returns_stub_devices(monkeypatch):
    monkeypatch.setattr(settings, "stub_mode", True)
    out = devices.audio_devices()
    assert out["inputs"] and out["outputs"]


def test_audio_devices_missing_sounddevice_degrades(monkeypatch):
    # A REAL-mode run without the accelerator stack has no `sounddevice`. Setting
    # the module to None makes `import sounddevice` raise ImportError, exercising
    # the degradation path even though the dep is installed in the test env.
    monkeypatch.setattr(settings, "stub_mode", False)
    monkeypatch.setattr(devices, "_audio_unavailable_warned", False)
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    out = devices.audio_devices()

    assert out == {"inputs": [], "outputs": []}
