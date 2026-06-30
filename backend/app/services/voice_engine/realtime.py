"""Native realtime voice session (P6R.2).

A live session owns a sounddevice duplex stream: the PortAudio callback only
moves samples in/out of ring buffers; a dedicated worker thread pulls fixed
chunks and feeds them to ``ChunkProcessor``, which runs a fully streaming
input chain (stateful resample to 16 kHz -> DTLN -> high-pass -> formant
resample), advances a fixed-length conversion context in blocks aligned to the
feature frame grid, re-converts through the shared ``pipeline.convert_audio``
core with latent noise pinned per absolute frame, and stitches seams with SOLA
+ equal-power crossfade in the model domain before a streaming output
resampler. Every stage that touches audio keeps state across calls so no
per-chunk filter edges are baked into the stream.

Threading model: the audio callback and the worker communicate through
``_InputRing`` / ``_OutputRing`` (lock-guarded deques of float32 samples);
settings are read from the ``VoiceEngine`` once per chunk (plain attribute
reads — atomic enough in CPython for floats/ints), so pitch/index/protect/
gain/pass-through changes apply on the next chunk without a restart.

STUB mode never imports sounddevice/torch: ``StubRealtimeSession`` just flips
``live`` and synthesizes deterministic VU/timing values so the API, the UI,
and the voice-lane parking are all testable in CI.
"""

from __future__ import annotations

from collections import deque
import logging
import math
import threading
import time
from typing import TYPE_CHECKING, Any

from ...config import settings
from . import dsp
from .realtime_processor import ChunkProcessor

if TYPE_CHECKING:
    from .engine import VoiceEngine

# w-okada convention kept for UI parity: read chunk = N * 128 samples.
CHUNK_UNIT_SAMPLES = 128
logger = logging.getLogger("hfabric")
MAX_RECORD_SECONDS = 180.0
RECORD_STOP_GRACE_MS = 650.0
LATENCY_HISTORY = 96
LATENCY_WARN_RATIO = 0.80


def _write_wav(path, samples, sample_rate: int) -> None:
    import wave  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * np.float32(32767.0)).astype("<i2", copy=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(int(sample_rate))
        writer.writeframes(pcm.tobytes())


class _Ring:
    """A minimal lock-guarded float32 sample FIFO (numpy-backed)."""

    def __init__(self) -> None:
        import numpy as np  # noqa: PLC0415

        self._np = np
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()

    def push(self, samples) -> None:
        with self._lock:
            self._buf = self._np.concatenate([self._buf, samples.astype(self._np.float32, copy=False)])

    def pull(self, count: int):
        """Take exactly ``count`` samples; missing samples are zero-padded.
        Returns (samples, missing_count)."""
        with self._lock:
            have = len(self._buf)
            if have >= count:
                out, self._buf = self._buf[:count], self._buf[count:]
                return out, 0
            out = self._np.concatenate([self._buf, self._np.zeros(count - have, dtype=self._np.float32)])
            self._buf = self._buf[:0]
            return out, count - have

    def available(self) -> int:
        with self._lock:
            return len(self._buf)

    def drop_to(self, max_samples: int) -> int:
        """Bound the queue (drop oldest); returns how many were dropped."""
        with self._lock:
            extra = len(self._buf) - max_samples
            if extra > 0:
                self._buf = self._buf[extra:]
                return extra
            return 0



def _rms(samples) -> float:
    import numpy as np  # noqa: PLC0415

    if len(samples) == 0:
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(np.square(samples))) * 4.0))


def _rolling_p95(values) -> float | None:
    items = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not items:
        return None
    idx = max(0, min(len(items) - 1, math.ceil(len(items) * 0.95) - 1))
    return round(items[idx], 3)


