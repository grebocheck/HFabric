from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import settings
from ...core.enums import ModelFamily


class SdxlLoaderMixin:
    def _load_sdxl(self, torch) -> Any:
        from diffusers import StableDiffusionXLPipeline  # noqa: PLC0415

        pipe = StableDiffusionXLPipeline.from_single_file(
            str(self.descriptor.path), torch_dtype=torch.float16
        )
        return self._runtime().move(pipe)

    def _maybe_apply_sdxl_turbo_lora(self, pipe: Any, report: dict[str, Any]) -> None:
        if self.descriptor.family is not ModelFamily.SDXL or not settings.sdxl_turbo_lora:
            return

        self._require_peft_for_lora()
        source = settings.sdxl_turbo_lora
        path = Path(source)
        if path.suffix.lower() == ".safetensors":
            pipe.load_lora_weights(str(path.parent), weight_name=path.name, adapter_name="turbo")
        else:
            pipe.load_lora_weights(source, adapter_name="turbo")
        if hasattr(pipe, "set_adapters"):
            pipe.set_adapters(["turbo"], adapter_weights=[settings.sdxl_turbo_lora_weight])

        self._active_features["sdxl_turbo_lora"] = {
            "source": source,
            "weight": settings.sdxl_turbo_lora_weight,
            "default_steps": settings.sdxl_turbo_steps,
            "default_guidance": settings.sdxl_turbo_guidance,
        }
        report["acceleration"]["sdxl_turbo_lora"] = self._active_features["sdxl_turbo_lora"]

    def _is_sdxl_lightning_checkpoint(self) -> bool:
        if self.descriptor.family is not ModelFamily.SDXL:
            return False
        haystack = f"{self.descriptor.id} {self.descriptor.name} {self.descriptor.path.name}".lower()
        return "sdxl" in haystack and "lightning" in haystack
