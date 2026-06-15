"""Input-side DSP helpers for native voice conversion.

All functions operate on mono float32-ish arrays. Heavy dependencies are loaded
inside functions so importing the voice engine stays cheap in stub/API tests.
"""

from __future__ import annotations

INPUT_SAMPLE_RATE = 16_000
DEFAULT_INPUT_HIGHPASS_HZ = 80
DEFAULT_INPUT_GATE_DB = GATE_OFF_DB = -90.0
DEFAULT_INPUT_FORMANT = 0.0
DEFAULT_SILENCE_THRESHOLD_DB = -72.0
DEFAULT_SILENCE_HOLD_MS = 250.0
SQUELCH_OFF_DB = -90.0
SQUELCH_CLOSE_HYSTERESIS_DB = 6.0
OUTPUT_LIMITER_CEILING_DBFS = -1.0


def dbfs_to_linear(dbfs: float) -> float:
    return float(10.0 ** (float(dbfs) / 20.0))


def peak_dbfs(audio) -> float:
    import numpy as np  # noqa: PLC0415

    arr = _as_float32(audio)
    if arr.size == 0:
        return -240.0
    peak = float(np.max(np.abs(arr)))
    return float(20.0 * np.log10(max(peak, 1e-12)))


def limit_output(audio, *, ceiling_dbfs: float = OUTPUT_LIMITER_CEILING_DBFS):
    """Transparent block limiter used as an output safety guard.

    It leaves audio unchanged below the ceiling and applies only the gain
    reduction needed to keep the block under the configured full-scale limit.
    """
    import numpy as np  # noqa: PLC0415

    arr = _as_float32(audio)
    if arr.size == 0:
        return arr.astype(np.float32, copy=True), {
            "peak": 0.0,
            "peak_dbfs": -240.0,
            "limiter_reduction_db": 0.0,
        }
    ceiling = dbfs_to_linear(ceiling_dbfs)
    peak_in = float(np.max(np.abs(arr)))
    if peak_in <= ceiling:
        out = arr.astype(np.float32, copy=True)
        reduction = 0.0
    else:
        gain = ceiling / max(peak_in, 1e-12)
        out = (arr * np.float32(gain)).astype(np.float32, copy=False)
        reduction = float(-20.0 * np.log10(max(gain, 1e-12)))
    peak_out = float(np.max(np.abs(out))) if out.size else 0.0
    return out, {
        "peak": min(1.0, peak_out),
        "peak_dbfs": peak_dbfs(out),
        "limiter_reduction_db": round(reduction, 3),
    }


def clamp_input_highpass_hz(value: object) -> int:
    """Clamp high-pass cutoff to 0..300 Hz. 0 or "off" disables the filter."""
    if isinstance(value, str) and value.strip().lower() == "off":
        return 0
    return max(0, min(300, int(float(value))))


def clamp_input_gate_db(value: object) -> float:
    """Clamp gate threshold to -90..-20 dBFS.

    -90 dB is treated as the off position. A legacy/UI value of 0 or the string
    "off" also maps to -90 so callers can disable the gate without remembering
    the exact sentinel.
    """
    if isinstance(value, str) and value.strip().lower() == "off":
        return GATE_OFF_DB
    n = float(value)
    if n == 0.0:
        return GATE_OFF_DB
    return max(GATE_OFF_DB, min(-20.0, n))


def clamp_input_formant(value: object) -> float:
    """Clamp input-side formant/brightness shift to +/-2 semitone-like units."""
    return max(-2.0, min(2.0, float(value)))


def clamp_silence_threshold_db(value: object) -> float:
    """Clamp realtime squelch threshold to -90..-20 dBFS.

    -90 dBFS is the off position: the realtime squelch always passes audio.
    """
    if isinstance(value, str) and value.strip().lower() == "off":
        return SQUELCH_OFF_DB
    n = float(value)
    if n == 0.0:
        return SQUELCH_OFF_DB
    return max(SQUELCH_OFF_DB, min(-20.0, n))


