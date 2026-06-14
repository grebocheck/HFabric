from __future__ import annotations

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