def _latency_warning(total_p95_ms: float | None, chunk_ms: float | None) -> str | None:
    if total_p95_ms is None or chunk_ms is None or chunk_ms <= 0:
        return None
    if total_p95_ms < chunk_ms * LATENCY_WARN_RATIO:
        return None
    return (
        "Realtime p95 is near the chunk budget; reduce extra buffer, switch RMVPE to FCPE, "
        "turn denoise off, or raise chunk size."
    )


class RealtimeSession:
    """Owns the duplex stream + worker thread for one live voice session."""

    def __init__(self, engine: VoiceEngine) -> None:
        self._engine = engine
        self._stream = None
        self._monitor_stream = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, Any] = {
            "input_vu": 0.0,
            "output_vu": 0.0,
            "output_peak": 0.0,
            "output_peak_dbfs": None,
            "limiter_reduction_db": 0.0,
            "timings_ms": {},
            "total_ms": None,
            "total_p95_ms": None,
            "chunk_ms": None,
            "latency_headroom_ms": None,
            "latency_warning": None,
            "provider_health": engine.provider_health(),
            "overruns": 0,
            "underruns": 0,
            "squelched": False,
        }
        self._latency_totals_ms: deque[float] = deque(maxlen=LATENCY_HISTORY)
        self._input_ring: _Ring | None = None
        self._output_ring: _Ring | None = None
        self._monitor_ring: _Ring | None = None
        self._processor: ChunkProcessor | None = None
        self._recording_lock = threading.Lock()
        self._recording_frames: list[Any] = []
        self._recording_started: float | None = None
        self._recording_sample_rate = 48_000
        self.stream_sr = 48000
        self.chunk_samples = 0
        self.error: str | None = None
        self._session_config: dict[str, int | None] | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self, model_id: str) -> None:
        import sounddevice as sd  # noqa: PLC0415

        engine = self._engine
        loaded = engine.load_model_sync(model_id)
        denoiser = engine.denoiser_sync()
        if denoiser is not None:
            denoiser.reset()
        self.stream_sr = int(engine.server_audio_sample_rate)
        self.chunk_samples = max(1, int(engine.server_read_chunk_size)) * CHUNK_UNIT_SAMPLES
        self._session_config = {
            "server_input_device_id": engine.server_input_device_id,
            "server_output_device_id": engine.server_output_device_id,
            "server_monitor_device_id": engine.server_monitor_device_id,
            "server_audio_sample_rate": self.stream_sr,
            "server_read_chunk_size": int(engine.server_read_chunk_size),
        }
        self._input_ring = _Ring()
        self._output_ring = _Ring()
        self._processor = ChunkProcessor(engine, loaded, self.stream_sr, denoiser=denoiser)
        # The processor emits audio in conversion-block bursts that are close
        # to but not exactly one chunk; one chunk of zero prefill absorbs that
        # jitter so the playback callback never starves between bursts.
        import numpy as np  # noqa: PLC0415

        self._output_ring.push(np.zeros(self.chunk_samples, dtype=np.float32))
        with self._metrics_lock:
            self._metrics["chunk_ms"] = round(self.chunk_samples / self.stream_sr * 1000, 1)
            self._metrics["provider_health"] = engine.provider_health()

        in_dev = engine.server_input_device_id
        out_dev = engine.server_output_device_id
        mon_dev = engine.server_monitor_device_id

        def callback(indata, outdata, frames, time_info, status) -> None:  # noqa: ARG001
            import numpy as np  # noqa: PLC0415

            assert self._input_ring is not None and self._output_ring is not None
            self._input_ring.push(indata[:, 0])
            # Bound the input queue to ~2s so a stalled worker degrades
            # (drops old audio) instead of growing without limit.
            dropped = self._input_ring.drop_to(self.stream_sr * 2)
            samples, missing = self._output_ring.pull(frames)
            rendered, limiter = dsp.limit_output(samples * float(self._engine.server_output_gain))
            if missing or dropped:
                with self._metrics_lock:
                    self._metrics["underruns"] += 1 if missing else 0
                    self._metrics["overruns"] += 1 if dropped else 0
            with self._metrics_lock:
                self._metrics["output_peak"] = limiter["peak"]
                self._metrics["output_peak_dbfs"] = limiter["peak_dbfs"]
                self._metrics["limiter_reduction_db"] = limiter["limiter_reduction_db"]
            outdata[:] = rendered.reshape(-1, 1).astype(np.float32)

        self._stop.clear()
        self._stream = sd.Stream(
            samplerate=self.stream_sr,
            blocksize=0,
            channels=1,
            dtype="float32",
            device=(
                in_dev if in_dev is not None and in_dev >= 0 else None,
                out_dev if out_dev is not None and out_dev >= 0 else None,
            ),
            callback=callback,
        )
        if mon_dev is not None and mon_dev >= 0 and mon_dev != out_dev:
            self._monitor_ring = _Ring()
            self._monitor_stream = sd.OutputStream(
                samplerate=self.stream_sr,
                blocksize=0,
                channels=1,
                dtype="float32",
                device=mon_dev,
                callback=self._monitor_callback,
            )
        self._worker = threading.Thread(target=self._run, name="hfabric-voice-rt", daemon=True)
        self._stream.start()
        if self._monitor_stream is not None:
            self._monitor_stream.start()
        self._worker.start()

    def _monitor_callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        import numpy as np  # noqa: PLC0415

        assert self._monitor_ring is not None
        samples, _missing = self._monitor_ring.pull(frames)
        rendered, _limiter = dsp.limit_output(samples * float(self._engine.server_monitor_gain))
        outdata[:] = rendered.reshape(-1, 1).astype(np.float32)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            self._worker = None
        for stream in (self._stream, self._monitor_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001 - device teardown must not raise
                    logger.debug("event=voice.realtime.stream_teardown_failed", exc_info=True)
        self._stream = None
        self._monitor_stream = None
        self._processor = None
        if not settings.stub_mode:
            try:
                import torch  # noqa: PLC0415

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - cleanup must not raise during stop
                logger.debug("event=voice.realtime.cuda_cleanup_failed", exc_info=True)

    # --------------------------------------------------------------- worker
    def _run(self) -> None:
        import numpy as np  # noqa: PLC0415

        assert self._input_ring is not None and self._output_ring is not None
        assert self._processor is not None
        wait_s = max(0.001, self.chunk_samples / self.stream_sr / 8)
        while not self._stop.is_set():
            if self._input_ring.available() < self.chunk_samples:
                time.sleep(wait_s)
                continue
            chunk, _ = self._input_ring.pull(self.chunk_samples)
            chunk = chunk * float(self._engine.server_input_gain)
            in_vu = _rms(chunk)
            try:
                if self._engine.pass_through:
                    out = chunk.astype(np.float32, copy=False)
                    timings: dict[str, float | bool] = {"pass_through": 0.0, "total": 0.0, "squelched": False}
                else:
                    out = self._processor.process(chunk)
                    timings = dict(self._processor.last_timings)
            except Exception as exc:  # noqa: BLE001 - keep the stream alive, surface the error
                self.error = repr(exc)
                out = np.zeros_like(chunk)
                timings = {"error": 0.0, "squelched": False}
            self._output_ring.push(out)
            if self._monitor_ring is not None:
                self._monitor_ring.push(out)
            self._record_chunk(out)
            squelched = bool(timings.pop("squelched", False))
            total_raw = timings.get("total")
            total = float(total_raw) if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool) else None
            if total is not None:
                self._latency_totals_ms.append(total)
            total_p95 = _rolling_p95(self._latency_totals_ms)
            chunk_ms_raw = self._metrics.get("chunk_ms")
            chunk_ms = (
                float(chunk_ms_raw)
                if isinstance(chunk_ms_raw, (int, float)) and not isinstance(chunk_ms_raw, bool)
                else None
            )
            headroom = round(chunk_ms - total_p95, 3) if chunk_ms is not None and total_p95 is not None else None
            with self._metrics_lock:
                self._metrics["input_vu"] = in_vu
                if len(out) or squelched:
                    self._metrics["output_vu"] = _rms(out)
                self._metrics["timings_ms"] = timings
                self._metrics["total_ms"] = total
                self._metrics["total_p95_ms"] = total_p95
                self._metrics["latency_headroom_ms"] = headroom
                self._metrics["latency_warning"] = _latency_warning(total_p95, chunk_ms)
                self._metrics["provider_health"] = self._engine.provider_health()
                self._metrics["squelched"] = squelched

    def metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            return dict(self._metrics)

    def session_config(self) -> dict[str, int | None] | None:
        return dict(self._session_config) if self._session_config is not None else None

    def recording_status(self) -> dict[str, Any]:
        with self._recording_lock:
            active = self._recording_started is not None
            duration = time.monotonic() - self._recording_started if active else 0.0
            samples = sum(len(frame) for frame in self._recording_frames)
            return {
                "active": active,
                "duration_s": round(float(duration), 3),
                "samples": int(samples),
                "sample_rate": int(self._recording_sample_rate),
            }

    def start_recording(self) -> dict[str, Any]:
        with self._recording_lock:
            if self._recording_started is not None:
                raise RuntimeError("voice recording is already active")
            self._recording_frames = []
            self._recording_started = time.monotonic()
            self._recording_sample_rate = int(self.stream_sr)
        return self.recording_status()

    def stop_recording(self) -> dict[str, Any]:
        import numpy as np  # noqa: PLC0415

        with self._recording_lock:
            if self._recording_started is None:
                raise RuntimeError("voice recording is not active")
        time.sleep(RECORD_STOP_GRACE_MS / 1000.0)
        with self._recording_lock:
            if self._recording_started is None:
                raise RuntimeError("voice recording is not active")
            frames = list(self._recording_frames)
            sample_rate = int(self._recording_sample_rate)
            self._recording_frames = []
            self._recording_started = None
        audio = np.concatenate(frames).astype(np.float32, copy=False) if frames else np.zeros(0, dtype=np.float32)
        from . import storage  # noqa: PLC0415

        token = storage.new_token()
        path = storage.resolve_output(token)
        assert path is not None
        _write_wav(path, audio, sample_rate)
        return {
            "token": token,
            "url": f"/api/voice/engine/file/{token}",
            "duration_s": len(audio) / float(sample_rate) if sample_rate else 0.0,
            "sample_rate": sample_rate,
            "samples": int(len(audio)),
        }

    def _record_chunk(self, chunk) -> None:
        import numpy as np  # noqa: PLC0415

        with self._recording_lock:
            if self._recording_started is None:
                return
            elapsed = time.monotonic() - self._recording_started
            if elapsed > MAX_RECORD_SECONDS:
                self._recording_started = None
                return
            self._recording_frames.append(np.asarray(chunk, dtype=np.float32).reshape(-1).copy())