def clamp_silence_hold_ms(value: object) -> float:
    """Clamp realtime squelch hangover to 0..2000 ms."""
    return max(0.0, min(2000.0, float(value)))


def rms_dbfs(audio) -> float:
    """Return RMS in dBFS for float audio where +/-1.0 is full scale."""
    import numpy as np  # noqa: PLC0415

    arr = _as_float32(audio)
    if arr.size == 0:
        return -240.0
    rms = float(np.sqrt(np.mean(np.square(arr, dtype=np.float32))))
    return float(20.0 * np.log10(max(rms, 1e-12)))


class SquelchGate:
    """Realtime silence gate with open hysteresis and close hangover.

    ``update`` returns True while the gate is closed and the caller should emit
    silence. It opens immediately above threshold and closes only after
    continuous time below threshold - 6 dB reaches the configured hold time.
    """

    def __init__(
        self,
        threshold_db: object = DEFAULT_SILENCE_THRESHOLD_DB,
        hold_ms: object = DEFAULT_SILENCE_HOLD_MS,
    ) -> None:
        self.threshold_db = clamp_silence_threshold_db(threshold_db)
        self.hold_ms = clamp_silence_hold_ms(hold_ms)
        self._open = False
        self._below_ms = 0.0
        self._disabled = self.threshold_db <= SQUELCH_OFF_DB

    @property
    def is_open(self) -> bool:
        return self._open or self._disabled

    @property
    def is_closed(self) -> bool:
        return not self.is_open

    def configure(self, *, threshold_db: object, hold_ms: object) -> None:
        threshold = clamp_silence_threshold_db(threshold_db)
        hold = clamp_silence_hold_ms(hold_ms)
        disabled = threshold <= SQUELCH_OFF_DB
        if disabled != self._disabled:
            self._open = disabled
            self._below_ms = 0.0
        self.threshold_db = threshold
        self.hold_ms = hold
        self._disabled = disabled

    def reset(self, *, open_gate: bool = False) -> None:
        self._open = bool(open_gate)
        self._below_ms = 0.0

    def update(
        self,
        rms_db: float,
        duration_ms: float,
        *,
        threshold_db: object | None = None,
        hold_ms: object | None = None,
    ) -> bool:
        if threshold_db is not None or hold_ms is not None:
            self.configure(
                threshold_db=self.threshold_db if threshold_db is None else threshold_db,
                hold_ms=self.hold_ms if hold_ms is None else hold_ms,
            )

        if self._disabled:
            self._open = True
            self._below_ms = 0.0
            return False

        if float(rms_db) >= self.threshold_db:
            self._open = True
            self._below_ms = 0.0
            return False

        if self._open:
            if float(rms_db) < self.threshold_db - SQUELCH_CLOSE_HYSTERESIS_DB:
                self._below_ms += max(0.0, float(duration_ms))
                if self._below_ms >= self.hold_ms:
                    self._open = False
                    self._below_ms = 0.0
            else:
                self._below_ms = 0.0

        return not self._open


