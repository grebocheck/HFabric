"""Anima loader mixin (heavy runtime stays lazy-imported)."""

from __future__ import annotations

from ...config import settings


class AnimaLoaderMixin:
    def _load_anima(self, torch):
        del torch  # the runtime imports and owns its concrete torch modules
        from .anima_runtime import AnimaPipeline  # noqa: PLC0415

        transformer_config = settings.root / "resources" / "anima" / "transformer"
        pipe = AnimaPipeline.from_checkpoint(
            checkpoint=self.descriptor.path,
            transformer_config_dir=transformer_config,
            text_encoder_path=settings.anima_text_encoder_path,
            qwen_config_dir=settings.anima_qwen_config_dir,
            t5_tokenizer_dir=settings.anima_t5_tokenizer_dir,
            vae_dir=settings.anima_vae_dir,
            device=self._runtime().torch_device,
            default_negative=("worst quality, low quality, score_1, score_2, score_3, artist name"),
        )
        self._active_features["anima"] = {
            "runtime": "native-diffusers-cosmos",
            "text_encoder": "qwen3-0.6b",
            "vae": "qwen-image",
            "offload": "staged",
        }
        return pipe
