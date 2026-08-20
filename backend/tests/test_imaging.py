from __future__ import annotations

import json

from PIL import Image
import pytest

from app.util import imaging


def test_save_png_commits_png_and_sidecar_without_temporary_files(tmp_path):
    path = tmp_path / "image.png"
    imaging.save_png(Image.new("RGB", (8, 8), "red"), path, {"prompt": "test"})

    assert path.is_file()
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) == {"prompt": "test"}
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_save_png_removes_partial_bundle_when_commit_fails(tmp_path, monkeypatch):
    path = tmp_path / "image.png"
    real_replace = imaging.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return real_replace(source, destination)

    monkeypatch.setattr(imaging.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="disk full"):
        imaging.save_png(Image.new("RGB", (8, 8), "red"), path, {})

    assert not path.exists()
    assert not path.with_suffix(".json").exists()
    assert list(tmp_path.iterdir()) == []


def test_remove_image_records_stays_inside_outputs_root(tmp_path):
    outputs = tmp_path / "outputs"
    output = outputs / "day" / "image.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"png")
    output.with_suffix(".json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")

    imaging.remove_image_records(
        [{"path": str(output)}, {"path": str(outside)}],
        outputs,
    )

    assert not output.exists()
    assert not output.with_suffix(".json").exists()
    assert outside.read_bytes() == b"keep"
