from __future__ import annotations

from pathlib import Path

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
