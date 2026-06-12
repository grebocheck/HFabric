from __future__ import annotations

from importlib.util import find_spec
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODEL_1 = ROOT / "models" / "voice" / "pretrain" / "denoise" / "dtln_model_1.onnx"
MODEL_2 = ROOT / "models" / "voice" / "pretrain" / "denoise" / "dtln_model_2.onnx"


def _tone_to_noise_db(audio, *, sr: int = 16_000, freq: float = 440.0) -> float:
    import numpy as np

    y = np.asarray(audio, dtype=np.float64).reshape(-1)
    window = np.hanning(y.size)
    power = np.abs(np.fft.rfft(y * window)) ** 2
    freqs = np.fft.rfftfreq(y.size, 1.0 / sr)
    center = int(np.argmin(np.abs(freqs - freq)))
    tone_bins = np.arange(max(0, center - 2), min(power.size, center + 3))
    excluded = np.zeros(power.size, dtype=bool)
    excluded[max(0, center - 12) : min(power.size, center + 13)] = True
    noise_band = (freqs >= 80.0) & (freqs <= 7600.0) & (~excluded)
    tone_power = float(power[tone_bins].sum())
    noise_power = float(power[noise_band].mean() * len(tone_bins))
    return 10.0 * math.log10(max(tone_power, 1e-20) / max(noise_power, 1e-20))


@pytest.mark.skipif(
    not (MODEL_1.is_file() and MODEL_2.is_file() and find_spec("onnxruntime") is not None),
    reason="local DTLN ONNX files or onnxruntime are not available",
)
def test_dtln_denoises_noisy_tone_and_keeps_stream_seam():
    import numpy as np

    from app.services.voice_engine.denoise import DtlnDenoiser

    sr = 16_000
    t = np.arange(sr * 2, dtype=np.float32) / sr
    rng = np.random.default_rng(0)
    tone = (0.005 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    noise = rng.normal(0.0, 0.3, t.size).astype(np.float32)
    noisy = (tone + noise).astype(np.float32)

    denoiser = DtlnDenoiser(MODEL_1, MODEL_2)
    out = denoiser.process(noisy)

    assert out.dtype == np.float32
    assert len(out) == len(noisy)
    assert np.all(np.isfinite(out))
    assert _tone_to_noise_db(out) - _tone_to_noise_db(noisy) >= 6.0

    denoiser.reset()
    first = denoiser.process(noisy[:8000])
    second = denoiser.process(noisy[8000:])
    assert len(first) + len(second) == len(noisy)
    assert abs(float(second[0] - first[-1])) <= 0.5
