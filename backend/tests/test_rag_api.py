from __future__ import annotations

from httpx import ASGITransport, AsyncClient
import pytest


@pytest.fixture
async def rag_client(isolated_runtime, monkeypatch, tmp_path):
    from app.config import settings
    from app.main import app
    from app.services.embedding_service import embedding_service

    embed_dir = tmp_path / "embed"
    embed_dir.mkdir()
    (embed_dir / "tiny-embed.gguf").write_bytes(b"GGUF")
    monkeypatch.setattr(settings, "embed_models_dir", embed_dir)

    async def fake_embed(texts: list[str], model_id: str | None = None) -> list[list[float]]:
        vectors = []
        for text in texts:
            low = text.lower()
            vectors.append([
                1.0 if "alpha" in low else 0.0,
                1.0 if "beta" in low else 0.0,
                1.0 if "gamma" in low else 0.0,
            ])
        return vectors

    monkeypatch.setattr(embedding_service, "embed", fake_embed)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_document_ingest_list_search_and_delete(rag_client):
    content = (
        "Alpha launch notes. " + ("alpha " * 90)
        + "\n\nBeta maintenance notes. " + ("beta " * 90)
    )
    created = (await rag_client.post(
        "/api/rag/documents",
        json={
            "title": "Release notes",
            "source": "unit-test",
            "content": content,
            "model_id": "tiny-embed",
        },
    )).json()

    assert created["title"] == "Release notes"
    assert created["source"] == "unit-test"
    assert created["model_id"] == "tiny-embed"
    assert created["chunks_count"] >= 1

    listed = (await rag_client.get("/api/rag/documents?q=release")).json()
    assert [doc["id"] for doc in listed] == [created["id"]]

    search = (await rag_client.post(
        "/api/rag/search",
        json={"query": "alpha", "top_k": 2, "model_id": "tiny-embed"},
    )).json()
    assert search["query"] == "alpha"
    assert search["results"]
    assert search["results"][0]["document_id"] == created["id"]
    assert "Alpha" in search["context"]

    deleted = (await rag_client.delete(f"/api/rag/documents/{created['id']}")).json()
    assert deleted == {"deleted": created["id"]}
    assert (await rag_client.get("/api/rag/documents")).json() == []
    empty_search = (await rag_client.post("/api/rag/search", json={"query": "alpha"})).json()
    assert empty_search["results"] == []
    assert empty_search["context"] == ""


async def test_upload_and_from_note_ingest_paths(rag_client):
    upload = await rag_client.post(
        "/api/rag/documents/upload",
        data={"title": "Uploaded"},
        files={"file": ("doc.txt", b"Gamma upload text", "text/plain")},
    )
    assert upload.status_code == 200
    assert upload.json()["title"] == "Uploaded"
    assert upload.json()["source"] == "doc.txt"

    note = (await rag_client.post("/api/notes", json={"title": "Note source", "content": "Alpha note"})).json()
    from_note = (await rag_client.post(f"/api/rag/documents/from-note/{note['id']}")).json()
    assert from_note["title"] == "Note source"
    assert from_note["source"] == f"note:{note['id']}"

    missing = await rag_client.post("/api/rag/documents/from-note/not-real")
    assert missing.status_code == 404


async def test_rag_embedding_model_errors(rag_client):
    bad_create = await rag_client.post(
        "/api/rag/documents",
        json={"title": "Bad", "content": "Alpha text", "model_id": "missing"},
    )
    assert bad_create.status_code == 404
    assert "embedding model not found" in bad_create.text

    seeded = await rag_client.post(
        "/api/rag/documents",
        json={"title": "Good", "content": "Alpha searchable text", "model_id": "tiny-embed"},
    )
    assert seeded.status_code == 200

    bad_search = await rag_client.post(
        "/api/rag/search",
        json={"query": "alpha", "model_id": "missing"},
    )
    assert bad_search.status_code == 404

    empty_upload = await rag_client.post(
        "/api/rag/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert empty_upload.status_code == 422

    missing_delete = await rag_client.delete("/api/rag/documents/not-real")
    assert missing_delete.status_code == 404
