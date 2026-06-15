"""F0 extraction for native RVC conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("hfabric")

F0_DETECTORS = {
    "rmvpe_onnx",
    "rmvpe",
    "crepe_onnx_tiny",
    "crepe_onnx_full",
    "crepe_tiny",
    "crepe_full",
    "fcpe",
    "fcpe_onnx",
}

SUPPORTED_DETECTORS = {"rmvpe", "fcpe", "crepe_tiny", "crepe_full"}
_CREPE_MODELS = {"crepe_tiny": "tiny", "crepe_full": "full"}

# Voiced/unvoiced confidence gate. Below this the frame is returned as 0
# (unvoiced) so the downstream protect mask and f0->coarse mapping treat
# consonants the same way they do under RMVPE.
FCPE_THRESHOLD = 0.006
F0_MIN = 50.0
F0_MAX = 1100.0
# CREPE returns a periodicity confidence per frame; below this the frame is
# unvoiced. 0.21 is the value RVC/torchcrepe integrations use for speech.
CREPE_PERIODICITY_THRESHOLD = 0.21
# 160 samples @ 16 kHz = one synth frame; f0 is resized to the feature grid
# downstream anyway, so this only needs to be in the right ballpark.
CREPE_HOP_16K = 160


class F0Extractor:
    def __init__(self, detector: str, model_path: Path, device: str = "cpu") -> None:
        if detector not in SUPPORTED_DETECTORS:
            raise ValueError(f"native voice engine supports {sorted(SUPPORTED_DETECTORS)} (got {detector})")
        self.detector = detector
        self.model_path = Path(model_path)
        self.device = device
        self._impl = None
        self._actual_provider: str | None = None

    def provider_health(self) -> dict[str, object]:
        return {
            "name": self.detector,
            "requested": f"torch:{self.device}",
            "actual": self._actual_provider,
            "loaded": self._impl is not None,
        }

    def _load(self):
        if self._impl is not None:
            return self._impl
        if self.detector == "fcpe":
            from torchfcpe import spawn_bundled_infer_model  # noqa: PLC0415

            # FCPE is ~8x faster than RMVPE on GPU and bundles its own weights
            # (downloaded/cached on first spawn); the rmvpe.pt path is ignored.
            self._impl = spawn_bundled_infer_model(device=self.device)
            self._actual_provider = f"torch:{self.device}"
            logger.info(
                "event=voice.provider component=f0 detector=%s requested=%s actual=%s",
                self.detector,
                f"torch:{self.device}",
                self._actual_provider,
            )
            return self._impl
        if self.detector in _CREPE_MODELS:
            import torchcrepe  # noqa: PLC0415

            # torchcrepe ships its weights in the package and lazily loads the
            # requested capacity on first predict; nothing to construct here, so
            # use the module itself as the impl handle (the cache key keeps tiny
            # and full as separate extractors).
            self._impl = torchcrepe
            self._actual_provider = f"torch:{self.device}"
            logger.info(
                "event=voice.provider component=f0 detector=%s requested=%s actual=%s",
                self.detector,
                f"torch:{self.device}",
                self._actual_provider,
            )
            return self._impl
        from .rvc.rmvpe import RMVPE  # noqa: PLC0415

        self._impl = RMVPE(self.model_path, device=self.device)
        actual_device = getattr(self._impl, "device", self.device)
        self._actual_provider = f"torch:{actual_device}"
        logger.info(
            "event=voice.provider component=f0 detector=%s requested=%s actual=%s",
            self.detector,
            f"torch:{self.device}",
            self._actual_provider,
        )
        return self._impl

    def compute(self, audio_16k: np.ndarray, sr: int = 16000) -> np.ndarray:
        import numpy as np  # noqa: PLC0415

        impl = self._load()
        audio = np.asarray(audio_16k, dtype=np.float32)
        if self.detector == "fcpe":
            return self._compute_fcpe(impl, audio, sr)
        if self.detector in _CREPE_MODELS:
            return self._compute_crepe(impl, audio, sr)
        f0 = impl.infer_from_audio(audio, sr=sr)
        return np.asarray(f0, dtype=np.float32)

    def _compute_crepe(self, torchcrepe, audio_16k: np.ndarray, sr: int) -> np.ndarray:
        import numpy as np  # noqa: PLC0415
        import torch  # noqa: PLC0415

        hop = max(1, int(round(CREPE_HOP_16K * sr / 16000)))
        wav = torch.from_numpy(audio_16k.reshape(-1))[None, :].to(self.device)
        with torch.no_grad():
            f0, periodicity = torchcrepe.predict(
                wav,
                sr,
                hop_length=hop,
                fmin=F0_MIN,
                fmax=F0_MAX,
                model=_CREPE_MODELS[self.detector],
                device=self.device,
                return_periodicity=True,
                batch_size=512,
                pad=True,
            )
        # Silence low-confidence frames so consonants stay unvoiced (f0 == 0).
        voiced = periodicity >= CREPE_PERIODICITY_THRESHOLD
        f0 = torch.where(voiced, f0, torch.zeros_like(f0))
        return f0.squeeze().detach().cpu().numpy().astype(np.float32).reshape(-1)

    def _compute_fcpe(self, impl, audio_16k: np.ndarray, sr: int) -> np.ndarray:
        import numpy as np  # noqa: PLC0415
        import torch  # noqa: PLC0415

        audio = torch.from_numpy(audio_16k.reshape(-1)).to(self.device)[None, :, None]
        with torch.no_grad():
            f0 = impl.infer(
                audio,
                sr=sr,
                decoder_mode="local_argmax",
                threshold=FCPE_THRESHOLD,
                f0_min=F0_MIN,
                f0_max=F0_MAX,
                interp_uv=False,
            )
        return f0.squeeze().detach().cpu().numpy().astype(np.float32).reshape(-1)


_EXTRACTOR_CACHE: dict[tuple[str, str, str], F0Extractor] = {}


def create_f0_extractor(detector: str, model_path: Path, device: str) -> F0Extractor:
    """Memoized: the RMVPE checkpoint is ~180 MB, and the realtime path calls
    this once per chunk — reloading it from disk each time costs ~0.5 s/chunk
    and was the difference between realtime and not."""
    key = (detector, str(model_path), device)
    cached = _EXTRACTOR_CACHE.get(key)
    if cached is None:
        cached = _EXTRACTOR_CACHE[key] = F0Extractor(detector, model_path, device)
    return cached


def provider_health(detector: str, model_path: Path, device: str) -> dict[str, object]:
    key = (detector, str(model_path), device)
    cached = _EXTRACTOR_CACHE.get(key)
    if cached is not None:
        return cached.provider_health()
    return {
        "name": detector,
        "requested": f"torch:{device}",
        "actual": None,
        "loaded": False,
    }
