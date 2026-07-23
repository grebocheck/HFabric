from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.backends.base import GpuBackend, ModelDescriptor
from app.config import settings
from app.core.arbiter import (
    GpuArbiter,
    GpuBusyConflict,
    PinOwnershipConflict,
    ResidentPinConflict,
)
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


async def test_resident_pin_returns_typed_conflict_for_free_and_swaps():
    bus = EventBus()
    arbiter = GpuArbiter(bus)
    first = _FakeBackend("first")
    second = _FakeBackend("second")

    await arbiter.ensure(first)
    await arbiter.pin_current("llm_api", "LLM API server")
    with pytest.raises(ResidentPinConflict, match="LLM API server"):
        await arbiter.free_all()

    assert first.loaded
    assert first.unloads == 0
    assert arbiter.status()["pin"]["id"] == "llm_api"

    with pytest.raises(ResidentPinConflict, match="LLM API server"):
        await arbiter.ensure(second)
    assert not second.loaded

    await arbiter.unpin("llm_api")
    await arbiter.free_all()
    assert not first.loaded


async def test_wrong_owner_cannot_release_resident_pin():
    arbiter = GpuArbiter(EventBus())
    backend = _FakeBackend("first")
    await arbiter.ensure(backend)
    await arbiter.pin_current("llm_api", "LLM API server")

    with pytest.raises(PinOwnershipConflict, match="LLM API server"):
        await arbiter.unpin("voice")

    assert arbiter.resident_pin is not None
    assert arbiter.resident_pin["id"] == "llm_api"
    assert backend.loaded


async def test_pinned_handoff_rolls_back_when_target_load_fails():
    class FailingBackend(_FakeBackend):
        async def load(self) -> None:
            # Simulate a launcher that created a process before health probing
            # failed; rollback must tear this partial target down too.
            self._loaded = True
            raise RuntimeError("launch failed")

    arbiter = GpuArbiter(EventBus())
    original = _FakeBackend("original")
    failing = FailingBackend("failing")
    await arbiter.ensure_pinned(original, "llm_api", "LLM API server")

    with pytest.raises(RuntimeError, match="launch failed"):
        await arbiter.ensure_pinned(failing, "llm_api", "LLM API server")

    assert arbiter.current is original
    assert original.loaded
    assert arbiter.resident_pin is not None
    assert arbiter.resident_pin["model_id"] == "original"
    assert not failing.loaded
    assert failing.unloads == 1


async def test_concurrent_ensure_and_free_are_serialized():
    class BlockingBackend(_FakeBackend):
        def __init__(self) -> None:
            super().__init__("blocking")
            self.load_started = asyncio.Event()
            self.release_load = asyncio.Event()

        async def load(self) -> None:
            self.load_started.set()
            await self.release_load.wait()
            self._loaded = True

    arbiter = GpuArbiter(EventBus())
    backend = BlockingBackend()
    ensure_task = asyncio.create_task(arbiter.ensure(backend))
    await backend.load_started.wait()
    free_task = asyncio.create_task(arbiter.free_all())
    await asyncio.sleep(0)

    assert not free_task.done()
    backend.release_load.set()
    await ensure_task
    await free_task

    assert arbiter.current is None
    assert not backend.loaded
    assert backend.unloads == 1


async def test_active_job_lease_blocks_free_and_swap_until_release():
    arbiter = GpuArbiter(EventBus())
    active = _FakeBackend("active")
    incoming = _FakeBackend("incoming")
    await arbiter.acquire(active, "job-1")

    with pytest.raises(GpuBusyConflict, match="job-1"):
        await arbiter.free_all()
    with pytest.raises(GpuBusyConflict, match="job-1"):
        await arbiter.ensure(incoming)

    assert arbiter.current is active
    assert active.loaded
    assert not incoming.loaded

    assert await arbiter.release("job-1")
    await arbiter.free_all()
    assert arbiter.current is None


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

    blocked_free = await app_client.post("/api/gpu/free")
    assert blocked_free.status_code == 409
    assert blocked_free.json()["code"] == "resident_pinned"
    assert (await app_client.get("/api/gpu")).json()["model_id"] == "stub-llm"

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
