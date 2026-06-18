#!/usr/bin/env python3
"""Fetch the shared RVC pretrain assets (ContentVec + RMVPE) for the voice engine.

Voice models you drop into models/voice/ all share a ContentVec encoder and (for
the quality pitch path) RMVPE; without them no voice model can run. This places
them in models/voice/pretrain/ so the Voice tab is ready. The in-app Voice tab has
a one-click "Download voice assets" button that does the same thing.
"""

from __future__ import annotations

from pathlib import Path
import sys
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.voice_engine.assets import ASSET_SOURCES  # noqa: E402


def main() -> int:
    out_dir = settings.voice_pretrain_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Fetching shared RVC pretrain assets (ContentVec + RMVPE).")
    print("Upstream: RVC-compatible ContentVec/RMVPE assets. These weights keep their upstream license.")
    print(f"Destination: {out_dir}")
    failures = 0
    for name, source in ASSET_SOURCES.items():
        target = out_dir / source["filename"]
        if target.is_file():
            print(f"  {source['filename']} already present, skipping.")
            continue
        tmp = target.with_suffix(target.suffix + ".tmp")
        print(f"Downloading {name} ({source['filename']}, ~{source['approx_mb']} MB)...")
        try:
            urlretrieve(source["url"], tmp)
            tmp.replace(target)
            print(f"  wrote {target} ({target.stat().st_size:,} bytes)")
        except Exception as exc:  # noqa: BLE001 - report and continue with the rest
            tmp.unlink(missing_ok=True)
            failures += 1
            print(f"  FAILED: {exc}")
            print("  Retry from the Voice tab, or rerun setup.bat all / ./setup.sh all when the network is stable.")
            print(f"  Source kept for diagnostics: {source['url']}")
    if failures:
        print("Done with {0} failure(s); retry via the Voice tab or setup.bat all / ./setup.sh all.".format(failures))
        return 1
    print("Voice asset fetch complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
