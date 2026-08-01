from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.core.enums import JobType
from app.schemas import JobCreate, PresetCreate, PresetImportIn


@pytest.mark.parametrize(
    "params",
    [
        {"prompt": "x", "steps": 0},
        {"prompt": "x", "guidance": float("nan")},
        {"prompt": "x", "width": 0},
        {"prompt": "x", "width": 1000},
        {"prompt": "x", "height": 4096},
        {"prompt": "x", "batch_size": 0},
        {"prompt": "x", "batch_size": 17},
        {"prompt": "x", "seed": -2},
        {"prompt": "x", "loras": [{"id": "lora", "weight": 3}]},
    ],
)
def test_image_job_rejects_unsafe_resource_params(params):
    with pytest.raises(ValidationError):
        JobCreate(type=JobType.IMAGE, model_id="image", params=params)


def test_image_job_requires_prompt_but_image_preset_may_be_style_only():
    with pytest.raises(ValidationError):
        JobCreate(type=JobType.IMAGE, model_id="image", params={"steps": 12})

    preset = PresetCreate(name=" Style ", type=JobType.IMAGE, params={"steps": 12})
    assert preset.name == "Style"
    assert preset.params == {"steps": 12}


def test_image_params_preserve_explicit_defaults_and_safe_extensions():
    job = JobCreate(
        type=JobType.IMAGE,
        model_id="image",
        params={
            "prompt": "portrait",
            "steps": 28,
            "guidance": 3.5,
            "assistant_message_id": "message-id",
            "future_safe_metadata": "kept",
        },
    )
    assert job.params == {
        "prompt": "portrait",
        "steps": 28,
        "guidance": 3.5,
        "assistant_message_id": "message-id",
        "future_safe_metadata": "kept",
    }


def test_preset_import_bounds_payload_and_validates_image_items():
    with pytest.raises(ValidationError):
        PresetImportIn(
            presets=[
                {"name": "bad", "type": "image", "params": {"batch_size": 0}},
            ]
        )

    with pytest.raises(ValidationError):
        PresetImportIn(presets=[{"name": f"p-{index}", "type": "llm", "params": {}} for index in range(501)])


def test_non_image_job_params_remain_compatible():
    job = JobCreate(
        type=JobType.LLM,
        model_id="llm",
        params={"messages": [{"role": "user", "content": "hello"}], "temperature": 0.8},
    )
    assert job.params["temperature"] == 0.8


async def test_jobs_api_caps_request_size_before_model_lookup(app_client):
    response = await app_client.post(
        "/api/jobs",
        json=[{"type": "image", "model_id": "missing", "params": {"prompt": "x"}} for _ in range(101)],
    )
    assert response.status_code == 400
    assert "at most 100" in response.json()["detail"]


async def test_jobs_api_rejects_missing_edit_upload_before_queueing(app_client):
    models = (await app_client.get("/api/models")).json()
    model = next(item for item in models if item["job_type"] == "image" and item["family"] == "sdxl")
    response = await app_client.post(
        "/api/jobs",
        json=[
            {
                "type": "image",
                "model_id": model["id"],
                "params": {"prompt": "edit", "init_image": "a" * 32},
            }
        ],
    )
    assert response.status_code == 400
    assert "upload it again" in response.json()["detail"]
