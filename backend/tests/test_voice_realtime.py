"""Stub-mode tests for the native realtime voice session (P6R.2)."""

from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from app.config import settings
from app.main import app
from app.services.voice_engine import engine as engine_mod
from app.services.voice_engine import realtime


@pytest.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "voice_models_dir", tmp_path / "voice")
    monkeypatch.setattr(settings, "voice_pretrain_dir", tmp_path / "pretrain")
    monkeypatch.setattr(engine_mod, "_ENGINE", None)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    realtime.stop_session()
    monkeypatch.setattr(engine_mod, "_ENGINE", None)


def _processor_engine(**overrides):
    from types import SimpleNamespace

    values = {
        "cross_fade_overlap_size": 0.0,
        "extra_convert_size": 0.2,
        "input_denoise": "off",
        "silence_threshold_db": -60.0,
        "silence_hold_ms": 0.0,
        "pitch": 0,
        "speaker_id": 0,
        "index_ratio": 0.0,
        "protect": 0.33,
        "noise_scale": 0.15,
        "f0_smoothing": 0.35,
        "f0_detector": "rmvpe",
        "input_highpass_hz": 80,
        "input_gate_db": -90.0,
        "input_formant": 0.0,
        "input_denoise_mix": 0.75,
        "device": "cpu",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_chunk_processor_flushes_tail_after_squelch(monkeypatch):
    import numpy as np

    from app.services.voice_engine import pipeline

    def fake_convert_audio(audio_16k, loaded, **kwargs):  # noqa: ARG001
        return np.ones(len(audio_16k), dtype=np.float32) * 0.25, 16000, {"fake_convert": 1.0}

    monkeypatch.setattr(pipeline, "convert_audio", fake_convert_audio)

    engine = _processor_engine(silence_threshold_db=-40.0)
    processor = realtime.ChunkProcessor(engine, loaded=object(), stream_sr=16000)
    # One conversion block at 16 kHz (chunk 1280 -> block 1280): each call
    # processes exactly one block, so squelch state is per-call deterministic.
    # 437.5 Hz fits the block exactly (35 periods), so the voice -> silence
    # edge does not ring the streaming high-pass above the squelch threshold.
    n = 1280
    t = np.arange(n, dtype=np.float32) / 16000.0
    voice = (0.1 * np.sin(2.0 * np.pi * 437.5 * t)).astype(np.float32)
    silence = np.zeros(n, dtype=np.float32)

    first = processor.process(voice)
    assert processor.last_timings["squelched"] is False
    assert np.max(np.abs(first)) > 0.0

    tail = processor.process(silence)
    assert processor.last_timings["squelched"] is False
    assert processor.last_timings["tail_flush"] is True
    assert np.max(np.abs(tail)) > 0.0

    out = tail
    for _ in range(8):
        out = processor.process(silence)
    assert processor.last_timings["squelched"] is True
    assert np.allclose(out, 0.0)


def test_chunk_processor_output_rate_is_exact(monkeypatch):
    """Variable-length block outputs must add up to the input duration (the
    output ring absorbs jitter, but the long-run rate has to be sample-exact
    modulo the constant stitch/resampler holdback)."""
    import numpy as np

    from app.services.voice_engine import pipeline

    def fake_convert_audio(audio_16k, loaded, **kwargs):  # noqa: ARG001
        return np.ones(len(audio_16k), dtype=np.float32) * 0.25, 16000, {"fake_convert": 1.0}

    monkeypatch.setattr(pipeline, "convert_audio", fake_convert_audio)

    engine = _processor_engine(silence_threshold_db=-90.0, cross_fade_overlap_size=0.05)
    processor = realtime.ChunkProcessor(engine, loaded=object(), stream_sr=48000)
    rng = np.random.default_rng(7)
    chunk_samples = 17024  # 133 * 128, not a multiple of any analysis hop
    total_in = 0
    total_out = 0
    for _ in range(20):
        chunk = (0.1 * rng.standard_normal(chunk_samples)).astype(np.float32)
        out = processor.process(chunk)
        assert np.all(np.isfinite(out))
        total_in += chunk_samples
        total_out += len(out)
    # Holdback: SOLA fade+search + resampler delay + up to one block in the FIFO.
    assert total_in - 2 * chunk_samples <= total_out <= total_in


def test_chunk_processor_blends_realtime_denoise_mix(monkeypatch):
    import numpy as np

    from app.services.voice_engine import pipeline

    class ZeroDenoiser:
        def reset(self):
            return None

        def process_stream(self, audio):
            return np.zeros_like(audio, dtype=np.float32)

    def fake_convert_audio(audio_16k, loaded, **kwargs):  # noqa: ARG001
        return np.asarray(audio_16k, dtype=np.float32), 16000, {"fake_convert": 1.0}

    monkeypatch.setattr(pipeline, "convert_audio", fake_convert_audio)

    engine = _processor_engine(
        input_denoise="dtln",
        input_denoise_mix=0.25,
        input_highpass_hz=0,
        silence_threshold_db=-90.0,
        extra_convert_size=0.0,
    )
    processor = realtime.ChunkProcessor(engine, loaded=object(), stream_sr=16000, denoiser=ZeroDenoiser())
    out = processor.process(np.ones(640, dtype=np.float32))

    assert processor.last_timings["input_denoise_mix"] == 0.25
    assert np.allclose(out, 0.75, atol=1e-6)


async def test_session_lifecycle_and_metrics(client):
    before = (await client.get("/api/voice/engine/status")).json()
    assert before["live"] is False
    assert before["metrics"]["input_vu"] == 0.0
    assert before["metrics"]["squelched"] is False
    assert before["session_config"] is None

    started = await client.post("/api/voice/engine/session/start", json={"model_id": "stub-voice"})
    assert started.status_code == 200
    body = started.json()
    assert body["live"] is True
    assert body["recording"]["active"] is False
    metrics = body["metrics"]
    assert 0.0 < metrics["input_vu"] <= 1.0
    assert 0.0 < metrics["output_vu"] <= 1.0
    assert metrics["total_ms"] == 5.0
    assert metrics["total_p95_ms"] == 5.0
    assert metrics["chunk_ms"] > 0
    assert metrics["latency_headroom_ms"] == pytest.approx(metrics["chunk_ms"] - 5.0)
    assert metrics["output_peak"] > 0.0
    assert metrics["provider_health"]["content_vec"]["actual"] == "stub"
    assert metrics["squelched"] is False
    assert body["session_config"]["server_audio_sample_rate"] == body["settings"]["server_audio_sample_rate"]
    assert body["session_config"]["server_read_chunk_size"] == body["settings"]["server_read_chunk_size"]

    # A second start while live is refused.
    again = await client.post("/api/voice/engine/session/start", json={"model_id": "stub-voice"})
    assert again.status_code == 409

    stopped = await client.post("/api/voice/engine/session/stop")
    assert stopped.status_code == 200
    assert stopped.json()["live"] is False


async def test_session_records_live_phrase(client):
    assert (await client.post("/api/voice/engine/recording/start")).status_code == 409

    start = await client.post("/api/voice/engine/session/start", json={"model_id": "stub-voice"})
    assert start.status_code == 200

    rec = await client.post("/api/voice/engine/recording/start")
    assert rec.status_code == 200
    assert rec.json()["recording"]["active"] is True

    await asyncio.sleep(0.05)
    done = await client.post("/api/voice/engine/recording/stop")
    assert done.status_code == 200
    body = done.json()
    assert body["recording"]["active"] is False
    result = body["recording_result"]
    assert result["duration_s"] > 0
    assert result["sample_rate"] == body["settings"]["server_audio_sample_rate"]

    wav = await client.get(result["url"])
    assert wav.status_code == 200
    assert wav.content.startswith(b"RIFF")

    stopped = await client.post("/api/voice/engine/session/stop")
    assert stopped.status_code == 200


async def test_session_start_unknown_model_404(client):
    response = await client.post("/api/voice/engine/session/start", json={"model_id": "nope"})
    assert response.status_code == 404
    assert not realtime.session_active()


async def test_voice_lane_parks_queued_jobs(client):
    """A queued GPU job must stay QUEUED while a native session is live and
    run after the session stops (the worker's voice lane)."""
    start = await client.post("/api/voice/engine/session/start", json={"model_id": "stub-voice"})
    assert start.status_code == 200

    models = (await client.get("/api/models")).json()
    image_model = next(m for m in models if m["job_type"] == "image")
    job = (await client.post("/api/jobs", json=[{
        "type": "image",
        "model_id": image_model["id"],
        "params": {"prompt": "voice lane parking test", "steps": 1},
    }])).json()[0]

    # Give the worker a few scheduler ticks: the job must NOT start.
    for _ in range(6):
        await asyncio.sleep(0.05)
        current = (await client.get(f"/api/jobs/{job['id']}")).json()
        assert current["status"] == "queued"

    stop = await client.post("/api/voice/engine/session/stop")
    assert stop.status_code == 200

    async def wait_done() -> str:
        while True:
            state = (await client.get(f"/api/jobs/{job['id']}")).json()
            if state["status"] in {"done", "error"}:
                return state["status"]
            await asyncio.sleep(0.05)

    status = await asyncio.wait_for(wait_done(), timeout=10.0)
    assert status == "done"
