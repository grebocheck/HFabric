"""Native realtime voice session.

Each live session owns a sounddevice duplex stream: the PortAudio callback only
moves samples in/out of ring buffers; a dedicated worker thread pulls fixed
chunks and feeds them to ``ChunkProcessor``, which runs a fully streaming
input chain (stateful resample to 16 kHz -> split F0/content DSP), advances a
fixed-length conversion context in blocks aligned to the feature frame grid,
re-converts through the shared ``pipeline.convert_audio`` core with latent
noise pinned per absolute frame, and stitches seams with SOLA plus a
complementary raised-cosine crossfade in the model domain before a streaming
output resampler. Every stage that touches audio keeps state across calls so
no per-chunk filter edges are baked into the stream.

Threading model: the audio callback and the worker communicate through
fixed-capacity circular float32 rings; settings are read from the
``VoiceEngine`` once per chunk (plain attribute reads — atomic enough in
CPython for floats/ints), so pitch/index/protect/gain/pass-through changes
apply on the next chunk without a restart.

STUB mode never imports sounddevice/torch: ``StubRealtimeSession`` just flips
``live`` and synthesizes deterministic VU/timing values so the API, the UI,
and the voice-lane parking are all testable in CI.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import logging
import math
import sys
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


def _initialize_audio_io_thread() -> None:
    """Give the process-lifetime PortAudio owner a Windows COM apartment."""
    if sys.platform != "win32":
        return

    import ctypes  # noqa: PLC0415

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    hresult = int(ole32.CoInitialize(None))
    # RPC_E_CHANGED_MODE means another library already initialized this thread
    # with a different apartment model; COM is nevertheless available. Keep a
    # successful initialization for the lifetime of this dedicated thread so
    # live PortAudio COM interfaces never outlive their apartment.
    rpc_e_changed_mode = -2147417850
    if hresult < 0 and hresult != rpc_e_changed_mode:
        raise OSError(f"could not initialize COM for Windows audio (HRESULT 0x{hresult & 0xFFFFFFFF:08X})")


# PortAudio's Windows WASAPI backend creates COM objects on the thread that
# first imports/initializes sounddevice, then marshals stream interfaces from
# the thread that starts them. A general asyncio worker pool can use different
# threads for device enumeration, start, and stop, causing intermittent
# CO_E_NOTINITIALIZED/WdmSyncIoctl failures. Keep every PortAudio operation on
# one process-lifetime owner thread; it also serializes enumeration with stream
# lifecycle changes.
_AUDIO_IO_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="hfabric-audio-io",
    initializer=_initialize_audio_io_thread,
)


async def run_audio_io[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a PortAudio operation on its thread-affine owner thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_AUDIO_IO_EXECUTOR, partial(func, *args, **kwargs))


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
    """Fixed-capacity, lock-guarded float32 circular FIFO.

    PortAudio callbacks must not repeatedly concatenate growing numpy arrays:
    those allocations and copies can pause the callback and create an audible
    underrun. This buffer allocates once and only copies into/out of its ring.
    """

    def __init__(self, capacity: int) -> None:
        import numpy as np  # noqa: PLC0415

        self._np = np
        self._capacity = max(1, int(capacity))
        self._buf = np.zeros(self._capacity, dtype=np.float32)
        self._read = 0
        self._write = 0
        self._size = 0
        self._read_total = 0
        self._write_total = 0
        self._lock = threading.Lock()

    def push(self, samples) -> int:
        data = self._np.asarray(samples, dtype=self._np.float32).reshape(-1)
        if data.size == 0:
            with self._lock:
                return self._write_total
        with self._lock:
            start_index = self._write_total
            original_size = int(data.size)
            self._write_total += original_size
            if data.size >= self._capacity:
                data = data[-self._capacity :]
                self._read = 0
                self._write = 0
                self._size = 0
                self._read_total = self._write_total - int(data.size)
            overflow = max(0, self._size + int(data.size) - self._capacity)
            if overflow:
                self._read = (self._read + overflow) % self._capacity
                self._size -= overflow
                self._read_total += overflow
            first = min(int(data.size), self._capacity - self._write)
            self._buf[self._write : self._write + first] = data[:first]
            remaining = int(data.size) - first
            if remaining:
                self._buf[:remaining] = data[first:]
            self._write = (self._write + int(data.size)) % self._capacity
            self._size += int(data.size)
            return start_index

    def pull(self, count: int):
        """Take exactly ``count`` samples; missing samples are zero-padded.
        Returns (samples, missing_count)."""
        out, missing, _start_index = self.pull_with_index(count)
        return out, missing

    def pull_with_index(self, count: int):
        """Like :meth:`pull`, plus the absolute index of the first sample."""
        with self._lock:
            wanted = max(0, int(count))
            take = min(wanted, self._size)
            start_index = self._read_total
            out = self._np.zeros(wanted, dtype=self._np.float32)
            first = min(take, self._capacity - self._read)
            out[:first] = self._buf[self._read : self._read + first]
            remaining = take - first
            if remaining:
                out[first : first + remaining] = self._buf[:remaining]
            self._read = (self._read + take) % self._capacity
            self._size -= take
            self._read_total += take
            return out, wanted - take, start_index

    def available(self) -> int:
        with self._lock:
            return self._size

    def drop_to(self, max_samples: int) -> int:
        """Bound the queue (drop oldest); returns how many were dropped."""
        with self._lock:
            extra = self._size - max(0, int(max_samples))
            if extra > 0:
                self._read = (self._read + extra) % self._capacity
                self._size -= extra
                self._read_total += extra
                return extra
            return 0


class _SampleClock:
    """Sparse mapping from absolute ring sample positions to stream time."""

    def __init__(self, max_marks: int = 512) -> None:
        self._marks: deque[tuple[int, float]] = deque(maxlen=max(2, int(max_marks)))

    def mark(self, sample_index: int, sample_time: float | None) -> None:
        if sample_time is None or not math.isfinite(float(sample_time)) or float(sample_time) <= 0.0:
            return
        self._marks.append((int(sample_index), float(sample_time)))

    def resolve(self, sample_index: int, sample_rate: int) -> float | None:
        if not self._marks or sample_rate <= 0:
            return None
        target = int(sample_index)
        while len(self._marks) > 1 and self._marks[1][0] <= target:
            self._marks.popleft()
        index, timestamp = self._marks[0]
        if index > target:
            return None
        return timestamp + (target - index) / float(sample_rate)


class _ClockDriftEstimator:
    """Estimate relative capture/render clock drift from PortAudio timestamps."""

    def __init__(self, window_seconds: float = 30.0) -> None:
        self._window_seconds = max(5.0, float(window_seconds))
        self._points: deque[tuple[float, float]] = deque()

    def update(
        self,
        input_adc_time: float | None,
        output_dac_time: float | None,
        current_time: float | None,
    ) -> tuple[float | None, float | None]:
        values = (input_adc_time, output_dac_time, current_time)
        if any(value is None or not math.isfinite(float(value)) for value in values):
            return None, None
        input_time = float(input_adc_time)
        output_time = float(output_dac_time)
        now = float(current_time)
        if input_time <= 0.0 or output_time <= 0.0 or now <= 0.0:
            return None, None
        delta = output_time - input_time
        self._points.append((now, delta))
        cutoff = now - self._window_seconds
        while len(self._points) > 2 and self._points[1][0] < cutoff:
            self._points.popleft()
        drift_ppm = None
        if len(self._points) >= 2:
            elapsed = self._points[-1][0] - self._points[0][0]
            if elapsed >= 5.0:
                drift_ppm = (self._points[-1][1] - self._points[0][1]) / elapsed * 1_000_000.0
        return round(delta * 1000.0, 3), (round(drift_ppm, 3) if drift_ppm is not None else None)


def _time_info_value(time_info: Any, name: str) -> float | None:
    try:
        value = float(getattr(time_info, name))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


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
        self.stream_sr = 48_000
        self.chunk_samples = 0
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
            "estimated_latency_ms": None,
            "measured_latency_ms": None,
            "measured_latency_p95_ms": None,
            "callback_transport_ms": None,
            "clock_drift_ppm": None,
            "input_stream_latency_ms": None,
            "output_stream_latency_ms": None,
            "input_queue_ms": 0.0,
            "output_queue_ms": 0.0,
            "provider_health": engine.provider_health(),
            "overruns": 0,
            "underruns": 0,
            "squelched": False,
        }
        self._latency_totals_ms: deque[float] = deque(maxlen=LATENCY_HISTORY)
        self._input_ring: _Ring | None = None
        self._output_ring: _Ring | None = None
        self._monitor_ring: _Ring | None = None
        self._input_clock = _SampleClock()
        self._output_clock = _SampleClock()
        self._clock_drift = _ClockDriftEstimator()
        self._measured_latencies_ms: deque[float] = deque(maxlen=LATENCY_HISTORY)
        self._latest_measured_latency_ms: float | None = None
        self._callback_transport_ms: float | None = None
        self._clock_drift_ppm: float | None = None
        self._processor: ChunkProcessor | None = None
        self._output_limiter = dsp.StreamingLimiter(sample_rate=self.stream_sr)
        self._monitor_limiter = dsp.StreamingLimiter(sample_rate=self.stream_sr)
        self._recording_lock = threading.Lock()
        self._recording_frames: list[Any] = []
        self._recording_raw_frames: list[Any] = []
        self._recording_started: float | None = None
        self._recording_sample_rate = 48_000
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
        self._output_limiter = dsp.StreamingLimiter(sample_rate=self.stream_sr)
        self._monitor_limiter = dsp.StreamingLimiter(sample_rate=self.stream_sr)
        self.chunk_samples = max(1, int(engine.server_read_chunk_size)) * CHUNK_UNIT_SAMPLES
        self._session_config = {
            "server_input_device_id": engine.server_input_device_id,
            "server_output_device_id": engine.server_output_device_id,
            "server_monitor_device_id": engine.server_monitor_device_id,
            "server_audio_sample_rate": self.stream_sr,
            "server_read_chunk_size": int(engine.server_read_chunk_size),
        }
        self._input_ring = _Ring(self.stream_sr * 3)
        self._output_ring = _Ring(self.stream_sr * 4)
        self._input_clock = _SampleClock()
        self._output_clock = _SampleClock()
        self._clock_drift = _ClockDriftEstimator()
        self._measured_latencies_ms.clear()
        self._latest_measured_latency_ms = None
        self._callback_transport_ms = None
        self._clock_drift_ppm = None
        self._processor = ChunkProcessor(engine, loaded, self.stream_sr, denoiser=denoiser)
        # Capture has to fill one chunk before inference can begin. Two chunks
        # of pre-roll cover both that capture interval and normal inference
        # jitter; one chunk left a guaranteed startup gap equal to inference
        # time and was the main source of initial underruns.
        import numpy as np  # noqa: PLC0415

        self._output_ring.push(np.zeros(self.chunk_samples * 2, dtype=np.float32))
        with self._metrics_lock:
            self._metrics["chunk_ms"] = round(self.chunk_samples / self.stream_sr * 1000, 1)
            self._metrics["provider_health"] = engine.provider_health()

        in_dev = engine.server_input_device_id
        out_dev = engine.server_output_device_id
        mon_dev = engine.server_monitor_device_id

        def callback(indata, outdata, frames, time_info, status) -> None:  # noqa: ARG001
            assert self._input_ring is not None and self._output_ring is not None
            input_adc_time = _time_info_value(time_info, "inputBufferAdcTime")
            output_dac_time = _time_info_value(time_info, "outputBufferDacTime")
            current_time = _time_info_value(time_info, "currentTime")
            input_index = self._input_ring.push(indata[:, 0])
            self._input_clock.mark(input_index, input_adc_time)
            # Bound the input queue to ~2s so a stalled worker degrades
            # (drops old audio) instead of growing without limit.
            dropped = self._input_ring.drop_to(self.stream_sr * 2)
            samples, missing, output_index = self._output_ring.pull_with_index(frames)
            if missing < frames and output_dac_time is not None:
                capture_time = self._output_clock.resolve(output_index, self.stream_sr)
                if capture_time is not None:
                    latency_ms = (output_dac_time - capture_time) * 1000.0
                    if 0.0 <= latency_ms <= 10_000.0:
                        self._latest_measured_latency_ms = round(latency_ms, 3)
                        self._measured_latencies_ms.append(latency_ms)
            transport_ms, drift_ppm = self._clock_drift.update(
                input_adc_time,
                output_dac_time,
                current_time,
            )
            if transport_ms is not None:
                self._callback_transport_ms = transport_ms
            if drift_ppm is not None:
                self._clock_drift_ppm = drift_ppm
            if missing or dropped:
                with self._metrics_lock:
                    self._metrics["underruns"] += 1 if missing else 0
                    self._metrics["overruns"] += 1 if dropped else 0
            outdata[:] = samples.reshape(-1, 1)

        self._stop.clear()
        self._stream = sd.Stream(
            samplerate=self.stream_sr,
            blocksize=0,
            latency="low",
            channels=1,
            dtype="float32",
            device=(
                in_dev if in_dev is not None and in_dev >= 0 else None,
                out_dev if out_dev is not None and out_dev >= 0 else None,
            ),
            callback=callback,
        )
        stream_latency = self._stream.latency
        if isinstance(stream_latency, (tuple, list)):
            input_latency_s, output_latency_s = float(stream_latency[0]), float(stream_latency[1])
        else:
            input_latency_s = output_latency_s = float(stream_latency)
        with self._metrics_lock:
            self._metrics["input_stream_latency_ms"] = round(input_latency_s * 1000.0, 3)
            self._metrics["output_stream_latency_ms"] = round(output_latency_s * 1000.0, 3)
        if mon_dev is not None and mon_dev >= 0 and mon_dev != out_dev:
            self._monitor_ring = _Ring(self.stream_sr * 4)
            self._monitor_stream = sd.OutputStream(
                samplerate=self.stream_sr,
                blocksize=0,
                latency="low",
                channels=1,
                dtype="float32",
                device=mon_dev,
                callback=self._monitor_callback,
            )
        self._worker = threading.Thread(target=self._run, name="hfabric-voice-rt", daemon=True)
        # Start the consumer before PortAudio begins invoking callbacks. Apart
        # from avoiding a guaranteed startup backlog, this ensures cleanup can
        # always join the worker if a device stream fails to start.
        self._worker.start()
        self._stream.start()
        if self._monitor_stream is not None:
            self._monitor_stream.start()

    def _monitor_callback(self, outdata, frames, _time_info, status) -> None:  # noqa: ARG002
        import numpy as np  # noqa: PLC0415

        assert self._monitor_ring is not None
        samples, _missing = self._monitor_ring.pull(frames)
        rendered, _limiter = self._monitor_limiter.process(samples * float(self._engine.server_monitor_gain))
        outdata[:] = rendered.reshape(-1, 1).astype(np.float32)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            # ``start`` can fail after constructing the Thread but before
            # starting it. ``Thread.join`` raises in that state and used to
            # hide the actual PortAudio/device error from the API.
            if self._worker.is_alive():
                self._worker.join(timeout=5.0)
            self._worker = None
        for stream in (self._stream, self._monitor_stream):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:  # noqa: BLE001 - device teardown must not raise
                    logger.debug("event=voice.realtime.stream_stop_failed", exc_info=True)
                try:
                    stream.close()
                except Exception:  # noqa: BLE001 - device teardown must not raise
                    logger.debug("event=voice.realtime.stream_close_failed", exc_info=True)
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
            chunk, _, input_index = self._input_ring.pull_with_index(self.chunk_samples)
            capture_time = self._input_clock.resolve(input_index, self.stream_sr)
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
            routed, limiter = self._output_limiter.process(out * float(self._engine.server_output_gain))
            output_index = self._output_ring.push(routed)
            self._output_clock.mark(output_index, capture_time)
            if self._monitor_ring is not None:
                self._monitor_ring.push(out)
            self._record_chunk(chunk, routed)
            squelched = bool(timings.pop("squelched", False))
            total_raw = timings.get("total")
            total = (
                float(total_raw)
                if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool)
                else None
            )
            if total is not None:
                self._latency_totals_ms.append(total)
            total_p95 = _rolling_p95(self._latency_totals_ms)
            chunk_ms_raw = self._metrics.get("chunk_ms")
            chunk_ms = (
                float(chunk_ms_raw)
                if isinstance(chunk_ms_raw, (int, float)) and not isinstance(chunk_ms_raw, bool)
                else None
            )
            headroom = (
                round(chunk_ms - total_p95, 3) if chunk_ms is not None and total_p95 is not None else None
            )
            input_queue_ms = round(self._input_ring.available() / self.stream_sr * 1000.0, 3)
            output_queue_ms = round(self._output_ring.available() / self.stream_sr * 1000.0, 3)
            measured_p95 = _rolling_p95(self._measured_latencies_ms)
            with self._metrics_lock:
                input_stream_ms = float(self._metrics.get("input_stream_latency_ms") or 0.0)
                output_stream_ms = float(self._metrics.get("output_stream_latency_ms") or 0.0)
                estimated_latency = (
                    input_stream_ms
                    + output_stream_ms
                    + (chunk_ms or 0.0)
                    + (total or 0.0)
                    + max(0.0, output_queue_ms - (len(out) / self.stream_sr * 1000.0))
                )
                self._metrics["input_vu"] = in_vu
                if len(routed) or squelched:
                    self._metrics["output_vu"] = _rms(routed)
                self._metrics["output_peak"] = limiter["peak"]
                self._metrics["output_peak_dbfs"] = limiter["peak_dbfs"]
                self._metrics["limiter_reduction_db"] = limiter["limiter_reduction_db"]
                self._metrics["timings_ms"] = timings
                self._metrics["total_ms"] = total
                self._metrics["total_p95_ms"] = total_p95
                self._metrics["latency_headroom_ms"] = headroom
                self._metrics["latency_warning"] = _latency_warning(total_p95, chunk_ms)
                self._metrics["estimated_latency_ms"] = round(estimated_latency, 3)
                self._metrics["measured_latency_ms"] = self._latest_measured_latency_ms
                self._metrics["measured_latency_p95_ms"] = measured_p95
                self._metrics["callback_transport_ms"] = self._callback_transport_ms
                self._metrics["clock_drift_ppm"] = self._clock_drift_ppm
                self._metrics["input_queue_ms"] = input_queue_ms
                self._metrics["output_queue_ms"] = output_queue_ms
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
            self._recording_raw_frames = []
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
            raw_frames = list(self._recording_raw_frames)
            sample_rate = int(self._recording_sample_rate)
            self._recording_frames = []
            self._recording_raw_frames = []
            self._recording_started = None
        audio = (
            np.concatenate(frames).astype(np.float32, copy=False) if frames else np.zeros(0, dtype=np.float32)
        )
        raw_audio = (
            np.concatenate(raw_frames).astype(np.float32, copy=False)
            if raw_frames
            else np.zeros(0, dtype=np.float32)
        )
        from . import storage  # noqa: PLC0415

        token = storage.new_token()
        raw_token = storage.new_token()
        path = storage.resolve_output(token)
        raw_path = storage.resolve_output(raw_token)
        metadata_path = storage.resolve_metadata(token)
        assert path is not None
        assert raw_path is not None
        assert metadata_path is not None
        _write_wav(path, audio, sample_rate)
        _write_wav(raw_path, raw_audio, sample_rate)
        metadata = self._recording_metadata(
            token=token,
            raw_token=raw_token,
            sample_rate=sample_rate,
            samples=len(audio),
            raw_samples=len(raw_audio),
            duration_s=len(audio) / float(sample_rate) if sample_rate else 0.0,
        )
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "token": token,
            "raw_token": raw_token,
            "url": f"/api/voice/engine/file/{token}",
            "raw_url": f"/api/voice/engine/file/{raw_token}",
            "metadata_url": f"/api/voice/engine/file/{token}/json",
            "duration_s": len(audio) / float(sample_rate) if sample_rate else 0.0,
            "sample_rate": sample_rate,
            "samples": int(len(audio)),
        }

    def _recording_metadata(
        self,
        *,
        token: str,
        raw_token: str,
        sample_rate: int,
        samples: int,
        raw_samples: int,
        duration_s: float,
    ) -> dict[str, Any]:
        return {
            "kind": "voice_ab_capture",
            "token": token,
            "raw_token": raw_token,
            "sample_rate": int(sample_rate),
            "samples": int(samples),
            "raw_samples": int(raw_samples),
            "duration_s": float(duration_s),
            "settings": self._engine.settings_payload(),
            "session_config": self.session_config(),
            "metrics": self.metrics(),
        }

    def _record_chunk(self, raw_chunk, output_chunk) -> None:
        import numpy as np  # noqa: PLC0415

        with self._recording_lock:
            if self._recording_started is None:
                return
            elapsed = time.monotonic() - self._recording_started
            if elapsed > MAX_RECORD_SECONDS:
                self._recording_started = None
                return
            self._recording_raw_frames.append(np.asarray(raw_chunk, dtype=np.float32).reshape(-1).copy())
            self._recording_frames.append(np.asarray(output_chunk, dtype=np.float32).reshape(-1).copy())


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
        chunk_ms = round(
            int(self._engine.server_read_chunk_size)
            * CHUNK_UNIT_SAMPLES
            / int(self._engine.server_audio_sample_rate)
            * 1000,
            1,
        )
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
            "estimated_latency_ms": round(chunk_ms * 2 + 5.0, 3),
            "measured_latency_ms": round(chunk_ms * 2 + 5.0, 3),
            "measured_latency_p95_ms": round(chunk_ms * 2 + 5.0, 3),
            "callback_transport_ms": 0.0,
            "clock_drift_ppm": 0.0,
            "input_stream_latency_ms": 0.0,
            "output_stream_latency_ms": 0.0,
            "input_queue_ms": 0.0,
            "output_queue_ms": chunk_ms,
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
        raw_audio = (0.08 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
        audio = (0.12 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
        from . import storage  # noqa: PLC0415

        token = storage.new_token()
        raw_token = storage.new_token()
        path = storage.resolve_output(token)
        raw_path = storage.resolve_output(raw_token)
        metadata_path = storage.resolve_metadata(token)
        assert path is not None
        assert raw_path is not None
        assert metadata_path is not None
        _write_wav(path, audio, sample_rate)
        _write_wav(raw_path, raw_audio, sample_rate)
        metadata = {
            "kind": "voice_ab_capture",
            "stub": True,
            "token": token,
            "raw_token": raw_token,
            "sample_rate": int(sample_rate),
            "samples": int(len(audio)),
            "raw_samples": int(len(raw_audio)),
            "duration_s": len(audio) / float(sample_rate) if sample_rate else 0.0,
            "settings": self._engine.settings_payload(),
            "session_config": self.session_config(),
            "metrics": self.metrics(),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "token": token,
            "raw_token": raw_token,
            "url": f"/api/voice/engine/file/{token}",
            "raw_url": f"/api/voice/engine/file/{raw_token}",
            "metadata_url": f"/api/voice/engine/file/{token}/json",
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
            try:
                session.stop()
            except Exception:  # noqa: BLE001 - preserve the startup exception
                logger.warning(
                    "event=voice.realtime.start_cleanup_failed",
                    exc_info=True,
                )
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
