#!/usr/bin/env python3
"""Benchmark the native realtime RVC chunk processor without audio devices."""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time
import warnings

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.voice_engine import assets as asset_discovery  # noqa: E402
from app.services.voice_engine import pipeline  # noqa: E402
from app.services.voice_engine.engine import get_engine  # noqa: E402
from app.services.voice_engine.realtime import CHUNK_UNIT_SAMPLES, ChunkProcessor  # noqa: E402

DEFAULT_MODEL_ID = "chocola_yagiyukiv2"
CHUNK_SIZES = (96, 133, 192)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--chunks", type=int, default=20)
    parser.add_argument("--stream-sr", type=int, default=48_000)
    return parser.parse_args()


def synth_voice_like(sr: int, samples: int) -> np.ndarray:
    """Same sawtooth/formant recipe as the smoke test, sized to exact chunks."""
    t = np.arange(samples, dtype=np.float32) / sr
    f0 = 150.0 * (1.0 + 0.02 * np.sin(2.0 * np.pi * 3.1 * t))
    phase = np.cumsum(f0, dtype=np.float64) / sr
    saw = (2.0 * (phase - np.floor(phase)) - 1.0).astype(np.float32)

    freqs = np.fft.rfftfreq(samples, 1.0 / sr)
    spectrum = np.fft.rfft(saw)
    envelope = (
        0.08
        + 1.00 * np.exp(-0.5 * ((freqs - 700.0) / 120.0) ** 2)
        + 0.75 * np.exp(-0.5 * ((freqs - 1220.0) / 160.0) ** 2)
        + 0.45 * np.exp(-0.5 * ((freqs - 2600.0) / 260.0) ** 2)
    )
    voice = np.fft.irfft(spectrum * envelope, n=samples).astype(np.float32)
    amp = (0.72 + 0.28 * np.sin(2.0 * np.pi * 4.5 * t + 0.3)).astype(np.float32)
    voice *= amp
    peak = float(np.max(np.abs(voice))) if voice.size else 0.0
    if peak > 0:
        voice = voice / peak
    return (0.35 * voice).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return float(np.percentile(np.asarray(values, dtype=np.float64), 95))


def require_assets() -> dict[str, str]:
    found = asset_discovery.discover_assets()
    for item in found["assets"]:
        print(f"asset {item['name']}: found={item['found']} source={item['source']} path={item['path']}")
    if not found["ready"]:
        missing = ", ".join(str(item["name"]) for item in found["assets"] if not item["found"])
        searched = ", ".join(asset_discovery.searched_dirs())
        raise RuntimeError(f"missing required asset(s): {missing}; searched {searched}")
    return {str(item["name"]): str(item["path"]) for item in found["assets"]}


def choose_model_id(requested: str) -> str:
    engine = get_engine()
    models = engine.models()
    if any(model["id"] == requested for model in models):
        return requested
    chocola = next((model["id"] for model in models if "chocola_yagiyukiv2" in model["id"].lower()), None)
    if chocola:
        return str(chocola)
    if models:
        available = ", ".join(str(model["id"]) for model in models)
        raise RuntimeError(f"model {requested!r} not found; available models: {available}")
    searched = str(settings.voice_models_dir)
    raise RuntimeError(f"no voice models found; searched {searched}")


