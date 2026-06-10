"""The arbiter's RAM-budget guard (the "Refused <model>: ... only N GB RAM
free" path). Warm-parked models are RAM *we* control, so a load that does not
fit must first evict them and re-measure — refusing is the last resort, not the
first response. Regression coverage for the swap-then-refuse bug where parking
the outgoing model consumed the very RAM the incoming model needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.base import GpuBackend, ModelDescriptor
from app.config import settings
from app.core.arbiter import GpuArbiter
from app.core.enums import ModelFamily
from app.core.events import EventBus
from app.util import sysmon


class _FakeBackend(GpuBackend):
    """Minimal backend whose unload returns its RAM share to a shared pool."""

    def __init__(self, model_id: str, ram: dict, *, ram_share_gb: float = 0.0) -> None:
        super().__init__(ModelDescriptor(
            id=model_id,
            name=model_id,
            family=ModelFamily.SDXL,
            path=Path(model_id),
            size_bytes=5 * 1_000_000_000,  # SDXL heuristic: needs 6.5 GB RAM
        ))
        self._ram = ram
        self._ram_share_gb = ram_share_gb

    async def load(self) -> None:
        self._loaded = True
        self._warm = False

    async def unload(self) -> None:
        if self._warm:
            self._ram["available_gb"] += self._ram_share_gb
        self._loaded = False
        self._warm = False


@pytest.fixture
def real_budget(monkeypatch):
    """Run the guard for real (not stub) against a fake, mutable RAM reading."""
    monkeypatch.setattr(settings, "stub_mode", False)
    ram = {"available_gb": 0.0}
    monkeypatch.setattr(sysmon, "ram_stats", lambda: dict(ram))
    return ram


async def test_guard_evicts_warm_model_to_make_room(real_budget):
    # Incoming SDXL needs 6.5 + 2.5 headroom = 9 GB; only 7 free, but the warm
    # model holds 8 GB. Evicting it must let the load proceed instead of refusing.
    real_budget["available_gb"] = 7.0
    bus = EventBus()
    arbiter = GpuArbiter(bus)

    warm = _FakeBackend("warm-old", real_budget, ram_share_gb=8.0)
    warm._warm = True
    arbiter._warm_backends.append(warm)

    incoming = _FakeBackend("incoming", real_budget)
    await arbiter.ensure(incoming)

    assert incoming.loaded
    assert warm not in arbiter._warm_backends
    assert not warm.warm


async def test_guard_still_refuses_when_eviction_is_not_enough(real_budget):
    # Even after evicting the warm model (frees 1 GB -> 6 GB free) the incoming
    # load needs 9 GB, so the guard must refuse with the clear MemoryError.
    real_budget["available_gb"] = 5.0
    bus = EventBus()
    arbiter = GpuArbiter(bus)

    warm = _FakeBackend("warm-old", real_budget, ram_share_gb=1.0)
    warm._warm = True
    arbiter._warm_backends.append(warm)

    incoming = _FakeBackend("incoming", real_budget)
    with pytest.raises(MemoryError, match="Not enough RAM"):
        await arbiter.ensure(incoming)

    assert not incoming.loaded
    assert warm not in arbiter._warm_backends  # the eviction attempt still ran


async def test_guard_refuses_without_warm_models(real_budget):
    real_budget["available_gb"] = 5.0
    arbiter = GpuArbiter(EventBus())
    incoming = _FakeBackend("incoming", real_budget)
    with pytest.raises(MemoryError, match="Not enough RAM"):
        await arbiter.ensure(incoming)
    assert not incoming.loaded
