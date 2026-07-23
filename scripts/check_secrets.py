"""High-confidence secret scan for tracked source files."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOW_MARKER = "pragma: allowlist secret"
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9]{40,}\b"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}


def findings(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                out.append((line_number, label))
    return out


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        ROOT / raw.decode("utf-8", errors="surrogateescape")
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def scan() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out.extend((path, line, label) for line, label in findings(text))
    return out


def main() -> int:
    found = scan()
    if not found:
        print("no high-confidence secrets found in tracked files")
        return 0
    for path, line, label in found:
        print(f"{path.relative_to(ROOT)}:{line}: possible {label}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
