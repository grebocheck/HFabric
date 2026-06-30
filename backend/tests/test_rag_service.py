from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.db.models import RagChunk, RagDocument
from app.db.session import init_db, session_scope
from app.services import rag_service


@pytest.fixture
async def rag_db():
    await init_db()
    async with session_scope() as s:
        await s.execute(delete(RagChunk))
        await s.execute(delete(RagDocument))
    yield
    async with session_scope() as s:
        await s.execute(delete(RagChunk))
        await s.execute(delete(RagDocument))


def test_resolve_embedding_model_id(monkeypatch):
    monkeypatch.setattr(rag_service, "embedding_model_map", lambda: {})
    with pytest.raises(RuntimeError, match="no embedding models"):
        rag_service.resolve_embedding_model_id()

    monkeypatch.setattr(rag_service, "embedding_model_map", lambda: {"tiny": {"id": "tiny"}, "other": {}})
    assert rag_service.resolve_embedding_model_id() == "tiny"
    assert rag_service.resolve_embedding_model_id("other") == "other"
    with pytest.raises(KeyError, match="embedding model not found"):
        rag_service.resolve_embedding_model_id("missing")


async def test_search_short_circuits_empty_query_and_empty_index(rag_db, monkeypatch):
    calls = 0

    async def embed(_texts: list[str], model_id: str | None = None) -> list[list[float]]:
        nonlocal calls
        calls += 1
        return [[1.0]]

    monkeypatch.setattr(rag_service.embedding_service, "embed", embed)

    async with session_scope() as s:
        assert await rag_service.search_documents(s, query="   ") == {"query": "", "results": [], "context": ""}
        assert await rag_service.search_documents(s, query="alpha") == {"query": "alpha", "results": [], "context": ""}
    assert calls == 0


async def test_search_scores_sorts_skips_empty_embeddings_and_clamps_top_k(rag_db, monkeypatch):
    monkeypatch.setattr(rag_service, "embedding_model_map", lambda: {"tiny": {"id": "tiny"}})

    async def embed(texts: list[str], model_id: str | None = None) -> list[list[float]]:
        assert texts == ["search_query: alpha"]
        assert model_id == "tiny"
        return [[1.0, 0.0]]

    monkeypatch.setattr(rag_service.embedding_service, "embed", embed)

    async with session_scope() as s:
        doc_a = RagDocument(title="Alpha doc", source="a", model_id="tiny")
        doc_b = RagDocument(title="Beta doc", source="b", model_id="tiny")
        s.add_all([doc_a, doc_b])
        await s.flush()
        s.add_all([
            RagChunk(document_id=doc_a.id, chunk_index=0, text="low score", embedding=[0.2, 0.8]),
            RagChunk(document_id=doc_a.id, chunk_index=1, text="winner", embedding=[0.9, 0.1]),
            RagChunk(document_id=doc_b.id, chunk_index=0, text="ignored", embedding=[]),
        ])

    async with session_scope() as s:
        one = await rag_service.search_documents(s, query="alpha", top_k=0, model_id="tiny")
        many = await rag_service.search_documents(s, query="alpha", top_k=99, model_id="tiny")

    assert [item["text"] for item in one["results"]] == ["winner"]
    assert [item["text"] for item in many["results"]] == ["winner", "low score"]
    assert many["context"].startswith("[1] Alpha doc (chunk 2)\nwinner")
    assert "ignored" not in many["context"]


async def test_search_rejects_unknown_model_before_embedding(rag_db, monkeypatch):
    monkeypatch.setattr(rag_service, "embedding_model_map", lambda: {"tiny": {"id": "tiny"}})

    async with session_scope() as s:
        doc = RagDocument(title="Doc", source=None, model_id="tiny")
        s.add(doc)
        await s.flush()
        s.add(RagChunk(document_id=doc.id, chunk_index=0, text="alpha", embedding=[1.0]))

    async with session_scope() as s:
        with pytest.raises(KeyError):
            await rag_service.search_documents(s, query="alpha", model_id="missing")
