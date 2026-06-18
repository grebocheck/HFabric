#!/usr/bin/env python3
"""Fetch the optional breizhn/DTLN ONNX denoiser weights."""

from __future__ import annotations

from pathlib import Path
import sys
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.voice_engine.assets import OPTIONAL_ASSET_SOURCES  # noqa: E402


def main() -> int:
    out_dir = settings.voice_pretrain_dir / "denoise"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Fetching optional DTLN denoiser weights.")
    print("Upstream: breizhn/DTLN, MIT license. These weights keep their upstream license.")
    print(f"Destination: {out_dir}")
    for source in OPTIONAL_ASSET_SOURCES["denoise_dtln"]:
        filename = source["filename"]
        url = source["url"]
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
