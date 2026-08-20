"""Saved parameter presets (flexible param sets the user can reuse)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Preset
from ..schemas import PresetCreate, PresetImportIn, PresetImportOut, PresetOut
from .contracts import ERROR_RESPONSES, DeleteOut
from .deps import get_session

router = APIRouter(
    prefix="/api/presets",
    tags=["presets"],
    responses=ERROR_RESPONSES,
)


def _unique_name(name: str, existing: set[str]) -> str:
    base = (name.strip() or "Imported preset")[:128]
    if base not in existing:
        existing.add(base)
        return base

    stem = base[:117].rstrip()
    i = 2
    while True:
        candidate = f"{stem} ({i})"[:128]
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        i += 1


@router.get("", response_model=list[PresetOut])
async def list_presets(session: AsyncSession = Depends(get_session)) -> list[PresetOut]:
    rows = (await session.execute(select(Preset).order_by(Preset.created_at.desc()))).scalars().all()
    return [PresetOut.model_validate(p) for p in rows]


@router.post("", response_model=PresetOut)
async def create_preset(
    body: PresetCreate, session: AsyncSession = Depends(get_session)
) -> PresetOut:
    preset = Preset(name=body.name, type=body.type, params=body.params)
    session.add(preset)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, f"preset name already exists for {body.type}: {body.name}")
    return PresetOut.model_validate(preset)


@router.post("/import", response_model=PresetImportOut)
async def import_presets(
    body: PresetImportIn, session: AsyncSession = Depends(get_session)
) -> PresetImportOut:
    rows = (await session.execute(select(Preset.type, Preset.name))).all()
    existing_by_type: dict[str, set[str]] = {}
    for preset_type, name in rows:
        existing_by_type.setdefault(preset_type, set()).add(name)
    imported: list[Preset] = []
    skipped = 0

    for item in body.presets:
        requested_name = item.name.strip() or "Imported preset"
        existing = existing_by_type.setdefault(item.type, set())
        if requested_name in existing and body.on_conflict == "skip":
            skipped += 1
            continue
        name = _unique_name(requested_name, existing)
        preset = Preset(name=name, type=item.type, params=item.params)
        session.add(preset)
        imported.append(preset)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "preset import conflicted with a concurrent change")
    return PresetImportOut(
        imported=len(imported),
        skipped=skipped,
        presets=[PresetOut.model_validate(p) for p in imported],
    )


@router.delete("/{preset_id}", response_model=DeleteOut)
async def delete_preset(
    preset_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeleteOut:
    preset = await session.get(Preset, preset_id)
    if not preset:
        raise HTTPException(404, "preset not found")
    await session.delete(preset)
    await session.commit()
    return {"deleted": preset_id}
