"""List or remove reproducible development artefacts.

Dry-run is the default. The allowlist is intentionally narrow and the safety
guard rejects data, models, credentials, managed tools and repository metadata.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".tools", ".venv", "bin", "data", "models", "node_modules"}
EXACT_DIRS = {
    ROOT / ".mypy_cache",
    ROOT / ".pytest_cache",
    ROOT / ".ruff_cache",
    ROOT / "backend" / ".mypy_cache",
    ROOT / "backend" / ".pytest_cache",
    ROOT / "backend" / ".ruff_cache",
    ROOT / "backend" / "htmlcov",
    ROOT / "frontend" / "coverage",
    ROOT / "frontend" / "dist",
    ROOT / "frontend" / "playwright-report",
    ROOT / "frontend" / "test-results",
}
EXACT_FILES = {
    ROOT / ".coverage",
    ROOT / "backend" / ".coverage",
    ROOT / "backend" / "coverage.json",
    ROOT / "backend" / "coverage.xml",
    ROOT / "backend" / "coverage.txt",
    ROOT / "backend" / "coverage-summary.md",
    ROOT / "backend" / "test-results.xml",
    ROOT / "frontend" / "bundle-sizes.json",
    ROOT / "frontend" / "preview.log",
    ROOT / "frontend" / "vitest.txt",
}
PROTECTED_PARTS = {".git", ".tools", ".venv", "bin", "data", "models", "node_modules"}
PROTECTED_NAMES = {".env", ".env.local"}


def candidates(root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    out = {
        path.resolve()
        for path in [*EXACT_DIRS, *EXACT_FILES]
        if path.exists() and _inside(path.resolve(), root)
    }
    for directory, dirnames, _filenames in os.walk(root):
        current = Path(directory)
        for name in list(dirnames):
            if name == "__pycache__":
                out.add((current / name).resolve())
                dirnames.remove(name)
            elif name in SKIP_DIRS:
                dirnames.remove(name)
    return sorted(out, key=lambda item: (len(item.parts), str(item)), reverse=True)


def _inside(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return (
        bool(relative.parts)
        and not PROTECTED_PARTS.intersection(relative.parts)
        and path.name not in PROTECTED_NAMES
    )


def remove(path: Path, root: Path = ROOT) -> None:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not _inside(resolved, resolved_root):
        raise ValueError(f"refusing unsafe cleanup target: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean reproducible HFabric development artefacts.")
    parser.add_argument("--apply", action="store_true", help="Actually remove allowlisted artefacts.")
    args = parser.parse_args()

    found = candidates()
    if not found:
        print("no development artefacts found")
        return 0
    for path in found:
        print(path.relative_to(ROOT))
        if args.apply:
            remove(path)
    if not args.apply:
        print(f"dry run: {len(found)} target(s); pass --apply to remove them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
