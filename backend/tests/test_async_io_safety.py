from __future__ import annotations

import asyncio
import io
from pathlib import Path
import threading
import time
import zipfile

import pytest

from app.backends.base import ModelDescriptor
from app.backends.registry import ModelRegistry
from app.core.enums import ModelFamily
from app.db.models import Image
from app.db.session import init_db, session_scope
from app.services import chat_attachments, gallery_service, model_storage
from app.util.async_files import build_temporary_artifact


async def _heartbeat() -> None:
    await asyncio.sleep(0.01)


async def test_registry_scan_runs_off_loop_and_publishes_atomically(
    monkeypatch,
    tmp_path,
):
    registry = ModelRegistry()
    old = ModelDescriptor(
        id="old",
        name="Old",
        family=ModelFamily.SDXL,
        path=tmp_path / "old.safetensors",
        size_bytes=1,
    )
    new = ModelDescriptor(
        id="new",
        name="New",
        family=ModelFamily.SDXL,
        path=tmp_path / "new.safetensors",
        size_bytes=2,
    )
    registry._descriptors = {"old": old}

    def slow_inventory():
        # Deterministically models a large/slow filesystem without making the
        # suite create gigabytes of fixtures.
        time.sleep(0.35)
        return {"new": new}, {}

    monkeypatch.setattr(registry, "_build_inventory", slow_inventory)
    scan = asyncio.create_task(registry.scan_async())

    await asyncio.wait_for(_heartbeat(), timeout=0.15)
    assert not scan.done()
    assert [item.id for item in registry.descriptors()] == ["old"]

    await scan
    assert [item.id for item in registry.descriptors()] == ["new"]


async def test_gallery_reconciliation_walk_runs_off_loop(
    isolated_runtime,
    monkeypatch,
    tmp_path,
):
    await init_db()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    real_scan = gallery_service._scan_media_inventory

    def slow_scan(
        output_dir: Path,
        stored_paths: tuple[str, ...],
        row_paths: tuple[tuple[str, str | None], ...],
    ):
        time.sleep(0.35)
        return real_scan(output_dir, stored_paths, row_paths)

    monkeypatch.setattr(gallery_service, "_scan_media_inventory", slow_scan)
    async with session_scope() as session:
        reconciliation = asyncio.create_task(
            gallery_service.reconcile_media(session, outputs)
        )
        await asyncio.wait_for(_heartbeat(), timeout=0.15)
        assert not reconciliation.done()
        report = await reconciliation

    assert report["recovered"] == 0


async def test_recursive_model_inventory_wrapper_keeps_loop_responsive(monkeypatch):
    def slow_installed(_in_use=None):
        time.sleep(0.35)
        return [{"kind": "image", "size_bytes": 1}]

    monkeypatch.setattr(model_storage, "installed", slow_installed)
    inventory = asyncio.create_task(model_storage.installed_async())

    await asyncio.wait_for(_heartbeat(), timeout=0.15)
    assert not inventory.done()
    assert await inventory == [{"kind": "image", "size_bytes": 1}]


async def test_large_document_extraction_runs_off_loop(monkeypatch):
    def slow_extract(_token: str):
        time.sleep(0.35)
        return "alpha document", None

    monkeypatch.setattr(
        chat_attachments,
        "_extract_clean_document",
        slow_extract,
    )
    extraction = asyncio.create_task(chat_attachments.build_document_context(
        "alpha",
        [{"token": "opaque", "kind": "document", "filename": "large.pdf"}],
        max_context_chars=10_000,
    ))

    await asyncio.wait_for(_heartbeat(), timeout=0.15)
    assert not extraction.done()
    context, enriched = await extraction

    assert "alpha document" in context
    assert enriched[0]["included_chars"] == len("alpha document")


def test_recursive_size_inventory_reuses_fresh_mtime_cache(monkeypatch, tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "weights.bin").write_bytes(b"1234")
    model_storage._SIZE_CACHE.clear()

    assert model_storage._dir_size(model_dir) == 4

    def unexpected_walk(_path):
        raise AssertionError("fresh inventory size should come from cache")

    monkeypatch.setattr(model_storage.os, "walk", unexpected_walk)
    assert model_storage._dir_size(model_dir) == 4


async def test_cancelled_artifact_build_is_removed_after_worker_finishes(tmp_path):
    artifact = tmp_path / "export.zip"
    started = threading.Event()
    release = threading.Event()

    def slow_builder(path: Path) -> None:
        path.write_bytes(b"partial")
        started.set()
        release.wait(timeout=2.0)
        path.write_bytes(b"complete")

    build = asyncio.create_task(
        build_temporary_artifact(artifact, slow_builder)
    )
    assert await asyncio.to_thread(started.wait, 1.0)

    build.cancel()
    with pytest.raises(asyncio.CancelledError):
        await build
    release.set()

    for _ in range(100):
        if not artifact.exists():
            break
        await asyncio.sleep(0.01)
    assert not artifact.exists()


async def test_image_export_builds_complete_archive_off_loop(app_client, tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"png payload")
    async with session_scope() as session:
        session.add(Image(
            id="async-export",
            path=str(source),
            width=16,
            height=16,
            family="sdxl",
            tags=[],
            params={"model": "test", "prompt": "archive"},
        ))

    response = await app_client.post(
        "/api/images/export",
        json={"image_ids": ["async-export"]},
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("images/async-export.png") == b"png payload"
        assert b'"prompt": "archive"' in archive.read(
            "metadata/async-export.json"
        )
