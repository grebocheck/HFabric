"""Shared test setup.

Critically, this runs *before* any `app.*` import: `app.config` builds a cached
`Settings` and `app.db.session` builds the async engine at import time, both from
the environment. So we pin STUB mode, a throwaway SQLite file, and temp model
dirs (seeded with dummy model files) here, so tests never touch the GPU stack or
the real `data/hfabric.db` and the registry still has something to discover.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import-time settings still need seed paths before fixtures run. Make that
# bootstrap tree unique per pytest process; every test gets its own DB below.
_TMP = Path(tempfile.mkdtemp(prefix="hfabric_test_"))
_IMAGE_DIR = _TMP / "image"
_LLM_DIR = _TMP / "llm"
_VISION_DIR = _TMP / "vision"
_VIDEO_DIR = _TMP / "video"
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
_LLM_DIR.mkdir(parents=True, exist_ok=True)
_VISION_DIR.mkdir(parents=True, exist_ok=True)
_VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def _write_safetensors(path: Path, keys: list[str]) -> None:
    """Write a minimal valid safetensors file (8-byte header length + JSON header
    + 2 data bytes) so the classifier reads real keys without multi-GB weights."""
    header = {k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}
    blob = json.dumps(header).encode("utf-8")
    with path.open("wb") as f:
        f.write(struct.pack("<Q", len(blob)))
        f.write(blob)
        f.write(b"\x00\x00")


# An SDXL-classified image model (UNet `input_blocks.*` key) and a GGUF LLM
# (recognized purely by extension). Enough for the stub pipeline + swap test.
_SDXL = _IMAGE_DIR / "stub-sdxl.safetensors"
if not _SDXL.exists():
    _write_safetensors(_SDXL, ["model.diffusion_model.input_blocks.0.0.weight"])
_GGUF = _LLM_DIR / "stub-llm.gguf"
if not _GGUF.exists():
    _GGUF.write_bytes(b"GGUF\x00")
_VIDEO = _VIDEO_DIR / "stub-ltx-video"
_VIDEO.mkdir(parents=True, exist_ok=True)
(_VIDEO / "model_index.json").write_text(
    json.dumps({"_class_name": "LTXPipeline"}), encoding="utf-8"
)

os.environ.setdefault("HFAB_STUB_MODE", "true")
# Popping is not enough: pydantic-settings also reads the repo .env FILE, so a
# developer's real HFAB_API_TOKEN/HFAB_HOST would leak into the suite (every
# request suddenly 401s). Env vars take precedence over env_file - pin them.
os.environ["HFAB_API_TOKEN"] = ""
os.environ["HFAB_ALLOW_INSECURE_LAN"] = "false"
os.environ["HFAB_HOST"] = "127.0.0.1"
os.environ["HFAB_PORT"] = "8260"
os.environ["HFAB_DB_PATH"] = str(_TMP / "hfabric_test.db")
os.environ["HFAB_DATA_DIR"] = str(_TMP / "data")
os.environ["HFAB_OUTPUTS_DIR"] = str(_TMP / "outputs")
os.environ["HFAB_IMAGE_MODELS_DIR"] = str(_IMAGE_DIR)
os.environ["HFAB_LLM_MODELS_DIR"] = str(_LLM_DIR)
os.environ["HFAB_VISION_MODELS_DIR"] = str(_VISION_DIR)
os.environ["HFAB_VIDEO_MODELS_DIR"] = str(_VIDEO_DIR)
# Keep the budget guard deterministic regardless of the host's free RAM.
os.environ.setdefault("HFAB_LEARN_MEMORY_PROFILES", "false")


@pytest.fixture(autouse=True)
async def isolated_runtime(monkeypatch, tmp_path):
    """Point global settings + DB session helpers at a per-test runtime tree."""
    from app.config import settings
    from app.db import session as db_session
    from app.services import capability_profile
    from app.services.embedding_service import embedding_service
    from app.services.voice_engine import engine as voice_engine
    from app.services.voice_engine import realtime
    from app.util import sysmon

    loop = asyncio.get_running_loop()
    previous_loop_handler = loop.get_exception_handler()
    previous_excepthook = sys.excepthook
    # Several APIs mutate the process-wide Settings singleton directly. Snapshot
    # every declared field, not only today's writable override allowlist, so a
    # newly-added runtime knob cannot silently leak into the next test.
    settings_snapshot = {
        key: deepcopy(getattr(settings, key))
        for key in type(settings).model_fields
    }

    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "outputs_dir", data_dir / "outputs")
    monkeypatch.setattr(settings, "logs_dir", data_dir / "logs")
    monkeypatch.setattr(settings, "runtime_dir", data_dir / "runtime")
    monkeypatch.setattr(settings, "backups_dir", data_dir / "backups")
    monkeypatch.setattr(settings, "db_path", data_dir / "hfabric.db")

    old_engine = db_session.engine
    old_session_local = db_session.SessionLocal
    new_engine = create_async_engine(settings.db_url, future=True)
    db_session.engine = new_engine
    db_session.SessionLocal = async_sessionmaker(
        new_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    try:
        yield {
            "data_dir": data_dir,
            "db_path": settings.db_path,
            "outputs_dir": settings.outputs_dir,
            "logs_dir": settings.logs_dir,
            "runtime_dir": settings.runtime_dir,
            "backups_dir": settings.backups_dir,
        }
    finally:
        # App lifespan normally performs these stops. Repeating them here makes
        # teardown safe even when startup or a test aborts before lifespan exits.
        with suppress(Exception):
            await asyncio.to_thread(realtime.stop_session)
        with suppress(Exception):
            await embedding_service.stop()
        voice_engine._ENGINE = None
        sysmon.clear_learned_profiles()
        cache_clear = getattr(capability_profile._hardware_profile, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()
        loop.set_exception_handler(previous_loop_handler)
        sys.excepthook = previous_excepthook
        await new_engine.dispose()
        db_session.engine = old_engine
        db_session.SessionLocal = old_session_local
        for key, value in settings_snapshot.items():
            setattr(settings, key, value)


@pytest.fixture
async def app_client(isolated_runtime):
    """Run the full FastAPI lifespan around an ASGI client on an isolated DB."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _wait_jobs_done(client, job_ids: list[str], timeout: float = 30.0) -> list[dict]:
    import asyncio

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    latest: list[dict] = []
    while loop.time() < deadline:
        latest = [(await client.get(f"/api/jobs/{job_id}")).json() for job_id in job_ids]
        if all(job["status"] in ("done", "error", "cancelled") for job in latest):
            return latest
        await asyncio.sleep(0.1)
    raise AssertionError(f"jobs did not finish in {timeout}s: {latest}")


@pytest.fixture
def wait_jobs_done():
    return _wait_jobs_done
