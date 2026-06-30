from __future__ import annotations

import asyncio
import logging

from app.core.events import Event, EventBus


async def test_publish_drops_oldest_when_subscriber_queue_is_full():
    bus = EventBus(max_queue=1)

    async with bus.subscribe() as q:
        await bus.publish(Event("one"))
        await bus.publish(Event("two"))

        assert q.qsize() == 1
        assert q.get_nowait()["type"] == "two"


async def test_publish_logs_when_drop_recovery_fails(caplog):
    class BrokenQueue:
        def put_nowait(self, _event):
            raise asyncio.QueueFull

        def get_nowait(self):
            raise RuntimeError("cannot drop")

    bus = EventBus()
    bus._subscribers.add(BrokenQueue())

    with caplog.at_level(logging.DEBUG, logger="hfabric"):
        await bus.publish(Event("progress"))

    assert "event=bus.drop_failed" in caplog.text


def test_emit_without_running_loop_logs_failed_sync_publish(monkeypatch, caplog):
    class BrokenQueue:
        def put_nowait(self, _event):
            raise RuntimeError("closed")

    bus = EventBus()
    bus._subscribers.add(BrokenQueue())
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))

    with caplog.at_level(logging.DEBUG, logger="hfabric"):
        bus.emit("progress")

    assert "event=bus.emit_failed" in caplog.text


async def test_emit_with_running_loop_schedules_publish():
    bus = EventBus()

    async with bus.subscribe() as q:
        bus.emit("progress", value=0.5)
        event = await asyncio.wait_for(q.get(), timeout=1.0)

    assert event["type"] == "progress"
    assert event["value"] == 0.5
