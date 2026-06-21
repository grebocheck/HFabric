from __future__ import annotations

from typing import Any

from ...config import settings


class QwenZLoaderMixin:
    def _load_qwen_image_edit(self, torch) -> Any:
        """Load Qwen-Image-Edit as its own arbiter resident (new weights)."""
        import json  # noqa: PLC0415

        from diffusers import QwenImageEditPipeline, QwenImageEditPlusPipeline  # noqa: PLC0415

        cls = QwenImageEditPipeline
        index = self.descriptor.path / "model_index.json"
        if index.is_file():
            try:
                class_name = str(
                    json.loads(index.read_text(encoding="utf-8")).get("_class_name", "")
                )
                if "EditPlus" in class_name:
                    cls = QwenImageEditPlusPipeline
            except (OSError, ValueError):
                pass
        kwargs = self._quantized_repo_kwargs(
            torch,
            settings.qwen_image_edit_quant,
            "HFAB_QWEN_IMAGE_EDIT_QUANT",
            ["transformer", "text_encoder"],
        )
        pipe = cls.from_pretrained(str(self.descriptor.path), **kwargs)
        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()
        quant = settings.qwen_image_edit_quant.lower().strip()
        if quant in ("bnb-nf4", "bnb-fp4"):
            if hasattr(getattr(pipe, "vae", None), "to"):
                self._runtime().move(pipe.vae)
            placement = "bnb-loader"
        else:
            self._place_repo_pipeline(
                pipe,
                settings.qwen_image_edit_offload,
                "HFAB_QWEN_IMAGE_EDIT_OFFLOAD",
            )
            placement = settings.qwen_image_edit_offload
        self._active_features["qwen_image_edit"] = {
            "quant": settings.qwen_image_edit_quant,
            "placement": placement,
            "instruction_edit": True,
        }
        return pipe

    def _load_qwen_image(self, torch) -> Any:
        """Qwen-Image-2512 multi-file Diffusers repo.

        The full bf16 repo is large, so the default path quantizes transformer
        and text encoder through Diffusers' bitsandbytes loader and uses model
        offload. Generation maps the UI guidance field to Qwen's true_cfg_scale.

        When the descriptor is a Nunchaku SVDQuant fp4 transformer (a single
        ~12 GB file), the much faster fp4 path is used instead — see
        ``_load_nunchaku_qwen_image``.
        """
        if self._is_nunchaku_quant():
            return self._load_nunchaku_qwen_image(torch)

        from diffusers import QwenImagePipeline  # noqa: PLC0415

        kwargs = self._quantized_repo_kwargs(
            torch,
            settings.qwen_image_quant,
            "HFAB_QWEN_IMAGE_QUANT",
            ["transformer", "text_encoder"],
        )
        pipe = QwenImagePipeline.from_pretrained(str(self.descriptor.path), **kwargs)
        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()
        quant = settings.qwen_image_quant.lower().strip()
        if quant in ("bnb-nf4", "bnb-fp4"):
            if hasattr(getattr(pipe, "vae", None), "to"):
                self._runtime().move(pipe.vae)
            placement = "bnb-loader"
        else:
            self._place_repo_pipeline(pipe, settings.qwen_image_offload, "HFAB_QWEN_IMAGE_OFFLOAD")
            placement = settings.qwen_image_offload
        self._active_features["qwen_image"] = {
            "quant": settings.qwen_image_quant,
            "offload": settings.qwen_image_offload,
            "placement": placement,
            "guidance_arg": "true_cfg_scale",
        }
        return pipe

    @staticmethod
    def _patch_nunchaku_qwen_forward(cls) -> None:
        """Fix a signature drift between Nunchaku 1.3.0 and diffusers 0.38.

        Diffusers 0.38's QwenImagePipeline no longer passes the (now deprecated)
        ``txt_seq_lens`` to the transformer — it relies on ``encoder_hidden_states_mask``
        and derives the RoPE text length internally. Nunchaku's forward still hands
        ``txt_seq_lens`` (defaulting to None) straight to ``QwenEmbedRope``, which then
        raises ``Either max_txt_seq_len or txt_seq_lens must be provided``. Wrap the
        forward to reconstruct ``txt_seq_lens`` from the mask (or the encoder hidden
        states shape) when the pipeline omits it. Idempotent."""
        if getattr(cls, "_hfab_txt_seq_patched", False):
            return
        orig_forward = cls.forward

        def forward(self, *args, **kwargs):
            if kwargs.get("txt_seq_lens") is None and kwargs.get("encoder_hidden_states") is not None:
                ehs = kwargs["encoder_hidden_states"]
                mask = kwargs.get("encoder_hidden_states_mask")
                if mask is not None:
                    kwargs["txt_seq_lens"] = mask.sum(dim=1).tolist()
                else:
                    kwargs["txt_seq_lens"] = [int(ehs.shape[1])] * int(ehs.shape[0])
            return orig_forward(self, *args, **kwargs)

        cls.forward = forward
        cls._hfab_txt_seq_patched = True

    def _load_nunchaku_qwen_image(self, torch) -> Any:
        """Qwen-Image-2512 via a Nunchaku SVDQuant fp4 transformer (Blackwell).

        The fp4 transformer is a single transformer-only file; the Qwen2.5-VL text
        encoder, VAE, tokenizer and scheduler come from the local base repo folder.
        On 16 GB cards the bf16 text encoder (~16 GB) would exhaust the 32 GB RAM
        under sequential offload, so it is quantized to 4-bit by default. The fp4
        transformer keeps ``blocks_on_gpu`` of its 60 blocks resident (the rest
        stream per-layer); VRAM is the slack resource here, so a higher block count
        trades free VRAM for far fewer CPU<->GPU swaps and much faster steps.
        """
        from diffusers import QwenImagePipeline  # noqa: PLC0415
        from nunchaku.models.transformers.transformer_qwenimage import (  # noqa: PLC0415
            NunchakuQwenImageTransformer2DModel,
        )

        self._patch_nunchaku_qwen_forward(NunchakuQwenImageTransformer2DModel)
        # Load to CPU then let set_offload() stage blocks onto the GPU. (device="cuda"
        # here would materialize all 13 GB on the GPU before offloading and OOM
        # alongside the resident text encoder.)
        transformer = NunchakuQwenImageTransformer2DModel.from_pretrained(str(self.descriptor.path))
        base = settings.qwen_image_base_repo

        te_quant = settings.qwen_image_nunchaku_text_encoder_quant.lower().strip()
        if te_quant not in ("bnb-nf4", "bnb-fp4", "", "none", "bf16"):
            raise ValueError(
                "HFAB_QWEN_IMAGE_NUNCHAKU_TEXT_ENCODER_QUANT must be one of: "
                f"bnb-nf4, bnb-fp4, none (got {te_quant!r})"
            )
        kwargs: dict[str, Any] = {"transformer": transformer, "torch_dtype": torch.bfloat16}
        # Prefer a pre-quantized text encoder on disk (scripts/prequant_qwen_text_
        # encoder.py): loading the ~5 GB nf4 checkpoint avoids the ~16 GB bf16 RAM
        # spike and ~50 s requant that an on-the-fly bitsandbytes load incurs.
        te_dir = base / "text_encoder_nf4"
        te_cached = te_quant in ("bnb-nf4", "bnb-fp4") and te_dir.is_dir() and any(te_dir.glob("*.safetensors"))
        te_on_gpu = te_quant in ("bnb-nf4", "bnb-fp4")
        if te_cached:
            from transformers import AutoModel  # noqa: PLC0415

            kwargs["text_encoder"] = AutoModel.from_pretrained(
                str(te_dir), dtype=torch.bfloat16, device_map=self._runtime().torch_device
            )
        elif te_quant in ("bnb-nf4", "bnb-fp4"):
            from diffusers import PipelineQuantizationConfig  # noqa: PLC0415

            kwargs["quantization_config"] = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": "nf4" if te_quant == "bnb-nf4" else "fp4",
                    "bnb_4bit_compute_dtype": torch.bfloat16,
                },
                components_to_quantize=["text_encoder"],
            )
        pipe = QwenImagePipeline.from_pretrained(str(base), **kwargs)
        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()

        blocks = max(1, int(settings.qwen_image_nunchaku_blocks_on_gpu))
        # Per-layer transformer offload: `blocks` of the 60 blocks stay resident,
        # the rest stream. Nunchaku manages the transformer's device moves itself.
        transformer.set_offload(True, use_pin_memory=False, num_blocks_on_gpu=blocks)
        if te_on_gpu:
            # The 4-bit text encoder lives on the GPU (~5 GB; it runs once per image).
            # bitsandbytes 4-bit modules can't ride the sequential/model offload hooks
            # ("Cannot copy out of meta tensor"), so just move the VAE on-device.
            if hasattr(getattr(pipe, "vae", None), "to"):
                self._runtime().move(pipe.vae)
            placement = f"nunchaku-per-layer({blocks})+bnb-te{'(cached)' if te_cached else ''}"
        else:
            # bf16 text encoder: stream it from RAM via sequential offload (exclude
            # the transformer, which Nunchaku already offloads per-layer).
            if "transformer" not in pipe._exclude_from_cpu_offload:
                pipe._exclude_from_cpu_offload.append("transformer")
            self._runtime().enable_sequential_cpu_offload(pipe)
            placement = f"nunchaku-per-layer({blocks})+sequential"
        self._active_features["qwen_image"] = {
            "quant": self.descriptor.quant,
            "placement": placement,
            "blocks_on_gpu": blocks,
            "text_encoder_quant": (te_quant or "bf16") + (" (cached)" if te_cached else ""),
            "guidance_arg": "true_cfg_scale",
        }
        return pipe

    @staticmethod
    def _patch_nunchaku_zimage_forward(cls) -> None:
        """Fix a signature drift between Nunchaku 1.3.0 and diffusers 0.38.

        Nunchaku's ``NunchakuZImageTransformer2DModel.forward`` calls the diffusers
        parent positionally as ``(x, t, cap_feats, patch_size, f_patch_size,
        return_dict)``, but diffusers 0.38 reordered ZImage's forward to
        ``(x, t, cap_feats, return_dict, controlnet_block_samples, siglip_feats,
        image_noise_mask, patch_size, f_patch_size)``. The positional call leaks
        ``patch_size`` into ``return_dict`` and ``f_patch_size`` (an int) into
        ``controlnet_block_samples`` -> ``TypeError: 'int' is not iterable``. Re-issue
        the parent call with keywords (what Nunchaku intended). Idempotent."""
        if getattr(cls, "_hfab_forward_patched", False):
            return
        from diffusers.models.transformers.transformer_z_image import (  # noqa: PLC0415
            ZImageTransformer2DModel,
        )
        from nunchaku.models.transformers.transformer_zimage import (  # noqa: PLC0415
            NunchakuZImageRopeHook,
        )

        def forward(self, x, t, cap_feats, patch_size=2, f_patch_size=1, return_dict=True):
            rope_hook = NunchakuZImageRopeHook()
            self.register_rope_hook(rope_hook)
            try:
                return ZImageTransformer2DModel.forward(
                    self,
                    x,
                    t,
                    cap_feats,
                    patch_size=patch_size,
                    f_patch_size=f_patch_size,
                    return_dict=return_dict,
                )
            finally:
                self.unregister_rope_hook()
                del rope_hook

        cls.forward = forward
        cls._hfab_forward_patched = True

    def _load_z_image(self, torch) -> Any:
        """Z-Image / Z-Image-Turbo multi-file Diffusers repo.

        The full base repo uses Diffusers' bitsandbytes 4-bit loader by default.
        A Nunchaku SVDQuant fp4 transformer (~4 GB) takes the place of the Turbo
        bf16 transformer when the descriptor is a Nunchaku checkpoint, borrowing
        the Qwen3 text encoder / VAE from the local Turbo repo folder.
        """
        from diffusers import ZImagePipeline  # noqa: PLC0415

        if self._is_nunchaku_quant():
            from nunchaku.models.transformers.transformer_zimage import (  # noqa: PLC0415
                NunchakuZImageTransformer2DModel,
            )

            self._patch_nunchaku_zimage_forward(NunchakuZImageTransformer2DModel)
            transformer = NunchakuZImageTransformer2DModel.from_pretrained(str(self.descriptor.path))
            pipe = ZImagePipeline.from_pretrained(
                str(settings.z_image_base_repo),
                transformer=transformer,
                torch_dtype=torch.bfloat16,
            )
            if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
                pipe.vae.enable_tiling()
            offload = settings.z_image_nunchaku_offload.lower().strip()
            if offload in ("", "none"):
                self._runtime().move(pipe)
            else:  # "model": frugal — fp4 transformer is small, encoders idle in RAM
                self._runtime().enable_model_cpu_offload(pipe)
            self._active_features["z_image"] = {
                "variant": "turbo",
                "quant": self.descriptor.quant,
                "offload": offload or "none",
                "default_steps": self._z_image_default_steps(),
                "default_guidance": self._z_image_default_guidance(),
            }
            return pipe

        kwargs = self._quantized_repo_kwargs(
            torch,
            settings.z_image_quant,
            "HFAB_Z_IMAGE_QUANT",
            ["transformer", "text_encoder"],
        )
        quant = settings.z_image_quant.lower().strip()
        if quant not in ("bnb-nf4", "bnb-fp4"):
            kwargs["low_cpu_mem_usage"] = False
        pipe = ZImagePipeline.from_pretrained(str(self.descriptor.path), **kwargs)
        if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
            pipe.vae.enable_tiling()
        if quant in ("bnb-nf4", "bnb-fp4"):
            if hasattr(getattr(pipe, "vae", None), "to"):
                self._runtime().move(pipe.vae)
            placement = "bnb-loader"
        else:
            self._place_repo_pipeline(pipe, settings.z_image_offload, "HFAB_Z_IMAGE_OFFLOAD")
            placement = settings.z_image_offload
        self._active_features["z_image"] = {
            "variant": "turbo" if self._is_z_image_turbo() else "base",
            "quant": settings.z_image_quant,
            "offload": settings.z_image_offload,
            "placement": placement,
            "default_steps": self._z_image_default_steps(),
            "default_guidance": self._z_image_default_guidance(),
        }
        return pipe
