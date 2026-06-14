from __future__ import annotations

from typing import Any

from ...config import settings


class Flux2LoaderMixin:
    def _load_flux2_klein(self, torch) -> Any:
        """FLUX.2 [klein] via diffusers (nunchaku has no FLUX.2 transformer yet).

        klein's text encoder is a small Qwen3 (not FLUX.2 [dev]'s 24 GB Mistral),
        so the 9B model in bitsandbytes 4-bit + model-offload fits a 16 GB card.
        Supports two layouts:
          * a multi-file diffusers repo folder under models/image/, or
          * a single-file transformer checkpoint (then the Qwen3 text encoder,
            VAE, tokenizer and scheduler come from HFAB_FLUX2_KLEIN_REPO)."""
        from diffusers import Flux2KleinPipeline  # noqa: PLC0415

        path = self.descriptor.path
        quant = settings.flux2_quant.lower().strip()
        if quant not in ("bnb-nf4", "bnb-fp4", "", "none", "bf16"):
            raise ValueError(
                "HFAB_FLUX2_QUANT must be one of: bnb-nf4, bnb-fp4, none "
                f"(got {settings.flux2_quant!r})"
            )
        use_bnb = quant in ("bnb-nf4", "bnb-fp4")
        qtype = "nf4" if quant == "bnb-nf4" else "fp4"

        def _pipe_quant(components: list[str]):
            from diffusers import PipelineQuantizationConfig  # noqa: PLC0415

            return PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": qtype,
                    "bnb_4bit_compute_dtype": torch.bfloat16,
                },
                components_to_quantize=components,
            )

        if path.is_dir():
            kwargs: dict[str, Any] = {"torch_dtype": torch.bfloat16}
            if use_bnb:
                kwargs["quantization_config"] = _pipe_quant(["transformer", "text_encoder"])
            pipe = Flux2KleinPipeline.from_pretrained(str(path), **kwargs)
        else:
            # single-file transformer: 4-bit it, borrow the rest from the repo
            from diffusers import Flux2Transformer2DModel  # noqa: PLC0415

            tkwargs: dict[str, Any] = {
                "config": settings.flux2_klein_repo,
                "subfolder": "transformer",
                "torch_dtype": torch.bfloat16,
            }
            if use_bnb:
                from diffusers import BitsAndBytesConfig as DBnb  # noqa: PLC0415

                tkwargs["quantization_config"] = DBnb(
                    load_in_4bit=True,
                    bnb_4bit_quant_type=qtype,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )
            transformer = Flux2Transformer2DModel.from_single_file(str(path), **tkwargs)
            kwargs = {"transformer": transformer, "torch_dtype": torch.bfloat16}
            if use_bnb:
                kwargs["quantization_config"] = _pipe_quant(["text_encoder"])
            pipe = Flux2KleinPipeline.from_pretrained(settings.flux2_klein_repo, **kwargs)

        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()

        offload = settings.flux2_offload.lower().strip()
        if use_bnb:
            # Diffusers' bitsandbytes loader places quantized components via its
            # own device_map. Calling pipe.to()/offload hooks afterwards can try
            # to copy meta tensors and fail ("Cannot copy out of meta tensor").
            if hasattr(getattr(pipe, "vae", None), "to"):
                self._runtime().move(pipe.vae)
            self._active_features["flux2_placement"] = {
                "mode": "bnb-loader",
                "requested_offload": offload or "model",
                "vae": self._runtime().torch_device,
            }
        elif offload == "sequential":
            self._runtime().enable_sequential_cpu_offload(pipe)
        elif offload in ("", "none"):
            self._runtime().move(pipe)
        else:  # "model" (default): encoders idle in RAM, frugal VRAM
            self._runtime().enable_model_cpu_offload(pipe)
        return pipe

    def _load_nunchaku_flux2_klein(self, torch) -> Any:
        """Experimental FLUX.2 [klein] SVDQuant transformer fast path.

        Official nunchaku releases on this machine do not yet expose a top-level
        NunchakuFlux2Transformer2DModel, so this can load the sidecar runtime
        shipped beside the local model weights in models/image/flux2-klein-9b-
        nunchaku. The Qwen3 text encoder still uses diffusers bitsandbytes 4-bit,
        which keeps the path within the local 16 GB GPU budget without requiring
        the separate Nunchaku Qwen3 text-encoder PR."""
        from diffusers import Flux2KleinPipeline, PipelineQuantizationConfig  # noqa: PLC0415

        NunchakuFlux2Transformer2DModel = self._import_nunchaku_flux2_transformer()
        transformer = NunchakuFlux2Transformer2DModel.from_pretrained(
            str(self.descriptor.path),
            device=self._runtime().torch_device,
            torch_dtype=torch.bfloat16,
        )

        base = settings.flux2_nunchaku_base_dir
        base_path = str(base) if base.is_dir() else settings.flux2_klein_repo
        quant = settings.flux2_quant.lower().strip()
        kwargs: dict[str, Any] = {
            "transformer": transformer,
            "torch_dtype": torch.bfloat16,
        }
        if quant in ("bnb-nf4", "bnb-fp4"):
            qtype = "nf4" if quant == "bnb-nf4" else "fp4"
            kwargs["quantization_config"] = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": qtype,
                    "bnb_4bit_compute_dtype": torch.bfloat16,
                },
                components_to_quantize=["text_encoder"],
            )

        pipe = Flux2KleinPipeline.from_pretrained(base_path, **kwargs)
        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()
        if hasattr(getattr(pipe, "vae", None), "to"):
            self._runtime().move(pipe.vae)
        self._active_features["flux2_nunchaku"] = {
            "mode": "sidecar" if self._using_flux2_sidecar() else "native",
            "transformer": str(self.descriptor.path),
            "text_encoder": quant if quant in ("bnb-nf4", "bnb-fp4") else "bf16",
            "base": base_path,
        }
        self._active_features["flux2_placement"] = {
            "mode": "nunchaku-transformer",
            "transformer": self._runtime().torch_device,
            "vae": self._runtime().torch_device,
        }
        return pipe
