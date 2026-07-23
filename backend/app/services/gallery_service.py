"""Read/maintenance access to generated images."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import threading
from typing import Any
import uuid

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Image
from ..util import imaging

_KNOWN_FAMILIES = {"anima", "flux", "flux2", "qwen-image", "z-image", "sdxl", "upscaler", "unknown"}
_MEDIA_STATUS_KEY = "_hfabric_media_status"
_MISSING_ORIGINAL = "missing_original"
_LAST_RECONCILIATION: dict[str, int] = {}
_RECONCILIATION_LOCK = asyncio.Lock()
_MEDIA_SCAN_THREAD_LOCK = threading.Lock()
_THUMBNAIL_REPAIR_CONCURRENCY = 2

# JSON path into the persisted param snapshot. Older rows may not have dedicated
# columns for these values, so the service keeps fallbacks for compatibility.
_MODEL_EXPR = Image.params["model"].as_string()
_FAMILY_EXPR = Image.params["family"].as_string()


@dataclass(frozen=True)
class _RecoveredImage:
    path: Path
    params: dict[str, Any]
    modified_at: float
    thumb_path: Path | None


@dataclass(frozen=True)
class _RowMediaProbe:
    original_exists: bool
    stored_thumb_valid: bool
    canonical_thumb_exists: bool
    destination_allowed: bool
    canonical_thumb: Path


@dataclass(frozen=True)
class _MediaInventory:
    recovered: tuple[_RecoveredImage, ...]
    row_probes: dict[str, _RowMediaProbe]
    thumbnail_paths: frozenset[str]
    orphan_files: int
    orphan_sidecars: int


def _family_expr():
    return func.coalesce(Image.family, _FAMILY_EXPR, "unknown")


def _valid_media_expr():
    status = Image.params[_MEDIA_STATUS_KEY].as_string()
    return or_(status.is_(None), status != _MISSING_ORIGINAL)


def _apply_filters(stmt, *, q, model, family, size, lora, favorite, tag, date_from, date_to):
    stmt = stmt.where(_valid_media_expr())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Image.id.ilike(like),
            Image.job_id.ilike(like),
            cast(Image.seed, String).ilike(like),
            cast(Image.tags, String).ilike(like),
            cast(Image.params, String).ilike(like),
        ))
    if model:
        stmt = stmt.where(_MODEL_EXPR == model)
    if family:
        stmt = stmt.where(_family_expr() == family)
    if size == "square":
        stmt = stmt.where(Image.width == Image.height)
    elif size == "landscape":
        stmt = stmt.where(Image.width > Image.height)
    elif size == "portrait":
        stmt = stmt.where(Image.height > Image.width)
    elif size == "large":
        stmt = stmt.where(or_(Image.width >= 1024, Image.height >= 1024))
    elif size == "small":
        stmt = stmt.where(and_(Image.width < 1024, Image.height < 1024))
    if lora:
        lora_item = func.json_each(Image.params, "$.loras").table_valued("value").alias("lora_item")
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(lora_item)
                .where(func.json_extract(lora_item.c.value, "$.id") == lora.strip())
            )
        )
    if favorite is not None:
        stmt = stmt.where(Image.favorite.is_(favorite))
    if tag:
        tag_item = func.json_each(Image.tags).table_valued("value").alias("tag_item")
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(tag_item)
                .where(tag_item.c.value == tag.strip())
            )
        )
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
    family: str | None = None,
    size: str | None = None,
    lora: str | None = None,
    favorite: bool | None = None,
    tag: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Image]:
    stmt = _apply_filters(
        select(Image),
        q=q,
        model=model,
        family=family,
        size=size,
        lora=lora,
        favorite=favorite,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = stmt.order_by(Image.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def get_image(session: AsyncSession, image_id: str) -> Image | None:
    return await session.get(Image, image_id)


async def recover_output_history(session: AsyncSession, outputs_dir: Path) -> int:
    """Restore missing rows and reconcile stale originals/thumbnails.

    Every generated PNG has a same-name JSON sidecar. Queue clearing used to
    cascade-delete its Image rows while leaving those files intact, so the
    sidecar is the durable source for a one-time, lossless-enough rebuild.
    Existing metadata is retained even when its original file is gone.
    """
    report = await reconcile_media(session, outputs_dir)
    return report["recovered"]


async def reconcile_media(
    session: AsyncSession,
    outputs_dir: Path,
) -> dict[str, int]:
    """Classify and repair image history without silently deleting metadata."""
    async with _RECONCILIATION_LOCK:
        return await _reconcile_media_locked(session, outputs_dir)


async def _reconcile_media_locked(
    session: AsyncSession,
    outputs_dir: Path,
) -> dict[str, int]:
    report = {
        "recovered": 0,
        "missing_originals": 0,
        "broken_db_rows": 0,
        "missing_thumbnails": 0,
        "repaired_thumbnails": 0,
        "thumbnail_failures": 0,
        "orphan_sidecars": 0,
        "orphan_files": 0,
        "orphan_thumbnails": 0,
    }

    rows = list((await session.execute(select(Image))).scalars().all())
    inventory = await asyncio.to_thread(
        _scan_media_inventory_serialized,
        outputs_dir,
        tuple(row.path for row in rows),
        tuple((row.path, row.thumb_path) for row in rows),
    )
    report["orphan_files"] = inventory.orphan_files
    report["orphan_sidecars"] = inventory.orphan_sidecars

    for discovered in inventory.recovered:
        family = discovered.params.get("family")
        if family not in _KNOWN_FAMILIES:
            family = None
        image = Image(
            job_id=None,
            path=str(discovered.path),
            thumb_path=str(discovered.thumb_path) if discovered.thumb_path else None,
            seed=_metadata_int(discovered.params.get("seed")),
            width=_metadata_int(discovered.params.get("width"), positive=True),
            height=_metadata_int(discovered.params.get("height"), positive=True),
            family=family,
            favorite=bool(discovered.params.get("favorite", False)),
            tags=_tag_entries(discovered.params.get("tags")),
            params=discovered.params,
            created_at=datetime.fromtimestamp(discovered.modified_at, UTC),
        )
        session.add(image)
        rows.append(image)
        report["recovered"] += 1

    repairs: list[tuple[Image, Path, Path]] = []
    for row in rows:
        probe = inventory.row_probes.get(row.path)
        if probe is None:
            # A file may appear between the inventory walk and DB processing.
            probe = await asyncio.to_thread(
                _probe_media_row,
                row.path,
                row.thumb_path,
                outputs_dir,
            )
        repair = _apply_row_probe(row, probe, report)
        if repair is not None:
            repairs.append((row, *repair))

    for start in range(0, len(repairs), _THUMBNAIL_REPAIR_CONCURRENCY):
        batch = repairs[start:start + _THUMBNAIL_REPAIR_CONCURRENCY]
        outcomes = await asyncio.gather(*(
            asyncio.to_thread(_try_repair_thumbnail, original, destination)
            for _, original, destination in batch
        ))
        for (row, _, destination), repaired in zip(batch, outcomes):
            if repaired:
                row.thumb_path = str(destination)
                report["repaired_thumbnails"] += 1
            else:
                row.thumb_path = None
                report["thumbnail_failures"] += 1

    referenced_thumbs = await asyncio.to_thread(
        _normalized_paths,
        tuple(row.thumb_path for row in rows if row.thumb_path),
    )
    for thumbnail in inventory.thumbnail_paths:
        if thumbnail not in referenced_thumbs:
            report["orphan_thumbnails"] += 1
            report["orphan_files"] += 1

    _remember_reconciliation(report)
    return report


def last_reconciliation_report() -> dict[str, int]:
    return dict(_LAST_RECONCILIATION)


def _remember_reconciliation(report: dict[str, int]) -> None:
    _LAST_RECONCILIATION.clear()
    _LAST_RECONCILIATION.update(report)


def _scan_media_inventory(
    outputs_dir: Path,
    stored_row_paths: tuple[str, ...],
    row_paths: tuple[tuple[str, str | None], ...],
) -> _MediaInventory:
    """Walk and parse the output tree in one worker-thread pass."""
    stored_paths = {_normalized_path(Path(path)) for path in stored_row_paths}
    png_paths: list[Path] = []
    sidecar_paths: list[Path] = []
    thumbnail_paths: set[str] = set()

    if outputs_dir.exists():
        for dirpath, _, filenames in os.walk(outputs_dir):
            directory = Path(dirpath)
            for filename in filenames:
                path = directory / filename
                lower_name = filename.lower()
                if lower_name.endswith(".thumb.webp"):
                    thumbnail_paths.add(_normalized_path(path))
                elif path.suffix.lower() == ".png":
                    png_paths.append(path)
                elif path.suffix.lower() == ".json":
                    sidecar_paths.append(path)

    recovered: list[_RecoveredImage] = []
    orphan_files = 0
    for png_path in sorted(png_paths):
        if _normalized_path(png_path) in stored_paths:
            continue
        sidecar = png_path.with_suffix(".json")
        if not sidecar.is_file():
            orphan_files += 1
            continue
        try:
            params = json.loads(sidecar.read_text(encoding="utf-8"))
            modified_at = png_path.stat().st_mtime
        except (OSError, UnicodeError, json.JSONDecodeError):
            orphan_files += 1
            continue
        if not isinstance(params, dict):
            orphan_files += 1
            continue
        thumb_path = png_path.with_suffix(".thumb.webp")
        recovered.append(_RecoveredImage(
            path=png_path,
            params=params,
            modified_at=modified_at,
            thumb_path=thumb_path if thumb_path.is_file() else None,
        ))

    orphan_sidecars = sum(
        not any(sidecar.with_suffix(suffix).is_file() for suffix in (".png", ".mp4", ".wav"))
        for sidecar in sidecar_paths
    )
    probes = {
        path: _probe_media_row(path, thumb_path, outputs_dir)
        for path, thumb_path in (
            *row_paths,
            *((str(item.path), str(item.thumb_path) if item.thumb_path else None) for item in recovered),
        )
    }
    return _MediaInventory(
        recovered=tuple(recovered),
        row_probes=probes,
        thumbnail_paths=frozenset(thumbnail_paths),
        orphan_files=orphan_files,
        orphan_sidecars=orphan_sidecars,
    )


def _scan_media_inventory_serialized(
    outputs_dir: Path,
    stored_row_paths: tuple[str, ...],
    row_paths: tuple[tuple[str, str | None], ...],
) -> _MediaInventory:
    # A cancelled to_thread await does not terminate its worker. Keep the
    # actual recursive walk single-flight even across that cancellation edge.
    with _MEDIA_SCAN_THREAD_LOCK:
        return _scan_media_inventory(outputs_dir, stored_row_paths, row_paths)


def _probe_media_row(
    original_path: str,
    stored_thumb_path: str | None,
    outputs_dir: Path,
) -> _RowMediaProbe:
    original = Path(original_path)
    canonical_thumb = original.with_suffix(".thumb.webp")
    stored_thumb = Path(stored_thumb_path) if stored_thumb_path else None
    output_root = outputs_dir.resolve(strict=False)
    try:
        stored_thumb_valid = bool(
            stored_thumb is not None
            and stored_thumb.is_file()
            and stored_thumb.resolve(strict=False).is_relative_to(output_root)
        )
        destination_allowed = canonical_thumb.resolve(strict=False).is_relative_to(
            output_root
        )
    except OSError:
        stored_thumb_valid = False
        destination_allowed = False
    return _RowMediaProbe(
        original_exists=original.is_file(),
        stored_thumb_valid=stored_thumb_valid,
        canonical_thumb_exists=canonical_thumb.is_file(),
        destination_allowed=destination_allowed,
        canonical_thumb=canonical_thumb,
    )


def _apply_row_probe(
    row: Image,
    probe: _RowMediaProbe,
    report: dict[str, int],
) -> tuple[Path, Path] | None:
    original = Path(row.path)
    params = dict(row.params) if isinstance(row.params, dict) else {}
    if not probe.original_exists:
        params[_MEDIA_STATUS_KEY] = _MISSING_ORIGINAL
        row.params = params
        report["missing_originals"] += 1
        report["broken_db_rows"] += 1
        return None

    if params.pop(_MEDIA_STATUS_KEY, None) is not None:
        row.params = params

    if probe.stored_thumb_valid:
        return None
    if probe.canonical_thumb_exists:
        row.thumb_path = str(probe.canonical_thumb)
        return None

    report["missing_thumbnails"] += 1
    if not probe.destination_allowed:
        # A stale DB path must never turn startup repair into an arbitrary write.
        row.thumb_path = None
        report["thumbnail_failures"] += 1
        return None
    return original, probe.canonical_thumb


def _try_repair_thumbnail(original: Path, destination: Path) -> bool:
    try:
        _repair_thumbnail(original, destination)
    except (OSError, ValueError):
        return False
    return True


def _repair_thumbnail(original: Path, destination: Path) -> None:
    from PIL import Image as PILImage  # noqa: PLC0415

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with PILImage.open(original) as source:
            imaging.make_thumbnail(source.convert("RGB"), temporary)
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


async def get_images(session: AsyncSession, image_ids: list[str]) -> list[Image]:
    """Fetch images by id while preserving the caller's order and de-duping."""
    ids = list(dict.fromkeys(image_ids))
    if not ids:
        return []
    rows = list((await session.execute(select(Image).where(Image.id.in_(ids)))).scalars().all())
    by_id = {img.id: img for img in rows}
    available_paths = await asyncio.to_thread(
        _existing_paths,
        tuple(img.path for img in rows),
    )
    return [
        by_id[image_id]
        for image_id in ids
        if (
            image_id in by_id
            and by_id[image_id].path in available_paths
        )
    ]


