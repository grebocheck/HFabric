"""Download the companion assets required by local Anima checkpoints.

Anima checkpoints contain the 2B DiT and LLM adapter, but intentionally omit
the Qwen3 0.6B text encoder, tokenizers, and Qwen-Image VAE. This script fetches
only those support files; it does not download another Anima checkpoint.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "models" / "image"
SUPPORT = IMAGE / "anima-support"


def download() -> list[Path]:
    paths: list[Path] = []
    paths.append(
        Path(
            hf_hub_download(
                repo_id="circlestone-labs/Anima",
                filename="split_files/text_encoders/qwen_3_06b_base.safetensors",
                local_dir=SUPPORT,
            )
        )
    )
    paths.append(
        Path(
            snapshot_download(
                repo_id="Qwen/Qwen3-0.6B-Base",
                local_dir=SUPPORT / "qwen3-0.6b",
                allow_patterns=[
                    "config.json",
                    "tokenizer*",
                    "vocab.json",
                    "merges.txt",
                    "added_tokens.json",
                    "special_tokens_map.json",
                    "chat_template.jinja",
                ],
            )
        )
    )
    paths.append(
        Path(
            snapshot_download(
                repo_id="google/t5-v1_1-xxl",
                local_dir=SUPPORT / "t5-tokenizer",
                allow_patterns=[
                    "tokenizer*",
                    "spiece.model",
                    "special_tokens_map.json",
                ],
            )
        )
    )
    paths.append(
        Path(
            snapshot_download(
                repo_id="Qwen/Qwen-Image-2512",
                local_dir=IMAGE / "qwen-image-2512",
                allow_patterns=[
                    "vae/config.json",
                    "vae/diffusion_pytorch_model.safetensors",
                ],
            )
        )
    )
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show destinations without downloading"
    )
    args = parser.parse_args()
    if args.dry_run:
        print(f"Anima Qwen3 encoder -> {SUPPORT}")
        print(f"Qwen3 tokenizer/config -> {SUPPORT / 'qwen3-0.6b'}")
        print(f"T5 tokenizer -> {SUPPORT / 't5-tokenizer'}")
        print(f"Qwen-Image VAE -> {IMAGE / 'qwen-image-2512' / 'vae'}")
        return 0
    for path in download():
        print(f"[done] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
