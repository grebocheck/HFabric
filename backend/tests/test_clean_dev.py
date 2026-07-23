from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from clean_dev import _inside, remove  # noqa: E402


def test_cleanup_guard_accepts_only_unprotected_descendants(tmp_path):
    cache = tmp_path / "backend" / "__pycache__"
    cache.mkdir(parents=True)

    assert _inside(cache.resolve(), tmp_path.resolve()) is True
    assert _inside(tmp_path.resolve(), tmp_path.resolve()) is False
    assert _inside((tmp_path / "data" / "__pycache__").resolve(), tmp_path.resolve()) is False
    assert _inside((tmp_path / "models" / "cache").resolve(), tmp_path.resolve()) is False
    assert _inside((tmp_path / ".env").resolve(), tmp_path.resolve()) is False


def test_cleanup_removes_allowlisted_cache_and_refuses_protected_data(tmp_path):
    cache = tmp_path / "backend" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"cache")
    remove(cache, tmp_path)
    assert not cache.exists()

    protected = tmp_path / "data" / "keep.txt"
    protected.parent.mkdir()
    protected.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe cleanup"):
        remove(protected, tmp_path)
    assert protected.read_text(encoding="utf-8") == "keep"
