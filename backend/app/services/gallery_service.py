"""Read/maintenance access to generated images."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Image

# JSON path into the persisted param snapshot. The diffusers backend stores the
# model *name* under params["model"] (see image_diffusers._persist).
_MODEL_EXPR = Image.params["model"].as_string()


def _apply_filters(stmt, *, q, model, date_from, date_to):
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Image.id.ilike(like),
            Image.job_id.ilike(like),
            cast(Image.seed, String).ilike(like),
            cast(Image.params, String).ilike(like),
        ))
    if model:
        stmt = stmt.where(_MODEL_EXPR == model)
    if date_from is not None:
        stmt = stmt.where(Image.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Image.created_at <= date_to)
    return stmt


async def list_images(
    session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
    q: str | None = None,
    model: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Image]:
    stmt = _apply_filters(select(Image), q=q, model=model, date_from=date_from, date_to=date_to)
    stmt = stmt.order_by(Image.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def get_image(session: AsyncSession, image_id: str) -> Image | None:
    return await session.get(Image, image_id)


async def delete_image(session: AsyncSession, image_id: str) -> bool:
    """Remove an image row and its files (best-effort on the filesystem)."""
    img = await session.get(Image, image_id)
    if img is None:
        return False
    for raw in (img.path, img.thumb_path):
        if not raw:
            continue
        try:
            Path(raw).unlink(missing_ok=True)
        except OSError:
            pass  # a locked/missing file should not block deleting the row
    await session.delete(img)
    return True


async def stats(session: AsyncSession) -> dict:
    """Generation counters for the History header: total, today, per-model."""
    total = (await session.execute(select(func.count(Image.id)))).scalar_one()

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = (await session.execute(
        select(func.count(Image.id)).where(Image.created_at >= start_of_day)
    )).scalar_one()

    rows = (await session.execute(
        select(_MODEL_EXPR.label("model"), func.count(Image.id))
        .group_by(_MODEL_EXPR)
        .order_by(func.count(Image.id).desc())
    )).all()
    by_model = [{"model": name or "unknown", "count": count} for name, count in rows]

    return {"total": total, "today": today, "by_model": by_model}


def to_out_dict(img: Image) -> dict:
    return {
        "id": img.id,
        "job_id": img.job_id,
        "seed": img.seed,
        "width": img.width,
        "height": img.height,
        "params": img.params,
        "created_at": img.created_at,
        "url": f"/api/images/{img.id}/file",
        "thumb_url": f"/api/images/{img.id}/thumb" if img.thumb_path else None,
    }
