"""Deterministic diagnostics for paired raw/converted voice recordings."""

from __future__ import annotations

import math
from typing import Any


def _dbfs(value: float) -> float:
    return round(20.0 * math.log10(max(abs(float(value)), 1e-12)), 3)


def analyze_signal(samples, sample_rate: int, *, chunk_ms: float | None = None) -> dict[str, Any]:
    """Return level, clipping, silence, and block-seam diagnostics."""
    import numpy as np  # noqa: PLC0415

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    sr = max(1, int(sample_rate))
    if audio.size == 0:
        return {
            "samples": 0,
            "duration_s": 0.0,
            "peak_dbfs": None,
            "rms_dbfs": None,
            "dc_offset": 0.0,
            "clipped_ratio": 0.0,
            "silence_ratio": 1.0,
            "derivative_p95_dbfs": None,
            "seam_jump_p95_dbfs": None,
            "seam_to_baseline_ratio": None,
        }

    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    frame = max(1, int(round(sr * 0.020)))
    usable = audio[: audio.size - (audio.size % frame)]
    if usable.size:
        framed = usable.reshape(-1, frame)
        frame_rms = np.sqrt(np.mean(np.square(framed, dtype=np.float64), axis=1))
        silence_ratio = float(np.mean(frame_rms < 10.0 ** (-60.0 / 20.0)))
    else:
        silence_ratio = float(rms < 10.0 ** (-60.0 / 20.0))

    derivative = np.abs(np.diff(audio.astype(np.float64)))
    derivative_p95 = float(np.percentile(derivative, 95.0)) if derivative.size else 0.0
    seam_jump_p95 = None
    seam_ratio = None
    if chunk_ms is not None and float(chunk_ms) > 0.0 and audio.size > 1:
        chunk = max(1, int(round(sr * float(chunk_ms) / 1000.0)))
        boundaries = np.arange(chunk, audio.size, chunk, dtype=np.int64)
        if boundaries.size:
            seam_jumps = np.abs(audio[boundaries] - audio[boundaries - 1]).astype(np.float64)
            seam_jump_p95 = float(np.percentile(seam_jumps, 95.0))
            seam_ratio = seam_jump_p95 / max(derivative_p95, 1e-12)

    return {
        "samples": int(audio.size),
        "duration_s": round(audio.size / float(sr), 6),
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": _dbfs(rms),
        "dc_offset": round(float(np.mean(audio, dtype=np.float64)), 7),
        "clipped_ratio": round(float(np.mean(np.abs(audio) >= 0.999)), 7),
        "silence_ratio": round(silence_ratio, 7),
        "derivative_p95_dbfs": _dbfs(derivative_p95),
        "seam_jump_p95_dbfs": _dbfs(seam_jump_p95) if seam_jump_p95 is not None else None,
        "seam_to_baseline_ratio": round(seam_ratio, 4) if seam_ratio is not None else None,
    }


def compare_recording_pair(
    raw_samples,
    converted_samples,
    sample_rate: int,
    *,
    chunk_ms: float | None = None,
) -> dict[str, Any]:
    """Analyze a live A/B capture without treating changed timbre as an error."""
    raw = analyze_signal(raw_samples, sample_rate, chunk_ms=chunk_ms)
    converted = analyze_signal(converted_samples, sample_rate, chunk_ms=chunk_ms)
    return {
        "sample_rate": int(sample_rate),
        "chunk_ms": float(chunk_ms) if chunk_ms is not None else None,
        "duration_delta_ms": round(
            (float(converted["duration_s"]) - float(raw["duration_s"])) * 1000.0,
            3,
        ),
        "raw": raw,
        "converted": converted,
    }
