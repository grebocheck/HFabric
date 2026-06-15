"""Source-image, mask, and chat-attachment uploads.

Tokens are opaque 32-char hex names for PNGs under ``outputs/uploads``. Both the
upload API and the diffusers backend resolve them through here so the path rules
(and the traversal guard) live in exactly one place.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import mimetypes
from pathlib import Path
import re
from typing import BinaryIO
import uuid

from fastapi import HTTPException, UploadFile

from ..config import settings

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
CHUNK_SIZE = 1024 * 1024

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOCUMENT_EXTENSIONS = {
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
    ".pdf",
    ".docx",
}


def uploads_dir() -> Path:
    d = settings.outputs_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def chat_uploads_dir() -> Path:
    d = settings.outputs_dir / "chat_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_upload(token: str) -> Path | None:
    """Map a token to its PNG path, or None if the token is malformed (which also
    blocks path traversal — only bare hex names are ever accepted)."""
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    return uploads_dir() / f"{token}.png"


def _safe_filename(name: str | None) -> str:
    raw = Path(name or "attachment").name
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw).strip(" .")
    return clean[:160] or "attachment"


def _kind_for(filename: str, content_type: str | None) -> str:
    ext = Path(filename).suffix.lower()
    ctype = (content_type or "").lower()
    if ctype.startswith("image/") or ext in IMAGE_EXTENSIONS:
        return "image"
    if (
        ctype.startswith("text/")
        or ctype in {
            "application/json",
            "application/pdf",
            "application/xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        or ext in DOCUMENT_EXTENSIONS
    ):
        return "document"
    return "file"


def _chat_upload_path(token: str, suffix: str) -> Path:
    return chat_uploads_dir() / f"{token}{suffix}"


def _chat_metadata_path(token: str) -> Path:
    return chat_uploads_dir() / f"{token}.json"


def resolve_chat_upload(token: str) -> tuple[Path, dict] | None:
    """Return ``(path, metadata)`` for a chat upload token.

    The token regex is the traversal guard: no slashes, dots, or user-provided
    path components are ever accepted.
    """
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    meta_path = _chat_metadata_path(token)
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    suffix = str(meta.get("stored_suffix") or "")
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix):
        return None
    path = _chat_upload_path(token, suffix)
    if not path.exists():
        return None
    return path, meta


def chat_attachment_out(meta: dict) -> dict:
    token = str(meta.get("token") or "")
    return {
        "token": token,
        "filename": str(meta.get("filename") or "attachment"),
        "content_type": str(meta.get("content_type") or "application/octet-stream"),
        "kind": str(meta.get("kind") or "file"),
        "size_bytes": int(meta.get("size_bytes") or 0),
        "url": f"/api/chat/uploads/{token}/file",
        **{
            key: meta[key]
            for key in ("extracted_chars", "included_chars", "truncated", "notice")
            if key in meta
        },
    }


async def store_chat_upload(file: UploadFile, *, max_bytes: int) -> dict:
    """Persist an arbitrary chat attachment and return public metadata."""
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix or ""):
        guessed = mimetypes.guess_extension(file.content_type or "") or ".bin"
        suffix = guessed.lower() if re.fullmatch(r"\.[A-Za-z0-9]{1,12}", guessed) else ".bin"
    token = uuid.uuid4().hex
    path = _chat_upload_path(token, suffix)
    with path.open("wb") as handle:
        size = await copy_limited_upload(file, handle, max_bytes=max_bytes, label="chat attachment")
    if size <= 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise HTTPException(422, "attachment is empty")
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    meta = {
        "token": token,
        "filename": filename,
        "content_type": content_type,
        "kind": _kind_for(filename, content_type),
        "size_bytes": size,
        "stored_suffix": suffix,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _chat_metadata_path(token).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return chat_attachment_out(meta)


async def read_limited_upload(file: UploadFile, *, max_bytes: int, label: str) -> bytes:
    """Read an upload in bounded chunks, raising 413 before an unbounded buffer."""
    data = bytearray()
    while True:
        remaining = max_bytes - len(data)
        chunk = await file.read(min(CHUNK_SIZE, max(1, remaining + 1)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(413, f"{label} exceeds {max_bytes // (1024 * 1024)} MB")
    return bytes(data)


async def copy_limited_upload(file: UploadFile, handle: BinaryIO, *, max_bytes: int, label: str) -> int:
    total = 0
    while True:
        remaining = max_bytes - total
        chunk = await file.read(min(CHUNK_SIZE, max(1, remaining + 1)))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"{label} exceeds {max_bytes // (1024 * 1024)} MB")
        handle.write(chunk)
    return total
