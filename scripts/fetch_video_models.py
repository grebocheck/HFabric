"""Pre-stage the P27 video-generation weights into ``models/video/``.

Standalone + resumable: run it any time, it skips what's already on disk
(``snapshot_download`` resumes partial files). It deliberately lives outside the
curated in-app catalog (``fetch_models.py``) for now — that integration is
ROADMAP P27.6. See ``docs/video-research.md`` for why these models were chosen.

Starter set (fits the 16 GB / RTX 5070 Ti box with bnb + offload at load):
  * LTX-Video        — fast default (diffusers components only, ~28 GB).
  * Wan 2.2 TI2V-5B  — quality tier (full diffusers repo, ~34 GB).
  * FramePack Hunyuan — long I2V composite: Hunyuan base components without the
    stock transformer (~16 GB), FramePack transformer (~26 GB), and SigLIP image
    encoder (~1 GB).

AnimateDiff (fallback) is intentionally NOT fetched here until the backend can
use it.

Usage:  .venv/Scripts/python.exe scripts/fetch_video_models.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "models" / "video"
LOG_PATH = ROOT / "data" / "logs" / "video_download.log"

# (repo_id, local subfolder, allow_patterns | None for whole repo)
#
# LTX-Video's repo root carries ~225 GB of single-file checkpoint variants we do
# NOT need; ``allow_patterns`` keeps only the diffusers subfolders that
# ``LTXPipeline.from_pretrained`` actually loads. Wan's diffusers repo is already
# lean, so we take it whole.
JOBS: list[tuple[str, str, list[str] | None]] = [
    (
        "Lightricks/LTX-Video",
        "ltx-video",
        [
            "model_index.json",
            "*.json",
            "transformer/*",
            "text_encoder/*",
            "tokenizer/*",
            "vae/*",
            "scheduler/*",
        ],
    ),
    (
        "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "wan2.2-ti2v-5b",
        None,
    ),
    (
        "hunyuanvideo-community/HunyuanVideo",
        "framepack-hunyuan-i2v/base",
        [
            "model_index.json",
            "scheduler/*",
            "text_encoder/*",
            "text_encoder_2/*",
            "tokenizer/*",
            "tokenizer_2/*",
            "vae/*",
        ],
    ),
    (
        "lllyasviel/FramePackI2V_HY",
        "framepack-hunyuan-i2v/transformer",
        None,
    ),
    (
        "lllyasviel/flux_redux_bfl",
        "framepack-hunyuan-i2v/redux",
        [
            "feature_extractor/*",
            "image_encoder/*",
        ],
    ),
]


def _log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    from huggingface_hub import snapshot_download

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    _log(f"=== video model fetch start -> {VIDEO_DIR} ===")

    failures: list[str] = []
    for repo_id, subdir, patterns in JOBS:
        dest = VIDEO_DIR / subdir
        dest.mkdir(parents=True, exist_ok=True)
        scope = "diffusers components" if patterns else "full repo"
        _log(f"downloading {repo_id} ({scope}) -> {dest}")
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(dest),
                allow_patterns=patterns,
                ignore_patterns=["media/*", "examples/*", "assets/*", "*.mp4", "*.gif", "*.png"],
            )
            _log(f"OK   {repo_id}")
        except Exception as exc:  # noqa: BLE001 - log and continue to the next model
            failures.append(repo_id)
            _log(f"FAIL {repo_id}: {type(exc).__name__}: {exc}")

    if failures:
        _log(f"=== done WITH FAILURES: {', '.join(failures)} ===")
        return 1
    _log("=== all video models present ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
