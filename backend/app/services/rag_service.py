"""Shared RAG search helpers."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import RagChunk, RagDocument
from .embedding_service import embedding_model_map, embedding_service


def chunk_document_text(text: str) -> list[str]:
    """Normalize and split a potentially large document for embedding."""
    clean = re.sub(r"\r\n?", "\n", text).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    if not clean:
        return []

    target = max(400, settings.rag_chunk_chars)
    overlap = max(0, min(settings.rag_chunk_overlap, target // 2))
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + target)
        if end < len(clean):
            boundary = max(
                clean.rfind("\n\n", start, end),
                clean.rfind(". ", start, end),
            )
            if boundary > start + target // 2:
                end = boundary + (1 if clean[boundary:boundary + 1] == "." else 0)
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


async def chunk_document_text_async(text: str) -> list[str]:
    return await asyncio.to_thread(chunk_document_text, text)


def resolve_embedding_model_id(model_id: str | None = None) -> str:
    models = embedding_model_map()
    if not models:
        raise RuntimeError(f"no embedding models found in {settings.embed_models_dir}")
    if model_id:
        if model_id not in models:
            raise KeyError("embedding model not found")
        return model_id
    return next(iter(models))


async def resolve_embedding_model_id_async(model_id: str | None = None) -> str:
    return await asyncio.to_thread(resolve_embedding_model_id, model_id)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _score_chunks(
    query_vec: list[float],
    chunks: list[tuple[list[Any], str, str, str, int, str]],
    limit: int,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, tuple[list[Any], str, str, str, int, str]]] = []
    for item in chunks:
        embedding = item[0]
        if not embedding:
            continue
        scored.append((_dot(query_vec, [float(x) for x in embedding]), item))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "document_id": item[1],
            "document_title": item[2],
            "chunk_id": item[3],
            "chunk_index": item[4],
            "text": item[5],
            "score": float(score),
        }
        for score, item in scored[:limit]
    ]


async def search_documents(
    session: AsyncSession,
    *,
    query: str,
    top_k: int = 5,
    model_id: str | None = None,
) -> dict[str, Any]:
    clean_query = query.strip()
    if not clean_query:
        return {"query": clean_query, "results": [], "context": ""}

    rows = (await session.execute(
        select(RagChunk, RagDocument)
        .join(RagDocument, RagDocument.id == RagChunk.document_id)
    )).all()
    if not rows:
        return {"query": clean_query, "results": [], "context": ""}

    resolved_model_id = await resolve_embedding_model_id_async(model_id)
    query_vec = (await embedding_service.embed(
        [f"search_query: {clean_query}"],
        model_id=resolved_model_id,
    ))[0]

    plain_chunks: list[tuple[list[Any], str, str, str, int, str]] = []
    for chunk, doc in rows:
        plain_chunks.append((
            chunk.embedding or [],
            doc.id,
            doc.title,
            chunk.id,
            chunk.chunk_index,
            chunk.text,
        ))

    limit = max(1, min(20, int(top_k)))
    results = await asyncio.to_thread(_score_chunks, query_vec, plain_chunks, limit)
    context = "\n\n".join(
        f"[{idx + 1}] {item['document_title']} (chunk {item['chunk_index'] + 1})\n{item['text']}"
        for idx, item in enumerate(results)
    )
    return {"query": clean_query, "results": results, "context": context}