def bench_chunk_size(
    loaded: object,
    chunk_size: int,
    chunks: int,
    stream_sr: int,
) -> tuple[dict[str, float | bool], np.ndarray, np.ndarray]:
    import soxr  # noqa: PLC0415

    engine = get_engine()
    chunk_samples = chunk_size * CHUNK_UNIT_SAMPLES
    signal = synth_voice_like(stream_sr, chunk_samples * chunks)
    processor = ChunkProcessor(engine, loaded, stream_sr)
    outputs: list[np.ndarray] = []
    timings: list[float] = []

    for i in range(chunks):
        chunk = signal[i * chunk_samples : (i + 1) * chunk_samples]
        start = time.perf_counter()
        out = processor.process(chunk)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(float(processor.last_timings.get("total", elapsed_ms)))
        outputs.append(out)

    stitched = np.concatenate(outputs).astype(np.float32) if outputs else np.zeros(0, dtype=np.float32)
    input_16k = soxr.resample(signal, stream_sr, 16_000).astype(np.float32)
    offline, model_sr, _offline_timings = pipeline.convert_audio(
        input_16k,
        loaded,
        pitch=engine.pitch,
        index_ratio=engine.index_ratio,
        protect=engine.protect,
        f0_detector=engine.f0_detector,
        input_highpass_hz=engine.input_highpass_hz,
        input_gate_db=engine.input_gate_db,
        input_formant=engine.input_formant,
        device=engine.device,
    )
    offline_stream = soxr.resample(offline, model_sr, stream_sr).astype(np.float32)
    if len(offline_stream) < len(stitched):
        offline_stream = np.pad(offline_stream, (0, len(stitched) - len(offline_stream)))
    else:
        offline_stream = offline_stream[: len(stitched)]

    chunk_ms = chunk_samples / stream_sr * 1000.0
    mean_ms = statistics.fmean(timings)
    result = {
        "chunk_size": float(chunk_size),
        "chunk_ms": chunk_ms,
        "mean_ms": mean_ms,
        "p95_ms": p95(timings),
        "realtime": mean_ms < chunk_ms,
        "stitched_rms": rms(stitched),
        "offline_rms": rms(offline_stream),
    }
    return result, stitched, offline_stream


def validate_stream(chunk_size: int, stitched: np.ndarray, offline: np.ndarray, expected_len: int) -> None:
    if not np.all(np.isfinite(stitched)):
        raise AssertionError(f"chunk {chunk_size}: stitched output contains NaN or Inf")
    # The processor emits in conversion-block bursts and holds back the SOLA
    # seam + resampler delay, so the total is a bit short of the input length
    # but must stay within two chunks of it (rate-exact long-run).
    chunk_samples = chunk_size * CHUNK_UNIT_SAMPLES
    if not (expected_len - 2 * chunk_samples <= len(stitched) <= expected_len):
        raise AssertionError(
            f"chunk {chunk_size}: expected ~{expected_len} output samples (-2 chunks), got {len(stitched)}"
        )
    stitched_rms = rms(stitched)
    offline_rms = rms(offline)
    if offline_rms <= 1e-8:
        raise AssertionError(f"chunk {chunk_size}: offline output RMS is too close to silence")
    ratio = stitched_rms / offline_rms
    if not (0.70 <= ratio <= 1.30):
        raise AssertionError(
            f"chunk {chunk_size}: stitched RMS {stitched_rms:.6f} is not within 30% "
            f"of offline RMS {offline_rms:.6f} (ratio {ratio:.3f})"
        )


