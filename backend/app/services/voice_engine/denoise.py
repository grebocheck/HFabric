"""Streaming DTLN neural denoising for the voice input chain.

DTLN runs on the 16 kHz analysis signal before the local HPF/gate/formant DSP.
Offline conversion resets one denoiser, processes the whole resampled file once,
and then hands the denoised signal to the normal RVC analysis path.

Realtime is different: ``ChunkProcessor`` denoises only each newly captured
chunk as it arrives, appends that denoised audio to its rolling context, and
then calls ``pipeline.convert_audio(..., denoiser=None)``. Re-running a stateful
neural denoiser over overlapping rolling context would double-process the same
samples and desynchronize the LSTM states.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class DtlnDenoiser:
    """Stateful streaming wrapper around breizhn/DTLN's two ONNX stages."""

    sample_rate = 16_000
    frame_size = 512
    hop_size = 128
    fft_bins = 257
    state_shape = (1, 2, 128, 2)

    def __init__(self, model_1_path: str | Path, model_2_path: str | Path) -> None:
        self.model_1_path = Path(model_1_path)
        self.model_2_path = Path(model_2_path)
        self._session_1: Any = None
        self._session_2: Any = None
        self._io_1: tuple[str, str, str, str] | None = None
        self._io_2: tuple[str, str, str, str] | None = None
        self._primed = False
        self._state_1 = None
        self._state_2 = None
        self._state_1_shape = self.state_shape
        self._state_2_shape = self.state_shape
        self.reset()
        self._load()

    def reset(self) -> None:
        import numpy as np  # noqa: PLC0415

        self._analysis_buffer = np.zeros(self.frame_size, dtype=np.float32)
        self._ola_buffer = np.zeros(self.frame_size, dtype=np.float32)
        self._pending_input = np.zeros(0, dtype=np.float32)
        self._pending_output = np.zeros(0, dtype=np.float32)
        self._stream_drop = 0
        self._primed = False
        self._state_1 = np.zeros(self._state_1_shape, dtype=np.float32)
        self._state_2 = np.zeros(self._state_2_shape, dtype=np.float32)

    def process(self, audio_16k):
        """Denoise a mono 16 kHz float array and return the same length."""
        self._load()
        import numpy as np  # noqa: PLC0415

        audio = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
        target_len = int(audio.size)
        if target_len == 0:
            return np.zeros(0, dtype=np.float32)

        if not self._primed:
            self._primed = True
            warmup = self._warmup_audio(audio)
            if warmup.size:
                out = self._process_samples(np.concatenate([warmup, audio]))
                return out[warmup.size : warmup.size + target_len].astype(np.float32, copy=False)

        return self._process_samples(audio)

    def process_stream(self, audio_16k):
        """Streaming variant for the realtime chain: returns only the samples
        actually produced so far (length may differ from the input) and never
        inserts zero padding mid-stream. ``process`` keeps the same-length
        contract for offline files; mixing both modes on one instance without a
        ``reset`` is not supported."""
        self._load()
        import numpy as np  # noqa: PLC0415

        audio = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return np.zeros(0, dtype=np.float32)

        if not self._primed:
            self._primed = True
            warmup = self._warmup_audio(audio)
            self._stream_drop = int(warmup.size)
            if warmup.size:
                audio = np.concatenate([warmup, audio])

        self._pending_input = np.concatenate([self._pending_input, audio])
        chunks: list[Any] = []
        while self._pending_input.size >= self.hop_size:
            hop = self._pending_input[: self.hop_size]
            self._pending_input = self._pending_input[self.hop_size :]
            chunks.append(self._process_hop(hop))
        out = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        if self._stream_drop > 0:
            drop = min(self._stream_drop, out.size)
            out = out[drop:]
            self._stream_drop -= drop
        return out.astype(np.float32, copy=False)

    def _process_samples(self, audio):
        import numpy as np  # noqa: PLC0415

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        target_len = int(audio.size)
        if target_len == 0:
            return np.zeros(0, dtype=np.float32)

        self._pending_input = np.concatenate([self._pending_input, audio])
        chunks: list[Any] = []
        while self._pending_input.size >= self.hop_size:
            hop = self._pending_input[: self.hop_size]
            self._pending_input = self._pending_input[self.hop_size :]
            chunks.append(self._process_hop(hop))
        if chunks:
            self._pending_output = np.concatenate([self._pending_output, *chunks])

        if self._pending_output.size >= target_len:
            out = self._pending_output[:target_len].copy()
            self._pending_output = self._pending_output[target_len:]
            return out.astype(np.float32, copy=False)

        out = np.concatenate(
            [
                self._pending_output,
                np.zeros(target_len - self._pending_output.size, dtype=np.float32),
            ]
        )
        self._pending_output = self._pending_output[:0]
        return out.astype(np.float32, copy=False)

    def _warmup_audio(self, audio):
        """Prime DTLN's STFT/LSTM state so first speech attacks are not muted."""
        import numpy as np  # noqa: PLC0415

        source = np.asarray(audio, dtype=np.float32).reshape(-1)
        if source.size == 0:
            return np.zeros(0, dtype=np.float32)
        if source.size >= self.frame_size:
            return source[: self.frame_size].copy()
        reps = int(np.ceil(self.frame_size / max(1, source.size)))
        return np.tile(source, reps)[: self.frame_size].astype(np.float32, copy=False)

    def _load(self) -> None:
        if self._session_1 is not None and self._session_2 is not None:
            return
        import onnxruntime as ort  # noqa: PLC0415

        self._session_1 = ort.InferenceSession(str(self.model_1_path), providers=["CPUExecutionProvider"])
        self._session_2 = ort.InferenceSession(str(self.model_2_path), providers=["CPUExecutionProvider"])
        self._io_1 = self._probe_io(self._session_1, self.fft_bins)
        self._io_2 = self._probe_io(self._session_2, self.frame_size)
        self._state_1_shape = self._state_input_shape(self._session_1, self._io_1[1])
        self._state_2_shape = self._state_input_shape(self._session_2, self._io_2[1])
        self.reset()

    def _process_hop(self, hop):
        import numpy as np  # noqa: PLC0415

        assert self._session_1 is not None
        assert self._session_2 is not None
        assert self._io_1 is not None
        assert self._io_2 is not None
        assert self._state_1 is not None
        assert self._state_2 is not None

        self._analysis_buffer[:-self.hop_size] = self._analysis_buffer[self.hop_size :]
        self._analysis_buffer[-self.hop_size :] = np.asarray(hop, dtype=np.float32)

        spectrum = np.fft.rfft(self._analysis_buffer)
        magnitude = np.abs(spectrum).astype(np.float32).reshape(1, 1, self.fft_bins)

        frame_in_1, state_in_1, frame_out_1, state_out_1 = self._io_1
        mask, self._state_1 = self._session_1.run(
            [frame_out_1, state_out_1],
            {frame_in_1: magnitude, state_in_1: self._state_1},
        )
        mask = np.asarray(mask, dtype=np.float32).reshape(self.fft_bins)
        masked = spectrum * mask
        time_frame = np.fft.irfft(masked, n=self.frame_size).astype(np.float32).reshape(1, 1, self.frame_size)

        frame_in_2, state_in_2, frame_out_2, state_out_2 = self._io_2
        enhanced, self._state_2 = self._session_2.run(
            [frame_out_2, state_out_2],
            {frame_in_2: time_frame, state_in_2: self._state_2},
        )
        enhanced = np.asarray(enhanced, dtype=np.float32).reshape(self.frame_size)

        self._ola_buffer[:-self.hop_size] = self._ola_buffer[self.hop_size :]
        self._ola_buffer[-self.hop_size :] = 0.0
        self._ola_buffer += enhanced
        return self._ola_buffer[: self.hop_size].copy()

    @classmethod
    def _probe_io(cls, session: Any, frame_size: int) -> tuple[str, str, str, str]:
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        frame_input = next((meta for meta in inputs if cls._last_dim(meta, frame_size)), inputs[0])
        state_input = next((meta for meta in inputs if meta.name != frame_input.name), inputs[-1])
        frame_output = next((meta for meta in outputs if cls._last_dim(meta, frame_size)), outputs[0])
        state_output = next((meta for meta in outputs if meta.name != frame_output.name), outputs[-1])
        return frame_input.name, state_input.name, frame_output.name, state_output.name

    @classmethod
    def _last_dim(cls, meta: Any, value: int) -> bool:
        shape = list(getattr(meta, "shape", []) or [])
        return bool(shape) and shape[-1] == value

    @classmethod
    def _state_input_shape(cls, session: Any, input_name: str) -> tuple[int, ...]:
        meta = next((item for item in session.get_inputs() if item.name == input_name), None)
        raw_shape = list(getattr(meta, "shape", []) or [])
        shape = tuple(int(dim) for dim in raw_shape if isinstance(dim, int))
        return shape if len(shape) == len(raw_shape) and shape else cls.state_shape
