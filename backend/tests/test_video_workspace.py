from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from app.backends import video_diffusers
from app.backends.base import ModelDescriptor
from app.backends.inspect import classify_video_dir
from app.core.enums import ModelFamily
from app.util import sysmon


def test_classify_video_diffusers_directories(tmp_path):
    cases = {
        "LTXPipeline": ModelFamily.LTX_VIDEO,
        "WanPipeline": ModelFamily.WAN_VIDEO,
        "HunyuanVideoFramepackPipeline": ModelFamily.HUNYUAN_VIDEO,
        "CogVideoXPipeline": ModelFamily.COGVIDEO,
        "AnimateDiffSDXLPipeline": ModelFamily.ANIMATEDIFF_VIDEO,
    }
    for index, (class_name, expected) in enumerate(cases.items()):
        folder = tmp_path / str(index)
        folder.mkdir()
        (folder / "model_index.json").write_text(
            f'{{"_class_name":"{class_name}"}}', encoding="utf-8"
        )
        assert classify_video_dir(folder) is expected


def test_video_decode_budget_scales_with_latent_volume():
    small = sysmon.video_decode_need_gb(512, 320, 17)
    large = sysmon.video_decode_need_gb(1280, 704, 121)
    assert large["ram_gb"] > small["ram_gb"]
    assert large["vram_gb"] > small["vram_gb"]


async def test_stub_video_queue_persists_and_serves_ranges(app_client, wait_jobs_done):
    models = (await app_client.get("/api/models")).json()
    model = next(item for item in models if item["job_type"] == "video")
    response = await app_client.post(
        "/api/jobs",
        json=[{
            "type": "video",
            "model_id": model["id"],
            "params": {
                "prompt": "a labelled test clip",
                "width": 256,
                "height": 256,
                "frames": 9,
                "fps": 8,
                "steps": 2,
            },
        }],
    )
    assert response.status_code == 200, response.text
    jobs = await wait_jobs_done(app_client, [response.json()[0]["id"]])
    assert jobs[0]["status"] == "done", jobs[0]

    videos = (await app_client.get("/api/videos")).json()
    video = videos[0]
    assert video["frames"] == 9
    assert video["family"] == "ltx-video"
    assert Path(video["url"]).suffix == ""

    whole = await app_client.get(video["url"])
    assert whole.status_code == 200
    assert whole.headers["content-type"].startswith("video/mp4")
    assert whole.headers["accept-ranges"] == "bytes"
    partial = await app_client.get(video["url"], headers={"Range": "bytes=0-31"})
    assert partial.status_code == 206
    assert len(partial.content) == 32
    assert partial.headers["content-range"].startswith("bytes 0-31/")

    assert (await app_client.get(video["poster_url"])).status_code == 200
    assert (await app_client.get(video["thumb_url"])).status_code == 200

    deleted = (await app_client.delete(f"/api/videos/{video['id']}")).json()
    assert deleted == {"deleted": video["id"]}
    assert (await app_client.get(video["url"])).status_code == 404
    assert (await app_client.delete(f"/api/videos/{video['id']}")).status_code == 404


async def test_video_media_missing_paths_return_404(app_client):
    assert (await app_client.get("/api/videos/missing/file")).status_code == 404
    assert (await app_client.get("/api/videos/missing/poster")).status_code == 404
    assert (await app_client.get("/api/videos/missing/thumb")).status_code == 404


async def test_bare_video_request_uses_ltx_family_recipe(app_client, wait_jobs_done):
    """A request that omits fps/steps/guidance must fall back to the model's
    validated recipe, not a generic 16 fps that puts LTX off its trained range."""
    models = (await app_client.get("/api/models")).json()
    model = next(item for item in models if item["job_type"] == "video")
    assert model["family"] == "ltx-video"
    response = await app_client.post(
        "/api/jobs",
        json=[{"type": "video", "model_id": model["id"], "params": {"prompt": "defaults only"}}],
    )
    assert response.status_code == 200, response.text
    jobs = await wait_jobs_done(app_client, [response.json()[0]["id"]])
    assert jobs[0]["status"] == "done", jobs[0]

    video = (await app_client.get("/api/videos")).json()[0]
    assert video["fps"] == 24
    assert video["params"]["steps"] == 30
    assert video["params"]["guidance"] == 3.0


async def test_video_progress_reserves_decode_encode_headroom(isolated_runtime, monkeypatch):
    """Sampling must not fill the whole bar: the VAE decode and mp4 encode that
    follow the last denoise step (minutes-long for Wan) need visible headroom,
    otherwise the bar freezes at 100% with no indication of the remaining work."""
    from app.config import settings

    monkeypatch.setattr(settings, "stub_mode", True)
    backend = video_diffusers.DiffusersVideoBackend(
        ModelDescriptor(id="wan", name="Wan", family=ModelFamily.WAN_VIDEO, path=Path("."), size_bytes=1)
    )
    events: list[tuple[float, str | None]] = []

    async def progress(frac: float, note: str | None) -> None:
        events.append((frac, note))

    await backend.generate(
        {"prompt": "p", "width": 256, "height": 256, "frames": 9, "steps": 4}, progress
    )

    fracs = [frac for frac, _ in events]
    assert fracs == sorted(fracs), "progress must be monotonic"
    # The backend never reports completion — the scheduler marks 100% on done.
    assert max(fracs) < 1.0
    step_fracs = [frac for frac, note in events if note and note.startswith("step")]
    assert step_fracs and max(step_fracs) <= video_diffusers._DENOISE_END
    assert events[-1] == (video_diffusers._ENCODE_START, "encoding video…")


