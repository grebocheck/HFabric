#!/usr/bin/env python3
"""Small release helper for HFabric tags and changelog notes."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import difflib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "backend" / "app" / "__init__.py"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/grebocheck/HFabric"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INIT_VERSION_RE = re.compile(
    r"^(__version__\s*=\s*)([\"'])([^\"']+)([\"'])(\s*)$",
    re.MULTILINE,
)
CHANGELOG_HEADING_RE = re.compile(r"^## \[([^\]]+)\][^\n]*(?:\n|$)", re.MULTILINE)
REFERENCE_RE = re.compile(r"^\[[^\]]+\]:\s+\S+.*$")
DASH = "\u2014"

UNRELEASED_STUB = """### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security"""


def read_version(init_text: str) -> str:
    """Read ``__version__`` from backend/app/__init__.py text."""
    match = INIT_VERSION_RE.search(init_text)
    if not match:
        raise ValueError("could not find __version__ assignment")
    version = match.group(3)
    _validate_version(version)
    return version


def set_version(init_text: str, new: str) -> str:
    """Return init text with ``__version__`` replaced by ``new``."""
    _validate_version(new)

    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{new}{match.group(4)}{match.group(5)}"

    updated, count = INIT_VERSION_RE.subn(replace, init_text, count=1)
    if count != 1:
        raise ValueError("could not find __version__ assignment")
    return updated


def extract_release_notes(changelog_text: str, version: str) -> str:
    """Return the body of the changelog section for ``version``."""
    _validate_version(version)
    text = _normalize_newlines(changelog_text)
    section = _find_section(text, version)
    if section is None:
        raise ValueError(f"release notes for version '{version}' not found")
    body = text[section.body_start:section.end]
    body, _references = _split_reference_footer(body)
    return body.strip()


def roll_changelog(changelog_text: str, version: str, date: str) -> str:
    """Fold Unreleased notes into a dated release section."""
    _validate_version(version)
    _validate_date(date)
    newline = _detect_newline(changelog_text)
    text = _normalize_newlines(changelog_text)
    main_text, references = _split_reference_footer(text)

    unreleased = _find_section(main_text, "Unreleased")
    if unreleased is None:
        raise ValueError("could not find [Unreleased] changelog section")

    version_section = _find_section(main_text, version)
    unreleased_body = main_text[unreleased.body_start:unreleased.end].strip()
    version_body = ""
    if version_section is not None:
        version_body = main_text[version_section.body_start:version_section.end].strip()
    release_body = _combine_bodies(unreleased_body, version_body)

    updated = _replace_section(
        main_text,
        unreleased,
        "## [Unreleased]",
        UNRELEASED_STUB,
    )

    version_heading = f"## [{version}] {DASH} {date}"
    if version_section is not None:
        current = _find_section(updated, version)
        if current is None:
            raise ValueError(f"could not find [{version}] changelog section")
        updated = _replace_section(updated, current, version_heading, release_body)
    else:
        current_unreleased = _find_section(updated, "Unreleased")
        if current_unreleased is None:
            raise ValueError("could not find [Unreleased] changelog section")
        release_section = f"{version_heading}\n\n{release_body.strip()}\n"
        updated = _insert_after_section(updated, current_unreleased, release_section)

    updated = _update_reference_links(updated, references, version)
    if newline != "\n":
        updated = updated.replace("\n", newline)
    return updated


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("current", help="Print the current app version.")

    check_tag = subparsers.add_parser("check-tag", help="Verify a tag matches the app version.")
    check_tag.add_argument("tag", help="Tag to verify, such as v0.1.0.")

    notes = subparsers.add_parser("notes", help="Print release notes for a version.")
    notes.add_argument("version", help="Version to read, such as 0.1.0.")

    prepare = subparsers.add_parser("prepare", help="Prepare version and changelog text.")
    prepare.add_argument("version", help="Version to prepare, such as 0.1.0.")
    prepare.add_argument("--date", help="Release date as YYYY-MM-DD; defaults to today in UTC.")
    prepare.add_argument("--dry-run", action="store_true", help="Print a diff and write nothing.")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command == "current":
            print(read_version(INIT_PATH.read_text(encoding="utf-8")))
            return 0
        if args.command == "check-tag":
            return _check_tag(args.tag)
        if args.command == "notes":
            return _notes(args.version)
        if args.command == "prepare":
            release_date = args.date or datetime.now(UTC).date().isoformat()
            return _prepare(args.version, release_date, args.dry_run)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"error: unknown command '{args.command}'", file=sys.stderr)
    return 2


class _Section:
    def __init__(self, start: int, body_start: int, end: int) -> None:
        self.start = start
        self.body_start = body_start
        self.end = end