class StreamingHighpass:
    """Causal 2nd-order Butterworth high-pass with persistent filter state.

    The realtime chunk processor filters each newly captured piece exactly once
    and appends it to its rolling context. A stateful IIR keeps the stream
    gapless; the FFT-based ``apply_highpass`` is only safe for whole files
    because its circular convolution changes both edges of a sliding window on
    every call.
    """

    def __init__(self, cutoff_hz: object = DEFAULT_INPUT_HIGHPASS_HZ, *, sample_rate: int = INPUT_SAMPLE_RATE) -> None:
        self.sample_rate = int(sample_rate)
        self.cutoff_hz = -1
        self._coeffs: tuple[float, float, float, float, float] | None = None
        self._zi = None
        self.configure(cutoff_hz)

    def configure(self, cutoff_hz: object) -> None:
        cutoff = clamp_input_highpass_hz(cutoff_hz)
        if cutoff == self.cutoff_hz:
            return
        self.cutoff_hz = cutoff
        if cutoff <= 0:
            self._coeffs = None
            self._zi = None
            return
        import numpy as np  # noqa: PLC0415

        # RBJ cookbook high-pass biquad, Q = 1/sqrt(2) (Butterworth).
        w0 = 2.0 * np.pi * float(cutoff) / float(self.sample_rate)
        cos_w0 = float(np.cos(w0))
        q = 2.0 ** -0.5
        alpha = float(np.sin(w0)) / (2.0 * q)
        a0 = 1.0 + alpha
        self._coeffs = (
            (1.0 + cos_w0) / 2.0 / a0,   # b0
            -(1.0 + cos_w0) / a0,        # b1
            (1.0 + cos_w0) / 2.0 / a0,   # b2
            -2.0 * cos_w0 / a0,          # a1
            (1.0 - alpha) / a0,          # a2
        )
        # Filter state survives a cutoff change: a brief coefficient blend
        # transient beats a hard discontinuity in a live stream.
        if self._zi is None:
            self._zi = np.zeros(2, dtype=np.float64)

    def process(self, audio, cutoff_hz: object | None = None):
        import numpy as np  # noqa: PLC0415

        if cutoff_hz is not None:
            self.configure(cutoff_hz)
        block = _as_float32(audio)
        if self._coeffs is None or block.size == 0:
            return block.astype(np.float32, copy=True)
        b0, b1, b2, a1, a2 = self._coeffs
        try:
            from scipy.signal import lfilter  # noqa: PLC0415

            out, self._zi = lfilter(
                [b0, b1, b2], [1.0, a1, a2], block.astype(np.float64), zi=self._zi
            )
            return out.astype(np.float32)
        except ImportError:
            out = np.empty(block.size, dtype=np.float64)
            z1, z2 = float(self._zi[0]), float(self._zi[1])
            for i in range(block.size):
                x = float(block[i])
                y = b0 * x + z1
                z1 = b1 * x - a1 * y + z2
                z2 = b2 * x - a2 * y
                out[i] = y
            self._zi[0], self._zi[1] = z1, z2
            return out.astype(np.float32)


def input_formant_factor(input_formant: float) -> float:
    return float(2.0 ** (clamp_input_formant(input_formant) / 12.0))


def compensate_f0_for_input_formant(f0, factor: float):
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(f0, dtype=np.float32)
    if factor <= 0.0 or abs(factor - 1.0) < 1e-6:
        return arr
    return (arr / float(factor)).astype(np.float32)


def _as_float32(audio):
    import numpy as np  # noqa: PLC0415

    return np.asarray(audio, dtype=np.float32).reshape(-1)


def apply_highpass(audio_16k, cutoff_hz: object = DEFAULT_INPUT_HIGHPASS_HZ, *, sample_rate: int = INPUT_SAMPLE_RATE):
    """FFT-domain high-pass with a raised-cosine transition below cutoff."""
    import numpy as np  # noqa: PLC0415

    audio = _as_float32(audio_16k)
    cutoff = clamp_input_highpass_hz(cutoff_hz)
    if cutoff <= 0 or audio.size == 0:
        return audio.astype(np.float32, copy=True)

    n = int(audio.size)
    freqs = np.fft.rfftfreq(n, d=1.0 / float(sample_rate))
    spectrum = np.fft.rfft(audio)

    gain = np.ones_like(freqs, dtype=np.float32)
    stop_hz = float(cutoff) * 0.75
    gain[freqs <= stop_hz] = 0.0
    transition = (freqs > stop_hz) & (freqs < float(cutoff))
    if np.any(transition):
        x = (freqs[transition] - stop_hz) / max(float(cutoff) - stop_hz, 1e-6)
        gain[transition] = (0.5 - 0.5 * np.cos(np.pi * x)).astype(np.float32)

    return np.fft.irfft(spectrum * gain, n=n).astype(np.float32)


