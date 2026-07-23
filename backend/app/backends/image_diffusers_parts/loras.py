"""Runtime LoRA selection, adapter loading, and bounded cache eviction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import settings


class LoraRuntimeMixin:
    def _apply_runtime_loras(
        self,
        params: dict[str, Any],
    ) -> None:
        adapters: list[str] = []
        weights: list[float] = []
        turbo = self._active_features.get("sdxl_turbo_lora")
        if turbo and params.get("turbo", True):
            adapters.append("turbo")
            weights.append(float(turbo["weight"]))

        requests = self._lora_requests(params)
        if requests and not hasattr(self._pipe, "load_lora_weights"):
            raise RuntimeError(f"Pipeline for {self.descriptor.name} does not support LoRA loading")
        if requests:
            self._require_peft_for_lora()
        for request in requests:
            adapter = self._load_lora_adapter(
                request["id"],
                Path(request["path"]),
            )
            adapters.append(adapter)
            weights.append(float(request["weight"]))
            self._loaded_lora_last_used[request["id"]] = self._generation_index

        if adapters:
            if not hasattr(self._pipe, "set_adapters"):
                raise RuntimeError(f"Pipeline for {self.descriptor.name} does not support LoRA adapters")
            self._pipe.set_adapters(
                adapters,
                adapter_weights=weights,
            )
            if hasattr(self._pipe, "enable_lora"):
                self._pipe.enable_lora()
        elif hasattr(self._pipe, "disable_lora"):
            self._pipe.disable_lora()

    def _lora_requests(
        self,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw_loras = params.get("loras") or []
        paths = params.get("_lora_paths") or {}
        if not isinstance(raw_loras, list) or not isinstance(paths, dict):
            return []

        requests: list[dict[str, Any]] = []
        for item in raw_loras:
            if not isinstance(item, dict):
                continue
            lora_id = item.get("id")
            if not isinstance(lora_id, str):
                continue
            path = item.get("path") or paths.get(lora_id)
            if not isinstance(path, str):
                raise RuntimeError(f"LoRA {lora_id!r} is missing its validated path")
            requests.append(
                {
                    "id": lora_id,
                    "path": path,
                    "weight": float(item.get("weight", 1.0)),
                }
            )
        return requests

    def _requested_lora_ids(
        self,
        params: dict[str, Any],
    ) -> set[str]:
        raw_loras = params.get("loras") or []
        if not isinstance(raw_loras, list):
            return set()
        ids: set[str] = set()
        for item in raw_loras:
            if isinstance(item, str):
                ids.add(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.add(item["id"])
        return ids

    def _load_lora_adapter(
        self,
        lora_id: str,
        path: Path,
    ) -> str:
        if lora_id in self._loaded_loras:
            return self._loaded_loras[lora_id]
        if not path.exists():
            raise FileNotFoundError(f"LoRA file not found: {path}")

        adapter = self._lora_adapter_name(lora_id)
        if path.is_dir():
            self._pipe.load_lora_weights(
                str(path),
                adapter_name=adapter,
            )
        elif path.suffix.lower() == ".safetensors":
            self._pipe.load_lora_weights(
                str(path.parent),
                weight_name=path.name,
                adapter_name=adapter,
            )
        else:
            self._pipe.load_lora_weights(
                str(path),
                adapter_name=adapter,
            )
        self._loaded_loras[lora_id] = adapter
        self._loaded_lora_last_used[lora_id] = self._generation_index
        return adapter

    def _prune_lora_cache(
        self,
        keep_ids: set[str],
    ) -> list[str]:
        if not self._loaded_loras:
            return []

        max_cached = int(settings.image_lora_cache_max)
        if max_cached < 0:
            return []

        if max_cached == 0:
            prune_ids = list(self._loaded_loras)
        else:
            ordered = sorted(
                self._loaded_loras,
                key=lambda lora_id: self._loaded_lora_last_used.get(
                    lora_id,
                    -1,
                ),
            )
            prune_ids = []
            for lora_id in ordered:
                if len(self._loaded_loras) - len(prune_ids) <= max_cached:
                    break
                if lora_id not in keep_ids:
                    prune_ids.append(lora_id)
        if not prune_ids:
            return []

        adapter_names = [self._loaded_loras[lora_id] for lora_id in prune_ids]
        if hasattr(self._pipe, "delete_adapters"):
            self._pipe.delete_adapters(adapter_names)
        elif (
            len(prune_ids) == len(self._loaded_loras)
            and not self._active_features.get("sdxl_turbo_lora")
            and hasattr(self._pipe, "unload_lora_weights")
        ):
            self._pipe.unload_lora_weights()
        else:
            return []

        for lora_id in prune_ids:
            self._loaded_loras.pop(lora_id, None)
            self._loaded_lora_last_used.pop(lora_id, None)
        return prune_ids

    @staticmethod
    def _lora_adapter_name(lora_id: str) -> str:
        body = "".join(ch if ch.isalnum() else "_" for ch in lora_id)[:80]
        return f"lora_{body}"
