from __future__ import annotations

import numpy as np

from app.services.voice_engine.quality import analyze_signal, compare_recording_pair


def test_quality_report_detects_a_chunk_boundary_discontinuity():
    sample_rate = 16_000
    chunk = 1_600
    t = np.arange(chunk * 4, dtype=np.float32) / sample_rate
    clean = (0.1 * np.sin(2.0 * np.pi * 200.0 * t)).astype(np.float32)
    broken = clean.copy()
    broken[chunk:] += 0.4

    clean_report = analyze_signal(clean, sample_rate, chunk_ms=100.0)
    broken_report = analyze_signal(broken, sample_rate, chunk_ms=100.0)

    assert clean_report["seam_to_baseline_ratio"] < 2.0
    assert broken_report["seam_to_baseline_ratio"] > 5.0
    assert broken_report["seam_jump_p95_dbfs"] > clean_report["seam_jump_p95_dbfs"]


def test_pair_report_exposes_duration_and_clipping_without_similarity_claims():
    raw = np.zeros(1_600, dtype=np.float32)
    converted = np.ones(1_760, dtype=np.float32)

    report = compare_recording_pair(raw, converted, 16_000, chunk_ms=40.0)

    assert report["duration_delta_ms"] == 10.0
    assert report["raw"]["silence_ratio"] == 1.0
    assert report["converted"]["clipped_ratio"] == 1.0
    assert "similarity" not in report
