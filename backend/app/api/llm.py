"""LLM runtime knobs that need a server (re)launch to take effect.

``llama-server`` is started with a fixed context size (``-c``) and GPU-offload
layer count (``-ngl``); changing those means relaunching the process. These
endpoints validate launch settings and, if an unpinned LLM is resident, unload
it before committing the new values so the next chat starts a genuinely new
process. Per-message knobs (temperature, max_tokens) are NOT here — they travel
with each ``/api/jobs/chat`` request.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..backends.registry import ModelRegistry
from ..config import (
    CONTEXT_TYPES,
    DEFAULT_CONTEXT_TYPE,
    LLAMA_BACKENDS,
    settings,
)
from ..core.arbiter import GpuArbiter
from ..core.enums import ModelFamily
from ..core.scheduler import Worker
from ..services import model_compatibility
from .contracts import ERROR_RESPONSES, LlmConfigOut, StoppedOut
from .deps import get_arbiter, get_registry, get_worker

router = APIRouter(
    prefix="/api/llm",
    tags=["llm"],
    responses=ERROR_RESPONSES,
)

CTX_MIN, CTX_MAX = 512, 131072
NGL_MIN, NGL_MAX = 0, 999
LLM_API_PIN_ID = "llm_api"
LLM_API_PIN_LABEL = "LLM API server"


class LlmConfigUpdate(BaseModel):
    ctx: int | None = None
    ngl: int | None = None
    backend: str | None = None
    context_type: str | None = None


class LlmApiServerUpdate(BaseModel):
    enabled: bool
    model_id: str | None = None


class LlmApiServerStatus(BaseModel):
    enabled: bool
    available: bool
    protocol: str
    base_url: str
    chat_completions_url: str
    models_url: str
    host: str
    port: int
    model_id: str | None = None
    model: str | None = None
    loaded: bool
    pinned: bool
    stub: bool
    note: str | None = None


def _llm_resident(arbiter: GpuArbiter) -> bool:
    cur = arbiter.current
    return bool(cur and cur.descriptor.family is ModelFamily.GGUF)


def _worker_idle_guard(
    worker: Worker, action: str
) -> Callable[[], str | None]:
    def guard() -> str | None:
        job_id = worker.running_job_id
        if job_id is None:
            return None
        return f"wait for the running job ({job_id}) to finish before {action}"

    return guard


def _backends_status() -> list[dict]:
    out = []
    for bid, spec in LLAMA_BACKENDS.items():
        bin_path = getattr(settings, spec["bin_attr"])
        out.append({
            "id": bid,
            "label": spec["label"],
            "available": bin_path.exists(),
            "path": str(bin_path),
            "context_types": list(spec["context_types"]),
        })
    return out


def _status(arbiter: GpuArbiter, **extra) -> LlmConfigOut:
    cur = arbiter.current
    loaded = _llm_resident(arbiter)
    return {
        "ctx": settings.llama_ctx,
        "ngl": settings.llama_ngl,
        "backend": settings.llama_backend,
        "backends": _backends_status(),
        "context_type": settings.llama_context_type,
        "context_types": [
            {"id": key, "label": spec["label"], "experimental": spec["experimental"]}
            for key, spec in CONTEXT_TYPES.items()
        ],
        "stub": settings.stub_mode,
        "loaded": loaded,
        "model_id": cur.descriptor.id if loaded else None,
        "defaults": {"temperature": 0.8, "max_tokens": 4096},
        **extra,
    }


def _client_llama_host() -> str:
    if settings.llama_host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return settings.llama_host


def _server_status(arbiter: GpuArbiter) -> LlmApiServerStatus:
    pin = arbiter.resident_pin
    cur = arbiter.current
    enabled = bool(pin and pin.get("id") == LLM_API_PIN_ID)
    loaded = _llm_resident(arbiter)
    host = _client_llama_host()
    base_url = f"http://{host}:{settings.llama_port}/v1"
    model_id = pin.get("model_id") if enabled and pin else (cur.descriptor.id if loaded and cur else None)
    model = pin.get("model") if enabled and pin else (cur.descriptor.name if loaded and cur else None)
    note = None
    if enabled and settings.stub_mode:
        note = "stub mode does not start an external llama-server process"
    elif enabled and not loaded:
        note = "API serving is enabled, but no LLM is currently resident"
    elif enabled:
        note = "Use the OpenAI-compatible API; most clients accept any placeholder API key."
    return LlmApiServerStatus(
        enabled=enabled,
        available=enabled and loaded and not settings.stub_mode,
        protocol="openai-compatible",
        base_url=base_url,
        chat_completions_url=f"{base_url}/chat/completions",
        models_url=f"{base_url}/models",
        host=host,
        port=settings.llama_port,
        model_id=model_id,
        model=model,
        loaded=loaded,
        pinned=enabled,
        stub=settings.stub_mode,
        note=note,
    )


@router.post("/stop", response_model=StoppedOut)
async def stop_generation(
    arbiter: GpuArbiter = Depends(get_arbiter),
) -> StoppedOut:
    """Interrupt the LLM that is currently streaming (best-effort)."""
    cur = arbiter.current
    if cur and cur.descriptor.family is ModelFamily.GGUF and hasattr(cur, "request_stop"):
        cur.request_stop()
        return {"stopped": True}
    return {"stopped": False}


@router.get("/server", response_model=LlmApiServerStatus)
async def get_api_server(arbiter: GpuArbiter = Depends(get_arbiter)) -> LlmApiServerStatus:
    return _server_status(arbiter)


@router.post("/server", response_model=LlmApiServerStatus)
async def set_api_server(
    body: LlmApiServerUpdate,
    arbiter: GpuArbiter = Depends(get_arbiter),
    registry: ModelRegistry = Depends(get_registry),
    worker: Worker = Depends(get_worker),
) -> LlmApiServerStatus:
    if worker.running_job_id:
        raise HTTPException(409, "wait for the running job to finish before toggling LLM API serving")

    if not body.enabled:
        await arbiter.release_pin(
            LLM_API_PIN_ID,
            unload=True,
            idle_guard=_worker_idle_guard(worker, "disabling LLM API serving"),
        )
        return _server_status(arbiter)

    model_id = body.model_id
    cur = arbiter.current
    if not model_id and cur and cur.descriptor.family is ModelFamily.GGUF:
        model_id = cur.descriptor.id
    if not model_id:
        raise HTTPException(422, "model_id is required when no LLM is loaded")

    try:
        desc = registry.get_descriptor(model_id)
    except KeyError:
        raise HTTPException(404, f"unknown model_id: {model_id}")
    if desc.family is not ModelFamily.GGUF:
        raise HTTPException(400, f"model '{desc.id}' is not an LLM")
    try:
        model_compatibility.require_model_available(desc)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    backend = registry.get_backend(desc.id)
    await arbiter.ensure_pinned(
        backend,
        LLM_API_PIN_ID,
        LLM_API_PIN_LABEL,
        idle_guard=_worker_idle_guard(worker, "toggling LLM API serving"),
    )
    return _server_status(arbiter)


@router.get("/config", response_model=LlmConfigOut)
async def get_config(
    arbiter: GpuArbiter = Depends(get_arbiter),
) -> LlmConfigOut:
    return _status(arbiter)


@router.post("/config", response_model=LlmConfigOut)
async def set_config(
    body: LlmConfigUpdate,
    arbiter: GpuArbiter = Depends(get_arbiter),
    worker: Worker = Depends(get_worker),
) -> LlmConfigOut:
    # Compute the target backend / context-type first and validate the *pair*
    # before committing anything, so we never leave settings in a state the
    # selected llama build can't actually launch.
    target_backend = body.backend if body.backend is not None else settings.llama_backend
    target_ct = body.context_type if body.context_type is not None else settings.llama_context_type

    if body.backend is not None and body.backend not in LLAMA_BACKENDS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown backend {body.backend!r}; choose one of {sorted(LLAMA_BACKENDS)}",
        )
    if body.context_type is not None and body.context_type not in CONTEXT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown context_type {body.context_type!r}; choose one of {sorted(CONTEXT_TYPES)}",
        )

    note = None
    supported = LLAMA_BACKENDS[target_backend]["context_types"]
    if target_ct not in supported:
        if body.context_type is not None:
            # An explicit type the (resulting) backend can't run -> reject and
            # tell the caller how to make it valid.
            raise HTTPException(
                status_code=422,
                detail=f"context type {target_ct!r} is not supported by the "
                f"{target_backend!r} backend; supported: {list(supported)}. "
                f"Switch to a backend that lists it (e.g. 'turbo' for turbo3/turbo4).",
            )
        # A backend switch left the existing type unsupported -> gracefully fall
        # back to the always-valid default instead of erroring.
        note = (
            f"context type reset to '{DEFAULT_CONTEXT_TYPE}' — "
            f"not supported by the '{target_backend}' backend"
        )
        target_ct = DEFAULT_CONTEXT_TYPE

    target_ctx = settings.llama_ctx
    if body.ctx is not None:
        target_ctx = max(CTX_MIN, min(CTX_MAX, body.ctx))
    target_ngl = settings.llama_ngl
    if body.ngl is not None:
        target_ngl = max(NGL_MIN, min(NGL_MAX, body.ngl))
    would_change = (
        target_ctx != settings.llama_ctx
        or target_ngl != settings.llama_ngl
        or target_backend != settings.llama_backend
        or target_ct != settings.llama_context_type
    )
    unloaded = False
    if would_change:

        def apply() -> None:
            settings.llama_ctx = target_ctx
            settings.llama_ngl = target_ngl
            settings.llama_backend = target_backend
            settings.llama_context_type = target_ct

        # Guard, unload and commit are serialized by the arbiter. A worker can
        # no longer start in the route-level check-to-unload gap.
        unloaded = await arbiter.reconfigure(
            apply,
            family=ModelFamily.GGUF,
            idle_guard=_worker_idle_guard(worker, "changing LLM launch settings"),
        )

    # This endpoint unloads rather than eagerly relaunching. ``reloaded`` must
    # only become true after an actual new process/model instance exists.
    return _status(
        arbiter,
        changed=would_change,
        unloaded=unloaded,
        reloaded=False,
        note=note,
    )