@pytest.mark.parametrize(
    ("offload", "expected_method", "expected_placement"),
    [
        ("model", "model", "bnb+model-offload"),
        ("sequential", "sequential", "bnb+sequential-offload"),
        ("none", "model", "bnb+model-offload"),
    ],
)
def test_bnb_video_load_uses_offload_hooks(monkeypatch, tmp_path, offload, expected_method, expected_placement):
    """Quantized video pipes must use Diffusers offload hooks, not bulk pipe.to().

    The bnb loader owns the quantized transformer/text-encoder placement; model
    offload is the safe 16 GB path and keeps the fp32 VAE decode from spilling.
    """
    from app.config import settings

    calls: list[str] = []

    class FakeVae:
        def enable_tiling(self) -> None:
            calls.append("tiling")

        def enable_slicing(self) -> None:
            calls.append("slicing")

    class FakePipe:
        def __init__(self) -> None:
            self.vae = FakeVae()

    class FakeLTXPipeline:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(f"load:{Path(path).name}:{'quantization_config' in kwargs}")
            return FakePipe()

    class FakeQuantConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAccelerator:
        backend = "cuda"
        memory_key = "cuda_process"

        def require_available(self, torch) -> None:
            calls.append("require")

        def enable_model_cpu_offload(self, pipe) -> None:
            calls.append("model")

        def enable_sequential_cpu_offload(self, pipe) -> None:
            calls.append("sequential")

        def move(self, pipe) -> None:
            calls.append("move")

        def public(self) -> dict:
            return {"backend": "cuda"}

        def process_memory(self, torch) -> dict:
            return {"reserved_gb": 1.0}

    fake_diffusers = types.SimpleNamespace(
        PipelineQuantizationConfig=FakeQuantConfig,
        LTXPipeline=FakeLTXPipeline,
    )
    fake_torch = types.SimpleNamespace(bfloat16="bf16", float32="fp32")
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(video_diffusers.accelerator_runtime, "current", lambda: FakeAccelerator())
    monkeypatch.setattr(video_diffusers.sysmon, "snapshot", lambda: {})
    monkeypatch.setattr(settings, "stub_mode", False)
    monkeypatch.setattr(settings, "video_quant", "bnb-nf4")
    monkeypatch.setattr(settings, "video_offload", offload)

    backend = video_diffusers.DiffusersVideoBackend(
        ModelDescriptor(
            id="ltx",
            name="LTX",
            family=ModelFamily.LTX_VIDEO,
            path=tmp_path / "ltx-video",
            size_bytes=1,
            quant="bnb-nf4",
        )
    )

    backend._load_pipeline_sync()

    assert expected_method in calls
    assert "move" not in calls
    assert "tiling" in calls and "slicing" in calls
    assert calls[0] == "require"
    assert backend.load_report and backend.load_report["video"]["placement"] == expected_placement


def test_ltx_i2v_pipeline_aligns_vae_dtype(monkeypatch, tmp_path):
    calls: list[str] = []

    class FakeVae:
        def to(self, **kwargs):
            calls.append(f"vae.to:{kwargs.get('dtype')}")
            return self

    class FakeI2VPipe:
        def __init__(self) -> None:
            self.vae = FakeVae()

    class FakeLTXImageToVideoPipeline:
        @classmethod
        def from_pipe(cls, pipe):
            calls.append(f"from_pipe:{pipe}")
            return FakeI2VPipe()

    fake_diffusers = types.SimpleNamespace(LTXImageToVideoPipeline=FakeLTXImageToVideoPipeline)
    fake_torch = types.SimpleNamespace(bfloat16="bf16")
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    backend = video_diffusers.DiffusersVideoBackend(
        ModelDescriptor(id="ltx", name="LTX", family=ModelFamily.LTX_VIDEO, path=tmp_path, size_bytes=1)
    )
    backend._pipe = "base-pipe"

    assert backend._pipeline_for_mode("i2v") is not None
    assert calls == ["from_pipe:base-pipe", "vae.to:bf16"]


async def test_video_guidance_is_clamped_in_stub_metadata(isolated_runtime, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "stub_mode", True)
    backend = video_diffusers.DiffusersVideoBackend(
        ModelDescriptor(id="wan", name="Wan", family=ModelFamily.WAN_VIDEO, path=Path("."), size_bytes=1)
    )

    async def progress(_frac: float, _note: str | None) -> None:
        return None

    high = await backend.generate(
        {"prompt": "p", "width": 256, "height": 256, "frames": 9, "steps": 1, "guidance": 99},
        progress,
    )
    low = await backend.generate(
        {"prompt": "p", "width": 256, "height": 256, "frames": 9, "steps": 1, "guidance": -3},
        progress,
    )
    fallback = await backend.generate(
        {"prompt": "p", "width": 256, "height": 256, "frames": 9, "steps": 1, "guidance": "bad"},
        progress,
    )

    assert high["params"]["guidance"] == 20.0
    assert low["params"]["guidance"] == 0.0
    assert fallback["params"]["guidance"] == 5.0