async def update_image(
    session: AsyncSession,
    image_id: str,
    *,
    favorite: bool | None = None,
    tags: list[str] | None = None,
) -> Image | None:
    img = await session.get(Image, image_id)
    if img is None:
        return None
    if favorite is not None:
        img.favorite = favorite
    if tags is not None:
        img.tags = _normalize_tags(tags)
    return img


async def delete_image(session: AsyncSession, image_id: str) -> bool:
    """Remove an image row and its files (best-effort on the filesystem)."""
    img = await session.get(Image, image_id)
    if img is None:
        return False
    sidecar = str(Path(img.path).with_suffix(".json"))
    await asyncio.to_thread(
        _unlink_media_files,
        tuple(raw for raw in (img.path, img.thumb_path, sidecar) if raw),
    )
    await session.delete(img)
    return True


def _existing_paths(paths: tuple[str, ...]) -> set[str]:
    return {
        raw
        for raw in paths
        if Path(raw).is_file()
    }


def _normalized_paths(paths: tuple[str, ...]) -> set[str]:
    return {_normalized_path(Path(path)) for path in paths}


def _unlink_media_files(paths: tuple[str, ...]) -> None:
    for raw in paths:
        if not raw:
            continue
        try:
            Path(raw).unlink(missing_ok=True)
        except OSError:
            pass  # a locked/missing file should not block deleting the row


