#!/usr/bin/env python3
"""Pre-quantize the Qwen-Image text encoder (Qwen2.5-VL) to 4-bit on disk, once.

The Nunchaku fp4 Qwen-Image path keeps the ~13 GB fp4 transformer in RAM while
Diffusers' bitsandbytes loader quantizes the bf16 Qwen2.5-VL text encoder on the
fly — that transiently materializes the full ~16 GB bf16 encoder, spiking total
RAM past 32 GB (near OOM) and adding ~50 s to every load. Quantizing the encoder
once to a small (~5 GB) nf4 checkpoint removes both problems: subsequent loads
read the pre-quantized weights directly.

    .venv\\Scripts\\python.exe scripts/prequant_qwen_text_encoder.py

Output: models/image/qwen-image-2512/text_encoder_nf4/  (auto-detected by the
DiffusersImageBackend nunchaku Qwen path).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    import torch  # noqa: PLC0415
    from transformers import AutoModel, BitsAndBytesConfig  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    src = settings.qwen_image_base_repo / "text_encoder"
    dst = settings.qwen_image_base_repo / "text_encoder_nf4"
    if not src.is_dir():
        print(f"text encoder not found at {src}", file=sys.stderr)
        return 2
    if dst.is_dir() and any(dst.glob("*.safetensors")):
        print(f"[skip] already pre-quantized at {dst}")
        return 0

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print(f"[load] {src} -> nf4 (this loads bf16 shards once; ~16 GB RAM peak)", flush=True)
    model = AutoModel.from_pretrained(
        str(src), quantization_config=bnb, torch_dtype=torch.bfloat16
    )
    dst.mkdir(parents=True, exist_ok=True)
    print(f"[save] {dst}", flush=True)
    model.save_pretrained(str(dst))
    size_gb = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1e9
    print(f"[done] {dst} ({size_gb:.2f} GB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
