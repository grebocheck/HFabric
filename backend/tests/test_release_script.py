from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def test_read_version_and_set_version():
    release = _load_release_module()
    init_text = '"""Package."""\n\n__version__ = "1.2.3"\n'

    assert release.read_version(init_text) == "1.2.3"
    assert release.set_version(init_text, "2.0.0") == '"""Package."""\n\n__version__ = "2.0.0"\n'


def test_extract_release_notes_reads_matching_section():
    release = _load_release_module()
    changelog = """# Changelog

## [Unreleased]

### Added
- Next thing.

## [1.2.3] - 2026-01-01

### Fixed
- Important fix.

## [1.2.2] - 2025-12-01

### Added
- Earlier thing.
"""

    assert release.extract_release_notes(changelog, "1.2.3") == "### Fixed\n- Important fix."
    with pytest.raises(ValueError, match="9.9.9"):
        release.extract_release_notes(changelog, "9.9.9")


def test_roll_changelog_dates_release_and_resets_unreleased():
    release = _load_release_module()
    changelog = """# Changelog

## [Unreleased]

### Added
- New release item.

## [1.2.3] - pre-release

### Fixed
- Existing release item.

[Unreleased]: https://github.com/grebocheck/HFabric/compare/v1.2.2...HEAD
[1.2.3]: https://github.com/grebocheck/HFabric/releases/tag/v1.2.3
"""

    rolled = release.roll_changelog(changelog, "1.2.3", "2026-06-16")

    assert "## [1.2.3] \u2014 2026-06-16" in rolled
    unreleased_body = rolled.split("## [Unreleased]", 1)[1].split("## [1.2.3]", 1)[0]
    assert "- New release item." not in unreleased_body
    assert "### Added\n\n### Changed" in unreleased_body
    notes = release.extract_release_notes(rolled, "1.2.3")
    assert "### Added\n- New release item." in notes
    assert "### Fixed\n- Existing release item." in notes
    assert "[Unreleased]: https://github.com/grebocheck/HFabric/compare/v1.2.3...HEAD" in rolled


def test_check_tag_main_uses_real_app_version(capsys):
    release = _load_release_module()
    root = Path(__file__).resolve().parents[2]
    init_text = (root / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    current = release.read_version(init_text)

    assert release.main(["check-tag", f"v{current}"]) == 0
    assert release.main(["check-tag", "v9.9.9"]) != 0
    captured = capsys.readouterr()
    assert "does not match app version" in captured.err


def test_notes_main_reads_real_changelog(capsys):
    release = _load_release_module()
    root = Path(__file__).resolve().parents[2]
    init_text = (root / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    current = release.read_version(init_text)

    assert release.main(["notes", current]) == 0
    captured = capsys.readouterr()
    assert "First version prepared for testing" in captured.out


def _load_release_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("hfabric_release_script", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
