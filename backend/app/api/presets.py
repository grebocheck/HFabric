"""Saved parameter presets (flexible param sets the user can reuse)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Preset
from ..schemas import PresetCreate, PresetOut
from .deps import get_session

router = APIRouter(prefix="/api/presets", tags=["presets"])


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
    except Exception:
        await session.rollback()
        raise HTTPException(409, f"preset name already exists: {body.name}")
    return PresetOut.model_validate(preset)


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    preset = await session.get(Preset, preset_id)
    if not preset:
        raise HTTPException(404, "preset not found")
    await session.delete(preset)
    await session.commit()
    return {"deleted": preset_id}
