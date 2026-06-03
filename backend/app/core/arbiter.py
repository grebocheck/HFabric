"""The VRAM arbiter — the architectural heart of ImageFabric.

On a 16 GB card you cannot hold an LLM (~12 GB) and a diffusion model at the
same time. The arbiter enforces the invariant **at most one GPU resident at a
time**: requesting a different model unloads the current one first. Swaps are
serialized by a lock and announced on the event bus so the UI can show what is
happening.
"""

from __future__ import annotations

import asyncio

from ..backends.base import GpuBackend
from .enums import EventType
from .events import Event, EventBus


class GpuArbiter:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = asyncio.Lock()
        self._current: GpuBackend | None = None

    @property
    def current(self) -> GpuBackend | None:
        return self._current

    async def ensure(self, backend: GpuBackend) -> None:
        """Guarantee ``backend`` is the sole GPU resident and loaded."""
        async with self._lock:
            if self._current is backend and backend.loaded:
                return
            if self._current is not None and self._current is not backend:
                await self._unload_current()
            if not backend.loaded:
                await self._bus.publish(Event(
                    EventType.MODEL_LOADING,
                    resident=backend.resident_key,
                    model=backend.descriptor.name,
                    family=backend.descriptor.family.value,
                ))
                await backend.load()
                await self._bus.publish(Event(
                    EventType.MODEL_LOADED,
                    resident=backend.resident_key,
                    model=backend.descriptor.name,
                    family=backend.descriptor.family.value,
                ))
            self._current = backend
            await self._publish_status()

    async def free_all(self) -> None:
        async with self._lock:
            if self._current is not None:
                await self._unload_current()
            await self._publish_status()

    async def _unload_current(self) -> None:
        cur = self._current
        assert cur is not None
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADING, resident=cur.resident_key, model=cur.descriptor.name
        ))
        await cur.unload()
        await self._bus.publish(Event(
            EventType.MODEL_UNLOADED, resident=cur.resident_key, model=cur.descriptor.name
        ))
        self._current = None

    def status(self) -> dict:
        cur = self._current
        return {
            "resident": cur.resident_key if cur else None,
            "model_id": cur.descriptor.id if cur else None,
            "model": cur.descriptor.name if cur else None,
            "family": cur.descriptor.family.value if cur else None,
        }

    async def _publish_status(self) -> None:
        await self._bus.publish(Event(EventType.GPU_STATUS, **self.status()))
