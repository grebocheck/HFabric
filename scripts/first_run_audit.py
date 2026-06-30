"""Collect a P24.7 first-run audit snapshot.

This script does not replace the human checklist in ``docs/first-run-audit.md``.
It creates a consistent machine-readable / pasteable report around that checklist:
clean-checkout state, bootstrap artifacts, managed tool visibility, disk headroom,
and the installer profile that this machine resolves to.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from hardware_probe import collect_report  # noqa: E402
from install_profiles import resolve_profile  # noqa: E402

SCHEMA_VERSION = 1

BOOTSTRAP_PATHS = (
    ".tools",
    ".venv",
    "frontend/node_modules",
    "data",
    "models",
)

FOUNDATION_PATHS = (
    "setup.bat",
    "run.bat",
    "setup.ps1",
    "scripts/run.ps1",
    "README.md",
    "ROADMAP.md",
    "docs/first-run-audit.md",
)


def path_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    exists = path.exists()
    return {
        "path": relative,
        "exists": exists,
        "kind": "dir" if path.is_dir() else ("file" if path.is_file() else "missing"),
    }


def path_entries(root: Path, relatives: Sequence[str]) -> list[dict[str, Any]]:
    return [path_entry(root, item) for item in relatives]


def clean_checkout_status(root: Path) -> dict[str, Any]:
    entries = path_entries(root, BOOTSTRAP_PATHS)
    present = [entry["path"] for entry in entries if entry["exists"]]
    return {
        "clean": not present,
        "present_bootstrap_paths": present,
        "paths": entries,
    }


def managed_tool_status(root: Path) -> dict[str, Any]:
    if platform.system().lower() == "windows":
        python_path = root / ".venv" / "Scripts" / "python.exe"
    else:
        python_path = root / ".venv" / "bin" / "python"
    npm_path = _managed_npm_path(root)
    return {
        "venv_python": _tool_entry(root, python_path, ["--version"]),
        "managed_npm": _tool_entry(root, npm_path, ["--version"]),
    }


def _managed_npm_path(root: Path) -> Path:
    tools = root / ".tools"
    if platform.system().lower() == "windows":
        candidates = [
            tools / "node" / "npm.cmd",
            *sorted(tools.glob("node-v*-win-x64/npm.cmd"), reverse=True),
        ]
    else:
        candidates = [
            tools / "node" / "bin" / "npm",
            *sorted(tools.glob("node-v*/bin/npm"), reverse=True),
        ]
    return next((path for path in candidates if path.exists()), candidates[0])


def _tool_entry(root: Path, path: Path, args: list[str]) -> dict[str, Any]:
    exists = path.exists()
    out: dict[str, Any] = {"path": _rel(root, path), "exists": exists, "version": None}
    if not exists:
        return out
    try:
        proc = subprocess.run(
            [str(path), *args],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        out["error"] = str(exc)
        return out
    text = (proc.stdout or proc.stderr).strip()
    out.update({"exit_code": proc.returncode, "version": text.splitlines()[0] if text else ""})
    return out


def disk_status(root: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(root)
    return {
        "total_gb": round(usage.total / 1024**3, 2),
        "free_gb": round(usage.free / 1024**3, 2),
        "used_gb": round(usage.used / 1024**3, 2),
    }


def git_status(root: Path) -> dict[str, Any]:
    head = _git(root, ["rev-parse", "--short", "HEAD"])
    branch = _git(root, ["branch", "--show-current"])
    dirty = _git(root, ["status", "--short"])
    return {
        "head": head["stdout"] if head["ok"] else None,
        "branch": branch["stdout"] if branch["ok"] else None,
        "dirty": bool(dirty["stdout"]) if dirty["ok"] else None,
        "status_short": dirty["stdout"].splitlines() if dirty["ok"] and dirty["stdout"] else [],
        "available": head["ok"],
    }


def _git(root: Path, args: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc)}
    return {"ok": proc.returncode == 0, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def hardware_profile(root: Path) -> dict[str, Any]:
    report = collect_report(str(root))
    profile = resolve_profile(report)
    gpu = profile.get("primary_gpu") or {}
    return {
        "report": {
            "generated_at": report.get("generated_at"),
            "os": report.get("os"),
            "python": report.get("python"),
            "memory": report.get("memory"),
            "torch": report.get("torch"),
            "gpus": report.get("gpus") or [],
        },
        "profile": {
            "selected_profile": profile.get("selected_profile"),
            "backend": (profile.get("runtime_defaults") or {}).get("backend"),
            "hardware_tier": profile.get("hardware_tier"),
            "gpu": gpu,
            "video_policy": ((profile.get("model_policy") or {}).get("video")) or {},
            "warnings": profile.get("warnings") or [],
        },
    }


def collect_audit(root: Path, *, phase: str, include_hardware: bool = True) -> dict[str, Any]:
    root = root.resolve()
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "phase": phase,
        "root": str(root),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "git": git_status(root),
        "clean_checkout": clean_checkout_status(root),
        "foundation_paths": path_entries(root, FOUNDATION_PATHS),
        "managed_tools": managed_tool_status(root),
        "disk": disk_status(root),
        "next_commands": next_commands(phase),
    }
    if include_hardware:
        out["hardware_profile"] = hardware_profile(root)
    return out


def next_commands(phase: str) -> list[str]:
    if phase == "pre":
        return ["setup.bat", "run.bat stub"]
    if phase == "post-setup":
        return ["run.bat stub", ".\\.venv\\Scripts\\python.exe scripts\\install_smoke.py"]
    if phase == "post-stub":
        return [".\\.venv\\Scripts\\python.exe scripts\\install_smoke.py", "run.bat"]
    return ["Attach this report with the manual checklist result from docs/first-run-audit.md"]


def render_markdown(report: dict[str, Any]) -> str:
    clean = report["clean_checkout"]
    lines = [
        "# First-Run Audit Snapshot",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Phase: {report['phase']}",
        f"- Root: `{report['root']}`",
        f"- Platform: {report['platform']['system']} {report['platform']['release']} ({report['platform']['machine']})",
        f"- Git: {report['git'].get('head') or 'n/a'}"
        + (" dirty" if report["git"].get("dirty") else ""),
        f"- Clean checkout: {'PASS' if clean['clean'] else 'NO'}",
    ]
    if clean["present_bootstrap_paths"]:
        lines.append(f"- Bootstrap paths present: {', '.join(clean['present_bootstrap_paths'])}")

    profile = ((report.get("hardware_profile") or {}).get("profile")) or {}
    if profile:
        lines.extend([
            "",
            "## Profile",
            "",
            f"- Selected: {profile.get('selected_profile')} / {profile.get('backend')}",
            f"- Tier: {profile.get('hardware_tier')}",
            f"- GPU: {(profile.get('gpu') or {}).get('name') or 'none detected'}",
            f"- Video recommended: {', '.join((profile.get('video_policy') or {}).get('recommended') or []) or 'none'}",
            f"- Video hidden: {', '.join((profile.get('video_policy') or {}).get('hidden') or []) or 'none'}",
        ])

    lines.extend([
        "",
        "## Bootstrap Paths",
        "",
        "| path | state |",
        "| --- | --- |",
    ])
    for entry in report["clean_checkout"]["paths"]:
        lines.append(f"| `{entry['path']}` | {'present' if entry['exists'] else 'absent'} |")

    lines.extend([
        "",
        "## Managed Tools",
        "",
        "| tool | path | state | version |",
        "| --- | --- | --- | --- |",
    ])
    for name, entry in report["managed_tools"].items():
        lines.append(
            f"| {name} | `{entry['path']}` | {'present' if entry['exists'] else 'missing'} | "
            f"{entry.get('version') or '-'} |"
        )

    lines.extend([
        "",
        "## Next Commands",
        "",
    ])
    for command in report["next_commands"]:
        lines.append(f"- `{command}`")
    lines.append("")
    return "\n".join(lines)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to inspect")
    parser.add_argument(
        "--phase",
        choices=("pre", "post-setup", "post-stub", "post-real"),
        default="pre",
        help="Where the tester is in docs/first-run-audit.md",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    parser.add_argument("--output", type=Path, help="Write the report to a file")
    parser.add_argument("--no-hardware", action="store_true", help="Skip hardware/profile probing")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = collect_audit(args.root, phase=args.phase, include_hardware=not args.no_hardware)
    text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else render_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
