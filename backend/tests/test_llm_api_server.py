from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.base import GpuBackend, ModelDescriptor
from app.config import settings
from app.core.arbiter import GpuArbiter
from app.core.enums import ModelFamily
from app.core.events import EventBus


class _FakeBackend(GpuBackend):
    def __init__(self, model_id: str) -> None:
        super().__init__(ModelDescriptor(
            id=model_id,
            name=model_id,
            family=ModelFamily.GGUF,
            path=Path(f"{model_id}.gguf"),
            size_bytes=4,
        ))
        self.unloads = 0

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self.unloads += 1
        self._loaded = False


@pytest.fixture
def restore_llama_ctx():
    original = settings.llama_ctx
    yield
    settings.llama_ctx = original


async def test_resident_pin_blocks_free_all_and_swaps():
    bus = EventBus()
    arbiter = GpuArbiter(bus)
    first = _FakeBackend("first")
    second = _FakeBackend("second")

    await arbiter.ensure(first)
    await arbiter.pin_current("llm_api", "LLM API server")
    await arbiter.free_all()

    assert first.loaded
    assert first.unloads == 0
    assert arbiter.status()["pin"]["id"] == "llm_api"

    with pytest.raises(RuntimeError, match="LLM API server"):
        await arbiter.ensure(second)
    assert not second.loaded

    await arbiter.unpin("llm_api")
    await arbiter.free_all()
    assert not first.loaded


async def test_llm_api_server_toggle_pins_loaded_model(app_client):
    initial = (await app_client.get("/api/llm/server")).json()
    assert initial["enabled"] is False
    assert initial["protocol"] == "openai-compatible"
    assert initial["base_url"].endswith("/v1")

    enabled = (await app_client.post(
        "/api/llm/server",
        json={"enabled": True, "model_id": "stub-llm"},
    )).json()
    assert enabled["enabled"] is True
    assert enabled["model_id"] == "stub-llm"
    assert enabled["loaded"] is True
    assert enabled["pinned"] is True

    gpu = (await app_client.get("/api/gpu")).json()
    assert gpu["model_id"] == "stub-llm"
    assert gpu["pin"]["id"] == "llm_api"

    disabled = (await app_client.post("/api/llm/server", json={"enabled": False})).json()
    assert disabled["enabled"] is False
    assert disabled["loaded"] is False
    assert (await app_client.get("/api/gpu")).json()["resident"] is None


async def test_launch_config_change_is_rejected_while_api_server_is_pinned(app_client, restore_llama_ctx):
    before = settings.llama_ctx
    await app_client.post("/api/llm/server", json={"enabled": True, "model_id": "stub-llm"})

    resp = await app_client.post("/api/llm/config", json={"ctx": before + 512})

    assert resp.status_code == 409
    assert settings.llama_ctx == before

    await app_client.post("/api/llm/server", json={"enabled": False})
