from __future__ import annotations

import types

import pytest

from app.services import accelerator_runtime


def profile(backend: str, torch_device: str | None = None) -> dict:
    defaults = {"backend": backend}
    if torch_device:
        defaults["torch_device"] = torch_device
    return {"backend": backend, "runtime_defaults": defaults}


def test_cuda_and_rocm_use_cuda_torch_device():
    cuda = accelerator_runtime.from_profile(profile("cuda"))
    rocm = accelerator_runtime.from_profile(profile("rocm"))

    assert cuda.torch_device == "cuda"
    assert cuda.generator_device == "cuda"
    assert cuda.cuda_family is True
    assert rocm.torch_device == "cuda"
    assert rocm.cuda_family is True
    assert rocm.memory_key == "cuda_process"


def test_mps_uses_mps_device_but_cpu_generator():
    runtime = accelerator_runtime.from_profile(profile("mps"))

    assert runtime.torch_device == "mps"
    assert runtime.generator_device == "cpu"
    assert runtime.cuda_family is False
    assert runtime.memory_key == "accelerator_process"


def test_cpu_runtime_is_non_accelerated():
    runtime = accelerator_runtime.from_profile(profile("cpu"))

    assert runtime.torch_device == "cpu"
    assert runtime.cpu is True
    assert runtime.cuda_family is False


def test_current_uses_capability_profile(monkeypatch):
    monkeypatch.setattr(
        accelerator_runtime.capability_profile,
        "get_capability_profile",
        lambda: profile("mps"),
    )

    assert accelerator_runtime.current().backend == "mps"


def test_public_generator_and_move_helpers():
    runtime = accelerator_runtime.AcceleratorRuntime(
        backend="cuda",
        torch_device="cuda",
        generator_device="cuda",
        memory_key="cuda_process",
    )
    generated: list[tuple[str, int]] = []

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int):
            generated.append((self.device, seed))
            return self

    class Movable:
        def __init__(self) -> None:
            self.device = None

        def to(self, device: str):
            self.device = device
            return self

    fake_torch = types.SimpleNamespace(Generator=Generator)
    obj = Movable()

    assert runtime.public() == {
        "backend": "cuda",
        "torch_device": "cuda",
        "generator_device": "cuda",
        "cuda_family": True,
    }
    assert runtime.generator(fake_torch, 123).device == "cuda"
    assert generated == [("cuda", 123)]
    assert runtime.move(obj) is obj
    assert obj.device == "cuda"
    plain = object()
    assert runtime.move(plain) is plain


def test_require_available_for_cuda_mps_and_cpu():
    cuda_runtime = accelerator_runtime.from_profile(profile("cuda"))
    cuda_ok = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
    cuda_bad = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    cuda_runtime.require_available(cuda_ok)
    with pytest.raises(RuntimeError, match="torch.cuda.is_available"):
        cuda_runtime.require_available(cuda_bad)

    mps_runtime = accelerator_runtime.from_profile(profile("mps"))
    mps_ok = types.SimpleNamespace(backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True)))
    mps_bad = types.SimpleNamespace(backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)))
    mps_runtime.require_available(mps_ok)
    with pytest.raises(RuntimeError, match="Apple MPS"):
        mps_runtime.require_available(mps_bad)

    with pytest.raises(RuntimeError, match="CPU-safe profile"):
        accelerator_runtime.from_profile(profile("cpu")).require_available(cuda_ok)


def test_offload_helpers_use_cuda_hooks_or_fallback_move():
    calls: list[str] = []

    class Pipe:
        def enable_model_cpu_offload(self) -> None:
            calls.append("model")

        def enable_sequential_cpu_offload(self) -> None:
            calls.append("sequential")

        def to(self, device: str):
            calls.append(f"to:{device}")
            return self

    cuda = accelerator_runtime.from_profile(profile("cuda"))
    pipe = Pipe()
    cuda.enable_model_cpu_offload(pipe)
    cuda.enable_sequential_cpu_offload(pipe)

    mps = accelerator_runtime.from_profile(profile("mps"))
    mps.enable_model_cpu_offload(pipe)
    with pytest.raises(RuntimeError, match="sequential CPU offload"):
        mps.enable_sequential_cpu_offload(pipe)

    assert calls == ["model", "sequential", "to:mps"]


def test_cuda_memory_helpers_call_optional_cleanup():
    calls: list[str] = []

    class Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def empty_cache() -> None:
            calls.append("empty")

        @staticmethod
        def ipc_collect() -> None:
            calls.append("ipc")

        @staticmethod
        def reset_peak_memory_stats() -> None:
            calls.append("reset")

        @staticmethod
        def max_memory_allocated() -> int:
            return 1_500_000_000

        @staticmethod
        def max_memory_reserved() -> int:
            return 2_500_000_000

        @staticmethod
        def memory_allocated() -> int:
            return 3_000_000_000

        @staticmethod
        def memory_reserved() -> int:
            return 4_000_000_000

    runtime = accelerator_runtime.from_profile(profile("cuda"))
    torch = types.SimpleNamespace(cuda=Cuda)

    runtime.empty_cache(torch, reset_peak=True)
    runtime.reset_peak_memory_stats(torch)

    assert calls == ["empty", "ipc", "reset", "reset"]
    assert runtime.peak_memory(torch) == {"peak_allocated_gb": 1.5, "peak_reserved_gb": 2.5}
    assert runtime.process_memory(torch) == {
        "backend": "cuda",
        "allocated_gb": 3.0,
        "reserved_gb": 4.0,
    }


def test_mps_memory_helpers_and_optional_call_failures():
    calls: list[str] = []

    class Mps:
        @staticmethod
        def empty_cache() -> None:
            calls.append("mps-empty")

        @staticmethod
        def current_allocated_memory() -> int:
            return 1_000_000_000

        @staticmethod
        def driver_allocated_memory() -> int:
            return 2_000_000_000

    runtime = accelerator_runtime.from_profile(profile("mps"))
    torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        mps=Mps,
    )

    runtime.empty_cache(torch)
    assert calls == ["mps-empty"]
    assert runtime.peak_memory(torch) == {}
    assert runtime.process_memory(torch) == {
        "backend": "mps",
        "allocated_gb": 1.0,
        "reserved_gb": 2.0,
    }

    broken = types.SimpleNamespace(current_allocated_memory=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert accelerator_runtime._call_optional(broken, "current_allocated_memory") is None
    assert accelerator_runtime._call_optional(broken, "missing") is None


def test_process_memory_returns_none_without_backend_memory_api():
    mps = accelerator_runtime.from_profile(profile("mps"))
    cpu = accelerator_runtime.from_profile(profile("cpu"))
    torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        mps=None,
    )

    assert mps.process_memory(torch) is None
    assert cpu.process_memory(torch) is None
