"""Repository code-context helpers for the Code workspace."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from .contracts import (
    ERROR_RESPONSES,
    CodeFileContentOut,
    CodeFileOut,
)

router = APIRouter(
    prefix="/api/code",
    tags=["code"],
    responses=ERROR_RESPONSES,
)

IGNORED_DIRS = {
    ".cache",
    ".git",
    ".gnupg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".ssh",
    ".venv",
    ".aws",
    "__pycache__",
    "bin",
    "data",
    "dist",
    "models",
    "node_modules",
}

TEXT_EXTS = {
    "",
    ".bat",
    ".cfg",
    ".css",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SAFE_DOTENV_FILES = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_FILES = {
    ".env",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "auth.json",
    "cookies.json",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "service-account.json",
    "secrets.json",
    "token.json",
}
SENSITIVE_SUFFIXES = {".jks", ".key", ".keystore", ".p12", ".pfx", ".pem"}
MAX_FILE_BYTES = 180_000


def _root() -> Path:
    return settings.root.resolve()


def _rel(path: Path) -> str:
    return path.relative_to(_root()).as_posix()


def _inside_root(rel_path: str) -> Path:
    root = _root()
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(400, "path escapes repository root")
    if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
        raise HTTPException(400, "path is ignored")
    if _is_sensitive_path(path):
        raise HTTPException(400, "sensitive file is not available in Code workspace")
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return path


def _is_text_candidate(path: Path) -> bool:
    return (
        not _is_sensitive_path(path)
        and (
            path.suffix.lower() in TEXT_EXTS
            or path.name in TEXT_EXTS
            or path.name.lower() in SAFE_DOTENV_FILES
        )
    )


def _is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    if name in SAFE_DOTENV_FILES:
        return False
    return (
        name in SENSITIVE_FILES
        or name.startswith(".env.")
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def _list_code_files(query: str, limit: int) -> list[dict]:
    out: list[dict] = []
    root = _root()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS and d != "dist"
        ]
        base = Path(dirpath)
        for name in sorted(filenames):
            path = base / name
            if not _is_text_candidate(path):
                continue
            rel = _rel(path)
            if query and query not in rel.lower():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            out.append({"path": rel, "size_bytes": size})
            if len(out) >= limit:
                return out
    return out


@router.get("/files", response_model=list[CodeFileOut])
async def list_code_files(
    q: str | None = Query(None, max_length=200),
    limit: int = Query(120, ge=1, le=500),
) -> list[CodeFileOut]:
    query = (q or "").strip().lower()
    return await asyncio.to_thread(_list_code_files, query, limit)


def _read_code_file(rel_path: str) -> dict:
    file_path = _inside_root(rel_path)
    size = file_path.stat().st_size
    with file_path.open("rb") as f:
        data = f.read(MAX_FILE_BYTES + 1)
    truncated = len(data) > MAX_FILE_BYTES
    if b"\0" in data[:4096]:
        raise HTTPException(415, "file looks binary")
    content = data[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    return {
        "path": _rel(file_path),
        "size_bytes": size,
        "content": content,
        "truncated": truncated,
    }


@router.get("/file", response_model=CodeFileContentOut)
async def get_code_file(
    path: str = Query(..., max_length=500),
) -> CodeFileContentOut:
    return await asyncio.to_thread(_read_code_file, path)
