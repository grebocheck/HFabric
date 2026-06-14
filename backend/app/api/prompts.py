"""Prompt library: named, taggable, reusable image-prompt snippets (P19.4).

Insertable from the image composer (and, later, the chat /image bridge);
exportable/importable as JSON for sharing between machines.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PromptSnippet
from ..schemas import (
    PromptSnippetCreate,
    PromptSnippetImportIn,
    PromptSnippetImportOut,
    PromptSnippetOut,
    PromptSnippetUpdate,
    _clean_tags,
)
from .deps import get_session

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _name_from(name: str | None, body: str) -> str:
    """A usable display name: explicit name, else the first line of the body."""
    if name and name.strip():
        return name.strip()[:128]
    first_line = body.strip().splitlines()[0] if body.strip() else ""
    return (first_line[:60] or "Untitled prompt").strip()


@router.get("", response_model=list[PromptSnippetOut])
async def list_prompts(
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[PromptSnippetOut]:
    stmt = select(PromptSnippet).order_by(PromptSnippet.updated_at.desc())
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PromptSnippet.name.ilike(like), PromptSnippet.body.ilike(like)))
    rows = (await session.execute(stmt)).scalars().all()
    if tag and tag.strip():
        needle = tag.strip().lower()
        rows = [r for r in rows if any(needle == t.lower() for t in (r.tags or []))]
    return [PromptSnippetOut.model_validate(r) for r in rows]


@router.post("", response_model=PromptSnippetOut)
async def create_prompt(
    body: PromptSnippetCreate, session: AsyncSession = Depends(get_session)
) -> PromptSnippetOut:
    if not body.body.strip():
        raise HTTPException(422, "prompt body is required")
    snippet = PromptSnippet(
        name=_name_from(body.name, body.body),
        body=body.body.strip(),
        negative=(body.negative.strip() or None) if body.negative else None,
        tags=_clean_tags(body.tags),
    )
    session.add(snippet)
    await session.commit()
    return PromptSnippetOut.model_validate(snippet)


@router.patch("/{prompt_id}", response_model=PromptSnippetOut)
async def update_prompt(
    prompt_id: str, body: PromptSnippetUpdate, session: AsyncSession = Depends(get_session)
) -> PromptSnippetOut:
    snippet = await session.get(PromptSnippet, prompt_id)
    if not snippet:
        raise HTTPException(404, "prompt not found")
    if body.body is not None:
        snippet.body = body.body.strip()
    if body.name is not None:
        snippet.name = _name_from(body.name, snippet.body)
    if body.negative is not None:
        snippet.negative = body.negative.strip() or None
    if body.tags is not None:
        snippet.tags = _clean_tags(body.tags)
    snippet.updated_at = datetime.now(UTC)
    await session.commit()
    return PromptSnippetOut.model_validate(snippet)


@router.post("/import", response_model=PromptSnippetImportOut)
async def import_prompts(
    body: PromptSnippetImportIn, session: AsyncSession = Depends(get_session)
) -> PromptSnippetImportOut:
    imported: list[PromptSnippet] = []
    for item in body.prompts:
        if not item.body.strip():
            continue
        snippet = PromptSnippet(
            name=_name_from(item.name, item.body),
            body=item.body.strip(),
            negative=(item.negative.strip() or None) if item.negative else None,
            tags=_clean_tags(item.tags),
        )
        session.add(snippet)
        imported.append(snippet)
    await session.commit()
    return PromptSnippetImportOut(
        imported=len(imported),
        prompts=[PromptSnippetOut.model_validate(s) for s in imported],
    )


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    snippet = await session.get(PromptSnippet, prompt_id)
    if not snippet:
        raise HTTPException(404, "prompt not found")
    await session.delete(snippet)
    await session.commit()
    return {"deleted": prompt_id}
