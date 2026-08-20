"""Image saving helpers shared by the stub and the real diffusers backend.

Reproducibility is a first-class goal: every saved PNG embeds its full
generation parameters in a ``parameters`` text chunk *and* gets a JSON sidecar,
so any image can be traced back to its exact prompt/seed/settings.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any
import uuid

from PIL import Image, ImageDraw, PngImagePlugin


def day_dir(outputs_dir: Path) -> Path:
    d = outputs_dir / datetime.now(UTC).strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_png(img: Image.Image, path: Path, metadata: dict[str, Any]) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", json.dumps(metadata, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    sidecar = path.with_suffix(".json")
    png_tmp = _temporary_sibling(path)
    json_tmp = _temporary_sibling(sidecar)
    try:
        img.save(png_tmp, format="PNG", pnginfo=info)
        json_tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(png_tmp, path)
        os.replace(json_tmp, sidecar)
    except BaseException:
        path.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise
    finally:
        png_tmp.unlink(missing_ok=True)
        json_tmp.unlink(missing_ok=True)


def make_thumbnail(img: Image.Image, path: Path, size: int = 384) -> None:
    thumb = img.copy()
    thumb.thumbnail((size, size))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_sibling(path)
    try:
        thumb.save(temporary, format="WEBP", quality=80)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_image_records(records: list[dict[str, Any]], outputs_dir: Path) -> None:
    """Best-effort cleanup for image bundles that were never committed to DB."""
    root = outputs_dir.resolve()
    for record in records:
        for key in ("path", "thumb_path"):
            raw = record.get(key)
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                continue
            path.unlink(missing_ok=True)
            if key == "path":
                path.with_suffix(".json").unlink(missing_ok=True)


def _temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def make_placeholder(width: int, height: int, lines: list[str]) -> Image.Image:
    """A labelled gradient stand-in used in STUB mode so the gallery/queue
    pipeline can be exercised end-to-end without a real diffusion model."""
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(0, width, 4):  # step 4 px: fast enough for a stub
            r = int(40 + 60 * x / max(width, 1))
            g = int(30 + 90 * y / max(height, 1))
            b = int(80 + 50 * (x + y) / max(width + height, 1))
            for dx in range(4):
                if x + dx < width:
                    px[x + dx, y] = (r, g, b)
    draw = ImageDraw.Draw(img)
    ty = 16
    for line in lines:
        draw.text((16, ty), line[:80], fill=(235, 235, 245))
        ty += 18
    return img