def validate_squelch_segment(
    loaded: object,
    stream_sr: int,
) -> dict[str, float | int]:
    engine = get_engine()
    old_threshold = engine.silence_threshold_db
    old_hold = engine.silence_hold_ms
    old_crossfade = engine.cross_fade_overlap_size
    old_extra = engine.extra_convert_size
    try:
        engine.silence_threshold_db = -48.0
        engine.silence_hold_ms = 400.0
        engine.cross_fade_overlap_size = 0.05
        engine.extra_convert_size = 2.0

        chunk_size = 133
        chunk_samples = chunk_size * CHUNK_UNIT_SAMPLES
        voiced = synth_voice_like(stream_sr, chunk_samples)
        silent = np.zeros(chunk_samples, dtype=np.float32)
        silent_count = 8
        chunks: list[tuple[str, np.ndarray]] = [
            ("voice-pre-1", voiced),
            ("voice-pre-2", voiced),
            *[(f"silence-{i + 1}", silent) for i in range(silent_count)],
            ("voice-after-1", voiced),
            ("voice-after-2", voiced),
        ]
        processor = ChunkProcessor(engine, loaded, stream_sr)
        records: list[dict[str, object]] = []

        for label, chunk in chunks:
            start = time.perf_counter()
            out = processor.process(chunk)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            timings = dict(processor.last_timings)
            records.append({
                "label": label,
                "out": out,
                "elapsed_ms": elapsed_ms,
                "timings": timings,
                "squelched": bool(timings.get("squelched", False)),
                "total_ms": float(timings.get("total", elapsed_ms)),
            })

        silence_records = [record for record in records if str(record["label"]).startswith("silence")]
        squelched = [record for record in silence_records if record["squelched"]]
        if len(squelched) < 3:
            raise AssertionError(f"squelch segment: only {len(squelched)} of {silent_count} silent chunks squelched")

        # Once the post-speech flush is exhausted (the first ~2 silent blocks
        # keep converting on purpose), squelched calls must emit pure zeros,
        # skip all conversion stages, and cost almost nothing.
        skipped_keys = {"content_vec", "f0", "synth"}
        for record in silence_records[-3:]:
            out = np.asarray(record["out"], dtype=np.float32)
            timings = dict(record["timings"])  # type: ignore[arg-type]
            total_ms = float(record["total_ms"])
            if not record["squelched"]:
                raise AssertionError(f"squelch segment: {record['label']} was not squelched")
            if not np.allclose(out, 0.0, atol=0.0):
                raise AssertionError(f"squelch segment: {record['label']} did not output pure zeros")
            if skipped_keys & set(timings):
                raise AssertionError(f"squelch segment: {record['label']} ran conversion stages: {timings}")
            # The streaming input chain (resample/DTLN/HPF) still runs while
            # squelched so the stream stays gapless; only conversion is skipped.
            if total_ms >= 50.0:
                raise AssertionError(f"squelch segment: {record['label']} took {total_ms:.3f} ms, expected < 50 ms")

        after_records = records[-2:]
        after_out = np.concatenate([np.asarray(record["out"], dtype=np.float32) for record in after_records])
        if not np.all(np.isfinite(after_out)):
            raise AssertionError("squelch segment: voiced audio after silence contains NaN or Inf")
        after_rms = rms(after_out)
        if after_rms <= 1e-6:
            raise AssertionError(f"squelch segment: voiced audio after silence is too quiet ({after_rms:.8f})")
        if not any("synth" in dict(record["timings"]) for record in after_records):  # type: ignore[arg-type]
            raise AssertionError("squelch segment: voiced chunks after silence did not convert")

        return {
            "chunk_size": chunk_size,
            "silent_chunks": silent_count,
            "squelched_chunks": len(squelched),
            "max_squelched_ms": max(float(record["total_ms"]) for record in silence_records[-3:]),
            "first_voice_after_ms": float(after_records[0]["total_ms"]),
            "first_voice_after_rms": after_rms,
        }
    finally:
        engine.silence_threshold_db = old_threshold
        engine.silence_hold_ms = old_hold
        engine.cross_fade_overlap_size = old_crossfade
        engine.extra_convert_size = old_extra


def main() -> int:
    args = parse_args()
    warnings.filterwarnings(
        "ignore",
        message="`torch.nn.utils.weight_norm` is deprecated.*",
        category=FutureWarning,
    )
    np.random.seed(1234)
    torch.manual_seed(1234)
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but torch.cuda.is_available() is false")

    settings.stub_mode = False
    settings.voice_device = args.device
    require_assets()

    engine = get_engine()
    engine.device = args.device
    model_id = choose_model_id(args.model_id)
    print(f"model: {model_id}")
    print(f"device: {args.device}")
    print(
        "settings: "
        f"pitch={engine.pitch} index_ratio={engine.index_ratio} protect={engine.protect} "
        f"f0_detector={engine.f0_detector}"
    )
    loaded = engine.load_model_sync(model_id)

    print("chunk_size,chunk_ms,mean_ms,p95_ms,realtime,stitched_rms,offline_rms")
    for chunk_size in CHUNK_SIZES:
        chunk_samples = chunk_size * CHUNK_UNIT_SAMPLES
        result, stitched, offline = bench_chunk_size(loaded, chunk_size, args.chunks, args.stream_sr)
        validate_stream(chunk_size, stitched, offline, chunk_samples * args.chunks)
        print(
            f"{chunk_size},"
            f"{result['chunk_ms']:.1f},"
            f"{result['mean_ms']:.1f},"
            f"{result['p95_ms']:.1f},"
            f"{'yes' if result['realtime'] else 'no'},"
            f"{result['stitched_rms']:.6f},"
            f"{result['offline_rms']:.6f}"
        )
    squelch = validate_squelch_segment(loaded, args.stream_sr)
    print(
        "squelch_segment: "
        f"chunk_size={squelch['chunk_size']} "
        f"silent_chunks={squelch['silent_chunks']} "
        f"squelched_chunks={squelch['squelched_chunks']} "
        f"max_squelched_ms={squelch['max_squelched_ms']:.3f} "
        f"first_voice_after_ms={squelch['first_voice_after_ms']:.1f} "
        f"first_voice_after_rms={squelch['first_voice_after_rms']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
