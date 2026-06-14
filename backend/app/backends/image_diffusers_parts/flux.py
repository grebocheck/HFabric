from __future__ import annotations

from contextlib import nullcontext
import re
from typing import Any

from ...config import settings
from ...core.enums import ModelFamily


class FluxLoaderMixin:
    def _load_flux(self, torch) -> Any:
        from diffusers import FluxPipeline  # noqa: PLC0415

        pipe = FluxPipeline.from_single_file(
            str(self.descriptor.path),
            config=settings.flux_config_repo,
            torch_dtype=torch.float8_e4m3fn,
        )
        pipe.transformer.enable_layerwise_casting(
            storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.bfloat16
        )
        skip = re.compile(r"pos_embed|patch_embed|norm")
        for name, mod in pipe.transformer.named_modules():
            if skip.search(name) or name.split(".")[-1] in ("proj_in", "proj_out"):
                mod.to(torch.bfloat16)
        pipe.text_encoder.to(torch.bfloat16)
        pipe.text_encoder_2.to(torch.bfloat16)
        pipe.vae.to(torch.bfloat16)
        pipe.vae.enable_tiling()
        self._runtime().enable_model_cpu_offload(pipe)
        return pipe

    def _load_nunchaku_flux(self, torch) -> Any:
        """SVDQuant fp4 FLUX (Blackwell turbo): ~8 s/1024, peak RAM ~13 GB.

        Assembled from light components so a single load stays well within the RAM
        budget (P0.1): nunchaku fp4 transformer + int4 T5 (~3 GB, not ~10 GB bf16),
        with CLIP/VAE/tokenizers/scheduler from the non-gated config repo. We do
        NOT read the local 16 GB fp8 checkpoint here."""
        from diffusers import FluxPipeline  # noqa: PLC0415
        from nunchaku import (  # noqa: PLC0415
            NunchakuFluxTransformer2dModel,
            NunchakuT5EncoderModel,
        )

        transformer = NunchakuFluxTransformer2dModel.from_pretrained(str(self.descriptor.path))
        text_encoder_2 = NunchakuT5EncoderModel.from_pretrained(settings.flux_t5_nunchaku)
        pipe = FluxPipeline.from_pretrained(
            settings.flux_config_repo,
            transformer=transformer,
            text_encoder_2=text_encoder_2,
            torch_dtype=torch.bfloat16,
        )
        pipe.vae.enable_tiling()
        self._runtime().enable_model_cpu_offload(pipe)
        return pipe

    def _maybe_apply_flux_step_cache(self, pipe: Any, report: dict[str, Any]) -> None:
        if self.descriptor.family is not ModelFamily.FLUX:
            return

        mode = settings.flux_step_cache.lower().strip()
        if mode in ("", "off", "none", "false"):
            return
        if mode == "fb":
            from nunchaku.caching.diffusers_adapters.flux import apply_cache_on_pipe  # noqa: PLC0415

            apply_cache_on_pipe(
                pipe,
                residual_diff_threshold=settings.flux_fb_cache_threshold,
                use_double_fb_cache=settings.flux_fb_cache_double,
            )
            self._active_features["flux_step_cache"] = {
                "mode": "fb",
                "threshold": settings.flux_fb_cache_threshold,
                "double": settings.flux_fb_cache_double,
            }
        elif mode == "teacache":
            self._active_features["flux_step_cache"] = {
                "mode": "teacache",
                "threshold": settings.flux_teacache_threshold,
                "skip_steps": settings.flux_teacache_skip_steps,
            }
        else:
            raise ValueError(
                "HFAB_FLUX_STEP_CACHE must be one of: off, fb, teacache "
                f"(got {settings.flux_step_cache!r})"
            )
        report["acceleration"]["flux_step_cache"] = self._active_features["flux_step_cache"]

    def _generation_context(self, steps: int):
        feature = self._active_features.get("flux_step_cache")
        if not feature or feature.get("mode") != "teacache":
            return nullcontext()

        from nunchaku.caching.teacache import TeaCache  # noqa: PLC0415

        return TeaCache(
            self._pipe.transformer,
            num_steps=steps,
            rel_l1_thresh=settings.flux_teacache_threshold,
            skip_steps=settings.flux_teacache_skip_steps,
            enabled=True,
            model_name="flux",
        )

