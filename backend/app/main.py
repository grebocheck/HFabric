"""FastAPI application entrypoint — wires the foundation together.

Lifespan: init DB -> scan models -> build bus/arbiter/worker -> start worker.
Shutdown: stop worker -> free the GPU. Everything GPU-related flows through the
single Worker + GpuArbiter, so the VRAM invariant holds no matter how requests
arrive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import (
    auth,
    chat,
    civitai,
    code,
    diagnostics,
    downloads,
    gallery,
    jobs,
    llama,
    llm,
    models,
    notes,
    presets,
    prompts,
    rag,
    transcription,
    tts,
    videos,
    voice_engine,
    ws,
)
from .api.contracts import ERROR_RESPONSES, HealthOut
from .backends.registry import ModelRegistry
from .config import settings
from .core.arbiter import ArbiterConflict, GpuArbiter
from .core.enums import EventType
from .core.events import Event, EventBus
from .core.scheduler import Worker
from .db.session import init_db
from .services import capability_profile, gallery_service, runtime_tuning, settings_overrides
from .services.embedding_service import embedding_service
from .util import request_context, security, sysmon
from .util.logging import (
    EventLogSubscriber,
    configure_file_logging,
    install_unhandled_exception_logging,
)
from .util.pidfiles import reap_known_pidfiles

logger = logging.getLogger("hfabric")
_WORKER_SHUTDOWN_TIMEOUT = 15.0
_WORKER_CANCEL_TIMEOUT = 2.0
_SHUTDOWN_PHASE_TIMEOUT = 15.0
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


async def _mem_monitor(bus: EventBus) -> None:
    """Broadcast RAM/VRAM so the UI can see pressure (never guess at it)."""
    loop = asyncio.get_running_loop()
    interval = max(0.05, float(settings.mem_poll_seconds))
    scheduled_at = loop.time()
    while True:
        snapshot = await asyncio.to_thread(sysmon.snapshot)
        now = loop.time()
        payload = {
            **snapshot,
            "event_loop_lag_ms": _event_loop_lag_ms(now, scheduled_at),
        }
        await bus.publish(Event(EventType.MEM_STATUS, **payload))
        scheduled_at += interval
        delay = scheduled_at - loop.time()
        if delay <= 0:
            # Report this missed deadline once, then resume a stable cadence
            # instead of emitting a burst of catch-up samples.
            scheduled_at = loop.time() + interval
            delay = interval
        await asyncio.sleep(delay)


def _event_loop_lag_ms(now: float, scheduled_at: float) -> float:
    return round(max(0.0, now - scheduled_at) * 1000.0, 3)


async def _prime_learned_profiles() -> None:
    """Load persisted per-model memory measurements into the sysmon cache."""
    from .db.session import session_scope
    from .services import model_profile_service as mps

    try:
        async with session_scope() as s:
            rows = await mps.load_all(s)
        sysmon.prime_learned_profiles([
            {"model_id": r.model_id, "ram_gb": r.ram_gb, "vram_gb": r.vram_gb} for r in rows
        ])
    except Exception:  # noqa: BLE001 - missing profiles must not block startup
        pass


async def _shutdown_phase(
    name: str,
    operation: Awaitable[Any],
    *,
    timeout: float = _SHUTDOWN_PHASE_TIMEOUT,
) -> Any | None:
    """Run one observable shutdown phase without letting it block forever."""
    logger.info("event=shutdown.phase.start phase=%s timeout_seconds=%.1f", name, timeout)
    task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        # Do not await a cancellation-resistant cleanup coroutine: shutdown's
        # outer bound is more important. Retrieve its result later to avoid an
        # unhandled-task warning if it eventually exits.
        task.add_done_callback(_consume_shutdown_task)
        logger.error(
            "event=shutdown.phase.timeout phase=%s timeout_seconds=%.1f",
            name,
            timeout,
        )
        return None
    try:
        result = task.result()
    except asyncio.CancelledError:
        logger.warning("event=shutdown.phase.cancelled phase=%s", name)
        return None
    except Exception:  # noqa: BLE001 - terminal cleanup continues phase-by-phase
        logger.exception("event=shutdown.phase.failed phase=%s", name)
        return None
    logger.info("event=shutdown.phase.done phase=%s", name)
    return result


def _consume_shutdown_task(task: asyncio.Future[Any]) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:  # noqa: BLE001 - failure was already logged as a timeout
        logger.debug("event=shutdown.phase.late_failure", exc_info=True)


def _autotune_acceleration(persisted_overrides: set[str]) -> None:
    """Apply hardware-appropriate acceleration defaults.

    Skipped in stub mode (the placeholder pipeline ignores these knobs) and for
    any knob the user pinned via env or a saved override. Detection failures must
    never block startup.
    """
    if settings.stub_mode or not settings.capability_autotune:
        return
    try:
        user_set = set(settings.model_fields_set) | persisted_overrides
        profile = capability_profile.get_capability_profile()
        applied = runtime_tuning.apply_autotune(settings, profile, user_set=user_set)
        if applied:
            logger.info(
                "event=startup.autotune %s",
                {"backend": profile.get("backend"), "applied": applied},
            )
    except Exception:  # noqa: BLE001 - autotune is best-effort, never fatal
        logger.warning("event=startup.autotune.failed", exc_info=True)


def _activate_managed_llama() -> None:
    """Point settings at the active managed llama.cpp build, if one is installed."""
    from .services import llama_manager

    try:
        applied = llama_manager.apply_active_to_settings()
        if applied:
            logger.info("event=startup.llama.active %s", {"binaries": applied})
    except Exception:  # noqa: BLE001 - a bad managed dir must not block startup
        logger.warning("event=startup.llama.failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed before mkdirs, DB migrations, process cleanup, or any other
    # startup side effect. This also catches a persisted/CLI host misconfiguration.
    security.enforce_startup_posture()
    await asyncio.to_thread(settings.ensure_dirs)
    persisted_overrides = await asyncio.to_thread(settings_overrides.load)
    await asyncio.to_thread(settings.ensure_dirs)
    await asyncio.to_thread(_autotune_acceleration, persisted_overrides)
    await asyncio.to_thread(_activate_managed_llama)
    configure_file_logging(settings)
    install_unhandled_exception_logging(logger, asyncio.get_running_loop())
    await asyncio.to_thread(reap_known_pidfiles, logger)
    await init_db()
    from .db.session import session_scope

    async with session_scope() as session:
        recovered_images = await gallery_service.recover_output_history(
            session, settings.outputs_dir
        )
    if recovered_images:
        logger.info("event=history.recovered images=%d", recovered_images)
    security.log_startup_posture(logger)
    await _prime_learned_profiles()
    registry = ModelRegistry()
    await registry.scan_async()
    bus = EventBus()
    event_logger = EventLogSubscriber(bus, logger, settings)
    await event_logger.start()
    arbiter = GpuArbiter(bus)
    worker = Worker(bus, arbiter, registry)

    app.state.registry = registry
    app.state.bus = bus
    app.state.arbiter = arbiter
    app.state.worker = worker
    app.state.accepting_mutations = True

    worker.start()
    mem_task = asyncio.create_task(_mem_monitor(bus), name="hfabric-mem-monitor")
    try:
        yield
    finally:
        app.state.accepting_mutations = False
        logger.info("event=shutdown.start")
        # Stop scheduler admission before releasing a Voice lane; otherwise a
        # queued job could start in the gap before the worker shutdown phase.
        worker.request_stop()
        await _shutdown_phase(
            "voice",
            voice_engine.shutdown_voice_session(arbiter, worker, bus),
            timeout=5.0,
        )
        await _shutdown_phase(
            "worker",
            worker.stop(
                timeout=_WORKER_SHUTDOWN_TIMEOUT,
                cancel_timeout=_WORKER_CANCEL_TIMEOUT,
                cleanup_arbiter=False,
            ),
            timeout=_WORKER_SHUTDOWN_TIMEOUT + _WORKER_CANCEL_TIMEOUT + 1.0,
        )
        await _shutdown_phase("embedding", embedding_service.stop(), timeout=10.0)
        await _shutdown_phase("arbiter", arbiter.force_shutdown())
        mem_task.cancel()
        await asyncio.gather(mem_task, return_exceptions=True)
        await _shutdown_phase("event_logger", event_logger.stop(), timeout=5.0)
        logger.info("event=shutdown.done")


app = FastAPI(title="HFabric", version=__version__, lifespan=lifespan)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    legacy_detail: Any = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", None),
        "detail": message if legacy_detail is None else legacy_detail,
    }
    if extra:
        payload.update(extra)
    return JSONResponse(
        jsonable_encoder(payload),
        status_code=status_code,
        headers=headers,
    )


@app.exception_handler(ArbiterConflict)
async def arbiter_conflict_handler(request: Request, exc: ArbiterConflict) -> JSONResponse:
    """Expose typed ownership conflicts as a stable, user-actionable 409."""
    return _error_response(
        request,
        status_code=409,
        code=exc.code,
        message=str(exc),
        details={"gpu": exc.status},
        extra={"gpu": exc.status},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    issues = exc.errors()
    return _error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=issues,
        legacy_detail=issues,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    raw_detail = exc.detail
    if isinstance(raw_detail, dict):
        message = str(raw_detail.get("message") or raw_detail.get("detail") or "Request failed")
        code = str(raw_detail.get("code") or f"http_{exc.status_code}")
        details = raw_detail.get("details")
    else:
        message = str(raw_detail)
        code = f"http_{exc.status_code}"
        details = None
    return _error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details,
        legacy_detail=raw_detail,
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("event=request.unhandled request_id=%s", request_id, exc_info=exc)
    return _error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_token_middleware(request, call_next):
    incoming_request_id = request.headers.get("x-request-id", "")
    request_id = (
        incoming_request_id
        if _REQUEST_ID_RE.fullmatch(incoming_request_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    context_token = request_context.set_request_id(request_id)

    def correlated(response: Response) -> Response:
        response.headers["X-Request-ID"] = request_id
        return response

    try:
        client_host = request.client.host if request.client else None
        if not security.remote_client_allowed(client_host):
            # This guard intentionally precedes health/static/API exceptions: an
            # uvicorn --host drift must not expose any surface without auth/opt-in.
            return correlated(
                _error_response(
                    request,
                    status_code=403,
                    code="remote_forbidden",
                    message="Remote clients are not allowed",
                )
            )
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and not getattr(request.app.state, "accepting_mutations", True)
        ):
            return correlated(
                _error_response(
                    request,
                    status_code=503,
                    code="shutting_down",
                    message="Application is shutting down",
                )
            )
        if request.method == "OPTIONS" or request.url.path == "/api/health":
            return correlated(await call_next(request))
        if not request.url.path.startswith("/api/"):
            return correlated(await call_next(request))
        if security.request_is_authorized(request):
            return correlated(await call_next(request))
        return correlated(
            _error_response(
                request,
                status_code=401,
                code="authentication_required",
                message="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        )
    finally:
        request_context.reset_request_id(context_token)


app.include_router(models.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(diagnostics.router)
app.include_router(llama.router)
app.include_router(downloads.router)
app.include_router(civitai.router)
app.include_router(llm.router)
app.include_router(chat.router)
app.include_router(code.router)
app.include_router(gallery.router)
app.include_router(notes.router)
app.include_router(presets.router)
app.include_router(prompts.router)
app.include_router(rag.router)
app.include_router(transcription.router)
app.include_router(tts.router)
app.include_router(voice_engine.router)
app.include_router(videos.router)
app.include_router(ws.router)


@app.get(
    "/api/health",
    response_model=HealthOut,
    responses=ERROR_RESPONSES,
)
async def health() -> HealthOut:
    memory = await asyncio.to_thread(sysmon.snapshot)
    return {
        "status": "ok",
        "version": __version__,
        "stub_mode": settings.stub_mode,
        "models": len(app.state.registry.descriptors()),
        "gpu": app.state.arbiter.status(),
        "mem": memory,
        "security": security.security_posture(),
    }


class FrontendAssets:
    async def __call__(self, scope, receive, send) -> None:
        if not settings.serve_frontend:
            await Response(status_code=404)(scope, receive, send)
            return
        static = StaticFiles(directory=settings.frontend_dist_dir / "assets", check_dir=False)

        async def send_with_cache(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"public, max-age=31536000, immutable"))
                message = {**message, "headers": headers}
            await send(message)

        await static(scope, receive, send_with_cache)


app.mount("/assets", FrontendAssets(), name="frontend-assets")


def _frontend_unavailable() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html>
          <head><title>HFabric frontend build missing</title></head>
          <body style="font-family: system-ui, sans-serif; margin: 2rem;">
            <h1>Frontend build missing</h1>
            <p>HFAB_SERVE_FRONTEND=true is enabled, but frontend/dist is not ready.</p>
            <p>Run <code>npm run build</code> in the <code>frontend</code> directory, then restart.</p>
          </body>
        </html>
        """,
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


def _frontend_headers(path: Path, *, index: bool = False) -> dict[str, str]:
    if index:
        return {"Cache-Control": "no-cache"}
    if "assets" in path.parts:
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "no-cache"}


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "not found")
    if not settings.serve_frontend:
        raise HTTPException(404, "frontend serving disabled")

    dist = settings.frontend_dist_dir.resolve()
    index = dist / "index.html"
    if not index.is_file():
        logger.error(
            "HFAB_SERVE_FRONTEND=true but %s is missing; run npm run build in frontend",
            index,
        )
        return _frontend_unavailable()

    if full_path:
        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist)
        except ValueError:
            raise HTTPException(404, "not found")
        if candidate.is_file():
            return FileResponse(candidate, headers=_frontend_headers(candidate))

    return FileResponse(
        index,
        media_type="text/html",
        headers=_frontend_headers(index, index=True),
    )
