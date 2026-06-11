"""Source-image and mask uploads for img2img/inpainting (P13.4/P13.5).

Tokens are opaque 32-char hex names for PNGs under ``outputs/uploads``. Both the
upload API and the diffusers backend resolve them through here so the path rules
(and the traversal guard) live in exactly one place.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import BinaryIO

from fastapi import HTTPException, UploadFile

from ..config import settings

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
CHUNK_SIZE = 1024 * 1024


def uploads_dir() -> Path:
    d = settings.outputs_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_upload(token: str) -> Path | None:
    """Map a token to its PNG path, or None if the token is malformed (which also
    blocks path traversal — only bare hex names are ever accepted)."""
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    return uploads_dir() / f"{token}.png"


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
