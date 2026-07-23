"""Gallery: list image metadata and serve the files/thumbnails."""

from __future__ import annotations

import asyncio
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4
import warnings
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ..config import settings
from ..schemas import ImageExportIn, ImageOut, ImageUpdateIn
from ..services import gallery_service
from ..util import security
from ..util import uploads as uploads_util
from ..util.async_files import build_temporary_artifact
from .contracts import (
    ERROR_RESPONSES,
    DeleteOut,
    ImageReconcileOut,
    ImageStatsOut,
    ImageUploadOut,
    MaskUploadOut,
    RevealOut,
    binary_response,
)
from .deps import get_session

router = APIRouter(
    prefix="/api/images",
    tags=["gallery"],
    responses=ERROR_RESPONSES,
)

_IMAGE_FORMAT_MIMES = {
    "PNG": {"image/png"},
    "JPEG": {"image/jpeg", "image/jpg"},
    "WEBP": {"image/webp"},
}


class _UnsupportedUploadImage(ValueError):
    pass


class _UnsafeUploadImage(ValueError):
    pass


class _InvalidUploadImage(ValueError):
    pass


@router.get("", response_model=list[ImageOut])
async def list_images(
    limit: int = Query(100, le=500),
    offset: int = 0,
    q: str | None = Query(None, max_length=200),
    model: str | None = Query(None, max_length=200),
    family: str | None = Query(
        None,
        pattern="^(anima|flux|flux2|flux-kontext|qwen-image|qwen-image-edit|z-image|sdxl|upscaler|unknown)$",
    ),
    size: str | None = Query(None, pattern="^(square|landscape|portrait|large|small)$"),
    lora: str | None = Query(None, max_length=200),
    favorite: bool | None = None,
    tag: str | None = Query(None, max_length=40),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ImageOut]:
    images = await gallery_service.list_images(
        session, limit=limit, offset=offset, q=q,
        model=model, family=family, size=size, lora=lora, favorite=favorite, tag=tag,
        date_from=date_from, date_to=date_to,
    )
    payloads = await gallery_service.to_out_dicts(images)
    return [ImageOut.model_validate(payload) for payload in payloads]


@router.get("/stats", response_model=ImageStatsOut)
async def image_stats(
    session: AsyncSession = Depends(get_session),
) -> ImageStatsOut:
    """Generation counters for the History header (total / today / per-model)."""
    return await gallery_service.stats(session)


@router.post("/reconcile", response_model=ImageReconcileOut)
async def reconcile_images(
    session: AsyncSession = Depends(get_session),
) -> ImageReconcileOut:
    """Run the same non-destructive media doctor used during startup."""
    return await gallery_service.reconcile_media(session, settings.outputs_dir)


async def _read_upload_bytes(file: UploadFile) -> bytes:
    return await uploads_util.read_limited_upload(
        file,
        max_bytes=settings.image_upload_max_mb * 1024 * 1024,
        label="image",
    )


def _detected_image_format(image, declared_mime: str | None) -> str:
    image_format = str(image.format or "").upper()
    allowed_mimes = _IMAGE_FORMAT_MIMES.get(image_format)
    if allowed_mimes is None:
        raise _UnsupportedUploadImage(
            f"unsupported image format: {image_format or 'unknown'}"
        )
    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    if mime and mime != "application/octet-stream" and mime not in allowed_mimes:
        raise _UnsupportedUploadImage(
            f"declared MIME {mime!r} does not match detected {image_format}"
        )
    return image_format


def _decode_and_store_upload(
    raw: bytes,
    destination: Path,
    *,
    declared_mime: str | None,
    mask: bool,
) -> tuple[int, int]:
    from PIL import Image as PILImage  # noqa: PLC0415
    from PIL import ImageChops, ImageOps  # noqa: PLC0415

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            try:
                with PILImage.open(io.BytesIO(raw)) as source:
                    _detected_image_format(source, declared_mime)
                    source.load()
                    normalized = ImageOps.exif_transpose(source)
                    if mask:
                        rgba = normalized.convert("RGBA")
                        grey = rgba.convert("L")
                        alpha = rgba.getchannel("A")
                        if alpha.getextrema() != (255, 255):
                            grey = ImageChops.multiply(grey, alpha)
                        output = grey
                    else:
                        output = normalized.convert("RGB")
            except (PILImage.DecompressionBombError, PILImage.DecompressionBombWarning) as exc:
                raise _UnsafeUploadImage(
                    "image dimensions exceed the safe decode limit"
                ) from exc
            except _UnsupportedUploadImage:
                raise
            except (OSError, SyntaxError, ValueError) as exc:
                raise _InvalidUploadImage("unsupported or corrupt image") from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        output.save(temporary, format="PNG")
        temporary.replace(destination)
        return output.width, output.height
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@router.post("/upload", response_model=ImageUploadOut)
async def upload_init_image(
    file: UploadFile = File(...),
) -> ImageUploadOut:
    """Accept a source image for img2img/inpainting. We re-encode to PNG via PIL
    so the stored file is normalized, and return an opaque token the composer
    puts in a job's ``init_image`` param."""
    raw = await _read_upload_bytes(file)
    token = uuid4().hex
    destination = uploads_util.uploads_dir() / f"{token}.png"
    try:
        width, height = await asyncio.to_thread(
            _decode_and_store_upload,
            raw,
            destination,
            declared_mime=file.content_type,
            mask=False,
        )
    except _UnsafeUploadImage as exc:
        raise HTTPException(413, str(exc)) from exc
    except _UnsupportedUploadImage as exc:
        raise HTTPException(415, str(exc)) from exc
    except _InvalidUploadImage as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "init_image": token,
        "url": f"/api/images/upload/{token}",
        "width": width,
        "height": height,
    }


