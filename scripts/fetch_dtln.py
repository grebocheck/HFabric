#!/usr/bin/env python3
"""Fetch the optional breizhn/DTLN ONNX denoiser weights."""

from __future__ import annotations

from pathlib import Path
import sys
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402

FILES = (
    (
        "dtln_model_1.onnx",
        "https://github.com/breizhn/DTLN/raw/master/pretrained_model/model_1.onnx",
    ),
    (
        "dtln_model_2.onnx",
        "https://github.com/breizhn/DTLN/raw/master/pretrained_model/model_2.onnx",
    ),
)


def main() -> int:
    out_dir = settings.voice_pretrain_dir / "denoise"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Fetching optional DTLN denoiser weights.")
    print("Upstream: breizhn/DTLN, MIT license. These weights keep their upstream license.")
    print(f"Destination: {out_dir}")
    for filename, url in FILES:
        target = out_dir / filename
        tmp = target.with_suffix(target.suffix + ".tmp")
        print(f"Downloading {filename}...")
        urlretrieve(url, tmp)
        tmp.replace(target)
        print(f"  wrote {target} ({target.stat().st_size:,} bytes)")
    print("DTLN fetch complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
