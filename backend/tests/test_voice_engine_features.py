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


def test_nsf_source_noise_can_be_pinned_across_overlap_renders():
    import torch

    from app.services.voice_engine.rvc.models import SineGen

    source = SineGen(32_000)
    f0 = torch.full((1, 20), 220.0)
    pinned = torch.linspace(-1.0, 1.0, 20 * 320).reshape(1, -1, 1)

    first, _uv1, noise1 = source(f0, 320, source_noise=pinned)
    # Advance torch's global RNG: pinned excitation must remain unchanged.
    torch.randn(1024)
    second, _uv2, noise2 = source(f0, 320, source_noise=pinned)

    assert torch.equal(noise1, noise2)
    assert torch.equal(first, second)


def test_f0_resize_does_not_voice_unvoiced_gap():
    from app.services.voice_engine.pipeline import _resize_f0_preserve_uv

    source = np.array([100.0, 110.0, 0.0, 0.0, 200.0, 210.0], dtype=np.float32)
    resized = _resize_f0_preserve_uv(source, 12)

    # Nearest-neighbour UV decisions keep the consonant gap exactly unvoiced,
    # while pitch inside each voiced island remains smoothly interpolated.
    assert np.all(resized[4:8] == 0.0)
    assert np.all(resized[:4] > 0.0)
    assert np.all(resized[8:] > 0.0)


def test_convert_audio_uses_existing_synth_tail_window():
    from types import SimpleNamespace

    import torch

    from app.services.voice_engine.pipeline import convert_audio

    class FakeContentVec:
        def extract(self, audio):
            # Fifty ContentVec frames become one hundred 100 Hz synth frames.
            return np.ones((50, 768), dtype=np.float32)

    class FakeSynth:
        def __init__(self):
            self.kwargs = None

        def infer(self, phone, phone_lengths, sid, **kwargs):  # noqa: ARG002
            self.kwargs = kwargs
            samples = int(kwargs["return_length"]) * 320
            audio = torch.zeros((1, 1, samples), dtype=torch.float32)
            return audio, None, None

    synth = FakeSynth()
    loaded = SimpleNamespace(
        content_vec=FakeContentVec(),
        index_state=None,
        f0=False,
        synthesizer=synth,
        default_speaker_id=0,
        speaker_count=1,
        sample_rate=32_000,
    )

    output, sample_rate, timings = convert_audio(
        np.ones(3_200, dtype=np.float32),
        loaded,
        pitch=0,
        index_ratio=0.0,
        protect=0.33,
        f0_detector="fcpe",
        device="cpu",
        input_highpass_hz=0,
        synthesis_tail_frames=5,
    )

    assert sample_rate == 32_000
    assert output.size == 5 * 320
    assert synth.kwargs["skip_head"] == 71
    assert synth.kwargs["return_length"] == 29
    assert timings["synth_skip_frames"] == 95.0
    assert timings["synth_warmup_frames"] == 24.0