async def stats(session: AsyncSession) -> dict:
    """Generation counters for the History header: total, today, per-model."""
    valid = _valid_media_expr()
    total = (
        await session.execute(select(func.count(Image.id)).where(valid))
    ).scalar_one()

    start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = (await session.execute(
        select(func.count(Image.id)).where(valid, Image.created_at >= start_of_day)
    )).scalar_one()

    rows = (await session.execute(
        select(_MODEL_EXPR.label("model"), func.count(Image.id))
        .where(valid)
        .group_by(_MODEL_EXPR)
        .order_by(func.count(Image.id).desc())
    )).all()
    by_model = [{"model": name or "unknown", "count": count} for name, count in rows]

    family_expr = _family_expr()
    family_rows = (await session.execute(
        select(family_expr.label("family"), func.count(Image.id))
        .where(valid)
        .group_by(family_expr)
        .order_by(func.count(Image.id).desc())
    )).all()
    by_family = [{"family": name or "unknown", "count": count} for name, count in family_rows]

    lora_counts: Counter[tuple[str, str]] = Counter()
    for (params,) in (
        await session.execute(select(Image.params).where(valid))
    ).all():
        for item in _lora_entries(params):
            lora_counts[(item["id"], item["name"])] += 1
    by_lora = [
        {"id": lora_id, "name": name, "count": count}
        for (lora_id, name), count in lora_counts.most_common()
    ]

    tag_counts: Counter[str] = Counter()
    for (tags,) in (
        await session.execute(select(Image.tags).where(valid))
    ).all():
        for tag in _tag_entries(tags):
            tag_counts[tag] += 1
    by_tag = [{"tag": tag, "count": count} for tag, count in tag_counts.most_common()]

    return {
        "total": total,
        "today": today,
        "by_model": by_model,
        "by_family": by_family,
        "by_lora": by_lora,
        "by_tag": by_tag,
    }


