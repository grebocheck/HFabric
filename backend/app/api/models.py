"""Model discovery + live GPU/arbiter status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..backends.registry import ModelRegistry
from ..core.arbiter import GpuArbiter
from ..schemas import GpuStatusOut, ModelOut
from .deps import get_arbiter, get_registry

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
    arbiter: GpuArbiter = Depends(get_arbiter),
) -> list[ModelOut]:
    current = arbiter.current
    out: list[ModelOut] = []
    for d in registry.descriptors():
        loaded = current is not None and current.descriptor.id == d.id
        out.append(ModelOut(
            id=d.id, name=d.name, family=d.family, job_type=d.job_type,
            size_bytes=d.size_bytes, loaded=loaded,
        ))
    return out


@router.get("/gpu", response_model=GpuStatusOut)
async def gpu_status(arbiter: GpuArbiter = Depends(get_arbiter)) -> GpuStatusOut:
    return GpuStatusOut(**arbiter.status())


@router.post("/gpu/free", response_model=GpuStatusOut)
async def gpu_free(arbiter: GpuArbiter = Depends(get_arbiter)) -> GpuStatusOut:
    await arbiter.free_all()
    return GpuStatusOut(**arbiter.status())
