"""Native RVC voice-conversion service (P6R).

The engine pipeline is file based for P6R.1: uploaded audio is decoded, mixed to
mono, resampled to 16 kHz, passed through ContentVec, optionally blended with an
RVC faiss index, aligned with RMVPE f0, and synthesized by the vendored RVC v2
decoder. All heavyweight libraries are imported lazily inside real conversion
paths so the default STUB mode can import the full app in CI without torch,
onnxruntime, faiss, soundfile, soxr, or sounddevice.

In STUB mode ``VoiceEngine.convert_file`` uses only the stdlib ``wave`` module
and writes a deterministic WAV transform. That keeps the API round-trip
testable while the real GPU/audio environment remains optional.
"""

from __future__ import annotations

from .engine import VoiceEngine, get_engine

__all__ = ["VoiceEngine", "get_engine"]
