from __future__ import annotations

import asyncio

import pytest

from app.services import embedding_service as es


def test_model_listing_and_id_normalization(isolated_runtime, monkeypatch, tmp_path):
    from app.config import settings

    embed_dir = tmp_path / "embed"
    embed_dir.mkdir()
    (embed_dir / "Tiny Embed.Q4_K_M.gguf").write_bytes(b"GGUF")
    (embed_dir / "readme.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(settings, "embed_models_dir", embed_dir)

    models = es.list_embedding_models()

    assert models == [{
        "id": "tiny-embed-q4-k-m",
        "name": "Tiny Embed.Q4_K_M",
        "path": str(embed_dir / "Tiny Embed.Q4_K_M.gguf"),
        "size_bytes": 4,
    }]
    assert es.embedding_model_map()["tiny-embed-q4-k-m"]["name"] == "Tiny Embed.Q4_K_M"


async def test_embed_trims_inputs_selects_model_and_normalizes(monkeypatch):
    service = es.LocalEmbeddingService()
    ensured: list[str] = []
    posts: list[dict] = []

    monkeypatch.setattr(es, "embedding_model_map", lambda: {
        "tiny": {"id": "tiny", "name": "Tiny", "path": "tiny.gguf"},
    })

    async def ensure(model):
        ensured.append(model["id"])

    class FakeResponse:
        def __init__(self, count: int) -> None:
            self._count = count

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [3.0, 4.0]} for _ in range(self._count)]}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: dict):
            posts.append({"url": url, "json": json, "timeout": self.timeout})
            return FakeResponse(len(json["input"]))

    monkeypatch.setattr(service, "_ensure_server_locked", ensure)
    monkeypatch.setattr(es.httpx, "AsyncClient", FakeClient)

    vectors = await service.embed([" alpha ", "", "beta"], model_id="tiny")

    assert ensured == ["tiny"]
    assert posts[0]["json"] == {"model": "Tiny", "input": ["alpha", "beta"]}
    assert vectors == [[0.6, 0.8], [0.6, 0.8]]


async def test_embed_empty_missing_models_and_bad_vector_count(monkeypatch):
    service = es.LocalEmbeddingService()
    assert await service.embed([" ", ""]) == []

    monkeypatch.setattr(es, "embedding_model_map", lambda: {})
    with pytest.raises(RuntimeError, match="no embedding models"):
        await service.embed(["alpha"])

    monkeypatch.setattr(es, "embedding_model_map", lambda: {
        "tiny": {"id": "tiny", "name": "Tiny", "path": "tiny.gguf"},
    })

    async def ensure(_model):
        return None

    class BadResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": []}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, *args, **kwargs):
            return BadResponse()

    monkeypatch.setattr(service, "_ensure_server_locked", ensure)
    monkeypatch.setattr(es.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="unexpected number"):
        await service.embed(["alpha"])


async def test_ensure_server_requires_llama_binary(monkeypatch, tmp_path):
    from app.config import settings

    service = es.LocalEmbeddingService()
    missing = tmp_path / "missing-llama-server"
    monkeypatch.setattr(settings, "llama_server_bin", missing)

    with pytest.raises(FileNotFoundError, match="llama-server binary not found"):
        await service._ensure_server_locked({"id": "tiny", "path": tmp_path / "tiny.gguf"})


async def test_stop_locked_terminates_or_kills_process(monkeypatch):
    service = es.LocalEmbeddingService()
    events: list[str] = []

    class SlowProc:
        returncode = None

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")
            self.returncode = -9

        async def wait(self) -> None:
            events.append("wait")

    async def timeout_wait(coro, timeout):
        coro.close()
        raise TimeoutError

    service._proc = SlowProc()
    service._model_id = "tiny"
    monkeypatch.setattr(asyncio, "wait_for", timeout_wait)

    await service._stop_locked()

    assert events == ["terminate", "kill", "wait"]
    assert service._proc is None
    assert service._model_id is None
