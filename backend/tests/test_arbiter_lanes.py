"""Non-arbiter GPU lanes (P24.10).

Voice/TTS/transcribe pin the GPU outside the arbiter's one-resident-model
invariant. They register a "lane" purely so status()/the topbar report that the
GPU is busy instead of claiming it is idle. A lane never loads a model.
"""

from __future__ import annotations

from app.core.arbiter import GpuArbiter
from app.core.enums import EventType
from app.core.events import EventBus


async def test_lane_shows_in_status_and_publishes_gpu_status():
    bus = EventBus()
    arbiter = GpuArbiter(bus)

    assert arbiter.status()["lanes"] == []

    async with bus.subscribe() as q:
        await arbiter.activate_lane("voice", "voice session")
        event = q.get_nowait()

    assert event["type"] == EventType.GPU_STATUS.value
    assert event["lanes"] == [{"id": "voice", "label": "voice session"}]
    # A lane is observability only — it never makes a model resident.
    assert arbiter.current is None
    assert arbiter.status()["resident"] is None
    assert arbiter.status()["lanes"] == [{"id": "voice", "label": "voice session"}]

    await arbiter.deactivate_lane("voice")
    assert arbiter.status()["lanes"] == []


async def test_activate_lane_is_idempotent_and_deactivate_is_safe():
    bus = EventBus()
    arbiter = GpuArbiter(bus)

    await arbiter.activate_lane("tts", "TTS synthesis")
    async with bus.subscribe() as q:
        # Re-registering the same label must not republish (no UI churn).
        await arbiter.activate_lane("tts", "TTS synthesis")
        assert q.empty()
        # Dropping an unknown lane is a no-op, not an error or a publish.
        await arbiter.deactivate_lane("nope")
        assert q.empty()

    assert arbiter.status()["lanes"] == [{"id": "tts", "label": "TTS synthesis"}]


async def test_gpu_lane_context_manager_releases_on_error():
    arbiter = GpuArbiter(EventBus())

    try:
        async with arbiter.gpu_lane("transcribe", "transcription"):
            assert arbiter.status()["lanes"] == [{"id": "transcribe", "label": "transcription"}]
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert arbiter.status()["lanes"] == []
