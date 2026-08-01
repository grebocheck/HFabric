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


def test_fixed_ring_wraps_pads_and_drops_oldest():
    import numpy as np

    ring = realtime._Ring(8)
    ring.push(np.arange(6, dtype=np.float32))
    first, missing = ring.pull(4)
    assert missing == 0
    assert np.array_equal(first, np.arange(4, dtype=np.float32))

    ring.push(np.arange(6, 12, dtype=np.float32))
    # The write wraps around the fixed allocation without changing order.
    assert ring.available() == 8
    out, missing = ring.pull(10)
    assert missing == 2
    assert np.array_equal(out[:8], np.arange(4, 12, dtype=np.float32))
    assert np.allclose(out[8:], 0.0)


def test_ring_sample_clock_survives_wrap_and_interpolates_timestamps():
    import numpy as np

    ring = realtime._Ring(8)
    clock = realtime._SampleClock()
    first_index = ring.push(np.arange(6, dtype=np.float32))
    clock.mark(first_index, 10.0)
    ring.pull(4)
    second_index = ring.push(np.arange(6, 12, dtype=np.float32))
    clock.mark(second_index, 10.006)

    _out, missing, start_index = ring.pull_with_index(4)

    assert missing == 0
    assert start_index == 4
    assert clock.resolve(start_index, 1000) == pytest.approx(10.004)


def test_clock_drift_estimator_reports_relative_ppm_after_warmup():
    estimator = realtime._ClockDriftEstimator(window_seconds=30.0)

    transport, drift = estimator.update(99.9, 100.1, 100.0)
    assert transport == pytest.approx(200.0)
    assert drift is None

    # Capture/render separation grows by 1 ms across ten seconds: 100 ppm.
    transport, drift = estimator.update(109.9, 110.101, 110.0)
    assert transport == pytest.approx(201.0)
    assert drift == pytest.approx(100.0)


async def test_audio_io_operations_keep_one_owner_thread():
    import threading

    thread_ids = await asyncio.gather(
        realtime.run_audio_io(threading.get_ident),
        realtime.run_audio_io(threading.get_ident),
        realtime.run_audio_io(threading.get_ident),
    )

    assert len(set(thread_ids)) == 1


def test_realtime_stop_accepts_a_worker_that_never_started(monkeypatch):
    import threading
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "stub_mode", True)
    engine = SimpleNamespace(provider_health=lambda: {})
    session = realtime.RealtimeSession(engine)
    session._worker = threading.Thread(target=lambda: None)

    session.stop()

    assert session._worker is None


def test_start_session_preserves_startup_error_when_cleanup_fails(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "stub_mode", False)
    monkeypatch.setattr(realtime, "_SESSION", None)

    def fail_start(self, model_id):  # noqa: ARG001
        raise OSError("audio device unavailable")

    def fail_cleanup(self):  # noqa: ARG001
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(realtime.RealtimeSession, "start", fail_start)
    monkeypatch.setattr(realtime.RealtimeSession, "stop", fail_cleanup)
    engine = SimpleNamespace(provider_health=lambda: {})

    with pytest.raises(OSError, match="audio device unavailable"):
        realtime.start_session(engine, "voice")

    assert realtime.current_session() is None


def test_sola_crossfade_preserves_unity_gain_for_identical_overlap():
    import numpy as np

    engine = _processor_engine(cross_fade_overlap_size=0.02)
    processor = realtime.ChunkProcessor(engine, loaded=object(), stream_sr=16000)
    processor._block_16k = 640
    fade = int(0.02 * 16000)
    processor._sola_buf = np.ones(fade, dtype=np.float32)
    converted = np.ones(640 + fade + 160, dtype=np.float32)

    stitched = processor._stitch(converted, 16000)

    assert len(stitched) == 640
    assert np.allclose(stitched, 1.0, atol=1e-6)


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


def test_chunk_processor_splits_raw_f0_from_denoised_content_and_limits_synth_tail(monkeypatch):
    import numpy as np

    from app.services.voice_engine import pipeline

    captured: dict[str, np.ndarray | int] = {}

    class ZeroDenoiser:
        def reset(self):
            return None

        def process_stream(self, audio):
            return np.zeros_like(audio, dtype=np.float32)

    def fake_convert_audio(audio_16k, loaded, **kwargs):  # noqa: ARG001
        captured["content"] = np.asarray(audio_16k, dtype=np.float32)
        captured["f0"] = np.asarray(kwargs["f0_audio_16k"], dtype=np.float32)
        captured["tail"] = int(kwargs["synthesis_tail_frames"])
        return np.zeros(len(audio_16k), dtype=np.float32), 16000, {"fake_convert": 1.0}

    monkeypatch.setattr(pipeline, "convert_audio", fake_convert_audio)
    engine = _processor_engine(
        input_denoise="dtln",
        input_denoise_mix=1.0,
        input_highpass_hz=0,
        silence_threshold_db=-90.0,
        extra_convert_size=1.0,
        cross_fade_overlap_size=0.03,
    )
    processor = realtime.ChunkProcessor(
        engine,
        loaded=object(),
        stream_sr=16000,
        denoiser=ZeroDenoiser(),
    )
    t = np.arange(640, dtype=np.float32) / 16000.0
    processor.process((0.1 * np.sin(2.0 * np.pi * 120.0 * t)).astype(np.float32))

    assert np.allclose(captured["content"], 0.0)
    assert np.max(np.abs(captured["f0"])) > 0.01
    assert 4 <= captured["tail"] < len(captured["content"]) // 160


