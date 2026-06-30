from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from video_vram_probe import family_for_model, require_backend  # noqa: E402

from app.core.enums import ModelFamily  # noqa: E402


@dataclass
class FakeRuntime:
    backend: str
    torch_device: str = "cuda"


def test_family_for_model_recognizes_video_fallbacks():
    assert family_for_model("framepack-hunyuan-i2v") is ModelFamily.HUNYUAN_VIDEO
    assert family_for_model("cogvideo-2b") is ModelFamily.COGVIDEO
    assert family_for_model("wan2.2-ti2v-5b") is ModelFamily.WAN_VIDEO
    assert family_for_model("ltx-video") is ModelFamily.LTX_VIDEO


def test_require_backend_allows_matching_or_unset_backend():
    runtime = FakeRuntime("rocm")

    require_backend(runtime, None)  # type: ignore[arg-type]
    require_backend(runtime, "ROCM")  # type: ignore[arg-type]


def test_require_backend_rejects_wrong_hardware_path():
    with pytest.raises(RuntimeError, match="REQUIRE_BACKEND"):
        require_backend(FakeRuntime("cpu"), "mps")  # type: ignore[arg-type]
