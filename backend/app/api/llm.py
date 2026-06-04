"""LLM runtime knobs that need a server (re)launch to take effect.

``llama-server`` is started with a fixed context size (``-c``) and GPU-offload
layer count (``-ngl``); changing those means relaunching the process. These
endpoints mutate the shared settings and, if an LLM is currently resident, free
it so the next chat reloads with the new values. Per-message knobs (temperature,
max_tokens) are NOT here — they travel with each ``/api/jobs/chat`` request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import settings
from ..core.arbiter import GpuArbiter
from ..core.enums import ModelFamily
from .deps import get_arbiter

router = APIRouter(prefix="/api/llm", tags=["llm"])

CTX_MIN, CTX_MAX = 512, 131072
NGL_MIN, NGL_MAX = 0, 999


class LlmConfigUpdate(BaseModel):
    ctx: int | None = None
    ngl: int | None = None


def _llm_resident(arbiter: GpuArbiter) -> bool:
    cur = arbiter.current
    return bool(cur and cur.descriptor.family is ModelFamily.GGUF)


def _status(arbiter: GpuArbiter, **extra) -> dict:
    cur = arbiter.current
    loaded = _llm_resident(arbiter)
    return {
        "ctx": settings.llama_ctx,
        "ngl": settings.llama_ngl,
        "loaded": loaded,
        "model_id": cur.descriptor.id if loaded else None,
        "defaults": {"temperature": 0.8, "max_tokens": 512},
        **extra,
    }


@router.post("/stop")
async def stop_generation(arbiter: GpuArbiter = Depends(get_arbiter)) -> dict:
    """Interrupt the LLM that is currently streaming (best-effort)."""
    cur = arbiter.current
    if cur and cur.descriptor.family is ModelFamily.GGUF and hasattr(cur, "request_stop"):
        cur.request_stop()
        return {"stopped": True}
    return {"stopped": False}


@router.get("/config")
async def get_config(arbiter: GpuArbiter = Depends(get_arbiter)) -> dict:
    return _status(arbiter)


@router.post("/config")
async def set_config(
    body: LlmConfigUpdate, arbiter: GpuArbiter = Depends(get_arbiter)
) -> dict:
    changed = False
    if body.ctx is not None:
        ctx = max(CTX_MIN, min(CTX_MAX, body.ctx))
        if ctx != settings.llama_ctx:
            settings.llama_ctx = ctx
            changed = True
    if body.ngl is not None:
        ngl = max(NGL_MIN, min(NGL_MAX, body.ngl))
        if ngl != settings.llama_ngl:
            settings.llama_ngl = ngl
            changed = True

    # New launch knobs only bite on the next server start, so drop the running
    # LLM (the next chat reloads it). Image models are untouched unless the LLM
    # is the current resident.
    reloaded = False
    if changed and _llm_resident(arbiter):
        await arbiter.free_all()
        reloaded = True

    return _status(arbiter, changed=changed, reloaded=reloaded)
