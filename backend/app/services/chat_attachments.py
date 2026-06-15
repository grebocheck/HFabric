"""Chat attachment preparation for prompt building.

Uploads stay as files under ``outputs/chat_uploads``. This module turns their
opaque tokens into persisted metadata, OpenAI image content parts, and bounded
document context for the current LLM turn.
"""

from __future__ import annotations

import base64
from collections import Counter
from html import unescape
from pathlib import Path
import re
from xml.etree import ElementTree
import zipfile

from fastapi import HTTPException

from ..config import settings
from ..util.uploads import chat_attachment_out, resolve_chat_upload

IMAGE_TOKEN_COST = 1024
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".log",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".scss",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
}


def load_attachment_metadata(tokens: list[str]) -> list[dict]:
    """Resolve upload tokens into public metadata or raise a clear API error."""
    out: list[dict] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        resolved = resolve_chat_upload(token)
        if resolved is None:
            raise HTTPException(404, f"attachment not found: {token}")
        _, meta = resolved
        public = chat_attachment_out(meta)
        if public["kind"] not in {"image", "document"}:
            raise HTTPException(415, f"unsupported chat attachment: {public['filename']}")
        out.append(public)
    return out


def estimate_attachment_tokens(attachments: list[dict]) -> int:
    total = 0
    for item in attachments:
        if item.get("kind") == "image":
            total += IMAGE_TOKEN_COST
        else:
            total += min(8192, max(1, int(item.get("size_bytes") or 0) // 4))
    return total


async def build_user_content(
    text: str,
    attachments: list[dict],
    *,
    allow_images: bool,
    max_context_tokens: int,
) -> tuple[str | list[dict], list[dict]]:
    """Build OpenAI-compatible user content and enriched attachment metadata."""
    enriched = [dict(item) for item in attachments]
    body = text.strip()
    doc_context, enriched = await build_document_context(
        body,
        enriched,
        max_context_chars=max(0, max_context_tokens * 4),
    )
    if doc_context:
        body = f"{body}\n\n{doc_context}".strip()

    image_attachments = [item for item in enriched if item.get("kind") == "image"]
    if not image_attachments:
        return body, enriched
    if not allow_images:
        raise HTTPException(400, "selected LLM model does not have a multimodal projector")

    parts: list[dict] = []
    if body:
        parts.append({"type": "text", "text": body})
    for item in image_attachments:
        parts.append({
            "type": "image_url",
            "image_url": {"url": image_data_url(str(item["token"]))},
        })
    return parts, enriched


def history_message_content(message) -> str | list[dict]:
    """Rebuild persisted user image attachments as OpenAI image parts."""
    content = str(message.content or "")
    attachments = list(message.attachments or [])
    images = [item for item in attachments if item.get("kind") == "image"]
    if not images:
        return content
    parts: list[dict] = []
    if content.strip():
        parts.append({"type": "text", "text": content})
    for item in images:
        token = str(item.get("token") or "")
        if resolve_chat_upload(token):
            parts.append({"type": "image_url", "image_url": {"url": image_data_url(token)}})
    return parts or content


def image_data_url(token: str) -> str:
    resolved = resolve_chat_upload(token)
    if resolved is None:
        raise HTTPException(404, f"attachment not found: {token}")
    path, meta = resolved
    ctype = str(meta.get("content_type") or "image/png")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{ctype};base64,{data}"


async def build_document_context(
    user_text: str,
    attachments: list[dict],
    *,
    max_context_chars: int,
) -> tuple[str, list[dict]]:
    docs = [item for item in attachments if item.get("kind") == "document"]
    if not docs or max_context_chars <= 0:
        return "", attachments

    blocks: list[str] = []
    remaining = max_context_chars
    for idx, item in enumerate(docs, start=1):
        token = str(item.get("token") or "")
        extracted, error = extract_document_text(token)
        if error:
            item["notice"] = error
            item["extracted_chars"] = 0
            item["included_chars"] = 0
            item["truncated"] = False
            continue
        clean = _clean_text(extracted)
        item["extracted_chars"] = len(clean)
        if not clean:
            item["notice"] = "no extractable text found"
            item["included_chars"] = 0
            item["truncated"] = False
            continue
        if remaining <= 240:
            item["notice"] = "not injected: token budget already used"
            item["included_chars"] = 0
            item["truncated"] = True
            continue

        included = clean
        transient = False
        if len(included) > remaining:
            included = await _select_relevant_text(clean, user_text, remaining)
            transient = True
        item["included_chars"] = len(included)
        item["truncated"] = len(included) < len(clean)
        if item["truncated"]:
            item["notice"] = (
                f"included {len(included):,} of {len(clean):,} extracted chars"
                + (" via transient attachment RAG" if transient else "")
            )
        else:
            item["notice"] = f"included {len(clean):,} extracted chars"
        blocks.append(
            f"[Attachment {idx}: {item.get('filename', 'document')}]\n"
            f"{included}"
        )
        remaining -= len(included) + 160

    if not blocks:
        return "", attachments
    header = (
        "Attached document context follows. Use it only when relevant; "
        "if it is insufficient, say what is missing."
    )
    return header + "\n\n" + "\n\n---\n\n".join(blocks), attachments


def extract_document_text(token: str) -> tuple[str, str | None]:
    resolved = resolve_chat_upload(token)
    if resolved is None:
        return "", "attachment file is missing"
    path, meta = resolved
    suffix = path.suffix.lower()
    ctype = str(meta.get("content_type") or "")
    try:
        if suffix in _TEXT_EXTENSIONS or ctype.startswith("text/"):
            return path.read_text(encoding="utf-8", errors="replace"), None
        if suffix == ".docx":
            return _extract_docx(path), None
        if suffix == ".pdf":
            return _extract_pdf(path), None
    except Exception as exc:  # noqa: BLE001
        return "", f"could not extract text: {exc}"
    return "", "unsupported document format"


def _extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", ns):
        pieces = [node.text or "" for node in para.findall(".//w:t", ns)]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ModuleNotFoundError:
        raise RuntimeError("PDF extraction needs pypdf installed") from None
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def _clean_text(text: str) -> str:
    clean = unescape(text.replace("\r\n", "\n").replace("\r", "\n"))
    clean = re.sub(r"\n{4,}", "\n\n\n", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    return clean.strip()


async def _select_relevant_text(text: str, query: str, max_chars: int) -> str:
    chunks = _chunk_text(text, max(800, min(settings.rag_chunk_chars, 2400)))
    if not chunks:
        return text[:max_chars]
    embedded = await _select_with_embeddings(chunks, query, max_chars)
    if embedded:
        return embedded
    query_terms = Counter(t.lower() for t in _TOKEN_RE.findall(query))
    if not query_terms:
        return text[:max_chars]
    scored = []
    for idx, chunk in enumerate(chunks):
        terms = Counter(t.lower() for t in _TOKEN_RE.findall(chunk))
        score = sum(min(terms[t], query_terms[t]) for t in query_terms)
        scored.append((score, -idx, chunk))
    scored.sort(reverse=True)
    selected: list[str] = []
    used = 0
    for score, _neg_idx, chunk in scored:
        if score <= 0 and selected:
            continue
        if used + len(chunk) + 8 > max_chars:
            continue
        selected.append(chunk)
        used += len(chunk) + 8
        if used >= max_chars * 0.85:
            break
    if not selected:
        return text[:max_chars]
    return "\n\n[...]\n\n".join(selected)


async def _select_with_embeddings(chunks: list[str], query: str, max_chars: int) -> str:
    clean_query = query.strip()
    if not clean_query:
        return ""
    try:
        from .embedding_service import embedding_model_map, embedding_service  # noqa: PLC0415
    except Exception:
        return ""
    if not embedding_model_map():
        return ""
    try:
        vectors = await embedding_service.embed(
            [f"search_query: {clean_query}", *[f"search_document: {chunk}" for chunk in chunks]]
        )
    except Exception:
        return ""
    if len(vectors) != len(chunks) + 1:
        return ""
    query_vec = vectors[0]
    scored = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors[1:])):
        score = sum(float(a) * float(b) for a, b in zip(query_vec, vec))
        scored.append((score, -idx, chunk))
    scored.sort(reverse=True)
    selected: list[str] = []
    used = 0
    for _score, _neg_idx, chunk in scored:
        if used + len(chunk) + 8 > max_chars:
            continue
        selected.append(chunk)
        used += len(chunk) + 8
        if used >= max_chars * 0.85:
            break
    return "\n\n[...]\n\n".join(selected)


def _chunk_text(text: str, target: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + target // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - 120, start + 1)
    return chunks
