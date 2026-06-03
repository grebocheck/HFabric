"""System memory telemetry + a pre-load budget guard.

Goal (ROADMAP objective #1): every single model load must fit comfortably, so
the app never OOMs, hangs, or spills to the Windows pagefile (which wears the
SSD). We surface RAM/VRAM continuously and refuse a load *with a clear error*
rather than letting the OS page out.
"""

from __future__ import annotations

import psutil

from ..config import settings
from ..core.enums import ModelFamily

_GB = 1e9
_proc = psutil.Process()


def ram_stats() -> dict:
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / _GB, 2),
        "available_gb": round(vm.available / _GB, 2),
        "used_gb": round((vm.total - vm.available) / _GB, 2),
        "percent": vm.percent,
        "process_rss_gb": round(_proc.memory_info().rss / _GB, 2),
    }


_nvml_ready: bool | None = None


def _nvml_handle():
    """Lazy NVML init. NVML reads device-wide VRAM (incl. other processes like
    llama-server) WITHOUT creating a CUDA context in our process — important so
    telemetry doesn't itself touch CUDA."""
    global _nvml_ready
    import pynvml  # noqa: PLC0415

    if _nvml_ready is None:
        pynvml.nvmlInit()
        _nvml_ready = True
    return pynvml.nvmlDeviceGetHandleByIndex(0)


def vram_stats() -> dict | None:
    try:
        import pynvml  # noqa: PLC0415

        mem = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle())
        return {
            "total_gb": round(mem.total / _GB, 2),
            "free_gb": round(mem.free / _GB, 2),
            "used_gb": round(mem.used / _GB, 2),
        }
    except Exception:
        return None


def snapshot() -> dict:
    return {"ram": ram_stats(), "vram": vram_stats()}


def estimate_ram_need_gb(family: ModelFamily, size_bytes: int, quant: str | None) -> float:
    """Rough CPU-RAM a load will need, by model kind."""
    gb = size_bytes / _GB
    if family is ModelFamily.GGUF:
        return 2.0  # llama-server mmaps the gguf (disk-backed) -> low RSS
    if quant == "nunchaku":
        return gb + 4.0  # + the int4 T5 (~3 GB) and headroom
    return gb * 1.3  # diffusers single-file materialization overhead


def check_ram_budget(family: ModelFamily, size_bytes: int, quant: str | None) -> None:
    """Raise a clear MemoryError if loading would risk the pagefile."""
    need = estimate_ram_need_gb(family, size_bytes, quant)
    ram = ram_stats()
    available = ram["available_gb"]
    if available < need + settings.min_free_ram_gb:
        raise MemoryError(
            f"Not enough RAM to load this model safely: needs ~{need:.1f} GB + "
            f"{settings.min_free_ram_gb:.0f} GB headroom, but only {available:.1f} GB "
            f"is available. Free some memory or pick a lighter model — refusing to "
            f"load rather than risk pagefile thrashing."
        )