class StubRealtimeSession:
    """CI stand-in: no audio devices, deterministic moving metrics."""

    def __init__(self, engine: VoiceEngine) -> None:
        self._engine = engine
        self._started = time.monotonic()
        self._recording_started: float | None = None
        self.error: str | None = None
        self._session_config: dict[str, int | None] | None = None

    def start(self, model_id: str) -> None:  # noqa: ARG002
        self._started = time.monotonic()
        self._session_config = {
            "server_input_device_id": self._engine.server_input_device_id,
            "server_output_device_id": self._engine.server_output_device_id,
            "server_monitor_device_id": self._engine.server_monitor_device_id,
            "server_audio_sample_rate": int(self._engine.server_audio_sample_rate),
            "server_read_chunk_size": int(self._engine.server_read_chunk_size),
        }

    def stop(self) -> None:
        return None

    def metrics(self) -> dict[str, Any]:
        tick = int((time.monotonic() - self._started) * 4)
        chunk_ms = round(int(self._engine.server_read_chunk_size) * CHUNK_UNIT_SAMPLES
                         / int(self._engine.server_audio_sample_rate) * 1000, 1)
        return {
            "input_vu": ((tick % 10) + 1) / 10.0,
            "output_vu": ((tick % 7) + 1) / 10.0,
            "output_peak": 0.5,
            "output_peak_dbfs": -6.0,
            "limiter_reduction_db": 0.0,
            "timings_ms": {"stub": 1.0, "total": 5.0},
            "total_ms": 5.0,
            "total_p95_ms": 5.0,
            "chunk_ms": chunk_ms,
            "latency_headroom_ms": round(chunk_ms - 5.0, 3),
            "latency_warning": _latency_warning(5.0, chunk_ms),
            "provider_health": self._engine.provider_health(),
            "overruns": 0,
            "underruns": 0,
            "squelched": False,
        }

    def session_config(self) -> dict[str, int | None] | None:
        return dict(self._session_config) if self._session_config is not None else None

    def recording_status(self) -> dict[str, Any]:
        active = self._recording_started is not None
        return {
            "active": active,
            "duration_s": round(time.monotonic() - self._recording_started, 3) if active else 0.0,
            "samples": 0,
            "sample_rate": int(self._engine.server_audio_sample_rate),
        }

    def start_recording(self) -> dict[str, Any]:
        if self._recording_started is not None:
            raise RuntimeError("voice recording is already active")
        self._recording_started = time.monotonic()
        return self.recording_status()

    def stop_recording(self) -> dict[str, Any]:
        import numpy as np  # noqa: PLC0415

        if self._recording_started is None:
            raise RuntimeError("voice recording is not active")
        duration = max(0.2, time.monotonic() - self._recording_started)
        self._recording_started = None
        sample_rate = int(self._engine.server_audio_sample_rate)
        t = np.arange(int(duration * sample_rate), dtype=np.float32) / float(sample_rate)
        audio = (0.12 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
        from . import storage  # noqa: PLC0415

        token = storage.new_token()
        path = storage.resolve_output(token)
        assert path is not None
        _write_wav(path, audio, sample_rate)
        return {
            "token": token,
            "url": f"/api/voice/engine/file/{token}",
            "duration_s": len(audio) / float(sample_rate) if sample_rate else 0.0,
            "sample_rate": sample_rate,
            "samples": int(len(audio)),
        }


_SESSION: RealtimeSession | StubRealtimeSession | None = None
_SESSION_LOCK = threading.Lock()


def session_active() -> bool:
    return _SESSION is not None


def current_session() -> RealtimeSession | StubRealtimeSession | None:
    return _SESSION


def recording_status() -> dict[str, Any]:
    session = current_session()
    if session is None:
        return {"active": False, "duration_s": 0.0, "samples": 0, "sample_rate": None}
    return session.recording_status()


def start_recording() -> dict[str, Any]:
    session = current_session()
    if session is None:
        raise RuntimeError("no live voice session is active")
    return session.start_recording()


def stop_recording() -> dict[str, Any]:
    session = current_session()
    if session is None:
        raise RuntimeError("no live voice session is active")
    return session.stop_recording()


def start_session(engine: VoiceEngine, model_id: str) -> None:
    """Create + start the singleton session. Raises on failure (no half-open
    session is left behind)."""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None:
            raise RuntimeError("a voice session is already live")
        session: RealtimeSession | StubRealtimeSession
        session = StubRealtimeSession(engine) if settings.stub_mode else RealtimeSession(engine)
        try:
            session.start(model_id)
        except Exception:
            session.stop()
            raise
        _SESSION = session


def stop_session() -> bool:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            return False
        try:
            _SESSION.stop()
        finally:
            _SESSION = None
    return True