@router.post("/upload-mask", response_model=MaskUploadOut)
async def upload_mask_image(
    file: UploadFile = File(...),
) -> MaskUploadOut:
    """Accept an inpainting mask. White/bright pixels mark the repaint region;
    grey pixels are preserved for feathered edges."""
    raw = await _read_upload_bytes(file)
    token = uuid4().hex
    destination = uploads_util.uploads_dir() / f"{token}.png"
    try:
        width, height = await asyncio.to_thread(
            _decode_and_store_upload,
            raw,
            destination,
            declared_mime=file.content_type,
            mask=True,
        )
    except _UnsafeUploadImage as exc:
        raise HTTPException(413, str(exc)) from exc
    except _UnsupportedUploadImage as exc:
        raise HTTPException(415, str(exc)) from exc
    except _InvalidUploadImage as exc:
        raise HTTPException(400, "unsupported or corrupt mask image") from exc
    return {
        "mask_image": token,
        "url": f"/api/images/upload/{token}",
        "width": width,
        "height": height,
    }


@router.get(
    "/upload/{token}",
    response_class=FileResponse,
    responses=binary_response("image/png", "Uploaded source image"),
)
async def upload_file(token: str) -> FileResponse:
    path = uploads_util.resolve_upload(token)
    if path is None or not path.exists():
        raise HTTPException(404, "upload not found")
    return FileResponse(path, media_type="image/png")


def _write_image_export_archive(
    zip_path: Path,
    records: tuple[tuple[str, Path, dict], ...],
) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for image_id, source, metadata in records:
            zf.writestr(
                f"metadata/{image_id}.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )
            if source.is_file():
                zf.write(
                    source,
                    f"images/{image_id}{source.suffix or '.png'}",
                )


@router.post(
    "/export",
    response_class=FileResponse,
    responses=binary_response("application/zip", "Selected images archive"),
)
async def export_images(body: ImageExportIn, session: AsyncSession = Depends(get_session)) -> FileResponse:
    images = await gallery_service.get_images(session, body.image_ids)
    if not images:
        raise HTTPException(404, "no selected images found")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        zip_path = Path(tmp.name)

    payloads = await gallery_service.to_out_dicts(images)
    records = tuple(
        (
            image.id,
            Path(image.path),
            ImageOut.model_validate(payload).model_dump(mode="json"),
        )
        for image, payload in zip(images, payloads)
    )
    await build_temporary_artifact(
        zip_path,
        _write_image_export_archive,
        records,
    )

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"hfabric-images-{len(images)}.zip",
        background=BackgroundTask(lambda: zip_path.unlink(missing_ok=True)),
    )


@router.patch("/{image_id}", response_model=ImageOut)
async def update_image(image_id: str, body: ImageUpdateIn, session: AsyncSession = Depends(get_session)) -> ImageOut:
    img = await gallery_service.update_image(session, image_id, favorite=body.favorite, tags=body.tags)
    if img is None:
        raise HTTPException(404, "image not found")
    payload = (await gallery_service.to_out_dicts([img]))[0]
    return ImageOut.model_validate(payload)


@router.delete("/{image_id}", response_model=DeleteOut)
async def delete_image(
    image_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeleteOut:
    if not await gallery_service.delete_image(session, image_id):
        raise HTTPException(404, "image not found")
    return {"deleted": image_id}


@router.get(
    "/{image_id}/file",
    response_class=FileResponse,
    responses=binary_response("image/png", "Generated image"),
)
async def image_file(image_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    img = await gallery_service.get_image(session, image_id)
    if not img or not Path(img.path).exists():
        raise HTTPException(404, "image not found")
    return FileResponse(img.path, media_type="image/png")


@router.get("/{image_id}/metadata", response_model=ImageOut)
async def image_metadata(image_id: str, session: AsyncSession = Depends(get_session)) -> JSONResponse:
    img = await gallery_service.get_image(session, image_id)
    if not img:
        raise HTTPException(404, "image not found")
    image_payload = (await gallery_service.to_out_dicts([img]))[0]
    payload = ImageOut.model_validate(image_payload).model_dump(mode="json")
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="{image_id}.metadata.json"'},
    )


@router.post("/{image_id}/reveal", response_model=RevealOut)
async def reveal_image(
    image_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RevealOut:
    """Open the OS file manager with the image file selected. Local-app
    convenience — the browser cannot reach the desktop file manager itself."""
    client_host = request.client.host if request.client else None
    if not security.is_loopback_host(client_host):
        raise HTTPException(403, "file reveal is only allowed from loopback clients")
    img = await gallery_service.get_image(session, image_id)
    if not img or not Path(img.path).exists():
        raise HTTPException(404, "image not found")
    path = Path(img.path)
    try:
        if sys.platform == "win32":
            await asyncio.to_thread(
                subprocess.Popen,
                ["explorer", f"/select,{path}"],
            )
        elif sys.platform == "darwin":
            await asyncio.to_thread(
                subprocess.Popen,
                ["open", "-R", str(path)],
            )
        else:
            await asyncio.to_thread(
                subprocess.Popen,
                ["xdg-open", str(path.parent)],
            )
    except OSError as exc:  # pragma: no cover - desktop-only path
        raise HTTPException(500, f"could not open file manager: {exc}")
    return {"revealed": str(path)}


@router.get(
    "/{image_id}/thumb",
    response_class=FileResponse,
    responses=binary_response("image/webp", "Generated image thumbnail"),
)
async def image_thumb(image_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    img = await gallery_service.get_image(session, image_id)
    if not img or not img.thumb_path or not Path(img.thumb_path).exists():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(img.thumb_path, media_type="image/webp")