def test_idle_squelch_keeps_streaming_resampler_instance(monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from app.services.voice_engine import pipeline

    def fake_convert_audio(audio_16k, loaded, **kwargs):  # noqa: ARG001
        return np.ones(len(audio_16k), dtype=np.float32) * 0.2, 16000, {"fake_convert": 1.0}

    monkeypatch.setattr(pipeline, "convert_audio", fake_convert_audio)
    engine = _processor_engine(silence_threshold_db=-40.0, silence_hold_ms=0.0)
    processor = realtime.ChunkProcessor(
        engine,
        loaded=SimpleNamespace(sample_rate=16000),
        stream_sr=48000,
    )
    rng = np.random.default_rng(8)
    for _ in range(2):
        processor.process((0.1 * rng.standard_normal(1920)).astype(np.float32))
    resampler = processor._out_rs
    assert resampler is not None

    for _ in range(8):
        processor.process(np.zeros(1920, dtype=np.float32))

    assert processor.last_timings["squelched"] is True
    assert processor.last_timings["idle_fade"] is True
    assert processor._out_rs is resampler


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
    assert metrics["estimated_latency_ms"] >= metrics["chunk_ms"]
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


async def test_session_start_rejects_pinned_llm_without_partial_handoff(client):
    enabled = await client.post(
        "/api/llm/server",
        json={"enabled": True, "model_id": "stub-llm"},
    )
    assert enabled.status_code == 200

    response = await client.post(
        "/api/voice/engine/session/start",
        json={"model_id": "stub-voice"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "resident_pinned"
    assert not realtime.session_active()
    gpu = (await client.get("/api/gpu")).json()
    assert gpu["model_id"] == "stub-llm"
    assert gpu["pin"]["id"] == "llm_api"
    assert gpu["lanes"] == []

    assert (
        await client.post(
            "/api/llm/server",
            json={"enabled": False},
        )
    ).status_code == 200


async def test_session_start_failure_rolls_back_voice_lane(client, monkeypatch):
    previous = app.state.registry.get_backend("stub-llm")
    await app.state.arbiter.ensure(previous)

    def fail_start(*args, **kwargs):  # noqa: ARG001
        raise OSError("device unavailable")

    monkeypatch.setattr(realtime, "start_session", fail_start)
    response = await client.post(
        "/api/voice/engine/session/start",
        json={"model_id": "stub-voice"},
    )

    assert response.status_code == 500
    assert not realtime.session_active()
    assert (await client.get("/api/gpu")).json()["lanes"] == []
    assert app.state.arbiter.current is previous
    assert previous.loaded


async def test_session_stop_releases_lane_when_audio_teardown_fails(client, monkeypatch):
    started = await client.post(
        "/api/voice/engine/session/start",
        json={"model_id": "stub-voice"},
    )
    assert started.status_code == 200
    original_stop = realtime.stop_session

    def fail_stop() -> bool:
        raise OSError("device teardown failed")

    monkeypatch.setattr(realtime, "stop_session", fail_stop)
    response = await client.post("/api/voice/engine/session/stop")

    assert response.status_code == 500
    assert (await client.get("/api/gpu")).json()["lanes"] == []

    # Restore before the fixture's own defensive teardown.
    monkeypatch.setattr(realtime, "stop_session", original_stop)
    original_stop()


async def test_app_shutdown_stops_realtime_and_clears_voice_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "shutdown-data")
    monkeypatch.setattr(settings, "voice_models_dir", tmp_path / "shutdown-voice")
    monkeypatch.setattr(settings, "voice_pretrain_dir", tmp_path / "shutdown-pretrain")
    monkeypatch.setattr(engine_mod, "_ENGINE", None)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as shutdown_client:
            started = await shutdown_client.post(
                "/api/voice/engine/session/start",
                json={"model_id": "stub-voice"},
            )
            assert started.status_code == 200
            arbiter = app.state.arbiter
            assert arbiter.status()["lanes"] == [{"id": "voice", "label": "voice session"}]

    assert not realtime.session_active()
    assert arbiter.status()["lanes"] == []
    assert arbiter.current is None


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
    assert result["raw_token"]
    assert result["raw_url"].startswith("/api/voice/engine/file/")
    assert result["metadata_url"].endswith("/json")

    wav = await client.get(result["url"])
    assert wav.status_code == 200
    assert wav.content.startswith(b"RIFF")

    raw = await client.get(result["raw_url"])
    assert raw.status_code == 200
    assert raw.content.startswith(b"RIFF")

    metadata = (await client.get(result["metadata_url"])).json()
    assert metadata["kind"] == "voice_ab_capture"
    assert metadata["token"] == result["token"]
    assert metadata["raw_token"] == result["raw_token"]
    assert metadata["settings"]["server_audio_sample_rate"] == result["sample_rate"]

    stopped = await client.post("/api/voice/engine/session/stop")
    assert stopped.status_code == 200


async def test_recording_stop_device_failure_keeps_session_state_consistent(client, monkeypatch):
    assert (
        await client.post(
            "/api/voice/engine/session/start",
            json={"model_id": "stub-voice"},
        )
    ).status_code == 200
    assert (await client.post("/api/voice/engine/recording/start")).status_code == 200
    session = realtime.current_session()
    assert session is not None

    def fail_recording_stop():
        raise RuntimeError("input device failed")

    monkeypatch.setattr(session, "stop_recording", fail_recording_stop)
    response = await client.post("/api/voice/engine/recording/stop")

    assert response.status_code == 409
    assert realtime.session_active()
    assert (await client.get("/api/gpu")).json()["lanes"] == [{"id": "voice", "label": "voice session"}]
    assert (await client.post("/api/voice/engine/session/stop")).status_code == 200


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
    job = (
        await client.post(
            "/api/jobs",
            json=[
                {
                    "type": "image",
                    "model_id": image_model["id"],
                    "params": {"prompt": "voice lane parking test", "steps": 1},
                }
            ],
        )
    ).json()[0]

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
