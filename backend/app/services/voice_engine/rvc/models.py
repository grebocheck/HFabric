"""Inference-only RVC synthesizers.

Attribution: RVC-Project/Retrieval-based-Voice-Conversion-WebUI, MIT License.
This module vendors the RVC v2 inference path used by standard ContentVec
checkpoints. Training-only modules such as posterior encoders and
discriminators are intentionally omitted so inference checkpoints without
``enc_q`` load with ``strict=True``.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import torch
from torch import nn
from torch.nn import Conv1d, ConvTranspose1d
from torch.nn import functional as F
from torch.nn.utils import remove_weight_norm, weight_norm

from . import attentions, commons, modules
from .commons import init_weights

logger = logging.getLogger(__name__)

SR_MAP = {"32k": 32000, "40k": 40000, "48k": 48000}


def _resolve_sr(sr: str | int | None) -> int:
    if isinstance(sr, int):
        return sr
    if isinstance(sr, str):
        if sr in SR_MAP:
            return SR_MAP[sr]
        if sr.endswith("k") and sr[:-1].isdigit():
            return int(sr[:-1]) * 1000
        try:
            return int(sr)
        except ValueError:
            pass
    return 40000


class TextEncoder(nn.Module):
    def __init__(
        self,
        in_channels,
        out_channels,
        hidden_channels,
        filter_channels,
        n_heads,
        n_layers,
        kernel_size,
        p_dropout,
        f0=True,
    ):
        super().__init__()
        self.out_channels = out_channels
        self.hidden_channels = hidden_channels
        self.filter_channels = filter_channels
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.kernel_size = kernel_size
        self.p_dropout = float(p_dropout)
        self.emb_phone = nn.Linear(in_channels, hidden_channels)
        self.sqrt_hidden_channels = math.sqrt(self.hidden_channels)
        self.lrelu = nn.LeakyReLU(0.1, inplace=True)
        if f0:
            self.emb_pitch = nn.Embedding(256, hidden_channels)
        self.encoder = attentions.Encoder(
            hidden_channels,
            filter_channels,
            n_heads,
            n_layers,
            kernel_size,
            float(p_dropout),
        )
        self.proj = nn.Conv1d(hidden_channels, out_channels * 2, 1)

    def forward(
        self,
        phone: torch.Tensor,
        pitch: Optional[torch.Tensor],
        lengths: torch.Tensor,
        skip_head: int = 0,
    ):
        if pitch is None:
            x = self.emb_phone(phone)
        else:
            x = self.emb_phone(phone) + self.emb_pitch(pitch)
        x = x * self.sqrt_hidden_channels
        x = self.lrelu(x)
        x = torch.transpose(x, 1, -1)
        x_mask = torch.unsqueeze(commons.sequence_mask(lengths, x.size(2)), 1).to(
            x.dtype
        )
        x = self.encoder(x * x_mask, x_mask)
        if skip_head:
            x = x[:, :, skip_head:]
            x_mask = x_mask[:, :, skip_head:]
        stats = self.proj(x) * x_mask
        m, logs = torch.split(stats, self.out_channels, dim=1)
        return m, logs, x_mask


class ResidualCouplingBlock(nn.Module):
    def __init__(
        self,
        channels,
        hidden_channels,
        kernel_size,
        dilation_rate,
        n_layers,
        n_flows=4,
        gin_channels=0,
    ):
        super().__init__()
        self.channels = channels
        self.hidden_channels = hidden_channels
        self.kernel_size = kernel_size
        self.dilation_rate = dilation_rate
        self.n_layers = n_layers
        self.n_flows = n_flows
        self.gin_channels = gin_channels

        self.flows = nn.ModuleList()
        for _ in range(n_flows):
            self.flows.append(
                modules.ResidualCouplingLayer(
                    channels,
                    hidden_channels,
                    kernel_size,
                    dilation_rate,
                    n_layers,
                    gin_channels=gin_channels,
                    mean_only=True,
                )
            )
            self.flows.append(modules.Flip())

    def forward(
        self,
        x: torch.Tensor,
        x_mask: torch.Tensor,
        g: Optional[torch.Tensor] = None,
        reverse: bool = False,
    ):
        if not reverse:
            for flow in self.flows:
                x, _ = flow(x, x_mask, g=g, reverse=reverse)
        else:
            for flow in reversed(self.flows):
                x, _ = flow.forward(x, x_mask, g=g, reverse=reverse)
        return x

    def remove_weight_norm(self):
        for i in range(self.n_flows):
            self.flows[i * 2].remove_weight_norm()


class Generator(nn.Module):
    def __init__(
        self,
        initial_channel,
        resblock,
        resblock_kernel_sizes,
        resblock_dilation_sizes,
        upsample_rates,
        upsample_initial_channel,
        upsample_kernel_sizes,
        gin_channels=0,
    ):
        super().__init__()
        self.num_kernels = len(resblock_kernel_sizes)
        self.num_upsamples = len(upsample_rates)
        self.conv_pre = Conv1d(initial_channel, upsample_initial_channel, 7, 1, padding=3)
        block = modules.ResBlock1 if resblock == "1" else modules.ResBlock2

        self.ups = nn.ModuleList()
        for i, (u, k) in enumerate(zip(upsample_rates, upsample_kernel_sizes)):
            self.ups.append(
                weight_norm(
                    ConvTranspose1d(
                        upsample_initial_channel // (2**i),
                        upsample_initial_channel // (2 ** (i + 1)),
                        k,
                        u,
                        padding=(k - u) // 2,
                    )
                )
            )

        self.resblocks = nn.ModuleList()
        for i in range(len(self.ups)):
            ch = upsample_initial_channel // (2 ** (i + 1))
            for k, d in zip(resblock_kernel_sizes, resblock_dilation_sizes):
                self.resblocks.append(block(ch, k, d))

        self.conv_post = Conv1d(ch, 1, 7, 1, padding=3, bias=False)
        self.ups.apply(init_weights)
        if gin_channels:
            self.cond = nn.Conv1d(gin_channels, upsample_initial_channel, 1)
        self.lrelu_slope = modules.LRELU_SLOPE

    def forward(
        self,
        x: torch.Tensor,
        g: Optional[torch.Tensor] = None,
        n_res: Optional[int] = None,
    ):
        if n_res is not None and n_res != x.shape[-1]:
            x = F.interpolate(x, size=n_res, mode="linear")
        x = self.conv_pre(x)
        if g is not None:
            x = x + self.cond(g)
        for i, up in enumerate(self.ups):
            x = F.leaky_relu(x, self.lrelu_slope, inplace=True)
            x = up(x)
            xs: Optional[torch.Tensor] = None
            start = i * self.num_kernels
            end = start + self.num_kernels
            for resblock in self.resblocks[start:end]:
                if xs is None:
                    xs = resblock(x)
                else:
                    xs = xs + resblock(x)
            assert isinstance(xs, torch.Tensor)
            x = xs / self.num_kernels
        x = F.leaky_relu(x, inplace=True)
        x = self.conv_post(x)
        return torch.tanh(x)

    def remove_weight_norm(self):
        for layer in self.ups:
            remove_weight_norm(layer)
        for layer in self.resblocks:
            layer.remove_weight_norm()


class SineGen(nn.Module):
    """Sine source generator used by NSF HiFi-GAN."""

    def __init__(
        self,
        samp_rate,
        harmonic_num=0,
        sine_amp=0.1,
        noise_std=0.003,
        voiced_threshold=0,
    ):
        super().__init__()
        self.sine_amp = sine_amp
        self.noise_std = noise_std
        self.harmonic_num = harmonic_num
        self.dim = self.harmonic_num + 1
        self.sampling_rate = samp_rate
        self.voiced_threshold = voiced_threshold
        self._rand_ini: Optional[torch.Tensor] = None

    def _f02uv(self, f0):
        uv = torch.ones_like(f0)
        uv = uv * (f0 > self.voiced_threshold)
        if uv.device.type == "privateuseone":
            uv = uv.float()
        return uv

    def _f02sine(self, f0, upp):
        a = torch.arange(1, upp + 1, dtype=f0.dtype, device=f0.device)
        rad = f0 / self.sampling_rate * a
        rad2 = torch.fmod(rad[:, :-1, -1:].float() + 0.5, 1.0) - 0.5
        rad_acc = rad2.cumsum(dim=1).fmod(1.0).to(f0)
        rad += F.pad(rad_acc, (0, 0, 1, 0), mode="constant")
        rad = rad.reshape(f0.shape[0], -1, 1)
        b = torch.arange(1, self.dim + 1, dtype=f0.dtype, device=f0.device).reshape(
            1, 1, -1
        )
        rad *= b
        # Deterministic per-instance harmonic phase offsets. Upstream draws
        # fresh random offsets on every call, which makes the realtime path
        # re-synthesize overlapping context with a different phase each chunk
        # (audible warble at the SOLA seams) without adding anything musically.
        if self._rand_ini is None or self._rand_ini.device != f0.device:
            generator = torch.Generator()
            generator.manual_seed(0x5F0_F0)
            rand_ini = torch.rand(1, 1, self.dim, generator=generator)
            rand_ini[..., 0] = 0
            self._rand_ini = rand_ini.to(device=f0.device)
        rad += self._rand_ini.to(dtype=f0.dtype)
        return torch.sin(2 * np.pi * rad)

    def forward(self, f0: torch.Tensor, upp: int):
        with torch.no_grad():
            f0 = f0.unsqueeze(-1)
            sine_waves = self._f02sine(f0, upp) * self.sine_amp
            uv = self._f02uv(f0)
            uv = F.interpolate(
                uv.transpose(2, 1),
                scale_factor=float(upp),
                mode="nearest",
            ).transpose(2, 1)
            noise_amp = uv * self.noise_std + (1 - uv) * self.sine_amp / 3
            noise = noise_amp * torch.randn_like(sine_waves)
            sine_waves = sine_waves * uv + noise
        return sine_waves, uv, noise


class SourceModuleHnNSF(nn.Module):
    def __init__(
        self,
        sampling_rate,
        harmonic_num=0,
        sine_amp=0.1,
        add_noise_std=0.003,
        voiced_threshod=0,
        is_half=False,
    ):
        super().__init__()
        self.sine_amp = sine_amp
        self.noise_std = add_noise_std
        self.is_half = is_half
        self.l_sin_gen = SineGen(
            sampling_rate,
            harmonic_num,
            sine_amp,
            add_noise_std,
            voiced_threshod,
        )
        self.l_linear = nn.Linear(harmonic_num + 1, 1)
        self.l_tanh = nn.Tanh()

    def forward(self, x: torch.Tensor, upp: int = 1):
        sine_wavs, uv, noise = self.l_sin_gen(x, upp)
        sine_wavs = sine_wavs.to(dtype=self.l_linear.weight.dtype)
        sine_merge = self.l_tanh(self.l_linear(sine_wavs))
        return sine_merge, noise, uv


class GeneratorNSF(nn.Module):
    def __init__(
        self,
        initial_channel,
        resblock,
        resblock_kernel_sizes,
        resblock_dilation_sizes,
        upsample_rates,
        upsample_initial_channel,
        upsample_kernel_sizes,
        gin_channels,
        sr,
        is_half=False,
    ):
        super().__init__()
        self.num_kernels = len(resblock_kernel_sizes)
        self.num_upsamples = len(upsample_rates)
        self.upp = math.prod(upsample_rates)
        self.f0_upsamp = nn.Upsample(scale_factor=self.upp)
        self.m_source = SourceModuleHnNSF(
            sampling_rate=sr,
            harmonic_num=0,
            is_half=is_half,
        )
        self.noise_convs = nn.ModuleList()
        self.conv_pre = Conv1d(initial_channel, upsample_initial_channel, 7, 1, padding=3)
        block = modules.ResBlock1 if resblock == "1" else modules.ResBlock2

        self.ups = nn.ModuleList()
        for i, (u, k) in enumerate(zip(upsample_rates, upsample_kernel_sizes)):
            c_cur = upsample_initial_channel // (2 ** (i + 1))
            self.ups.append(
                weight_norm(
                    ConvTranspose1d(
                        upsample_initial_channel // (2**i),
                        c_cur,
                        k,
                        u,
                        padding=(k - u) // 2,
                    )
                )
            )
            if i + 1 < len(upsample_rates):
                stride_f0 = math.prod(upsample_rates[i + 1 :])
                self.noise_convs.append(
                    Conv1d(
                        1,
                        c_cur,
                        kernel_size=stride_f0 * 2,
                        stride=stride_f0,
                        padding=stride_f0 // 2,
                    )
                )
            else:
                self.noise_convs.append(Conv1d(1, c_cur, kernel_size=1))

        self.resblocks = nn.ModuleList()
        for i in range(len(self.ups)):
            ch = upsample_initial_channel // (2 ** (i + 1))
            for k, d in zip(resblock_kernel_sizes, resblock_dilation_sizes):
                self.resblocks.append(block(ch, k, d))

        self.conv_post = Conv1d(ch, 1, 7, 1, padding=3, bias=False)
        self.ups.apply(init_weights)
        if gin_channels:
            self.cond = nn.Conv1d(gin_channels, upsample_initial_channel, 1)
        self.lrelu_slope = modules.LRELU_SLOPE

    def forward(
        self,
        x: torch.Tensor,
        f0: torch.Tensor,
        g: Optional[torch.Tensor] = None,
        n_res: Optional[int] = None,
    ):
        har_source, _noise, _uv = self.m_source(f0, self.upp)
        har_source = har_source.transpose(1, 2)
        if n_res is not None:
            n = n_res * self.upp
            if n != har_source.shape[-1]:
                har_source = F.interpolate(har_source, size=n, mode="linear")
            if n_res != x.shape[-1]:
                x = F.interpolate(x, size=n_res, mode="linear")
        x = self.conv_pre(x)
        if g is not None:
            x = x + self.cond(g)
        for i, (up, noise_conv) in enumerate(zip(self.ups, self.noise_convs)):
            x = F.leaky_relu(x, self.lrelu_slope, inplace=True)
            x = up(x)
            x = x + noise_conv(har_source)
            xs: Optional[torch.Tensor] = None
            start = i * self.num_kernels
            end = start + self.num_kernels
            for resblock in self.resblocks[start:end]:
                if xs is None:
                    xs = resblock(x)
                else:
                    xs = xs + resblock(x)
            assert isinstance(xs, torch.Tensor)
            x = xs / self.num_kernels
        x = F.leaky_relu(x, inplace=True)
        x = self.conv_post(x)
        return torch.tanh(x)

    def remove_weight_norm(self):
        for layer in self.ups:
            remove_weight_norm(layer)
        for layer in self.resblocks:
            layer.remove_weight_norm()


class _BaseSynthesizer(nn.Module):
    def __init__(
        self,
        spec_channels,
        segment_size,
        inter_channels,
        hidden_channels,
        filter_channels,
        n_heads,
        n_layers,
        kernel_size,
        p_dropout,
        resblock,
        resblock_kernel_sizes,
        resblock_dilation_sizes,
        upsample_rates,
        upsample_initial_channel,
        upsample_kernel_sizes,
        spk_embed_dim,
        gin_channels,
        sr,
        *,
        is_half=False,
        f0=True,
        phone_channels=768,
    ):
        super().__init__()
        sr = _resolve_sr(sr)
        self.sample_rate = sr
        self.spec_channels = spec_channels
        self.inter_channels = inter_channels
        self.hidden_channels = hidden_channels
        self.filter_channels = filter_channels
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.kernel_size = kernel_size
        self.p_dropout = float(p_dropout)
        self.resblock = resblock
        self.resblock_kernel_sizes = resblock_kernel_sizes
        self.resblock_dilation_sizes = resblock_dilation_sizes
        self.upsample_rates = upsample_rates
        self.upsample_initial_channel = upsample_initial_channel
        self.upsample_kernel_sizes = upsample_kernel_sizes
        self.segment_size = segment_size
        self.gin_channels = gin_channels
        self.spk_embed_dim = spk_embed_dim
        self.enc_p = TextEncoder(
            phone_channels,
            inter_channels,
            hidden_channels,
            filter_channels,
            n_heads,
            n_layers,
            kernel_size,
            float(p_dropout),
            f0=f0,
        )
        if f0:
            self.dec = GeneratorNSF(
                inter_channels,
                resblock,
                resblock_kernel_sizes,
                resblock_dilation_sizes,
                upsample_rates,
                upsample_initial_channel,
                upsample_kernel_sizes,
                gin_channels=gin_channels,
                sr=sr,
                is_half=is_half,
            )
        else:
            self.dec = Generator(
                inter_channels,
                resblock,
                resblock_kernel_sizes,
                resblock_dilation_sizes,
                upsample_rates,
                upsample_initial_channel,
                upsample_kernel_sizes,
                gin_channels=gin_channels,
            )
        self.flow = ResidualCouplingBlock(
            inter_channels,
            hidden_channels,
            5,
            1,
            3,
            gin_channels=gin_channels,
        )
        self.emb_g = nn.Embedding(self.spk_embed_dim, gin_channels)
        logger.debug("gin_channels: %s, spk_embed_dim: %s", gin_channels, spk_embed_dim)

    def remove_weight_norm(self):
        self.dec.remove_weight_norm()
        self.flow.remove_weight_norm()


class SynthesizerTrnMs768NSFsid(_BaseSynthesizer):
    """RVC v2 ContentVec-768 f0 synthesizer."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("phone_channels", 768)
        kwargs.setdefault("f0", True)
        super().__init__(*args, **kwargs)

    @torch.no_grad()
    def infer(
        self,
        phone: torch.Tensor,
        phone_lengths: torch.Tensor,
        pitch: torch.Tensor,
        nsff0: torch.Tensor,
        sid: torch.Tensor,
        skip_head: int = 0,
        return_length: Optional[int] = None,
        formant_length: Optional[int] = None,
        noise_scale: float = 0.66666,
        latent_noise: Optional[torch.Tensor] = None,
    ):
        if return_length is None:
            return_length = int(phone_lengths.reshape(-1)[0].item()) - int(skip_head)
        g = self.emb_g(sid).unsqueeze(-1)
        flow_head = max(int(skip_head) - 24, 0)
        dec_head = int(skip_head) - flow_head
        m_p, logs_p, x_mask = self.enc_p(phone, pitch, phone_lengths, flow_head)
        scale = max(0.0, float(noise_scale))
        if scale <= 0.0:
            latent = torch.zeros_like(m_p)
        elif latent_noise is not None:
            # Realtime passes a noise buffer pinned to absolute frame positions
            # (newest frame last) so re-synthesizing the overlapping context
            # uses the same latent sample for the same audio frame each chunk.
            latent = latent_noise[:, :, -m_p.size(-1) :].to(dtype=m_p.dtype) * scale
        else:
            latent = torch.randn_like(m_p) * scale
        z_p = (m_p + torch.exp(logs_p) * latent) * x_mask
        z = self.flow(z_p, x_mask, g=g, reverse=True)
        z = z[:, :, dec_head : dec_head + return_length]
        x_mask = x_mask[:, :, dec_head : dec_head + return_length]
        nsff0 = nsff0[:, int(skip_head) : int(skip_head) + return_length]
        audio = self.dec(z * x_mask, nsff0, g=g, n_res=formant_length)
        return audio, x_mask, (z, z_p, m_p, logs_p)


