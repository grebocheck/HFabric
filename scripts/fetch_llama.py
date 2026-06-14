"""Install the right prebuilt llama.cpp build for this machine (setup helper).

Called from setup.ps1 / setup.sh in the REAL path so users don't hand-place
binaries. Detects the accelerator via the shared hardware probe + install-profile
resolver, then downloads the matching GitHub release into bin/llama/versions/,
keeping old builds for rollback. Best-effort: network/asset failures warn and
exit 0 so they never abort setup.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import llama_release as lr  # noqa: E402

ROOT = SCRIPTS.parent
MANAGED_ROOT = ROOT / "bin" / "llama"


def detect_variant() -> str:
    """Resolve the llama.cpp release variant from the detected accelerator."""
    try:
        import hardware_probe
        import install_profiles

        report = hardware_probe.collect_report(str(ROOT))
        profile = install_profiles.resolve_profile(report)
        backend = profile.get("runtime_defaults", {}).get("backend")
    except Exception as exc:  # noqa: BLE001 - fall back to CPU on any probe error
        print(f"[fetch-llama] could not detect accelerator ({exc}); using cpu build")
        backend = None
    return lr.backend_to_variant(backend, platform.system())


def _progress(asset: str, done: int, total: int) -> None:
    if total:
        pct = int(done / total * 100)
        sys.stdout.write(f"\r[fetch-llama] {asset}: {pct}%")
    else:
        sys.stdout.write(f"\r[fetch-llama] {asset}: {done // 1024} KiB")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a prebuilt llama.cpp build for this machine.")
    parser.add_argument("--variant", help="cuda | hip | metal | vulkan | cpu (default: auto-detect).")
    parser.add_argument("--tag", help="Specific llama.cpp release tag (default: latest).")
    parser.add_argument("--force", action="store_true", help="Install even if a managed build already exists.")
    args = parser.parse_args(argv)

    state = lr.read_state(MANAGED_ROOT)
    if state.get("active") and not args.force:
        active = lr.active_version(MANAGED_ROOT)
        print(f"[fetch-llama] managed build already present ({active.get('tag')}); use --force to reinstall.")
        return 0

    variant = args.variant or detect_variant()
    print(f"[fetch-llama] installing llama.cpp ({variant}) for {platform.system()}/{platform.machine()}…")
    try:
        version = lr.install(
            MANAGED_ROOT,
            system=platform.system(),
            machine=platform.machine(),
            variant=variant,
            tag=args.tag,
            progress_cb=_progress,
        )
    except Exception as exc:  # noqa: BLE001 - never abort setup on a download failure
        print(f"\n[fetch-llama] WARNING: could not install llama.cpp: {exc}")
        print("[fetch-llama] You can install it later from Settings -> LLM runtime.")
        return 0

    note = "" if version.get("variant_matched", True) else f"  ({version.get('selection_reason')})"
    print(f"\n[fetch-llama] installed {version.get('tag')} ({variant}){note}")
    print(f"[fetch-llama] server: {version.get('binaries', {}).get('llama-server')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
