"""Native Anima text-to-image runtime built on Diffusers' Cosmos core.

Anima is a Cosmos-Predict2 2B derivative whose checkpoint adds a learned
Qwen3-to-T5-token LLM adapter. Diffusers already converts the Cosmos core; this
module implements the small Anima-specific adapter and a deterministic flow
sampling loop while reusing the Qwen-Image VAE.

Heavy ML imports are intentionally confined to this module. It is imported only
when an Anima model is actually loaded, so STUB/CPU-safe installs stay light.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from accelerate import init_empty_weights
from diffusers import (
    AutoencoderKLQwenImage,
    CosmosTransformer3DModel,
    FlowMatchEulerDiscreteScheduler,
)
from diffusers.image_processor import VaeImageProcessor
from diffusers.utils import logging as diffusers_logging
from safetensors import safe_open
import torch
from torch import nn
import torch.nn.functional as F
from transformers import AutoConfig, AutoTokenizer, Qwen3Model, T5TokenizerFast


class _Attention(nn.Module):
    def __init__(self, query_dim: int, context_dim: int, heads: int = 16) -> None:
        super().__init__()
        self.heads = heads
        self.head_dim = query_dim // heads
        inner = self.heads * self.head_dim
        self.q_proj = nn.Linear(query_dim, inner, bias=False)
        self.q_norm = nn.RMSNorm(self.head_dim, eps=1e-6)
        self.k_proj = nn.Linear(context_dim, inner, bias=False)
        self.k_norm = nn.RMSNorm(self.head_dim, eps=1e-6)
        self.v_proj = nn.Linear(context_dim, inner, bias=False)
        self.o_proj = nn.Linear(inner, query_dim, bias=False)

    @staticmethod
    def _rotate_half(value: torch.Tensor) -> torch.Tensor:
        left, right = value.chunk(2, dim=-1)
        return torch.cat((-right, left), dim=-1)

    def _apply_rope(self, value: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        cos = cos.unsqueeze(1)
        sin = sin.unsqueeze(1)
        return value * cos + self._rotate_half(value) * sin

    def forward(
        self,
        query: torch.Tensor,
        context: torch.Tensor,
        *,
        query_rope: tuple[torch.Tensor, torch.Tensor] | None = None,
        context_rope: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        batch, query_len, _ = query.shape
        context_len = context.shape[1]
        q = self.q_norm(self.q_proj(query).view(batch, query_len, self.heads, self.head_dim)).transpose(1, 2)
        k = self.k_norm(self.k_proj(context).view(batch, context_len, self.heads, self.head_dim)).transpose(
            1, 2
        )
        v = self.v_proj(context).view(batch, context_len, self.heads, self.head_dim).transpose(1, 2)
        if query_rope is not None:
            q = self._apply_rope(q, *query_rope)
        if context_rope is not None:
            k = self._apply_rope(k, *context_rope)
        output = F.scaled_dot_product_attention(q, k, v)
        output = output.transpose(1, 2).reshape(batch, query_len, -1)
        return self.o_proj(output)


class _AdapterBlock(nn.Module):
    def __init__(self, dim: int = 1024) -> None:
        super().__init__()
        self.norm_self_attn = nn.RMSNorm(dim, eps=1e-6)
        self.self_attn = _Attention(dim, dim)
        self.norm_cross_attn = nn.RMSNorm(dim, eps=1e-6)
        self.cross_attn = _Attention(dim, dim)
        self.norm_mlp = nn.RMSNorm(dim, eps=1e-6)
        self.mlp = nn.Sequential(nn.Linear(dim, dim * 4), nn.GELU(), nn.Linear(dim * 4, dim))

    def forward(
        self,
        hidden_states: torch.Tensor,
        source: torch.Tensor,
        *,
        target_rope: tuple[torch.Tensor, torch.Tensor],
        source_rope: tuple[torch.Tensor, torch.Tensor],
    ) -> torch.Tensor:
        normalized = self.norm_self_attn(hidden_states)
        hidden_states = hidden_states + self.self_attn(
            normalized,
            normalized,
            query_rope=target_rope,
            context_rope=target_rope,
        )
        hidden_states = hidden_states + self.cross_attn(
            self.norm_cross_attn(hidden_states),
            source,
            query_rope=target_rope,
            context_rope=source_rope,
        )
        return hidden_states + self.mlp(self.norm_mlp(hidden_states))


class AnimaLLMAdapter(nn.Module):
    """Map Qwen3 hidden states onto the T5-token sequence used by Anima."""

    def __init__(self, dim: int = 1024, layers: int = 6, heads: int = 16) -> None:
        super().__init__()
        self.dim = dim
        self.head_dim = dim // heads
        self.embed = nn.Embedding(32128, dim)
        self.blocks = nn.ModuleList([_AdapterBlock(dim) for _ in range(layers)])
        self.out_proj = nn.Linear(dim, dim)
        self.norm = nn.RMSNorm(dim, eps=1e-6)

    def _rope(
        self, length: int, *, device: torch.device, dtype: torch.dtype
    ) -> tuple[torch.Tensor, torch.Tensor]:
        positions = torch.arange(length, device=device, dtype=torch.float32)
        frequencies = 1.0 / (
            10000 ** (torch.arange(0, self.head_dim, 2, device=device, dtype=torch.float32) / self.head_dim)
        )
        angles = torch.outer(positions, frequencies)
        embedding = torch.cat((angles, angles), dim=-1).unsqueeze(0)
        return embedding.cos().to(dtype), embedding.sin().to(dtype)

    def forward(self, source_hidden_states: torch.Tensor, target_ids: torch.Tensor) -> torch.Tensor:
        hidden_states = self.embed(target_ids).to(source_hidden_states.dtype)
        target_rope = self._rope(
            hidden_states.shape[1], device=hidden_states.device, dtype=hidden_states.dtype
        )
        source_rope = self._rope(
            source_hidden_states.shape[1],
            device=source_hidden_states.device,
            dtype=source_hidden_states.dtype,
        )
        for block in self.blocks:
            hidden_states = block(
                hidden_states,
                source_hidden_states,
                target_rope=target_rope,
                source_rope=source_rope,
            )
        hidden_states = self.norm(self.out_proj(hidden_states))
        if hidden_states.shape[1] < 512:
            hidden_states = F.pad(hidden_states, (0, 0, 0, 512 - hidden_states.shape[1]))
        return hidden_states[:, :512]


def _load_prefixed_state(module: nn.Module, path: Path, prefix: str) -> None:
    state: dict[str, torch.Tensor] = {}
    with safe_open(path, framework="pt", device="cpu") as checkpoint:
        for key in checkpoint.keys():
            if key.startswith(prefix):
                state[key.removeprefix(prefix)] = checkpoint.get_tensor(key)
    result = module.load_state_dict(state, strict=True, assign=True)
    if result.missing_keys or result.unexpected_keys:
        raise RuntimeError(
            f"Anima state mismatch: missing={result.missing_keys}, unexpected={result.unexpected_keys}"
        )
    if any(parameter.is_meta for parameter in module.parameters()):
        raise RuntimeError("Anima state load left meta parameters unresolved")
    module.requires_grad_(False).eval()


def _load_adapter(path: Path) -> AnimaLLMAdapter:
    with init_empty_weights():
        adapter = AnimaLLMAdapter()
    _load_prefixed_state(adapter, path, "net.llm_adapter.")
    return adapter


def _load_qwen_encoder(path: Path, config_dir: Path) -> Qwen3Model:
    config = AutoConfig.from_pretrained(config_dir, local_files_only=True)
    with init_empty_weights():
        encoder = Qwen3Model(config)
    _load_prefixed_state(encoder, path, "model.")
    return encoder


class AnimaPipeline:
    """Small pipeline facade compatible with ``DiffusersImageBackend``."""

    def __init__(
        self,
        *,
        transformer: CosmosTransformer3DModel,
        adapter: AnimaLLMAdapter,
        text_encoder: Qwen3Model,
        qwen_tokenizer: Any,
        t5_tokenizer: T5TokenizerFast,
        vae: AutoencoderKLQwenImage,
        device: str,
        default_negative: str,
    ) -> None:
        self.transformer = transformer
        self.adapter = adapter
        self.text_encoder = text_encoder
        self.qwen_tokenizer = qwen_tokenizer
        self.t5_tokenizer = t5_tokenizer
        self.vae = vae
        self.device = torch.device(device)
        self.default_negative = default_negative
        self.image_processor = VaeImageProcessor(vae_scale_factor=8)
        self.scheduler = FlowMatchEulerDiscreteScheduler(shift=3.0)

    @classmethod
    def from_checkpoint(
        cls,
        *,
        checkpoint: Path,
        transformer_config_dir: Path,
        text_encoder_path: Path,
        qwen_config_dir: Path,
        t5_tokenizer_dir: Path,
        vae_dir: Path,
        device: str,
        default_negative: str,
    ) -> AnimaPipeline:
        dtype = torch.bfloat16
        previous_verbosity = diffusers_logging.get_verbosity()
        try:
            # The checkpoint also contains net.llm_adapter.*. Diffusers correctly
            # ignores those while converting the Cosmos core; suppress its very
            # large expected-unused-keys warning and load the adapter below.
            diffusers_logging.set_verbosity_error()
            transformer = CosmosTransformer3DModel.from_single_file(
                str(checkpoint),
                config=str(transformer_config_dir),
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
            )
        finally:
            diffusers_logging.set_verbosity(previous_verbosity)
        transformer.requires_grad_(False).eval()
        adapter = _load_adapter(checkpoint)
        text_encoder = _load_qwen_encoder(text_encoder_path, qwen_config_dir)
        qwen_tokenizer = AutoTokenizer.from_pretrained(qwen_config_dir, local_files_only=True)
        t5_tokenizer = T5TokenizerFast.from_pretrained(t5_tokenizer_dir, local_files_only=True, legacy=True)
        vae = AutoencoderKLQwenImage.from_pretrained(
            vae_dir,
            torch_dtype=dtype,
            local_files_only=True,
        )
        vae.requires_grad_(False).eval()
        if hasattr(vae, "enable_tiling"):
            vae.enable_tiling()
        return cls(
            transformer=transformer,
            adapter=adapter,
            text_encoder=text_encoder,
            qwen_tokenizer=qwen_tokenizer,
            t5_tokenizer=t5_tokenizer,
            vae=vae,
            device=device,
            default_negative=default_negative,
        )

    def _empty_cache(self) -> None:
        if self.device.type == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _all_modules(self) -> tuple[nn.Module, ...]:
        return self.transformer, self.adapter, self.text_encoder, self.vae

    def to(self, device: str | torch.device) -> AnimaPipeline:
        target = torch.device(device)
        for module in self._all_modules():
            module.to(target)
        self.device = target
        return self

    def enable_model_cpu_offload(self) -> None:
        # Generation performs explicit stage offload (encoder -> DiT -> VAE),
        # which is both more predictable and lighter than hook-based offload.
        self.maybe_free_model_hooks()

    def maybe_free_model_hooks(self) -> None:
        for module in self._all_modules():
            module.to("cpu")
        self._empty_cache()

    def _encode_one(self, prompt: str) -> torch.Tensor:
        qwen = self.qwen_tokenizer(
            prompt,
            return_tensors="pt",
            add_special_tokens=False,
            truncation=True,
            max_length=512,
        )
        target = self.t5_tokenizer(
            prompt,
            return_tensors="pt",
            add_special_tokens=True,
            truncation=True,
            max_length=512,
        )
        input_ids = qwen["input_ids"].to(self.device)
        attention_mask = qwen.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(self.device)
        source = self.text_encoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
            return_dict=True,
        ).last_hidden_state
        return self.adapter(source, target["input_ids"].to(self.device))

    def _encode_prompts(
        self, prompt: str, negative_prompt: str | None, guidance_scale: float
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        self.text_encoder.to(self.device)
        self.adapter.to(self.device)
        positive = self._encode_one(prompt)
        negative = None
        if guidance_scale != 1.0:
            negative = self._encode_one(negative_prompt or self.default_negative)
        self.text_encoder.to("cpu")
        self.adapter.to("cpu")
        self._empty_cache()
        return positive, negative

    @torch.inference_mode()
    def __call__(
        self,
        *,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 30,
        guidance_scale: float = 4.0,
        generator: torch.Generator | None = None,
        image: Any | None = None,
        strength: float = 0.55,
        callback_on_step_end: Callable | None = None,
        **_: Any,
    ) -> SimpleNamespace:
        if width % 64 or height % 64:
            raise ValueError("Anima width and height must be multiples of 64")
        if not (512 <= width <= 1536 and 512 <= height <= 1536):
            raise ValueError("Anima supports dimensions from 512 to 1536 pixels")

        positive, negative = self._encode_prompts(prompt, negative_prompt, guidance_scale)
        self.transformer.to(self.device)
        positive = positive.to(self.device)
        if negative is not None:
            negative = negative.to(self.device)

        latent_height, latent_width = height // 8, width // 8
        scheduler = FlowMatchEulerDiscreteScheduler(shift=3.0)
        scheduler.set_timesteps(num_inference_steps, device=self.device)
        timesteps = scheduler.timesteps
        if image is None:
            latents = torch.randn(
                (1, 16, 1, latent_height, latent_width),
                generator=generator,
                device=self.device,
                dtype=torch.float32,
            )
        else:
            # Anima reuses Qwen-Image's VAE. Encode the fitted source, normalize
            # with the same latent statistics used by Qwen, then enter the flow
            # schedule at the strength-selected sigma instead of pure noise.
            self.vae.to(self.device)
            source = self.image_processor.preprocess(image, height=height, width=width)
            source = source.to(device=self.device, dtype=self.vae.dtype)
            if source.dim() == 4:
                source = source.unsqueeze(2)
            encoded = self.vae.encode(source).latent_dist.sample(generator=generator)
            mean = torch.tensor(
                self.vae.config.latents_mean, device=self.device, dtype=encoded.dtype
            ).view(1, 16, 1, 1, 1)
            inv_std = 1.0 / torch.tensor(
                self.vae.config.latents_std, device=self.device, dtype=encoded.dtype
            ).view(1, 16, 1, 1, 1)
            encoded = (encoded - mean) * inv_std
            self.vae.to("cpu")
            self._empty_cache()
            strength = max(0.05, min(1.0, float(strength)))
            init_steps = min(num_inference_steps, max(1, round(num_inference_steps * strength)))
            start = max(0, num_inference_steps - init_steps)
            timesteps = scheduler.timesteps[start:]
            if hasattr(scheduler, "set_begin_index"):
                scheduler.set_begin_index(start)
            noise = torch.randn(
                encoded.shape,
                generator=generator,
                device=self.device,
                dtype=encoded.dtype,
            )
            latents = scheduler.scale_noise(encoded, timesteps[:1], noise).float()
        padding_mask = torch.zeros(
            (1, 1, latent_height, latent_width), device=self.device, dtype=torch.bfloat16
        )

        for step, timestep in enumerate(timesteps):
            model_input = latents.to(torch.bfloat16)
            # Anima is trained with ComfyUI's flow multiplier=1. Diffusers keeps
            # scheduler timesteps on its conventional 0..1000 scale, while the
            # Cosmos time embedder must receive the corresponding 0..1 sigma.
            model_timestep = (
                (timestep / scheduler.config.num_train_timesteps).expand(latents.shape[0]).to(torch.float32)
            )
            conditioned = self.transformer(
                hidden_states=model_input,
                timestep=model_timestep,
                encoder_hidden_states=positive,
                padding_mask=padding_mask,
                return_dict=False,
            )[0]
            if negative is not None:
                unconditioned = self.transformer(
                    hidden_states=model_input,
                    timestep=model_timestep,
                    encoder_hidden_states=negative,
                    padding_mask=padding_mask,
                    return_dict=False,
                )[0]
                model_output = unconditioned + guidance_scale * (conditioned - unconditioned)
            else:
                model_output = conditioned
            latents = scheduler.step(
                model_output.float(), timestep, latents, generator=generator, return_dict=False
            )[0]
            if callback_on_step_end is not None:
                callback_result = callback_on_step_end(self, step, timestep, {"latents": latents})
                if isinstance(callback_result, dict):
                    latents = callback_result.get("latents", latents)

        self.transformer.to("cpu")
        self._empty_cache()
        self.vae.to(self.device)
        mean = torch.tensor(self.vae.config.latents_mean, device=self.device).view(1, 16, 1, 1, 1)
        std = torch.tensor(self.vae.config.latents_std, device=self.device).view(1, 16, 1, 1, 1)
        decoded = self.vae.decode((latents * std + mean).to(dtype=self.vae.dtype), return_dict=False)[0]
        frame = decoded[:, :, 0].float()
        images = self.image_processor.postprocess(frame, output_type="pil")
        self.vae.to("cpu")
        self._empty_cache()
        return SimpleNamespace(images=images)
