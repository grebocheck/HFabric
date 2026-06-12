"""F0 extraction for native RVC conversion."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

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

SUPPORTED_DETECTORS = {"rmvpe"}


class F0Extractor:
    def __init__(self, detector: str, model_path: Path, device: str = "cpu") -> None:
        if detector not in SUPPORTED_DETECTORS:
            raise ValueError(f"native voice engine supports only rmvpe for now (got {detector})")
        self.detector = detector
        self.model_path = Path(model_path)
        self.device = device
        self._impl = None

    def _load(self):
        if self._impl is not None:
            return self._impl
        from .rvc.rmvpe import RMVPE  # noqa: PLC0415

        self._impl = RMVPE(self.model_path, device=self.device)
        return self._impl

    def compute(self, audio_16k: np.ndarray, sr: int = 16000) -> np.ndarray:
        import numpy as np  # noqa: PLC0415

        impl = self._load()
        f0 = impl.infer_from_audio(np.asarray(audio_16k, dtype=np.float32), sr=sr)
        return np.asarray(f0, dtype=np.float32)


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
