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

import threading
import time
from typing import TYPE_CHECKING, Any

from ...config import settings
from . import dsp

if TYPE_CHECKING:
    from .engine import VoiceEngine

# w-okada convention kept for UI parity: read chunk = N * 128 samples.
CHUNK_UNIT_SAMPLES = 128
# The conversion context must stay bounded no matter what extra_convert_size
# says, or a long setting would make every chunk arbitrarily expensive.
MAX_CONTEXT_SECONDS = 8.0
# SOLA: how far (in samples @ model sr) we search for the best seam alignment.
SOLA_SEARCH_MS = 10.0
# All analysis happens on the 16 kHz stream ContentVec/RMVPE expect.
ANALYSIS_SR = 16_000
# Conversion advances in multiples of this quantum: the LCM of the ContentVec
# hop (320 @ 16 kHz) and the DTLN hop (128). Sliding the context by a whole
# number of feature frames keeps the analysis frame grid aligned with the audio
# from block to block — otherwise overlapping audio is re-analyzed on a shifted
# grid every chunk and the seams wobble no matter how good the crossfade is.
BLOCK_QUANTUM = 640
# Feature hop after the x2 upsample (160 samples @ 16 kHz = one synth frame).
FEATURE_HOP_16K = 160
MAX_RECORD_SECONDS = 180.0
# Keep converting a little after VAD closes. RVC/DTLN can still have a short
# audible tail even after the raw mic chunk drops below the silence threshold.
POST_SPEECH_FLUSH_MS = 450.0
RECORD_STOP_GRACE_MS = 650.0


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


