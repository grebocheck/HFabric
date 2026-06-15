"""Offline native RVC conversion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from . import dsp
from .f0 import create_f0_extractor
from .features import ContentVec


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def _sample_rate(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.endswith("k") and value[:-1].isdigit():
            return int(value[:-1]) * 1000
        try:
            return int(value)
        except ValueError:
            pass
    return 40000


def f0_to_coarse(f0):
    import numpy as np  # noqa: PLC0415

    f0 = np.asarray(f0, dtype=np.float32)
    f0_mel = 1127.0 * np.log1p(np.maximum(f0, 0.0) / 700.0)
    f0_mel_min = 1127.0 * np.log1p(50.0 / 700.0)
    f0_mel_max = 1127.0 * np.log1p(1100.0 / 700.0)
    voiced = f0_mel > 0
    f0_mel[voiced] = (f0_mel[voiced] - f0_mel_min) * 254.0 / (f0_mel_max - f0_mel_min) + 1.0
    f0_mel[f0_mel <= 1.0] = 1.0
    f0_mel[f0_mel > 255.0] = 255.0
    return np.rint(f0_mel).astype("int64")


def _resize_1d(values, target: int):
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(values, dtype=np.float32).reshape(-1)
    if arr.size == target:
        return arr
    if arr.size == 0:
        return np.zeros(target, dtype=np.float32)
    old = np.linspace(0.0, 1.0, num=arr.size, endpoint=True)
    new = np.linspace(0.0, 1.0, num=target, endpoint=True)
    return np.interp(new, old, arr).astype(np.float32)


def _median_filter(values, width: int):
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(values, dtype=np.float32).reshape(-1)
    if width <= 1 or arr.size < width:
        return arr.astype(np.float32, copy=True)
    pad = width // 2
    padded = np.pad(arr, (pad, pad), mode="edge")
    out = np.empty_like(arr)
    for idx in range(arr.size):
        out[idx] = np.median(padded[idx : idx + width])
    return out.astype(np.float32, copy=False)


def _smooth_f0(f0, amount: float):
    """Smooth voiced islands only so consonants stay unvoiced and crisp."""
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(f0, dtype=np.float32).reshape(-1)
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0 or arr.size < 3:
        return arr.astype(np.float32, copy=True)

    out = arr.astype(np.float32, copy=True)
    voiced = out > 0.0
    width = 3 if amount < 0.5 else 5
    idx = 0
    while idx < out.size:
        if not voiced[idx]:
            idx += 1
            continue
        start = idx
        while idx < out.size and voiced[idx]:
            idx += 1
        end = idx
        if end - start < 3:
            continue
        run = out[start:end]
        median = _median_filter(run, width)
        out[start:end] = run * (1.0 - amount) + median * amount
    return out.astype(np.float32, copy=False)


def _upsample_features(features):
    import numpy as np  # noqa: PLC0415

    feats = np.asarray(features, dtype=np.float32)
    if feats.ndim != 2:
        raise ValueError(f"ContentVec output must be [T, 768], got {feats.shape}")
    # Frame-repeat, exactly like upstream RVC's F.interpolate(scale_factor=2)
    # with the default nearest mode. The synthesizer was trained on repeated
    # frames; linear interpolation smears consonant transients and audibly
    # softens sibilants.
    return np.repeat(feats, 2, axis=0)


def _index_mix(features, index_state: dict[str, Any] | None, index_ratio: float):
    if not index_state or index_ratio <= 0.0:
        return features
    import numpy as np  # noqa: PLC0415

    index = index_state["index"]
    big_npy = index_state["big_npy"]
    if big_npy is None:
        return features
    k = min(8, int(getattr(index, "ntotal", 0) or 0))
    if k <= 0:
        return features
    distances, indices = index.search(features.astype(np.float32), k)
    valid = indices >= 0
    safe_indices = np.where(valid, indices, 0)
    neighbors = big_npy[safe_indices]
    # Upstream RVC weighting: faiss returns squared-L2 distances and neighbors
    # are weighted by square(1/d), normalized. The previous exp(-d) collapsed
    # for typical ContentVec distances (d ~ 60: 74% of frames had every
    # neighbor clamped, averaging 8 spread-out vectors into ~zero), so at high
    # index_ratio the synthesizer got empty phones - audible as a pitch-only
    # "ahh" with no articulation. Measured on the real index: retrieved norm
    # 0.11 / cos 0.06 (old) vs 6.67 / cos 0.67 (this formula) for query
    # features of norm 7.4.
    safe_distances = np.asarray(distances, dtype=np.float32)
    safe_distances = np.where(np.isfinite(safe_distances), np.maximum(safe_distances, 1e-8), np.inf)
    weights = np.square(1.0 / safe_distances)
    weights = np.where(valid, weights, 0.0)
    denom = np.maximum(weights.sum(axis=1, keepdims=True), 1e-8)
    weights = weights / denom
    retrieved = (neighbors * weights[..., None]).sum(axis=1).astype(np.float32)
    return features * (1.0 - index_ratio) + retrieved * index_ratio


def _load_index(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    import faiss  # noqa: PLC0415

    index = faiss.read_index(str(path))
    count = int(getattr(index, "ntotal", 0) or 0)
    if count <= 0:
        return {"index": index, "big_npy": None}
    big_npy = index.reconstruct_n(0, count)
    return {"index": index, "big_npy": big_npy}


@dataclass
class LoadedVoiceModel:
    slot: dict[str, Any]
    synthesizer: Any
    version: str
    f0: bool
    sample_rate: int
    speaker_count: int
    default_speaker_id: int
    content_vec: ContentVec
    f0_model_path: Path
    index_state: dict[str, Any] | None


def _phone_embed_dim(state: dict[str, Any]) -> int | None:
    """Return the ContentVec input dim of an RVC state dict (768=v2, 256=v1).

    ``enc_p.emb_phone`` is a Linear(in=ContentVec dim, out=hidden), so its
    weight is [hidden, dim]. Returns None when the key is absent (e.g. an
    unexpected export layout) so the caller can fall back to the version field.
    """
    weight = state.get("enc_p.emb_phone.weight")
    shape = getattr(weight, "shape", None)
    if shape is None or len(shape) != 2:
        return None
    return int(shape[1])


def _clamp_speaker_id(value: object, speaker_count: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    upper = max(0, int(speaker_count) - 1)
    return max(0, min(upper, n))


def _checkpoint_speaker_id(checkpoint: dict[str, Any]) -> int | None:
    # `speakers_id` in some exports is the speaker count, not the target id.
    # Only trust explicit sid-style fields for the default inference id.
    for key in ("speaker_id", "speakerId", "sid"):
        if key in checkpoint:
            try:
                return int(checkpoint[key])
            except (TypeError, ValueError):
                return None
    return None


def _slot_speaker_id(slot: dict[str, Any]) -> int | None:
    for key in ("speaker_id", "speakerId", "sid"):
        if key in slot and slot[key] is not None:
            try:
                return int(slot[key])
            except (TypeError, ValueError):
                return None
    return None


def load_model(slot: dict[str, Any], assets: dict[str, str], device: str) -> LoadedVoiceModel:
    import torch  # noqa: PLC0415

    model_path = Path(slot["model_path"])
    if model_path.suffix.lower() == ".pth":
        # Standard RVC checkpoints store a Python dict with `weight`, `config`,
        # `f0`, `version`, and `sr`. `weights_only=False` is required because the
        # outer dict is not a pure tensor state_dict in current torch releases.
        checkpoint = torch.load(str(model_path), map_location="cpu", weights_only=False)
        if not isinstance(checkpoint, dict):
            raise ValueError("RVC checkpoint did not contain a dict")
        state = checkpoint.get("weight") or {}
        config = list(checkpoint.get("config") or [])
        f0 = bool(checkpoint.get("f0", 1))
        version = str(checkpoint.get("version") or "")
        sample_rate = _sample_rate(checkpoint.get("sr") or (config[-1] if config else None))
        checkpoint_sid = _checkpoint_speaker_id(checkpoint)
    elif model_path.suffix.lower() == ".safetensors":
        from safetensors.torch import load_file  # noqa: PLC0415

        state = load_file(str(model_path), device="cpu")
        config = []
        f0 = bool(slot.get("f0", True))
        version = str(slot.get("version") or "")
        sample_rate = _sample_rate(slot.get("sampling_rate"))
        checkpoint_sid = None
    else:
        raise ValueError(f"unsupported RVC model file: {model_path.suffix}")

    # Trust the weights over the metadata string: v2 uses a 768-dim ContentVec
    # phone embedding, v1 a 256-dim one. Many community v2 checkpoints ship with
    # an empty/missing `version` field, and the old `or "v1"` default rejected
    # them outright. Detecting from the embedding shape lets any real v2 model
    # load while still giving v1 models a precise, actionable error.
    phone_dim = _phone_embed_dim(state)
    if phone_dim is not None and phone_dim != 768:
        raise NotImplementedError(
            f"native voice engine supports RVC v2 (768-dim ContentVec) checkpoints only; "
            f"this model has a {phone_dim}-dim phone embedding (looks like RVC v1)"
        )
    if phone_dim is None and version and version != "v2":
        raise NotImplementedError(
            f"native voice engine supports RVC v2 checkpoints only (got version {version!r})"
        )
    if not config:
        raise NotImplementedError("native voice engine real mode requires RVC checkpoint config metadata")

    from .rvc.models import SynthesizerTrnMs768NSFsid, SynthesizerTrnMs768NSFsid_nono  # noqa: PLC0415

    cls = SynthesizerTrnMs768NSFsid if f0 else SynthesizerTrnMs768NSFsid_nono
    synthesizer = cls(*config, is_half=False)
    incompatible = synthesizer.load_state_dict(state, strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise RuntimeError(
            "RVC checkpoint strict load failed: "
            f"missing={incompatible.missing_keys}, unexpected={incompatible.unexpected_keys}"
        )
    synthesizer.remove_weight_norm()
    synthesizer.eval().to(device)
    speaker_count = int(getattr(synthesizer, "spk_embed_dim", 1) or 1)
    default_sid = _slot_speaker_id(slot)
    if default_sid is None:
        default_sid = checkpoint_sid
    default_sid = _clamp_speaker_id(0 if default_sid is None else default_sid, speaker_count)

    return LoadedVoiceModel(
        slot=slot,
        synthesizer=synthesizer,
        version=version,
        f0=f0,
        sample_rate=sample_rate,
        speaker_count=speaker_count,
        default_speaker_id=default_sid,
        content_vec=ContentVec(Path(assets["content_vec"])),
        f0_model_path=Path(assets["rmvpe"]),
        index_state=_load_index(slot.get("index_path")),
    )


def convert(
    input_path: Path,
    loaded: LoadedVoiceModel,
    *,
    pitch: int,
    index_ratio: float,
    protect: float,
    f0_detector: str,
    device: str,
    input_highpass_hz: int = dsp.DEFAULT_INPUT_HIGHPASS_HZ,
    input_gate_db: float = dsp.DEFAULT_INPUT_GATE_DB,
    input_formant: float = dsp.DEFAULT_INPUT_FORMANT,
    speaker_id: int | None = None,
    noise_scale: float = 0.66666,
    f0_smoothing: float = 0.0,
    denoiser: Any | None = None,
    denoise_mix: float = 1.0,
):
    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415
    import soxr  # noqa: PLC0415

    timings: dict[str, float] = {}

    stage = time.perf_counter()
    audio, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
    mono = np.mean(audio, axis=1).astype(np.float32)
    timings["load_audio"] = _ms(stage)

    stage = time.perf_counter()
    audio_16k = mono if int(sr) == 16000 else soxr.resample(mono, int(sr), 16000).astype(np.float32)
    timings["resample_16k"] = _ms(stage)

    out, out_sr, core_timings = convert_audio(
        audio_16k,
        loaded,
        pitch=pitch,
        index_ratio=index_ratio,
        protect=protect,
        f0_detector=f0_detector,
        input_highpass_hz=input_highpass_hz,
        input_gate_db=input_gate_db,
        input_formant=input_formant,
        speaker_id=speaker_id,
        noise_scale=noise_scale,
        f0_smoothing=f0_smoothing,
        denoiser=denoiser,
        denoise_mix=denoise_mix,
        device=device,
    )
    timings.update(core_timings)
    return out, out_sr, timings


def convert_audio(
    audio_16k,
    loaded: LoadedVoiceModel,
    *,
    pitch: int,
    index_ratio: float,
    protect: float,
    f0_detector: str,
    device: str,
    input_highpass_hz: int = dsp.DEFAULT_INPUT_HIGHPASS_HZ,
    input_gate_db: float = dsp.DEFAULT_INPUT_GATE_DB,
    input_formant: float = dsp.DEFAULT_INPUT_FORMANT,
    speaker_id: int | None = None,
    noise_scale: float = 0.66666,
    f0_smoothing: float = 0.0,
    denoiser: Any | None = None,
    denoise_mix: float = 1.0,
    external_formant_factor: float | None = None,
    compensate_duration: bool = True,
    latent_noise: Any | None = None,
):
    """Shared conversion core: 16 kHz mono float32 array -> (audio @ model sr,
    sr, per-stage timings). The offline file path and the realtime chunk
    processor both run through here so their outputs can never diverge.

    The realtime chunk processor pre-cleans its stream (DTLN/HPF/formant run
    statefully on each new piece exactly once): it passes
    ``external_formant_factor`` so this core skips ``dsp.process_input`` but
    still compensates f0 for the analysis-side shift, sets
    ``compensate_duration=False`` because it corrects duration in its streaming
    output resampler, and supplies ``latent_noise`` ([channels, frames], newest
    frame last) so overlapping context re-synthesizes identically each chunk.
    """
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    timings: dict[str, float] = {}

    audio = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
    if denoiser is not None:
        stage = time.perf_counter()
        raw_audio = audio
        denoised = np.asarray(denoiser.process(audio), dtype=np.float32).reshape(-1)
        mix = max(0.0, min(1.0, float(denoise_mix)))
        if denoised.size != raw_audio.size:
            target = min(denoised.size, raw_audio.size)
            denoised = denoised[:target]
            raw_audio = raw_audio[:target]
        audio = denoised * np.float32(mix) + raw_audio * np.float32(1.0 - mix)
        timings["input_denoise"] = _ms(stage)
        timings["input_denoise_mix"] = round(mix, 3)

    if external_formant_factor is None:
        stage = time.perf_counter()
        analysis_audio, formant_factor = dsp.process_input(
            audio,
            input_highpass_hz=input_highpass_hz,
            input_gate_db=input_gate_db,
            input_formant=input_formant,
        )
        timings["input_dsp"] = _ms(stage)
    else:
        analysis_audio = audio
        formant_factor = float(external_formant_factor)

    stage = time.perf_counter()
    base_features = loaded.content_vec.extract(analysis_audio)
    timings["content_vec"] = _ms(stage)

    stage = time.perf_counter()
    mixed_features = _index_mix(base_features, loaded.index_state, float(index_ratio))
    timings["index_mix"] = _ms(stage)

    stage = time.perf_counter()
    features = _upsample_features(mixed_features)
    protected_features = _upsample_features(base_features)
    timings["feature_upsample"] = _ms(stage)

    f0 = None
    pitch_coarse = None
    stage = time.perf_counter()
    if loaded.f0:
        extractor = create_f0_extractor(f0_detector, loaded.f0_model_path, device)
        f0 = extractor.compute(analysis_audio, sr=16000)
        f0 = _resize_1d(f0, features.shape[0])
        f0 = dsp.compensate_f0_for_input_formant(f0, formant_factor)
        if pitch:
            f0 = f0 * (2.0 ** (float(pitch) / 12.0))
        f0 = _smooth_f0(f0, f0_smoothing)
        pitch_coarse = f0_to_coarse(f0)
    timings["f0"] = _ms(stage)

    stage = time.perf_counter()
    if loaded.f0 and protect < 0.5 and f0 is not None:
        pitchff = np.where(f0 > 0.0, 1.0, float(protect)).astype(np.float32)[:, None]
        features = features * pitchff + protected_features * (1.0 - pitchff)
    timings["protect"] = _ms(stage)

    stage = time.perf_counter()
    phone = torch.from_numpy(features[None, :, :]).to(device=device, dtype=torch.float32)
    phone_lengths = torch.tensor([features.shape[0]], device=device, dtype=torch.long)
    sid_value = loaded.default_speaker_id if speaker_id is None else _clamp_speaker_id(speaker_id, loaded.speaker_count)
    sid = torch.tensor([sid_value], device=device, dtype=torch.long)
    latent_tensor = None
    if latent_noise is not None:
        latent_array = np.ascontiguousarray(np.asarray(latent_noise, dtype=np.float32))
        latent_tensor = torch.from_numpy(latent_array)[None, :, :].to(device=device, dtype=torch.float32)
    with torch.no_grad():
        if loaded.f0:
            assert pitch_coarse is not None and f0 is not None
            pitch_tensor = torch.from_numpy(pitch_coarse[None, :]).to(device=device, dtype=torch.long)
            f0_tensor = torch.from_numpy(f0[None, :]).to(device=device, dtype=torch.float32)
            output = loaded.synthesizer.infer(
                phone,
                phone_lengths,
                pitch_tensor,
                f0_tensor,
                sid,
                noise_scale=float(noise_scale),
                latent_noise=latent_tensor,
            )[0]
        else:
            output = loaded.synthesizer.infer(
                phone,
                phone_lengths,
                sid,
                noise_scale=float(noise_scale),
                latent_noise=latent_tensor,
            )[0]
    timings["synth"] = _ms(stage)

    stage = time.perf_counter()
    out = output.detach().cpu().numpy().reshape(-1).astype(np.float32)
    if compensate_duration:
        out = dsp.compensate_output_duration_for_input_formant(
            out,
            formant_factor,
            sample_rate=loaded.sample_rate,
        )
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out = out / peak
    timings["postprocess"] = _ms(stage)
    return out, loaded.sample_rate, timings
