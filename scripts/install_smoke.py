"""Validate the installer's profile decision against the live machine.

This is the real-hardware counterpart to the fake-probe unit tests: it probes
the machine, resolves the install profile, and cross-checks that the chosen
backend agrees with what ``torch`` actually sees. Run it on a real CUDA or ROCm
box after setup and paste the summary block into ``docs/gpu-smoke.md``.

The decision logic lives in :func:`evaluate`, which takes a report dict, so the
NVIDIA/AMD/CPU branches are unit-testable without owning every GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from hardware_probe import collect_report
    from install_profiles import resolve_profile
except ImportError:  # pragma: no cover - exercised only when run as a module
    from scripts.hardware_probe import collect_report  # type: ignore[no-redef]
    from scripts.install_profiles import resolve_profile  # type: ignore[no-redef]

OK = "ok"
WARN = "warn"
ERROR = "error"


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def evaluate(report: dict[str, Any], *, prefer: str | None = None, run_verify: bool = True) -> dict[str, Any]:
    """Resolve a profile for ``report`` and grade it against torch visibility.

    Returns ``{"profile", "checks", "ok"}``. ``ok`` is False when any check has
    ``error`` status. ``warn`` checks never fail the run (missing torch, etc.).
    """
    profile = resolve_profile(report, prefer)
    backend = str(profile["runtime_defaults"].get("backend") or "cpu")
    torch_info = report.get("torch") or {}
    installed = bool(torch_info.get("installed"))
    cuda_available = bool(torch_info.get("cuda_available"))
    hip = torch_info.get("torch_hip_version")
    mps_available = bool(torch_info.get("mps_available"))

    checks = [_check("profile_resolved", OK, f"selected {profile['selected_profile']} ({backend})")]

    # Backend vs what torch reports.
    if backend in {"cuda", "rocm", "mps"} and not installed:
        checks.append(_check(
            "torch_visible", WARN,
            "torch is not importable yet; install the profile before verifying the accelerator.",
        ))
    elif backend == "cuda":
        if cuda_available and not hip:
            checks.append(_check("torch_visible", OK, "torch.cuda.is_available() is True on a CUDA build"))
        elif cuda_available and hip:
            checks.append(_check("torch_visible", ERROR, "profile is CUDA but torch is a ROCm/HIP build"))
        else:
            checks.append(_check("torch_visible", ERROR, "profile is CUDA but torch.cuda.is_available() is False"))
    elif backend == "rocm":
        if cuda_available and hip:
            checks.append(_check("torch_visible", OK, f"torch HIP build sees the device (hip {hip})"))
        else:
            checks.append(_check("torch_visible", ERROR, "profile is ROCm but torch reports no HIP accelerator"))
    elif backend == "mps":
        if mps_available:
            checks.append(_check("torch_visible", OK, "torch.backends.mps.is_available() is True"))
        else:
            checks.append(_check("torch_visible", ERROR, "profile is MPS but torch reports no Apple MPS accelerator"))
    else:  # cpu-safe
        if installed and (cuda_available or mps_available):
            checks.append(_check(
                "torch_visible", WARN,
                "CPU-safe profile chosen, but torch sees an accelerator; check why the GPU path was rejected.",
            ))
        else:
            checks.append(_check("torch_visible", OK, "no accelerator expected for CPU-safe mode"))

    # The installer pip-installs optional_features, so they must match capability.
    optional = set(profile.get("optional_features") or [])
    allow_nunchaku = bool(profile["runtime_defaults"].get("allow_nunchaku"))
    if "nunchaku_cuda" in optional and not allow_nunchaku:
        checks.append(_check("feature_sanity", ERROR, "nunchaku_cuda offered but allow_nunchaku is False"))
    elif "nunchaku_cuda" in optional and backend != "cuda":
        checks.append(_check("feature_sanity", ERROR, "nunchaku_cuda offered on a non-CUDA backend"))
    elif "metal_llama_binaries" in optional and backend != "mps":
        checks.append(_check("feature_sanity", ERROR, "metal_llama_binaries offered on a non-MPS backend"))
    else:
        checks.append(_check("feature_sanity", OK, f"optional features: {', '.join(sorted(optional)) or 'none'}"))

    if run_verify:
        checks.append(_run_verify(profile["install"]["verify"]))

    ok = all(c["status"] != ERROR for c in checks)
    return {"profile": profile, "checks": checks, "ok": ok}


def _run_verify(snippet: str) -> dict[str, str]:
    """Execute a profile's verify snippet in-process and capture pass/fail."""
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exec(snippet, {"__name__": "__hfab_verify__"})  # noqa: S102 - trusted profile snippet
    except Exception as exc:  # noqa: BLE001 - surface any failure as a graded check
        return _check("verify_snippet", ERROR, f"{type(exc).__name__}: {exc}")
    output = buffer.getvalue().strip().replace("\n", " ")
    return _check("verify_snippet", OK, output or "verify snippet ran")


_STATUS_MARK = {OK: "PASS", WARN: "warn", ERROR: "FAIL"}


def render_text(result: dict[str, Any], report: dict[str, Any]) -> str:
    profile = result["profile"]
    gpu = profile.get("primary_gpu") or {}
    lines = [
        "## Installer profile smoke",
        "",
        f"- Generated: {report.get('generated_at', '-')}",
        f"- OS: {(report.get('os') or {}).get('system', '-')} / Python {(report.get('python') or {}).get('version', '-')}",
        f"- GPU: {gpu.get('name') or 'none detected'}"
        + (f" ({round((gpu.get('vram_mb') or 0) / 1024)} GB, {gpu.get('architecture') or 'n/a'})" if gpu.get("vram_mb") else ""),
        f"- Selected profile: {profile['selected_profile']} ({profile['runtime_defaults'].get('backend')})"
        f" - tier {profile['hardware_tier']}",
        f"- torch index: {profile['install']['torch']['index_url']}",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    for c in result["checks"]:
        lines.append(f"| {c['name']} | {_STATUS_MARK[c['status']]} | {c['detail']} |")
    lines.append("")
    lines.append(f"**Overall: {'PASS' if result['ok'] else 'FAIL'}**")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the installer profile decision on this machine.")
    parser.add_argument("--report", help="Path to a hardware_probe.py JSON report. If omitted, probe now.")
    parser.add_argument("--prefer", help="Require a specific valid profile id.")
    parser.add_argument("--no-verify", action="store_true", help="Skip running the profile verify snippet (no torch import).")
    parser.add_argument("--json", action="store_true", help="Emit the graded result as JSON.")
    args = parser.parse_args(argv)

    if args.report:
        with open(args.report, encoding="utf-8") as handle:
            report = json.load(handle)
    else:
        report = collect_report()

    result = evaluate(report, prefer=args.prefer, run_verify=not args.no_verify)

    if args.json:
        sys.stdout.write(json.dumps({"ok": result["ok"], "checks": result["checks"]}, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(result, report) + "\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