def apply_noise_gate(
    audio_16k,
    gate_db: object = DEFAULT_INPUT_GATE_DB,
    *,
    sample_rate: int = INPUT_SAMPLE_RATE,
):
    """Frame-RMS noise gate with attack/release smoothing.

    The off position is -90 dBFS (or 0/"off" through the clamp helper). Closed
    gain is -80 dB rather than zero to avoid hard pumping artifacts.
    """
    import numpy as np  # noqa: PLC0415

    audio = _as_float32(audio_16k)
    threshold = clamp_input_gate_db(gate_db)
    if threshold <= GATE_OFF_DB or audio.size == 0:
        return audio.astype(np.float32, copy=True)

    frame = max(1, int(round(float(sample_rate) * 0.010)))
    frame_count = int(np.ceil(audio.size / frame))
    padded = np.pad(audio, (0, frame_count * frame - audio.size))
    frames = padded.reshape(frame_count, frame)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float32), axis=1))
    db = 20.0 * np.log10(np.maximum(rms, 1e-12))

    floor = np.float32(10.0 ** (-80.0 / 20.0))
    target = np.where(db >= threshold, 1.0, floor).astype(np.float32)

    env = np.empty_like(target)
    env[0] = target[0]
    frame_s = frame / float(sample_rate)
    attack = 1.0 - np.exp(-frame_s / 0.005)
    release = 1.0 - np.exp(-frame_s / 0.120)
    for i in range(1, frame_count):
        coeff = attack if target[i] > env[i - 1] else release
        env[i] = env[i - 1] + np.float32(coeff) * (target[i] - env[i - 1])

    frame_pos = np.arange(frame_count, dtype=np.float32) * frame + (frame - 1) / 2.0
    sample_pos = np.arange(audio.size, dtype=np.float32)
    gain = np.interp(sample_pos, frame_pos, env, left=float(env[0]), right=float(env[-1])).astype(np.float32)
    return (audio * gain).astype(np.float32)


def apply_input_formant(
    audio_16k,
    input_formant: object = DEFAULT_INPUT_FORMANT,
    *,
    sample_rate: int = INPUT_SAMPLE_RATE,
) -> tuple[object, float]:
    """Shift the analysis signal's formant/brightness by resampling.

    Positive values are brighter: the analysis signal is resampled to
    ``sample_rate / factor`` and then interpreted by ContentVec/RMVPE as 16 kHz,
    raising the measured spectrum by ``factor``. The downstream f0 path divides
    by the same factor so pitch transpose remains the dedicated pitch control.
    """
    import numpy as np  # noqa: PLC0415

    audio = _as_float32(audio_16k)
    factor = input_formant_factor(clamp_input_formant(input_formant))
    if abs(factor - 1.0) < 1e-6 or audio.size == 0:
        return audio.astype(np.float32, copy=True), 1.0

    import soxr  # noqa: PLC0415

    shifted = soxr.resample(audio, float(sample_rate), float(sample_rate) / factor).astype(np.float32)
    return shifted, factor


def compensate_output_duration_for_input_formant(
    audio,
    factor: float,
    *,
    sample_rate: int,
):
    """Undo the analysis-path duration change before offline return/realtime tailing.

    Keeping this as the single output-length correction point means the realtime
    ``ChunkProcessor`` can continue to take the tail matching the current chunk,
    while offline conversion returns roughly the same duration as the source.
    """
    import numpy as np  # noqa: PLC0415

    out = np.asarray(audio, dtype=np.float32).reshape(-1)
    if abs(float(factor) - 1.0) < 1e-6 or out.size == 0:
        return out.astype(np.float32, copy=True)

    import soxr  # noqa: PLC0415

    return soxr.resample(out, float(sample_rate), float(sample_rate) * float(factor)).astype(np.float32)


def process_input(
    audio_16k,
    *,
    input_highpass_hz: object = DEFAULT_INPUT_HIGHPASS_HZ,
    input_gate_db: object = DEFAULT_INPUT_GATE_DB,
    input_formant: object = DEFAULT_INPUT_FORMANT,
) -> tuple[object, float]:
    """Apply input clean-up and analysis-side character shift."""
    cleaned = apply_highpass(audio_16k, input_highpass_hz)
    cleaned = apply_noise_gate(cleaned, input_gate_db)
    return apply_input_formant(cleaned, input_formant)