def _lora_entries(params: Any) -> list[dict[str, str]]:
    if not isinstance(params, dict):
        return []
    raw = params.get("loras")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        lora_id = item.get("id")
        if not isinstance(lora_id, str) or not lora_id:
            continue
        name = item.get("name")
        out.append({"id": lora_id, "name": name if isinstance(name, str) and name else lora_id})
    return out


def _tag_entries(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    return _normalize_tags([tag for tag in tags if isinstance(tag, str)])


def _normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = " ".join(raw.strip().split())[:40]
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= 32:
            break
    return out


def _normalized_path(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


def _metadata_int(value: Any, *, positive: bool = False) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if positive and number <= 0:
        return None
    return number


def to_out_dict(img: Image) -> dict:
    thumb_available = bool(img.thumb_path and Path(img.thumb_path).is_file())
    return _to_out_dict(img, thumb_available=thumb_available)


async def to_out_dicts(images: list[Image]) -> list[dict[str, Any]]:
    thumb_paths = tuple(
        image.thumb_path
        for image in images
        if image.thumb_path
    )
    available = await asyncio.to_thread(_existing_paths, thumb_paths)
    return [
        _to_out_dict(
            image,
            thumb_available=bool(
                image.thumb_path and image.thumb_path in available
            ),
        )
        for image in images
    ]


def _to_out_dict(img: Image, *, thumb_available: bool) -> dict[str, Any]:
    return {
        "id": img.id,
        "job_id": img.job_id,
        "seed": img.seed,
        "width": img.width,
        "height": img.height,
        "family": img.family or (img.params or {}).get("family") or "unknown",
        "favorite": bool(img.favorite),
        "tags": _tag_entries(img.tags),
        "params": img.params,
        "created_at": img.created_at,
        "url": f"/api/images/{img.id}/file",
        "thumb_url": f"/api/images/{img.id}/thumb" if thumb_available else None,
    }