class SynthesizerTrnMs768NSFsid_nono(_BaseSynthesizer):
    """RVC v2 ContentVec-768 no-f0 synthesizer."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("phone_channels", 768)
        kwargs.setdefault("f0", False)
        super().__init__(*args, **kwargs)

    @torch.no_grad()
    def infer(
        self,
        phone: torch.Tensor,
        phone_lengths: torch.Tensor,
        sid: torch.Tensor,
        skip_head: int = 0,
        return_length: Optional[int] = None,
        formant_length: Optional[int] = None,
        noise_scale: float = 0.66666,
        latent_noise: Optional[torch.Tensor] = None,
    ):
        if return_length is None:
            return_length = int(phone_lengths.reshape(-1)[0].item()) - int(skip_head)
        g = self.emb_g(sid).unsqueeze(-1)
        flow_head = max(int(skip_head) - 24, 0)
        dec_head = int(skip_head) - flow_head
        m_p, logs_p, x_mask = self.enc_p(phone, None, phone_lengths, flow_head)
        scale = max(0.0, float(noise_scale))
        if scale <= 0.0:
            latent = torch.zeros_like(m_p)
        elif latent_noise is not None:
            latent = latent_noise[:, :, -m_p.size(-1) :].to(dtype=m_p.dtype) * scale
        else:
            latent = torch.randn_like(m_p) * scale
        z_p = (m_p + torch.exp(logs_p) * latent) * x_mask
        z = self.flow(z_p, x_mask, g=g, reverse=True)
        z = z[:, :, dec_head : dec_head + return_length]
        x_mask = x_mask[:, :, dec_head : dec_head + return_length]
        audio = self.dec(z * x_mask, g=g, n_res=formant_length)
        return audio, x_mask, (z, z_p, m_p, logs_p)


class SynthesizerTrnMs256NSFsid:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        raise NotImplementedError(
            "RVC v1/ContentVec-256 inference is not implemented; use an RVC v2/768 checkpoint"
        )


class SynthesizerTrnMs256NSFsid_nono:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        raise NotImplementedError(
            "RVC v1/ContentVec-256 no-f0 inference is not implemented; use an RVC v2/768 checkpoint"
        )
