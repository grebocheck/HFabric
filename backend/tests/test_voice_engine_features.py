from __future__ import annotations

from pathlib import Path

import numpy as np

from app.services.voice_engine.features import ContentVec


class FakeSession:
    def __init__(self) -> None:
        self.payload: np.ndarray | None = None

    def run(self, _outputs, feeds):
        self.payload = feeds["source"]
        return [np.zeros((1, 3, 768), dtype=np.float32)]


def test_contentvec_adds_channel_axis_for_rank3_onnx():
    session = FakeSession()
    content_vec = ContentVec(Path("vec-768-layer-12.onnx"))
    content_vec._session = session
    content_vec._input_name = "source"
    content_vec._output_name = "embed"
    content_vec._input_rank = 3

    features = content_vec.extract(np.arange(160, dtype=np.float32))

    assert session.payload is not None
    assert session.payload.shape == (1, 1, 160)
    assert features.shape == (3, 768)


def test_contentvec_keeps_rank2_payload_for_legacy_onnx():
    session = FakeSession()
    content_vec = ContentVec(Path("content_vec_500.onnx"))
    content_vec._session = session
    content_vec._input_name = "source"
    content_vec._output_name = "embed"
    content_vec._input_rank = 2

    content_vec.extract(np.arange(160, dtype=np.float32))

    assert session.payload is not None
    assert session.payload.shape == (1, 160)
