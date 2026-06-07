"""Source-image uploads for img2img (P13.4).

Tokens are opaque 32-char hex names for PNGs under ``outputs/uploads``. Both the
upload API and the diffusers backend resolve them through here so the path rules
(and the traversal guard) live in exactly one place.
"""

from __future__ import annotations

from pathlib import Path
import re

from ..config import settings

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


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
