"""Make onnxruntime's CUDA execution provider loadable on Windows.

The CUDA build of onnxruntime ships ``onnxruntime_providers_cuda.dll`` but not
the CUDA/cuDNN runtime it links against (``cublasLt64_12.dll``,
``cudnn64_9.dll``, ...). The project's torch (``+cu128``) wheel already bundles
exactly those DLLs under ``torch/lib``, so we add that directory to the process
DLL search path before the first ``InferenceSession`` is created. Without this
the CUDA provider silently fails to load and onnxruntime falls back to CPU —
which is what made ContentVec the realtime per-chunk bottleneck.

``ensure_cuda_dll_search_path`` is idempotent and never raises: in the stub
venv (no torch) or on a CPU-only box it just returns False and callers keep
their CPU fallback.
"""

from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_REGISTERED: bool | None = None


def ensure_cuda_dll_search_path() -> bool:
    """Add torch's bundled CUDA/cuDNN DLL directory to the search path once.

    Returns True if a directory was registered (or already had been), False if
    torch is unavailable or its lib directory could not be found.
    """
    global _REGISTERED
    if _REGISTERED is not None:
        return _REGISTERED
    with _LOCK:
        if _REGISTERED is not None:
            return _REGISTERED
        _REGISTERED = _register()
        return _REGISTERED


def _register() -> bool:
    if not hasattr(os, "add_dll_directory"):  # non-Windows: loader uses RPATH
        return False
    try:
        import torch  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - torch absent (stub venv) => CPU fallback
        return False
    lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
    if not os.path.isdir(lib_dir):
        return False
    try:
        os.add_dll_directory(lib_dir)
    except OSError:
        return False
    return True
