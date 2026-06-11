"""RMVPE f0 extraction.

Attribution: RVC-Project/Retrieval-based-Voice-Conversion-WebUI, MIT License.
This module vendors the RMVPE E2E/DeepUnet inference model and replaces the
upstream librosa dependency with a local Slaney-style mel filterbank.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def _hz_to_mel(frequencies: np.ndarray, *, htk: bool = False) -> np.ndarray:
    frequencies = np.asanyarray(frequencies, dtype=np.float64)
    if htk:
        return 2595.0 * np.log10(1.0 + frequencies / 700.0)
    f_min = 0.0
    f_sp = 200.0 / 3
    mels = (frequencies - f_min) / f_sp
    min_log_hz = 1000.0
    min_log_mel = (min_log_hz - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    log_t = frequencies >= min_log_hz
    mels[log_t] = min_log_mel + np.log(frequencies[log_t] / min_log_hz) / logstep
    return mels


def _mel_to_hz(mels: np.ndarray, *, htk: bool = False) -> np.ndarray:
    mels = np.asanyarray(mels, dtype=np.float64)
    if htk:
        return 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
    f_min = 0.0
    f_sp = 200.0 / 3
    freqs = f_min + f_sp * mels
    min_log_hz = 1000.0
    min_log_mel = (min_log_hz - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    log_t = mels >= min_log_mel
    freqs[log_t] = min_log_hz * np.exp(logstep * (mels[log_t] - min_log_mel))
    return freqs


def mel(
    *,
    sr: int,
    n_fft: int,
    n_mels: int,
    fmin: float,
    fmax: float | None,
    htk: bool = False,
) -> np.ndarray:
    """Return a librosa-compatible Slaney-normalized mel filterbank."""
    if fmax is None:
        fmax = float(sr) / 2
    fftfreqs = np.linspace(0.0, float(sr) / 2, int(1 + n_fft // 2), dtype=np.float64)
    min_mel = _hz_to_mel(np.array([fmin], dtype=np.float64), htk=htk)[0]
    max_mel = _hz_to_mel(np.array([fmax], dtype=np.float64), htk=htk)[0]
    mel_points = np.linspace(min_mel, max_mel, n_mels + 2, dtype=np.float64)
    mel_f = _mel_to_hz(mel_points, htk=htk)
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fftfreqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0.0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2 : n_mels + 2] - mel_f[:n_mels])
    weights *= enorm[:, None]
    return weights.astype(np.float32)


class BiGRU(nn.Module):
    def __init__(self, input_features, hidden_features, num_layers):
        super().__init__()
        self.gru = nn.GRU(
            input_features,
            hidden_features,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
        )

    def forward(self, x):
        return self.gru(x)[0]


class ConvBlockRes(nn.Module):
    def __init__(self, in_channels, out_channels, momentum=0.01):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(
                in_channels=in_channels,
                out_channels=out_channels,
                kernel_size=(3, 3),
                stride=(1, 1),
                padding=(1, 1),
                bias=False,
            ),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
            nn.Conv2d(
                in_channels=out_channels,
                out_channels=out_channels,
                kernel_size=(3, 3),
                stride=(1, 1),
                padding=(1, 1),
                bias=False,
            ),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
        )
        if in_channels != out_channels:
            self.shortcut = nn.Conv2d(in_channels, out_channels, (1, 1))

    def forward(self, x: torch.Tensor):
        if not hasattr(self, "shortcut"):
            return self.conv(x) + x
        return self.conv(x) + self.shortcut(x)


class ResEncoderBlock(nn.Module):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        n_blocks=1,
        momentum=0.01,
    ):
        super().__init__()
        self.n_blocks = n_blocks
        self.conv = nn.ModuleList()
        self.conv.append(ConvBlockRes(in_channels, out_channels, momentum))
        for _ in range(n_blocks - 1):
            self.conv.append(ConvBlockRes(out_channels, out_channels, momentum))
        self.kernel_size = kernel_size
        if self.kernel_size is not None:
            self.pool = nn.AvgPool2d(kernel_size=kernel_size)

    def forward(self, x):
        for conv in self.conv:
            x = conv(x)
        if self.kernel_size is not None:
            return x, self.pool(x)
        return x


class Encoder(nn.Module):
    def __init__(
        self,
        in_channels,
        in_size,
        n_encoders,
        kernel_size,
        n_blocks,
        out_channels=16,
        momentum=0.01,
    ):
        super().__init__()
        self.n_encoders = n_encoders
        self.bn = nn.BatchNorm2d(in_channels, momentum=momentum)
        self.layers = nn.ModuleList()
        self.latent_channels = []
        for _ in range(self.n_encoders):
            self.layers.append(
                ResEncoderBlock(
                    in_channels,
                    out_channels,
                    kernel_size,
                    n_blocks,
                    momentum=momentum,
                )
            )
            self.latent_channels.append([out_channels, in_size])
            in_channels = out_channels
            out_channels *= 2
            in_size //= 2
        self.out_size = in_size
        self.out_channel = out_channels

    def forward(self, x: torch.Tensor):
        concat_tensors: List[torch.Tensor] = []
        x = self.bn(x)
        for layer in self.layers:
            t, x = layer(x)
            concat_tensors.append(t)
        return x, concat_tensors


class Intermediate(nn.Module):
    def __init__(self, in_channels, out_channels, n_inters, n_blocks, momentum=0.01):
        super().__init__()
        self.n_inters = n_inters
        self.layers = nn.ModuleList()
        self.layers.append(
            ResEncoderBlock(in_channels, out_channels, None, n_blocks, momentum)
        )
        for _ in range(self.n_inters - 1):
            self.layers.append(
                ResEncoderBlock(out_channels, out_channels, None, n_blocks, momentum)
            )

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class ResDecoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride, n_blocks=1, momentum=0.01):
        super().__init__()
        out_padding = (0, 1) if stride == (1, 2) else (1, 1)
        self.n_blocks = n_blocks
        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(
                in_channels=in_channels,
                out_channels=out_channels,
                kernel_size=(3, 3),
                stride=stride,
                padding=(1, 1),
                output_padding=out_padding,
                bias=False,
            ),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
        )
        self.conv2 = nn.ModuleList()
        self.conv2.append(ConvBlockRes(out_channels * 2, out_channels, momentum))
        for _ in range(n_blocks - 1):
            self.conv2.append(ConvBlockRes(out_channels, out_channels, momentum))

    def forward(self, x, concat_tensor):
        x = self.conv1(x)
        x = torch.cat((x, concat_tensor), dim=1)
        for conv2 in self.conv2:
            x = conv2(x)
        return x


class Decoder(nn.Module):
    def __init__(self, in_channels, n_decoders, stride, n_blocks, momentum=0.01):
        super().__init__()
        self.layers = nn.ModuleList()
        self.n_decoders = n_decoders
        for _ in range(self.n_decoders):
            out_channels = in_channels // 2
            self.layers.append(
                ResDecoderBlock(in_channels, out_channels, stride, n_blocks, momentum)
            )
            in_channels = out_channels

    def forward(self, x: torch.Tensor, concat_tensors: List[torch.Tensor]):
        for i, layer in enumerate(self.layers):
            x = layer(x, concat_tensors[-1 - i])
        return x


class DeepUnet(nn.Module):
    def __init__(
        self,
        kernel_size,
        n_blocks,
        en_de_layers=5,
        inter_layers=4,
        in_channels=1,
        en_out_channels=16,
    ):
        super().__init__()
        self.encoder = Encoder(
            in_channels,
            128,
            en_de_layers,
            kernel_size,
            n_blocks,
            en_out_channels,
        )
        self.intermediate = Intermediate(
            self.encoder.out_channel // 2,
            self.encoder.out_channel,
            inter_layers,
            n_blocks,
        )
        self.decoder = Decoder(
            self.encoder.out_channel,
            en_de_layers,
            kernel_size,
            n_blocks,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x, concat_tensors = self.encoder(x)
        x = self.intermediate(x)
        return self.decoder(x, concat_tensors)


class E2E0(nn.Module):
    def __init__(
        self,
        n_blocks,
        n_gru,
        kernel_size,
        en_de_layers=5,
        inter_layers=4,
        in_channels=1,
        en_out_channels=16,
    ):
        super().__init__()
        if not n_gru:
            raise NotImplementedError("RMVPE E2E0 without the BiGRU head is not implemented")
        self.unet = DeepUnet(
            kernel_size,
            n_blocks,
            en_de_layers,
            inter_layers,
            in_channels,
            en_out_channels,
        )
        self.cnn = nn.Conv2d(en_out_channels, 3, (3, 3), padding=(1, 1))
        self.fc = nn.Sequential(
            BiGRU(3 * 128, 256, n_gru),
            nn.Linear(512, 360),
            nn.Dropout(0.25),
            nn.Sigmoid(),
        )

    def forward(self, mel_spec):
        mel_spec = mel_spec.transpose(-1, -2).unsqueeze(1)
        x = self.cnn(self.unet(mel_spec)).transpose(1, 2).flatten(-2)
        return self.fc(x)


E2E = E2E0


class MelSpectrogram(nn.Module):
    def __init__(
        self,
        is_half,
        n_mel_channels,
        sampling_rate,
        win_length,
        hop_length,
        n_fft=None,
        mel_fmin=0,
        mel_fmax=None,
        clamp=1e-5,
    ):
        super().__init__()
        n_fft = win_length if n_fft is None else n_fft
        mel_basis = mel(
            sr=sampling_rate,
            n_fft=n_fft,
            n_mels=n_mel_channels,
            fmin=mel_fmin,
            fmax=mel_fmax,
            htk=True,
        )
        self.register_buffer("mel_basis", torch.from_numpy(mel_basis).float())
        self.hann_window = {}
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.win_length = win_length
        self.sampling_rate = sampling_rate
        self.n_mel_channels = n_mel_channels
        self.clamp = clamp
        self.is_half = is_half

    def forward(self, audio, keyshift=0, speed=1, center=True):
        factor = 2 ** (keyshift / 12)
        n_fft_new = int(np.round(self.n_fft * factor))
        win_length_new = int(np.round(self.win_length * factor))
        hop_length_new = int(np.round(self.hop_length * speed))
        key = f"{keyshift}_{audio.device}_{audio.dtype}"
        if key not in self.hann_window:
            self.hann_window[key] = torch.hann_window(
                win_length_new,
                dtype=audio.dtype,
                device=audio.device,
            )
        fft = torch.stft(
            audio,
            n_fft=n_fft_new,
            hop_length=hop_length_new,
            win_length=win_length_new,
            window=self.hann_window[key],
            center=center,
            return_complex=True,
        )
        magnitude = torch.sqrt(fft.real.pow(2) + fft.imag.pow(2))
        if keyshift != 0:
            size = self.n_fft // 2 + 1
            resize = magnitude.size(1)
            if resize < size:
                magnitude = F.pad(magnitude, (0, 0, 0, size - resize))
            magnitude = magnitude[:, :size, :] * self.win_length / win_length_new
        mel_output = torch.matmul(self.mel_basis.to(dtype=magnitude.dtype), magnitude)
        if self.is_half:
            mel_output = mel_output.half()
        return torch.log(torch.clamp(mel_output, min=self.clamp))


class RMVPE:
    def __init__(self, model_path: Path, device: str = "cpu") -> None:
        self.model_path = Path(model_path)
        self.device = torch.device(device)
        self.is_half = self.device.type == "cuda"
        self.model = E2E0(4, 1, (2, 2))
        checkpoint = torch.load(
            str(self.model_path),
            map_location=self.device if self.device.type == "cuda" else "cpu",
            weights_only=True,
        )
        if not isinstance(checkpoint, dict):
            raise ValueError(f"RMVPE checkpoint is not a state_dict: {self.model_path}")
        state = checkpoint.get("state_dict") if "state_dict" in checkpoint else checkpoint
        self.model.load_state_dict(state, strict=True)
        self.model = self.model.eval().to(self.device)
        if self.is_half:
            self.model = self.model.half()

        self.mel_extractor = MelSpectrogram(
            self.is_half,
            128,
            16000,
            1024,
            160,
            None,
            30,
            8000,
        ).to(self.device)
        self.idx = torch.arange(360, device=self.device)[None, None, :]
        self.idx_cents = self.idx * 20 + 1997.3794084376191

    def mel2hidden(self, mel_spec: torch.Tensor) -> torch.Tensor:
        n_frames = mel_spec.shape[-1]
        padded_frames = 32 * ((n_frames - 1) // 32 + 1)
        mel_spec = F.pad(mel_spec, (0, padded_frames - n_frames), mode="reflect")
        return self.model(mel_spec)[:, :n_frames]

    def decode(self, hidden: torch.Tensor, threshold: float):
        center = torch.argmax(hidden, dim=2, keepdim=True)
        start = torch.clip(center - 4, min=0)
        end = torch.clip(center + 5, max=360)
        idx_mask = (self.idx >= start) & (self.idx < end)
        weights = hidden * idx_mask
        product_sum = torch.sum(weights * self.idx_cents, dim=2)
        weight_sum = torch.sum(weights, dim=2)
        cents = product_sum / (weight_sum + (weight_sum == 0))
        f0 = 10 * 2 ** (cents / 1200)
        uv = hidden.max(dim=2)[0] < threshold
        return f0 * ~uv

    def to_local_average_cents(self, hidden: torch.Tensor) -> torch.Tensor:
        center = torch.argmax(hidden, dim=2, keepdim=True)
        start = torch.clip(center - 4, min=0)
        end = torch.clip(center + 5, max=360)
        idx_mask = (self.idx >= start) & (self.idx < end)
        weights = hidden * idx_mask
        product_sum = torch.sum(weights * self.idx_cents, dim=2)
        weight_sum = torch.sum(weights, dim=2)
        return product_sum / (weight_sum + (weight_sum == 0))

    @torch.no_grad()
    def infer_from_audio_t(self, audio: torch.Tensor, threshold: float = 0.03) -> torch.Tensor:
        mel_spec = self.mel_extractor(audio.unsqueeze(0), center=True)
        hidden = self.mel2hidden(mel_spec)
        return self.decode(hidden, threshold)

    @torch.no_grad()
    def infer_from_audio(self, audio, sr: int = 16000, threshold: float = 0.03):
        if int(sr) != 16000:
            raise ValueError("RMVPE expects 16 kHz audio; resample before calling infer_from_audio")
        y = np.asarray(audio, dtype=np.float32).reshape(-1)
        audio_t = torch.from_numpy(y).to(self.device)
        if self.is_half:
            audio_t = audio_t.half()
        f0 = self.infer_from_audio_t(audio_t, threshold=threshold)
        return f0.squeeze(0).detach().float().cpu().numpy().astype(np.float32)
