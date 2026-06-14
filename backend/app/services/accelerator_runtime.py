"""Runtime device helper derived from the active CapabilityProfile.

PyTorch's ROCm build intentionally exposes AMD GPUs through the ``cuda`` device
API, while Apple Silicon uses ``mps`` and CPU-safe mode should not try to load
real image models at all. Keeping those rules here prevents image backends from
scattering literal ``"cuda"`` strings and CUDA-only cleanup calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import capability_profile

_GB = 1e9


@dataclass(frozen=True)
class AcceleratorRuntime:
    backend: str
    torch_device: str
    generator_device: str
    memory_key: str

    @property
    def cuda_family(self) -> bool:
        """True for CUDA and ROCm, because ROCm is cuda-aliased in PyTorch."""
        return self.torch_device == "cuda"

    @property
    def mps(self) -> bool:
        return self.backend == "mps"

    @property
    def cpu(self) -> bool:
        return self.backend == "cpu"

    def cuda_available(self, torch: Any) -> bool:
        return self.cuda_family and bool(torch.cuda.is_available())

    def public(self) -> dict[str, str | bool]:
        return {
            "backend": self.backend,
            "torch_device": self.torch_device,
            "generator_device": self.generator_device,
            "cuda_family": self.cuda_family,
        }

    def require_available(self, torch: Any) -> None:
        if self.cuda_family:
            if not self.cuda_available(torch):
                raise RuntimeError(
                    f"{self.backend} profile is active, but torch.cuda.is_available() is False"
                )
            return
        if self.mps:
            mps = getattr(getattr(torch, "backends", None), "mps", None)
            if mps is None or not bool(mps.is_available()):
                raise RuntimeError("Apple MPS profile is active, but torch.backends.mps is not available")
            return
        raise RuntimeError("CPU-safe profile cannot load real image models; use STUB mode")

    def generator(self, torch: Any, seed: int):
        return torch.Generator(device=self.generator_device).manual_seed(seed)

    def move(self, obj: Any) -> Any:
        if not hasattr(obj, "to"):
            return obj
        return obj.to(self.torch_device)

    def enable_model_cpu_offload(self, pipe: Any) -> None:
        if self.cuda_family and hasattr(pipe, "enable_model_cpu_offload"):
            # Keep the validated CUDA/ROCm path unchanged; diffusers defaults to
            # the cuda device, which is also the ROCm alias.
            pipe.enable_model_cpu_offload()
            return
        self.move(pipe)

    def enable_sequential_cpu_offload(self, pipe: Any) -> None:
        if self.cuda_family and hasattr(pipe, "enable_sequential_cpu_offload"):
            pipe.enable_sequential_cpu_offload()
            return
        raise RuntimeError(f"sequential CPU offload is not supported on the {self.backend} backend")

    def empty_cache(self, torch: Any, *, ipc: bool = True, reset_peak: bool = False) -> None:
        if self.cuda_available(torch):
            torch.cuda.empty_cache()
            if ipc and hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
            if reset_peak and hasattr(torch.cuda, "reset_peak_memory_stats"):
                torch.cuda.reset_peak_memory_stats()
            return
        if self.mps:
            mps = getattr(torch, "mps", None)
            if mps is not None and hasattr(mps, "empty_cache"):
                mps.empty_cache()

    def reset_peak_memory_stats(self, torch: Any) -> None:
        if self.cuda_available(torch) and hasattr(torch.cuda, "reset_peak_memory_stats"):
            torch.cuda.reset_peak_memory_stats()

    def peak_memory(self, torch: Any) -> dict[str, float]:
        if not self.cuda_available(torch):
            return {}
        return {
            "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / _GB, 2),
            "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / _GB, 2),
        }

    def process_memory(self, torch: Any) -> dict[str, Any] | None:
        if self.cuda_available(torch):
            return {
                "backend": self.backend,
                "allocated_gb": round(torch.cuda.memory_allocated() / _GB, 2),
                "reserved_gb": round(torch.cuda.memory_reserved() / _GB, 2),
            }
        if self.mps:
            mps = getattr(torch, "mps", None)
            if mps is None:
                return None
            allocated = _call_optional(mps, "current_allocated_memory")
            driver = _call_optional(mps, "driver_allocated_memory")
            out: dict[str, Any] = {"backend": self.backend}
            if allocated is not None:
                out["allocated_gb"] = round(float(allocated) / _GB, 2)
            if driver is not None:
                out["reserved_gb"] = round(float(driver) / _GB, 2)
            return out if len(out) > 1 else None
        return None


def current() -> AcceleratorRuntime:
    return from_profile(capability_profile.get_capability_profile())


def from_profile(profile: dict[str, Any]) -> AcceleratorRuntime:
    backend = str(profile.get("backend") or "cpu").lower()
    defaults = profile.get("runtime_defaults") or {}
    device = str(defaults.get("torch_device") or defaults.get("device") or "")
    if not device:
        device = "cuda" if backend in {"cuda", "rocm"} else ("mps" if backend == "mps" else "cpu")
    generator_device = "cpu" if backend == "mps" else device
    memory_key = "cuda_process" if device == "cuda" else "accelerator_process"
    return AcceleratorRuntime(
        backend=backend,
        torch_device=device,
        generator_device=generator_device,
        memory_key=memory_key,
    )


def _call_optional(obj: Any, name: str) -> int | float | None:
    fn = getattr(obj, name, None)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None
