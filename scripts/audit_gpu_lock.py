"""Audit the compiled GPU graph with an expiring, explained allowlist."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "backend" / "requirements-gpu.lock"
ALLOWLIST = ROOT / "backend" / "audit-allowlist.json"
EXPECTED_UNAUDITABLE = {"torch", "torchvision"}


def _allowlist(today: date) -> dict[tuple[str, str], dict]:
    payload = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if payload.get("schema") != 1 or not isinstance(payload.get("entries"), list):
        raise ValueError("invalid Python audit allowlist schema")
    allowed: dict[tuple[str, str], dict] = {}
    for entry in payload["entries"]:
        key = (str(entry.get("package") or "").lower(), str(entry.get("id") or ""))
        expiry = date.fromisoformat(str(entry.get("expires") or ""))
        reason = str(entry.get("reason") or "").strip()
        if not all(key) or not reason:
            raise ValueError(f"incomplete audit allowlist entry: {entry!r}")
        if expiry < today:
            raise ValueError(f"expired audit exception {key[1]} for {key[0]} ({expiry})")
        allowed[key] = entry
    return allowed


def evaluate(report: dict, *, today: date) -> list[str]:
    allowed = _allowlist(today)
    observed: set[tuple[str, str]] = set()
    errors: list[str] = []
    for dependency in report.get("dependencies", []):
        package = str(dependency.get("name") or "").lower()
        for vulnerability in dependency.get("vulns", []):
            key = (package, str(vulnerability.get("id") or ""))
            observed.add(key)
            if key not in allowed:
                errors.append(f"unapproved vulnerability {key[1]} in {package}")
    for key in sorted(set(allowed) - observed):
        errors.append(f"stale audit exception {key[1]} for {key[0]}")

    skipped = {
        str(item.get("name") or "").lower()
        for item in report.get("fixes", [])
        if item.get("skip_reason")
    }
    unexpected_skips = skipped - EXPECTED_UNAUDITABLE
    if unexpected_skips:
        errors.append(f"unexpected unaudited packages: {', '.join(sorted(unexpected_skips))}")
    return errors


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(LOCK),
        "--no-deps",
        "--disable-pip",
        "--format=json",
        "--progress-spinner=off",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stderr or result.stdout or "pip-audit produced no report", file=sys.stderr)
        return 2
    errors = evaluate(report, today=date.today())
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("GPU lock audit passed; only documented unexpired exceptions remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
