"""Model discovery + live GPU/arbiter status."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..backends.registry import ModelRegistry
from ..config import settings
from ..core.arbiter import GpuArbiter
from ..core.enums import JobStatus, ModelFamily
from ..db.models import Job
from ..schemas import GpuStatusOut, LoraOut, ModelOut, ModelProfileOut
from ..services import (
    capability_profile,
    model_compatibility,
    model_download_service,
    model_storage,
    settings_overrides,
)
from ..services import model_profile_service as mps
from ..util import sysmon
from .contracts import (
    ERROR_RESPONSES,
    CapabilityProfileOut,
    DeletedCountOut,
    InstalledModelDeleteOut,
    InstalledModelsOut,
    ModelRescanOut,
    RuntimeSettingsOut,
    SettingsOverridesOut,
)
from .deps import get_arbiter, get_registry, get_session

router = APIRouter(
    prefix="/api",
    tags=["models"],
    responses=ERROR_RESPONSES,
)


def _related_registry_paths(
    registry: ModelRegistry,
    paths: set[Path],
) -> set[Path]:
    """Add descriptor companions (notably GGUF mmproj files) to busy paths."""
    protected = set(paths)
    image_backend_busy = False
    for descriptor in registry.descriptors():
        companions = {Path(descriptor.path)}
        if descriptor.mmproj_path is not None:
            companions.add(Path(descriptor.mmproj_path))
        if any(
            model_storage.paths_overlap(companion, busy)
            for companion in companions
            for busy in protected
        ):
            protected.update(companions)
            image_backend_busy = image_backend_busy or (
                descriptor.job_type.value == "image"
            )
    if image_backend_busy:
        # Diffusers may retain adapter weights in a warm backend after the job
        # row is done. Its public contract does not expose cache internals, so
        # conservatively protect all registered LoRAs until the GPU is freed.
        protected.update(Path(lora.path) for lora in registry.loras())
    return protected


async def _queued_job_paths(
    session: AsyncSession,
    registry: ModelRegistry,
) -> set[Path]:
    rows = (
        await session.execute(
            select(Job.model_id, Job.params).where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])
            )
        )
    ).all()
    descriptors = {item.id: item for item in registry.descriptors()}
    loras = {item.id: item for item in registry.loras()}
    protected: set[Path] = set()
    for model_id, raw_params in rows:
        descriptor = descriptors.get(model_id)
        if descriptor is not None:
            protected.add(Path(descriptor.path))
            if descriptor.mmproj_path is not None:
                protected.add(Path(descriptor.mmproj_path))

        params = raw_params if isinstance(raw_params, dict) else {}
        for item in params.get("loras") or []:
            if not isinstance(item, dict):
                continue
            lora = loras.get(item.get("id"))
            if lora is not None:
                protected.add(Path(lora.path))
        raw_lora_paths = params.get("_lora_paths")
        if isinstance(raw_lora_paths, dict):
            protected.update(
                Path(path)
                for path in raw_lora_paths.values()
                if isinstance(path, str) and path
            )
    return protected


def _lane_blocks_kind(arbiter: GpuArbiter, kind: str) -> bool:
    lane_kinds = {
        "voice": "voice",
        "tts": "tts",
        "transcribe": "transcribe",
    }
    expected = lane_kinds.get(kind)
    return bool(
        expected
        and any(
            lane.get("id") == expected
            for lane in arbiter.status().get("lanes", [])
        )
    )


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
    arbiter: GpuArbiter = Depends(get_arbiter),
) -> list[ModelOut]:
    current = arbiter.current
    out: list[ModelOut] = []
    profile = await asyncio.to_thread(capability_profile.get_capability_profile)
    for d in registry.descriptors():
        loaded = current is not None and current.descriptor.id == d.id
        existing = registry.peek_backend(d.id)
        warm = bool(existing and existing.warm)
        # raw fp8 FLUX (no quant backend) is the slow / high-mem path on 16 GB
        slow = d.family is ModelFamily.FLUX and d.quant is None
        prof = sysmon.get_learned_profile(d.id)
        estimated_vram = sysmon.estimate_vram_need_gb(d.family, d.size_bytes, d.quant, d.id)
        compat = model_compatibility.compatibility_for_model(
            d,
            profile=profile,
            estimated_vram_gb=estimated_vram,
        )
        out.append(
            ModelOut(
                id=d.id,
                name=d.name,
                family=d.family,
                job_type=d.job_type,
                size_bytes=d.size_bytes,
                loaded=loaded,
                warm=warm,
                quant=d.quant,
                multimodal=d.multimodal,
                mmproj_path=str(d.mmproj_path) if d.mmproj_path else None,
                mmproj_size_bytes=d.mmproj_size_bytes,
                estimated_vram_gb=estimated_vram,
                vram_measured=bool(prof and prof.get("vram_gb")),
                slow=slow,
                available=compat["available"],
                runtime_mode=compat["runtime_mode"],
                unavailable_reason=compat["unavailable_reason"],
                compatibility_warnings=compat["compatibility_warnings"],
                recommendation=compat.get("recommendation", "neutral"),
            )
        )
    return out


@router.post("/models/rescan", response_model=ModelRescanOut)
async def rescan_models(
    registry: ModelRegistry = Depends(get_registry),
) -> ModelRescanOut:
    """Re-read the model directories so files added after startup (dropped in by
    hand or pulled by the in-app download manager) appear without a restart.

    The disk walk runs off-loop and publishes one complete descriptor snapshot,
    so concurrent readers never observe a partially rebuilt registry."""
    await registry.scan_async()
    descriptors = registry.descriptors()
    return {
        "models": len(descriptors),
        "image_models": sum(1 for d in descriptors if d.job_type.value == "image"),
        "video_models": sum(1 for d in descriptors if d.job_type.value == "video"),
        "llm_models": sum(1 for d in descriptors if d.job_type.value == "llm"),
        "loras": len(registry.loras()),
    }


@router.get("/models/installed", response_model=InstalledModelsOut)
async def list_installed_models(
    arbiter: GpuArbiter = Depends(get_arbiter),
    registry: ModelRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_session),
) -> InstalledModelsOut:
    """Everything installed on disk across all model kinds, with sizes + in-use flags,
    for the Model Manager."""
    busy = _related_registry_paths(registry, arbiter.busy_paths())
    busy.update(await _queued_job_paths(session, registry))
    items, disk = await asyncio.gather(
        model_storage.installed_async(in_use=busy),
        asyncio.to_thread(model_download_service.disk_status),
    )
    return {
        "items": items,
        "kinds": model_storage.KIND_LABELS,
        "total_used_bytes": sum(item["size_bytes"] for item in items),
        "disk": disk,
    }


@router.delete("/models/installed", response_model=InstalledModelDeleteOut)
async def delete_installed_model(
    kind: str = Query(..., description="model kind (image, llm, lora, tts, …)"),
    path: str = Query(..., description="path of the file or repo folder within the kind folder"),
    registry: ModelRegistry = Depends(get_registry),
    arbiter: GpuArbiter = Depends(get_arbiter),
    session: AsyncSession = Depends(get_session),
) -> InstalledModelDeleteOut:
    """Delete one installed model unit to reclaim disk, then rescan."""
    if model_download_service.is_downloading():
        raise HTTPException(
            409,
            "Model deletion is blocked while a download is writing into the model folders.",
        )
    if _lane_blocks_kind(arbiter, kind):
        raise HTTPException(
            409,
            f"The active {kind} session is using this model folder. Stop it before deleting.",
        )

    job_paths = await _queued_job_paths(session, registry)

    def busy_paths() -> set[Path]:
        return _related_registry_paths(
            registry,
            {*arbiter.busy_paths(), *job_paths},
        )

    try:
        result = await model_storage.delete_async(
            kind,
            path,
            in_use=busy_paths,
        )
        try:
            await registry.scan_async()
        except Exception as exc:  # noqa: BLE001 - deletion already committed on disk
            raise model_storage.ModelInventoryError(
                f"'{path}' was deleted, but the model inventory refresh failed; "
                f"run Rescan Models: {exc}"
            ) from exc
    except model_storage.ModelInUseError as exc:
        raise HTTPException(
            409,
            "That model, one of its files, or a companion is loaded, warm, "
            "queued, or currently running. Free/cancel it before deleting.",
        ) from exc
    except model_storage.ModelInventoryError as exc:
        raise HTTPException(500, str(exc)) from exc
    except model_storage.ModelDeleteError as exc:
        raise HTTPException(409, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "model not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    disk = await asyncio.to_thread(model_download_service.disk_status)
    return {
        **result,
        "disk": disk,
    }


@router.get("/loras", response_model=list[LoraOut])
async def list_loras(
    family: ModelFamily | None = None,
    registry: ModelRegistry = Depends(get_registry),
) -> list[LoraOut]:
    return [
        LoraOut(id=l.id, name=l.name, family=l.family, size_bytes=l.size_bytes)
        for l in registry.loras(family)
    ]


@router.get("/models/profiles", response_model=list[ModelProfileOut])
async def list_model_profiles(
    session: AsyncSession = Depends(get_session),
    registry: ModelRegistry = Depends(get_registry),
) -> list[ModelProfileOut]:
    by_id = {d.id: d for d in registry.descriptors()}
    rows = await mps.load_all(session)
    return [
        ModelProfileOut(
            model_id=row.model_id,
            model=by_id.get(row.model_id).name if row.model_id in by_id else row.model_id,
            family=row.family,
            quant=row.quant,
            ram_gb=row.ram_gb,
            vram_gb=row.vram_gb,
            samples=row.samples,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.delete("/models/profiles", response_model=DeletedCountOut)
async def reset_all_model_profiles(
    session: AsyncSession = Depends(get_session),
) -> DeletedCountOut:
    deleted = await mps.delete_all(session)
    sysmon.clear_learned_profiles()
    return {"deleted": deleted}


@router.delete(
    "/models/profiles/{model_id}",
    response_model=DeletedCountOut,
)
async def reset_model_profile(
    model_id: str,
    all_profiles: bool = Query(False, alias="all"),
    session: AsyncSession = Depends(get_session),
) -> DeletedCountOut:
    if all_profiles:
        deleted = await mps.delete_all(session)
        sysmon.clear_learned_profiles()
        return {"deleted": deleted}
    deleted = await mps.delete(session, model_id)
    sysmon.delete_learned_profile(model_id)
    return {"deleted": deleted}


def _filesystem_model_counts() -> dict[str, int]:
    return {
        "tts_models": (
            sum(1 for _ in settings.tts_models_dir.glob("*.gguf"))
            if settings.tts_models_dir.exists()
            else 0
        ),
        "transcription_models": (
            sum(
                1
                for path in settings.transcription_models_dir.iterdir()
                if not path.name.startswith(".")
            )
            if settings.transcription_models_dir.exists()
            else 0
        ),
        "embed_models": (
            sum(1 for _ in settings.embed_models_dir.glob("*.gguf"))
            if settings.embed_models_dir.exists()
            else 0
        ),
        "vision_models": (
            sum(1 for _ in settings.vision_models_dir.glob("*.gguf"))
            if settings.vision_models_dir.exists()
            else 0
        ),
    }


@router.get("/settings", response_model=RuntimeSettingsOut)
async def runtime_settings(
    registry: ModelRegistry = Depends(get_registry),
    arbiter: GpuArbiter = Depends(get_arbiter),
) -> RuntimeSettingsOut:
    descriptors = registry.descriptors()
    mem, capability, filesystem_counts = await asyncio.gather(
        asyncio.to_thread(sysmon.snapshot),
        asyncio.to_thread(capability_profile.get_capability_profile),
        asyncio.to_thread(_filesystem_model_counts),
    )
    return {
        "stub_mode": settings.stub_mode,
        "paths": {
            "image_models_dir": str(settings.image_models_dir),
            "video_models_dir": str(settings.video_models_dir),
            "lora_models_dir": str(settings.lora_models_dir),
            "llm_models_dir": str(settings.llm_models_dir),
            "tts_models_dir": str(settings.tts_models_dir),
            "transcription_models_dir": str(settings.transcription_models_dir),
            "embed_models_dir": str(settings.embed_models_dir),
            "vision_models_dir": str(settings.vision_models_dir),
            "outputs_dir": str(settings.outputs_dir),
            "db_path": str(settings.db_path),
            "llama_server_bin": str(settings.llama_server_bin),
            "llama_tts_bin": str(settings.llama_tts_bin),
        },
        "memory": {
            "min_free_ram_gb": settings.min_free_ram_gb,
            "keep_warm_models": settings.keep_warm_models,
            "keep_warm_max_models": settings.keep_warm_max_models,
            "keep_warm_min_available_ram_gb": settings.keep_warm_min_available_ram_gb,
            "mem_poll_seconds": settings.mem_poll_seconds,
        },
        "generation_defaults": {
            "default_steps": settings.default_steps,
            "default_guidance": settings.default_guidance,
            "default_width": settings.default_width,
            "default_height": settings.default_height,
            "video_width": settings.video_default_width,
            "video_height": settings.video_default_height,
            "video_frames": settings.video_default_frames,
            "video_fps": settings.video_default_fps,
            "video_steps": settings.video_default_steps,
            "video_guidance": settings.video_default_guidance,
            "keep_warm_models": settings.keep_warm_models,
            "keep_warm_max_models": settings.keep_warm_max_models,
            "anima_steps": settings.anima_default_steps,
            "anima_guidance": settings.anima_default_guidance,
            "anima_width": settings.anima_default_width,
            "anima_height": settings.anima_default_height,
        },
        "acceleration": {
            "attention_backend": settings.attention_backend,
            "attention_allow_tf32": settings.attention_allow_tf32,
            "attention_matmul_precision": settings.attention_matmul_precision,
            "torch_compile": settings.torch_compile,
            "torch_compile_mode": settings.torch_compile_mode,
            "flux_step_cache": settings.flux_step_cache,
            "qwen_image_quant": settings.qwen_image_quant,
            "qwen_image_offload": settings.qwen_image_offload,
            "qwen_image_default_steps": settings.qwen_image_default_steps,
            "qwen_image_default_guidance": settings.qwen_image_default_guidance,
            "qwen_image_default_width": settings.qwen_image_default_width,
            "qwen_image_default_height": settings.qwen_image_default_height,
            "z_image_quant": settings.z_image_quant,
            "z_image_offload": settings.z_image_offload,
            "z_image_default_steps": settings.z_image_default_steps,
            "z_image_default_guidance": settings.z_image_default_guidance,
            "z_image_base_default_steps": settings.z_image_base_default_steps,
            "z_image_base_default_guidance": settings.z_image_base_default_guidance,
            "z_image_default_width": settings.z_image_default_width,
            "z_image_default_height": settings.z_image_default_height,
            "sdxl_turbo_lora": settings.sdxl_turbo_lora,
            "image_cleanup_after_each_job": settings.image_cleanup_after_each_job,
            "image_lora_cache_max": settings.image_lora_cache_max,
            "image_recycle_cuda_growth_gb": settings.image_recycle_cuda_growth_gb,
            "image_recycle_min_jobs": settings.image_recycle_min_jobs,
            "tts_gpu_layers": settings.tts_gpu_layers,
            "tts_timeout_seconds": settings.tts_timeout_seconds,
            "transcription_device": settings.transcription_device,
            "transcription_compute_type": settings.transcription_compute_type,
            "transcription_timeout_seconds": settings.transcription_timeout_seconds,
            "embed_gpu_layers": settings.embed_gpu_layers,
            "embed_timeout_seconds": settings.embed_timeout_seconds,
            "rag_chunk_chars": settings.rag_chunk_chars,
            "rag_chunk_overlap": settings.rag_chunk_overlap,
        },
        "counts": {
            "models": len(descriptors),
            "image_models": sum(1 for d in descriptors if d.job_type.value == "image"),
            "llm_models": sum(1 for d in descriptors if d.job_type.value == "llm"),
            "multimodal_llm_models": sum(
                1 for d in descriptors if d.job_type.value == "llm" and d.multimodal
            ),
            "loras": len(registry.loras()),
            **filesystem_counts,
            "learned_profiles": sysmon.learned_count(),
        },
        "gpu": arbiter.status(),
        "mem": mem,
        "capability": capability,
    }


@router.get("/capabilities", response_model=CapabilityProfileOut)
async def runtime_capabilities(
    refresh: bool = Query(False),
) -> CapabilityProfileOut:
    return await asyncio.to_thread(
        capability_profile.get_capability_profile,
        refresh=refresh,
    )


@router.get("/settings/overrides", response_model=SettingsOverridesOut)
async def get_settings_overrides() -> SettingsOverridesOut:
    return await asyncio.to_thread(settings_overrides.payload)


@router.put("/settings/overrides", response_model=SettingsOverridesOut)
async def put_settings_overrides(
    body: dict[str, Any],
) -> SettingsOverridesOut:
    unknown = sorted(set(body) - settings_overrides.WRITABLE_KEYS)
    if unknown:
        raise HTTPException(422, f"settings are env-only or unknown: {', '.join(unknown)}")
    try:
        return await asyncio.to_thread(settings_overrides.save, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/gpu", response_model=GpuStatusOut)
async def gpu_status(arbiter: GpuArbiter = Depends(get_arbiter)) -> GpuStatusOut:
    return GpuStatusOut(**arbiter.status())


@router.post("/gpu/free", response_model=GpuStatusOut)
async def gpu_free(arbiter: GpuArbiter = Depends(get_arbiter)) -> GpuStatusOut:
    await arbiter.free_all()
    return GpuStatusOut(**arbiter.status())
