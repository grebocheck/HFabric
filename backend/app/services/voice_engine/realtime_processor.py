"""Realtime voice chunk processing core.

This module is intentionally audio-device-free: live sessions and tests feed
fixed chunks in, and the processor returns converted stream-rate samples.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from . import dsp

if TYPE_CHECKING:
    from .engine import VoiceEngine

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
# Keep converting a little after VAD closes. RVC/DTLN can still have a short
# audible tail even after the raw mic chunk drops below the silence threshold.
POST_SPEECH_FLUSH_MS = 450.0


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
        self._denoise_raw_pending = np.zeros(0, dtype=np.float32)
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
            raw_piece = piece
            self._denoise_raw_pending = np.concatenate([self._denoise_raw_pending, raw_piece])
            denoised = np.asarray(denoiser.process_stream(piece), dtype=np.float32).reshape(-1)
            mix = max(0.0, min(1.0, float(self._engine.input_denoise_mix)))
            if denoised.size > self._denoise_raw_pending.size:
                denoised = denoised[: self._denoise_raw_pending.size]
            raw_for_mix = self._denoise_raw_pending[: denoised.size]
            self._denoise_raw_pending = self._denoise_raw_pending[denoised.size :]
            piece = denoised * np.float32(mix) + raw_for_mix * np.float32(1.0 - mix)
            timings["input_denoise"] = round((time.perf_counter() - stage) * 1000, 3)
            timings["input_denoise_mix"] = round(mix, 3)
        elif denoiser is None:
            self._denoise_raw_pending = np.zeros(0, dtype=np.float32)

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

