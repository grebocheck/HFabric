"""Shared FastAPI dependencies / app-state accessors."""

from __future__ import annotations

from fastapi import Request

from ..backends.registry import ModelRegistry
from ..core.arbiter import GpuArbiter
from ..core.events import EventBus
from ..core.scheduler import Worker
from ..db.session import get_session  # re-export for routers

__all__ = ["get_session", "get_registry", "get_bus", "get_arbiter", "get_worker"]


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_arbiter(request: Request) -> GpuArbiter:
    return request.app.state.arbiter


def get_worker(request: Request) -> Worker:
    return request.app.state.worker
