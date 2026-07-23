"""Canonical, dependency-free dotenv parsing for platform launch adapters."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.util.network_policy import require_secure_bind  # noqa: E402

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DotenvError(ValueError):
    pass


def _unquoted_value(raw: str) -> str:
    # A comment starts only after whitespace, so URL fragments remain intact.
    match = re.search(r"\s+#", raw)
    return (raw[: match.start()] if match else raw).strip()


def _quoted_value(raw: str, *, line_number: int) -> str:
    quote = raw[0]
    escaped = False
    chars: list[str] = []
    closing = -1
    for index, char in enumerate(raw[1:], start=1):
        if quote == '"' and escaped:
            chars.append(
                {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(
                    char,
                    f"\\{char}",
                )
            )
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char == quote:
            closing = index
            break
        chars.append(char)
    if closing < 0 or escaped:
        raise DotenvError(f"line {line_number}: unterminated quoted value")
    remainder = raw[closing + 1 :].strip()
    if remainder and not remainder.startswith("#"):
        raise DotenvError(f"line {line_number}: unexpected text after quoted value")
    return "".join(chars)


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a small, explicit dotenv subset without interpolation or execution."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")
    if "\0" in text:
        raise DotenvError("dotenv file contains a NUL byte")
    for line_number, original in enumerate(text.splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not _KEY_RE.fullmatch(key):
            raise DotenvError(f"line {line_number}: invalid dotenv assignment")
        raw_value = raw_value.strip()
        value = (
            _quoted_value(raw_value, line_number=line_number)
            if raw_value.startswith(("'", '"'))
            else _unquoted_value(raw_value)
        )
        values[key] = value
    return values


def effective_dotenv(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """Return file keys with process-environment precedence."""

    return {
        key: environ.get(key, value)
        for key, value in parse_dotenv(path).items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    parser.add_argument("--check-security", action="store_true")
    parser.add_argument("--host")
    args = parser.parse_args(argv)
    try:
        values = effective_dotenv(args.path, os.environ)
    except (OSError, UnicodeError, DotenvError) as exc:
        print(f"[env] {exc}", file=sys.stderr)
        return 2
    if args.check_security:
        host = args.host or values.get("HFAB_HOST") or os.environ.get("HFAB_HOST") or "127.0.0.1"
        token = values.get("HFAB_API_TOKEN") or os.environ.get("HFAB_API_TOKEN")
        allow_raw = (
            values.get("HFAB_ALLOW_INSECURE_LAN")
            or os.environ.get("HFAB_ALLOW_INSECURE_LAN")
            or ""
        )
        allow = allow_raw.strip().lower() in {"1", "true", "yes", "on"}
        try:
            insecure = require_secure_bind(host, token, allow)
        except ValueError as exc:
            print(f"[security] {exc}", file=sys.stderr)
            return 3
        if insecure:
            print(
                "[security] WARNING: explicit insecure LAN mode is active "
                "without an API token",
                file=sys.stderr,
            )
        return 0
    if args.format == "shell":
        for key, value in values.items():
            print(f"export {key}={shlex.quote(value)}")
    else:
        print(json.dumps(values, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
