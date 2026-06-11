"""ContentVec feature extraction via ONNX Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np


class ContentVec:
    """Lazy ONNX Runtime wrapper for ``content_vec_500(.fp16).onnx``."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self._session: Any = None
        self._input_name: str | None = None
        self._output_name: str | None = None
        self._input_type = ""

    def _load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort  # noqa: PLC0415

        self._session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        input_meta = self._session.get_inputs()[0]
        outputs = self._session.get_outputs()
        output_meta = next(
            (
                output
                for output in outputs
                if len(output.shape) >= 3 and output.shape[-1] == 768 and output.name == "unit12"
            ),
            None,
        )
        if output_meta is None:
            output_meta = next(
                (
                    output
                    for output in outputs
                    if len(output.shape) >= 3 and output.shape[-1] == 768
                ),
                outputs[0],
            )
        self._input_name = input_meta.name
        self._output_name = output_meta.name
        self._input_type = str(getattr(input_meta, "type", ""))

    def extract(self, audio_16k: np.ndarray) -> np.ndarray:
        self._load()
        import numpy as np  # noqa: PLC0415

        assert self._session is not None
        assert self._input_name is not None
        assert self._output_name is not None
        audio = np.asarray(audio_16k, dtype=np.float32)
        if audio.ndim != 1:
            audio = audio.reshape(-1)
        payload = audio[None, :]
        if "float16" in self._input_type or self.model_path.name.endswith(".fp16.onnx"):
            payload = payload.astype(np.float16)
        out = self._session.run([self._output_name], {self._input_name: payload})[0]
        feats = np.asarray(out)
        if feats.ndim == 3:
            feats = feats[0]
        if feats.shape[-1] != 768 and feats.shape[0] == 768:
            feats = feats.T
        return feats.astype(np.float32, copy=False)
