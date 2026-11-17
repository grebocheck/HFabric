from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException
import pytest

from app.api.jobs import _validate_model
from app.backends.base import ModelDescriptor
from app.backends.registry import ModelRegistry
from app.config import settings
from app.core.arbiter import GpuArbiter
from app.core.enums import JobType, ModelFamily
from app.core.events import EventBus
from app.schemas import JobCreate
from app.services.image_quantization import image_quant_options


def registry_for(quant="bnb-nf4", family=ModelFamily.FLUX2):
    registry = ModelRegistry()
    registry._descriptors["model"] = ModelDescriptor(
        id="model", name="Model", family=family,
        path=Path("model"), size_bytes=1, quant=quant,
    )
    return registry


@pytest.mark.parametrize("default,expected", [("bnb-nf4", "bnb-nf4"), ("bf16", "none"), ("", "none")])
def test_queue_captures_precision_before_defaults_change(default, expected):
    registry = registry_for(default)
    payload = JobCreate(type=JobType.IMAGE, model_id="model", params={"prompt": "sample"})
    _validate_model(registry, payload)
    assert payload.params["image_quant"] == expected
    registry._descriptors["model"] = replace(registry.get_descriptor("model"), quant="none")
    backend = registry.get_backend("model", image_quant=payload.params["image_quant"])
    assert backend.descriptor.quant == expected
    assert registry.get_descriptor("model").quant == "none"


async def test_precision_change_reloads_only_through_arbiter():
    registry = registry_for()
    original_default = settings.flux2_quant
    arbiter = GpuArbiter(EventBus())
    original = registry.get_backend("model", image_quant="none")
    await arbiter.ensure(original)
    assert registry.get_backend("model", image_quant="none") is original
    compressed = registry.get_backend("model", image_quant="bnb-fp4")
    assert original.loaded
    assert not compressed.loaded
    assert arbiter.current is original
    await arbiter.ensure(compressed)
    assert not original.loaded
    assert arbiter.current is compressed
    assert settings.flux2_quant == original_default
    await arbiter.free_all()


@pytest.mark.parametrize("family,quant", [(ModelFamily.SDXL, None), (ModelFamily.ANIMA, None), (ModelFamily.FLUX2, "nunchaku-fp4")])
def test_fixed_checkpoints_never_offer_runtime_quantization(family, quant):
    registry = registry_for(quant, family)
    assert image_quant_options(registry.get_descriptor("model")) == ()
    payload = JobCreate(type=JobType.IMAGE, model_id="model", params={"prompt": "sample", "image_quant": "none"})
    with pytest.raises(HTTPException, match="not supported"):
        _validate_model(registry, payload)


async def test_api_rejects_unsupported_precision_before_queue(app_client):
    models = (await app_client.get("/api/models")).json()
    model = next(model for model in models if model["family"] == "sdxl")
    assert model["quant_options"] == []
    response = await app_client.post("/api/jobs", json=[{
        "type": "image", "model_id": model["id"], "params": {"prompt": "sample", "image_quant": "bnb-nf4"},
    }])
    assert response.status_code == 400
