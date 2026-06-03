"""Discovers local model files and hands out (cached) backends for them.

Scanning only reads safetensors headers, so it is instant even for the 16 GB
FLUX file. Backends are created lazily on first use and cached; the arbiter is
what decides which one is actually resident in VRAM.
"""

from __future__ import annotations

import re

from ..config import settings
from ..core.enums import ModelFamily
from .base import GpuBackend, ModelDescriptor
from .image_diffusers import DiffusersImageBackend
from .inspect import classify_image_model
from .llm_llamacpp import LlamaCppBackend


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class ModelRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ModelDescriptor] = {}
        self._backends: dict[str, GpuBackend] = {}

    def scan(self) -> None:
        self._descriptors.clear()
        for path in sorted(settings.image_models_dir.glob("*.safetensors")):
            name = path.stem.lower()
            if "svdq" in name or "nunchaku" in name:
                # SVDQuant transformer-only checkpoint (Blackwell fp4/int4 turbo)
                self._add(path, ModelFamily.FLUX, quant="nunchaku")
            else:
                self._add(path, classify_image_model(path))
        for path in sorted(settings.llm_models_dir.glob("*.gguf")):
            self._add(path, ModelFamily.GGUF)

    def _add(self, path, family: ModelFamily, quant: str | None = None) -> None:
        mid = _slug(path.stem)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self._descriptors[mid] = ModelDescriptor(
            id=mid, name=path.stem, family=family, path=path, size_bytes=size, quant=quant
        )

    def descriptors(self) -> list[ModelDescriptor]:
        return list(self._descriptors.values())

    def get_descriptor(self, model_id: str) -> ModelDescriptor:
        if model_id not in self._descriptors:
            raise KeyError(f"unknown model id: {model_id}")
        return self._descriptors[model_id]

    def get_backend(self, model_id: str) -> GpuBackend:
        if model_id in self._backends:
            return self._backends[model_id]
        desc = self.get_descriptor(model_id)
        backend: GpuBackend
        if desc.family is ModelFamily.GGUF:
            backend = LlamaCppBackend(desc)
        else:
            backend = DiffusersImageBackend(desc)
        self._backends[model_id] = backend
        return backend

    def loaded_backends(self) -> list[GpuBackend]:
        return [b for b in self._backends.values() if b.loaded]
