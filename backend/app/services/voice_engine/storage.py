"""Opaque-token storage for native voice-engine audio outputs."""

from __future__ import annotations

from pathlib import Path
import re
import uuid

from ...config import settings

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def output_dir() -> Path:
    path = settings.outputs_dir / "voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_token() -> str:
    return uuid.uuid4().hex


def resolve_output(token: str) -> Path | None:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    return output_dir() / f"{token}.wav"


def resolve_mp3(token: str) -> Path | None:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    return output_dir() / f"{token}.mp3"


def resolve_metadata(token: str) -> Path | None:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    return output_dir() / f"{token}.json"
