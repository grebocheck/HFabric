from __future__ import annotations

import asyncio
from typing import Any

from ...config import settings
from ...core.enums import ModelFamily
from ...util import sysmon


class DiffusersMemoryMixin:
    def _memory_snapshot(self, torch) -> dict[str, Any]:
        snap = sysmon.snapshot()
        runtime = self._runtime()
        process_memory = runtime.process_memory(torch)
        if process_memory:
            snap["accelerator_process"] = process_memory
            if runtime.memory_key == "cuda_process":
                snap["cuda_process"] = process_memory
        return snap

    async def unload(self) -> None:
        if not self._loaded and not self._warm:
            return
        try:
            if not settings.stub_mode and self._pipe is not None:
                await asyncio.to_thread(self._free_pipeline_sync)
        finally:
            self._clear_resident_state(reset_generation=True)

    async def park(self) -> bool:
        if not self._loaded:
            return False
        if settings.stub_mode:
            await asyncio.sleep(0.1)
            self._loaded = False
            self._warm = True
            return True
        if self._pipe is None:
            return False
        await asyncio.to_thread(self._park_pipeline_sync)
        self._loaded = False
        self._warm = True
        return True

    def _park_pipeline_sync(self) -> None:
        import gc  # noqa: PLC0415

        import torch  # noqa: PLC0415

        if hasattr(self._pipe, "maybe_free_model_hooks"):
            self._pipe.maybe_free_model_hooks()
        if self.descriptor.family is ModelFamily.SDXL and hasattr(self._pipe, "to"):
            self._pipe.to("cpu")
        gc.collect()
        self._runtime().empty_cache(torch)

    def _resume_pipeline_sync(self) -> None:
        import torch  # noqa: PLC0415

        report: dict[str, Any] = {
            "keep_warm": {"resumed": True},
            "memory": {"start": self._memory_snapshot(torch)},
        }
        if self.descriptor.family is ModelFamily.SDXL and hasattr(self._pipe, "to"):
            self._runtime().move(self._pipe)
        elif hasattr(self._pipe, "enable_model_cpu_offload"):
            self._runtime().enable_model_cpu_offload(self._pipe)
        report["memory"]["end"] = self._memory_snapshot(torch)
        self._remember_accelerator_baseline(torch)
        self._load_report = report

    def _free_pipeline_sync(self) -> None:
        import gc  # noqa: PLC0415

        import torch  # noqa: PLC0415

        del self._pipe
        self._pipe = None
        self._img2img_pipe = None  # shares _pipe's weights; drop the view too
        self._inpaint_pipe = None
        self._controlnet_pipe = None
        self._controlnet_model = None
        self._controlnet_pipes = {}
        self._controlnet_models = {}
        gc.collect()
        self._runtime().empty_cache(torch)

    def _clear_resident_state(self, *, reset_generation: bool) -> None:
        self._pipe = None
        self._img2img_pipe = None
        self._inpaint_pipe = None
        self._controlnet_pipe = None
        self._controlnet_model = None
        self._controlnet_pipes = {}
        self._controlnet_models = {}
        self._loaded = False
        self._warm = False
        self._active_features = {}
        self._loaded_loras = {}
        self._loaded_lora_last_used = {}
        self._accelerator_allocated_baseline_gb = None
        self._accelerator = None
        if reset_generation:
            self._generation_index = 0

    def _recycle_pipeline_sync(self) -> None:
        try:
            self._free_pipeline_sync()
        finally:
            self._clear_resident_state(reset_generation=False)
        self._load_pipeline_sync()
        self._loaded = True

    async def after_job(self, job_id: str, params: dict[str, Any], *, failed: bool = False) -> dict[str, Any] | None:
        if settings.stub_mode or not settings.image_cleanup_after_each_job or self._pipe is None:
            return None
        return await asyncio.to_thread(self._stabilize_after_job_sync, params, failed)

    def _stabilize_after_job_sync(self, params: dict[str, Any], failed: bool) -> dict[str, Any]:
        import gc  # noqa: PLC0415

        import torch  # noqa: PLC0415

        before = self._memory_snapshot(torch)
        prune_error: str | None = None
        try:
            pruned_loras = self._prune_lora_cache(self._requested_lora_ids(params))
        except Exception as exc:  # noqa: BLE001
            pruned_loras = []
            prune_error = repr(exc)

        # Offload-style pipelines can leave their last active module on device
        # until the next call. Freeing hooks keeps the one-resident invariant honest
        # without unloading the pipeline object itself.
        if self.descriptor.family is not ModelFamily.SDXL and hasattr(self._pipe, "maybe_free_model_hooks"):
            self._pipe.maybe_free_model_hooks()

        gc.collect()
        self._runtime().empty_cache(torch, reset_peak=True)

        after_cleanup = self._memory_snapshot(torch)
        recycled = False
        recycle_reason = self._recycle_reason(after_cleanup)
        if recycle_reason:
            self._recycle_pipeline_sync()
            recycled = True

        after = self._memory_snapshot(torch)
        return {
            "backend": self.resident_key,
            "family": self.descriptor.family.value,
            "failed": failed,
            "cleanup": {
                "before": before.get(self._runtime().memory_key),
                "after": after.get(self._runtime().memory_key),
                "accelerator": self._runtime().public(),
                "pruned_loras": pruned_loras,
                "lora_prune_error": prune_error,
                "cached_loras": len(self._loaded_loras),
                "recycled": recycled,
                "recycle_reason": recycle_reason,
                "generation_index": self._generation_index,
            },
        }

    def _recycle_reason(self, snapshot: dict[str, Any]) -> str | None:
        threshold = float(settings.image_recycle_cuda_growth_gb)
        if threshold <= 0 or self._accelerator_allocated_baseline_gb is None:
            return None
        if self._generation_index < max(1, int(settings.image_recycle_min_jobs)):
            return None
        memory = snapshot.get(self._runtime().memory_key) or {}
        allocated = memory.get("allocated_gb")
        if allocated is None:
            return None
        growth = float(allocated) - self._accelerator_allocated_baseline_gb
        if growth > threshold:
            return (
                f"{self._runtime().backend} allocated grew {growth:.2f} GB over loaded baseline "
                f"{self._accelerator_allocated_baseline_gb:.2f} GB"
            )
        return None

    def _remember_accelerator_baseline(self, torch) -> None:
        memory = self._runtime().process_memory(torch)
        if not memory or memory.get("allocated_gb") is None:
            self._accelerator_allocated_baseline_gb = None
            return
        self._accelerator_allocated_baseline_gb = float(memory["allocated_gb"])