class ChunkProcessor:
    """The realtime conversion core, audio-device-free so the bench script and
    the live session run the *same* code.

    Everything that touches the audio stream is stateful and processes each
    sample exactly once, in order: stream resample to 16 kHz, DTLN, high-pass,
    formant resample. The cleaned analysis stream is cut into blocks that are a
    multiple of ``BLOCK_QUANTUM`` so the feature/f0 frame grid stays aligned
    with the audio between conversions; each block slides a fixed-length
    context window (so every conversion has identical cost and geometry), the
    context is converted with latent noise pinned per absolute frame, and the
    seam is stitched with SOLA + equal-power crossfade in the model's sample
    rate before a streaming output resampler produces stream-rate audio.

    ``process`` therefore returns a *variable* number of samples (0..n blocks
    worth); the output ring buffer absorbs the jitter.
    """

    def __init__(self, engine: VoiceEngine, loaded: Any, stream_sr: int, denoiser: Any | None = None) -> None:
        import numpy as np  # noqa: PLC0415

        self._np = np
        self._engine = engine
        self._loaded = loaded
        self._denoiser = denoiser
        self._denoise_mode = "dtln" if denoiser is not None else "off"
        self.stream_sr = int(stream_sr)
        self._rng = np.random.default_rng(0xC0FFEE)
        self._in_rs: Any | None = None
        self._hpf = dsp.StreamingHighpass(engine.input_highpass_hz)
        self._formant_rs: Any | None = None
        self._formant_factor = 1.0
        self._out_rs: Any | None = None
        self._out_rs_key: tuple[int, float] | None = None
        self._fifo_16k = np.zeros(0, dtype=np.float32)
        self._block_16k = 0
        self._context_16k = np.zeros(0, dtype=np.float32)
        self._noise_ring: Any | None = None
        self._sola_buf: Any | None = None  # @ model sr
        self._silence_acc = 0.0
        self._tail_flush_remaining = 0
        self._squelch = dsp.SquelchGate(
            threshold_db=engine.silence_threshold_db,
            hold_ms=engine.silence_hold_ms,
        )
        self.last_timings: dict[str, float | bool] = {}

    # ------------------------------------------------------------ sizing
    def _ensure_block(self, chunk_len: int) -> None:
        if self._block_16k:
            return
        ideal = max(1.0, float(chunk_len)) / self.stream_sr * ANALYSIS_SR
        self._block_16k = max(BLOCK_QUANTUM, int(round(ideal / BLOCK_QUANTUM)) * BLOCK_QUANTUM)

    def _context_len_16k(self) -> int:
        extra = min(max(float(self._engine.extra_convert_size), 0.0), MAX_CONTEXT_SECONDS)
        extra_16k = int(round(extra * ANALYSIS_SR / BLOCK_QUANTUM)) * BLOCK_QUANTUM
        return max(BLOCK_QUANTUM, extra_16k) + self._block_16k

    def _noise_channels(self) -> int:
        synthesizer = getattr(self._loaded, "synthesizer", None)
        return int(getattr(synthesizer, "inter_channels", 192) or 192)

    def _resize_state(self) -> None:
        np = self._np
        target = self._context_len_16k()
        if len(self._context_16k) != target:
            if len(self._context_16k) < target:
                pad = np.zeros(target - len(self._context_16k), dtype=np.float32)
                self._context_16k = np.concatenate([pad, self._context_16k])
            else:
                self._context_16k = self._context_16k[-target:]
        frames = target // FEATURE_HOP_16K
        if self._noise_ring is None or self._noise_ring.shape[1] != frames:
            ring = self._rng.standard_normal((self._noise_channels(), frames)).astype(np.float32)
            if self._noise_ring is not None:
                keep = min(self._noise_ring.shape[1], frames)
                # Newest frames keep their noise so the next conversions still
                # re-synthesize the overlap identically after a resize.
                ring[:, -keep:] = self._noise_ring[:, -keep:]
            self._noise_ring = ring

    # ------------------------------------------------------- input chain
    def _active_denoiser(self):
        mode = str(self._engine.input_denoise)
        if mode != "dtln":
            self._denoise_mode = "off"
            return None
        if self._denoiser is None:
            self._denoiser = self._engine.denoiser_sync()
        if self._denoise_mode != "dtln":
            self._denoiser.reset()
            self._denoise_mode = "dtln"
        return self._denoiser

    def _resample_in(self, chunk):
        np = self._np
        if self.stream_sr == ANALYSIS_SR:
            return chunk.astype(np.float32, copy=False)
        if self._in_rs is None:
            import soxr  # noqa: PLC0415

            self._in_rs = soxr.ResampleStream(float(self.stream_sr), float(ANALYSIS_SR), 1, dtype="float32")
        return np.asarray(self._in_rs.resample_chunk(chunk)).reshape(-1).astype(np.float32, copy=False)

    def _apply_formant(self, piece):
        np = self._np
        factor = dsp.input_formant_factor(self._engine.input_formant)
        if abs(factor - 1.0) < 1e-6:
            self._formant_rs = None
            self._formant_factor = 1.0
            return piece
        if piece.size == 0:
            return piece
        if self._formant_rs is None or abs(factor - self._formant_factor) > 1e-9:
            import soxr  # noqa: PLC0415

            self._formant_rs = soxr.ResampleStream(
                float(ANALYSIS_SR), float(ANALYSIS_SR) / factor, 1, dtype="float32"
            )
            self._formant_factor = factor
        return np.asarray(self._formant_rs.resample_chunk(piece)).reshape(-1).astype(np.float32, copy=False)

    # ------------------------------------------------------------ output
    def _resample_out(self, out_model, model_sr: int, factor: float):
        np = self._np
        # out_rate folds in the formant duration compensation: the converted
        # audio is in analysis time (shorter/longer by 1/factor), playing it at
        # stream_sr * factor restores real-time duration without a second pass.
        out_rate = float(self.stream_sr) * float(factor)
        key = (int(model_sr), round(out_rate, 6))
        if self._out_rs is None or self._out_rs_key != key:
            import soxr  # noqa: PLC0415

            self._out_rs = soxr.ResampleStream(float(model_sr), out_rate, 1, dtype="float32")
            self._out_rs_key = key
        return np.asarray(self._out_rs.resample_chunk(out_model)).reshape(-1).astype(np.float32, copy=False)

    def _sola_offset(self, tail, fade: int, search: int) -> int:
        np = self._np
        sola = self._sola_buf
        sola_energy = float(np.dot(sola, sola))
        if search <= 0 or sola_energy <= 1e-12:
            return 0
        segment = tail[: fade + search]
        corr = np.correlate(segment, sola, mode="valid")
        squares = np.concatenate([[0.0], np.cumsum(np.square(segment, dtype=np.float64))])
        window_energy = squares[fade : fade + search + 1] - squares[: search + 1]
        scores = corr / (np.sqrt(np.maximum(window_energy, 1e-12)) * (sola_energy ** 0.5 + 1e-8))
        return int(np.argmax(scores))

    def _stitch(self, converted, model_sr: int):
        """SOLA-align and crossfade in the model domain; returns exactly one
        block worth of model-rate samples, continuous with the previous one."""
        np = self._np
        emit = max(1, int(round(self._block_16k * model_sr / ANALYSIS_SR)))
        fade = max(0, int(float(self._engine.cross_fade_overlap_size) * model_sr))
        fade = min(fade, emit // 2)
        search = max(0, int(model_sr * SOLA_SEARCH_MS / 1000.0))
        need = emit + fade + search
        if len(converted) >= need:
            tail = converted[-need:]
        else:
            tail = np.concatenate([np.zeros(need - len(converted), dtype=np.float32), converted])
        if fade <= 0:
            self._sola_buf = None
            return tail[-emit:].astype(np.float32, copy=True)
        if self._sola_buf is None or len(self._sola_buf) != fade:
            self._sola_buf = np.zeros(fade, dtype=np.float32)
        offset = self._sola_offset(tail, fade, search)
        aligned = tail[offset:]
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        blended = self._sola_buf * np.sqrt(1.0 - ramp) + aligned[:fade] * np.sqrt(ramp)
        emitted = np.concatenate([blended, aligned[fade:emit]])
        # The seam reference for the next block continues exactly where the
        # emitted audio stopped — storing the unaligned tail here is what used
        # to repeat/skip up to SOLA_SEARCH_MS of audio at every seam.
        self._sola_buf = aligned[emit : emit + fade].astype(np.float32, copy=True)
        return emitted.astype(np.float32, copy=False)

    # ------------------------------------------------------------ blocks
    def _process_block(self, block, timings: dict[str, float | bool]):
        np = self._np
        self._resize_state()
        self._context_16k = np.concatenate([self._context_16k[self._block_16k :], block])
        shift = self._block_16k // FEATURE_HOP_16K
        ring = self._noise_ring
        if ring is not None and shift > 0:
            if shift >= ring.shape[1]:
                ring[:, :] = self._rng.standard_normal(ring.shape).astype(np.float32)
            else:
                ring[:, :-shift] = ring[:, shift:]
                ring[:, -shift:] = self._rng.standard_normal((ring.shape[0], shift)).astype(np.float32)

        block_ms = self._block_16k / ANALYSIS_SR * 1000.0
        rms_db = dsp.rms_dbfs(block)
        squelched = self._squelch.update(
            rms_db,
            block_ms,
            threshold_db=self._engine.silence_threshold_db,
            hold_ms=self._engine.silence_hold_ms,
        )
        timings["input_rms_dbfs"] = round(rms_db, 1)
        if not squelched:
            self._tail_flush_remaining = max(1, int(np.ceil(POST_SPEECH_FLUSH_MS / block_ms)))
        elif self._tail_flush_remaining > 0:
            self._tail_flush_remaining -= 1
            squelched = False
            timings["tail_flush"] = True
        timings["squelched"] = squelched

        factor = self._formant_factor if self._formant_rs is not None else 1.0
        if squelched:
            # Hard silence: drop the seam/resampler state so the next voiced
            # block fades in from zero, and keep the long-run output rate exact
            # with a fractional sample accumulator.
            self._sola_buf = None
            self._out_rs = None
            self._out_rs_key = None
            self._silence_acc += self._block_16k * factor * self.stream_sr / ANALYSIS_SR
            count = int(self._silence_acc)
            self._silence_acc -= count
            return np.zeros(count, dtype=np.float32)

        from . import pipeline  # noqa: PLC0415

        converted, model_sr, core_timings = pipeline.convert_audio(
            self._context_16k,
            self._loaded,
            pitch=self._engine.pitch,
            speaker_id=self._engine.speaker_id,
            index_ratio=self._engine.index_ratio,
            protect=self._engine.protect,
            noise_scale=self._engine.noise_scale,
            f0_smoothing=self._engine.f0_smoothing,
            f0_detector=self._engine.f0_detector,
            input_highpass_hz=0,
            input_gate_db=dsp.GATE_OFF_DB,
            input_formant=0.0,
            external_formant_factor=factor,
            compensate_duration=False,
            latent_noise=self._noise_ring,
            denoiser=None,
            device=self._engine.device,
        )
        timings.update(core_timings)

        stage = time.perf_counter()
        out_model = self._stitch(np.asarray(converted, dtype=np.float32).reshape(-1), int(model_sr))
        out = self._resample_out(out_model, int(model_sr), factor)
        timings["stitch"] = round((time.perf_counter() - stage) * 1000, 3)
        return out

    def process(self, chunk):
        """Feed one captured chunk (float32 @ stream sr); returns whatever
        converted stream-rate audio became ready (possibly zero samples)."""
        np = self._np
        started = time.perf_counter()
        timings: dict[str, float | bool] = {}
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        self._ensure_block(len(chunk))

        stage = time.perf_counter()
        piece = self._resample_in(chunk)
        timings["resample_16k"] = round((time.perf_counter() - stage) * 1000, 3)

        denoiser = self._active_denoiser()
        if denoiser is not None and piece.size:
            stage = time.perf_counter()
            piece = denoiser.process_stream(piece)
            timings["input_denoise"] = round((time.perf_counter() - stage) * 1000, 3)

        stage = time.perf_counter()
        piece = self._hpf.process(piece, cutoff_hz=self._engine.input_highpass_hz)
        piece = self._apply_formant(piece)
        timings["input_dsp"] = round((time.perf_counter() - stage) * 1000, 3)

        if piece.size:
            self._fifo_16k = np.concatenate([self._fifo_16k, piece])

        outputs = []
        while len(self._fifo_16k) >= self._block_16k:
            block = self._fifo_16k[: self._block_16k]
            self._fifo_16k = self._fifo_16k[self._block_16k :]
            outputs.append(self._process_block(block, timings))

        if "squelched" not in timings:
            timings["squelched"] = self._squelch.is_closed
        timings["total"] = round((time.perf_counter() - started) * 1000, 3)
        self.last_timings = timings
        if outputs:
            return np.concatenate(outputs).astype(np.float32, copy=False)
        return np.zeros(0, dtype=np.float32)


def _rms(samples) -> float:
    import numpy as np  # noqa: PLC0415

    if len(samples) == 0:
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(np.square(samples))) * 4.0))


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
            "timings_ms": {},
            "total_ms": None,
            "chunk_ms": None,
            "overruns": 0,
            "underruns": 0,
            "squelched": False,
        }
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
            if missing or dropped:
                with self._metrics_lock:
                    self._metrics["underruns"] += 1 if missing else 0
                    self._metrics["overruns"] += 1 if dropped else 0
            outdata[:] = (samples * float(self._engine.server_output_gain)).reshape(-1, 1).astype(np.float32)

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
        outdata[:] = (samples * float(self._engine.server_monitor_gain)).reshape(-1, 1).astype(np.float32)

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
                    pass
        self._stream = None
        self._monitor_stream = None
        self._processor = None
        if not settings.stub_mode:
            try:
                import torch  # noqa: PLC0415

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass

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
            with self._metrics_lock:
                self._metrics["input_vu"] = in_vu
                if len(out) or squelched:
                    self._metrics["output_vu"] = _rms(out)
                self._metrics["timings_ms"] = timings
                self._metrics["total_ms"] = total
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
            "timings_ms": {"stub": 1.0, "total": 5.0},
            "total_ms": 5.0,
            "chunk_ms": chunk_ms,
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