def _check_tag(tag: str) -> int:
    if not TAG_RE.fullmatch(tag):
        print(f"error: invalid tag '{tag}'; expected vX.Y.Z", file=sys.stderr)
        return 2
    version = read_version(INIT_PATH.read_text(encoding="utf-8"))
    expected = f"v{version}"
    if tag != expected:
        print(
            f"error: tag '{tag}' does not match app version '{version}' "
            f"(expected '{expected}')",
            file=sys.stderr,
        )
        return 1
    return 0


def _notes(version: str) -> int:
    if not VERSION_RE.fullmatch(version):
        print(f"error: invalid version '{version}'; expected X.Y.Z", file=sys.stderr)
        return 2
    notes = extract_release_notes(CHANGELOG_PATH.read_text(encoding="utf-8"), version)
    if notes:
        print(notes)
    return 0


def _prepare(version: str, release_date: str, dry_run: bool) -> int:
    if not VERSION_RE.fullmatch(version):
        print(f"error: invalid version '{version}'; expected X.Y.Z", file=sys.stderr)
        return 2
    if not DATE_RE.fullmatch(release_date):
        print(f"error: invalid date '{release_date}'; expected YYYY-MM-DD", file=sys.stderr)
        return 2

    old_init = INIT_PATH.read_text(encoding="utf-8")
    old_changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    new_init = set_version(old_init, version)
    new_changelog = roll_changelog(old_changelog, version, release_date)

    if dry_run:
        output = (
            _unified_diff("backend/app/__init__.py", old_init, new_init)
            + _unified_diff("CHANGELOG.md", old_changelog, new_changelog)
        )
        sys.stdout.write(output or "No changes.\n")
        return 0

    INIT_PATH.write_text(new_init, encoding="utf-8")
    CHANGELOG_PATH.write_text(new_changelog, encoding="utf-8")
    return 0


def _validate_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid version '{version}'; expected X.Y.Z")


def _validate_date(date: str) -> None:
    if not DATE_RE.fullmatch(date):
        raise ValueError(f"invalid date '{date}'; expected YYYY-MM-DD")


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _find_section(text: str, name: str) -> _Section | None:
    matches = list(CHANGELOG_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1) != name:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return _Section(match.start(), match.end(), end)
    return None


def _replace_section(text: str, section: _Section, heading: str, body: str) -> str:
    section_text = f"{heading}\n\n{body.strip()}\n\n"
    prefix = text[:section.start].rstrip()
    suffix = text[section.end:].lstrip("\n")
    if prefix:
        return f"{prefix}\n\n{section_text}{suffix}"
    return section_text + suffix


def _insert_after_section(text: str, section: _Section, section_text: str) -> str:
    before = text[:section.end].rstrip()
    after = text[section.end:].lstrip("\n")
    suffix = f"\n\n{after}" if after else ""
    return f"{before}\n\n{section_text.strip()}\n{suffix}"


def _combine_bodies(*bodies: str) -> str:
    parts = [body.strip() for body in bodies if body.strip()]
    if not parts:
        return "- No changes recorded."
    return "\n\n".join(parts)


def _split_reference_footer(text: str) -> tuple[str, str]:
    stripped = text.rstrip("\n")
    if not stripped:
        return "", ""

    lines = stripped.split("\n")
    cursor = len(lines)
    while cursor > 0 and not lines[cursor - 1].strip():
        cursor -= 1

    end = cursor
    found_reference = False
    while cursor > 0:
        line = lines[cursor - 1]
        if REFERENCE_RE.fullmatch(line):
            found_reference = True
            cursor -= 1
            continue
        if found_reference and not line.strip():
            cursor -= 1
            continue
        break

    if not found_reference:
        return stripped, ""

    main_text = "\n".join(lines[:cursor]).rstrip()
    references = "\n".join(line for line in lines[cursor:end] if line.strip()).strip()
    return main_text, references


def _update_reference_links(main_text: str, references: str, version: str) -> str:
    unreleased = f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD"
    release = f"[{version}]: {REPO_URL}/releases/tag/v{version}"

    updated_lines: list[str] = []
    saw_unreleased = False
    saw_release = False
    for line in references.splitlines():
        if line.startswith("[Unreleased]:"):
            updated_lines.append(unreleased)
            saw_unreleased = True
        elif line.startswith(f"[{version}]:"):
            updated_lines.append(release)
            saw_release = True
        elif line.strip():
            updated_lines.append(line)

    if not saw_unreleased:
        updated_lines.insert(0, unreleased)
    if not saw_release:
        updated_lines.append(release)

    reference_text = "\n".join(updated_lines)
    return f"{main_text.rstrip()}\n\n{reference_text}\n"


def _unified_diff(path: str, old: str, new: str) -> str:
    if old == new:
        return ""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
