"""Generate a JSON diagnostics report for a paired live voice recording.

Usage:
    .venv/Scripts/python scripts/voice_quality_report.py \
        --raw raw.wav --converted output.wav --chunk-ms 90
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.voice_engine.quality import compare_recording_pair  # noqa: E402


def _mono(path: Path):
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    return np.mean(audio, axis=1).astype(np.float32), int(sample_rate)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze raw/output WAV captures for clipping, silence, duration drift, and chunk seams."
    )
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--converted", type=Path, required=True)
    parser.add_argument("--chunk-ms", type=float, default=90.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    raw, raw_rate = _mono(args.raw)
    converted, converted_rate = _mono(args.converted)
    if raw_rate != converted_rate:
        parser.error(
            f"sample rates differ: raw={raw_rate} Hz, converted={converted_rate} Hz"
        )
    report = compare_recording_pair(
        raw,
        converted,
        raw_rate,
        chunk_ms=args.chunk_ms,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
