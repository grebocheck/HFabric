"""Download and version-manage prebuilt llama.cpp binaries.

Shared, stdlib-only core used by both the installer (`scripts/fetch_llama.py`)
and the backend manager (`app/services/llama_manager.py`). It picks the right
release asset for the host + accelerator, extracts it into a versioned directory,
and keeps a small `installed.json` so old builds survive an update (rollback
safety). At most ``KEEP_VERSIONS`` builds are retained; the active one is never
pruned.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable
import urllib.request
import zipfile

GITHUB_REPO = "ggml-org/llama.cpp"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
KEEP_VERSIONS = 3

# Binaries the app launches. Discovered case-insensitively after extraction.
KNOWN_BINARIES = ("llama-server", "llama-tts", "llama-mtmd-cli")

# accelerator -> the token llama.cpp uses in its release asset names.
VARIANT_TOKENS = {
    "cuda": ("cuda",),
    "rocm": ("hip", "rocm"),
    "vulkan": ("vulkan",),
    "cpu": ("cpu",),
}


def backend_to_variant(backend: str | None, system: str) -> str:
    """Map a CapabilityProfile backend to a llama.cpp release variant.

    ROCm prebuilts (``hip``) ship for Windows; Linux ROCm users usually build
    their own, so fall back to vulkan there. Unknown backends use CPU.
    """
    backend = (backend or "").lower()
    if backend == "cuda":
        return "cuda"
    if backend == "rocm":
        return "hip" if system.lower().startswith("win") else "vulkan"
    if backend in {"vulkan", "cpu"}:
        return backend
    return "cpu"


def _platform_tokens(system: str) -> tuple[str, ...]:
    system = system.lower()
    if system.startswith("win"):
        return ("win",)
    if system == "darwin":
        return ("macos", "macm", "darwin")
    return ("ubuntu", "linux")


def _arch_token(machine: str) -> str:
    machine = (machine or "").lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return "x64"


def select_assets(
    assets: list[dict[str, Any]],
    *,
    system: str,
    machine: str,
    variant: str,
) -> dict[str, Any]:
    """Choose the best release asset for this host. Pure (no network).

    Returns ``{"primary", "extras", "variant_matched", "reason"}``. ``primary``
    is the main binaries zip; ``extras`` includes the CUDA runtime companion on
    Windows. ``variant_matched`` is False when no accelerator-specific build
    exists and a CPU/portable zip was used instead.
    """
    platform_tokens = _platform_tokens(system)
    arch = _arch_token(machine)
    variant_tokens = VARIANT_TOKENS.get(variant, ())

    candidates: list[tuple[int, dict[str, Any]]] = []
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if not name.endswith(".zip"):
            continue
        # cudart-* is the CUDA runtime DLL bundle, never the main binaries.
        if name.startswith("cudart"):
            continue
        if not any(token in name for token in platform_tokens):
            continue
        score = 10
        if arch in name:
            score += 4
        elif system.lower() == "darwin" and arch == "arm64" and "arm" in name:
            score += 4
        if variant_tokens and any(token in name for token in variant_tokens):
            score += 100
        elif "cpu" in name:
            score += 2  # a plain CPU build is the safe fallback
        candidates.append((score, asset))

    if not candidates:
        return {"primary": None, "extras": [], "variant_matched": False,
                "reason": f"no {system}/{arch} llama.cpp asset in this release"}

    candidates.sort(key=lambda item: item[0], reverse=True)
    primary = candidates[0][1]
    variant_matched = bool(
        variant_tokens and any(token in str(primary.get("name")).lower() for token in variant_tokens)
    )

    extras: list[dict[str, Any]] = []
    if variant == "cuda" and variant_matched and system.lower().startswith("win"):
        cudart = _matching_cudart(assets, primary)
        if cudart:
            extras.append(cudart)

    reason = "matched accelerator build" if variant_matched else "no accelerator build; using portable/CPU zip"
    return {"primary": primary, "extras": extras, "variant_matched": variant_matched, "reason": reason}


def _matching_cudart(assets: list[dict[str, Any]], primary: dict[str, Any]) -> dict[str, Any] | None:
    """Find the cudart-*.zip whose CUDA version matches the chosen primary zip."""
    primary_name = str(primary.get("name") or "").lower()
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.startswith("cudart") and name.endswith(".zip"):
            # Prefer one sharing a CUDA version token (e.g. "cuda-12.4") with primary.
            token = _cuda_version_token(primary_name)
            if token is None or token in name:
                return asset
    return None


def _cuda_version_token(name: str) -> str | None:
    for part in name.replace("_", "-").split("-"):
        if part.startswith("12") or part.startswith("11"):
            return part
    return None


# --------------------------------------------------------------- state / versions

def version_id(tag: str, variant: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in f"{tag}-{variant}")
    return safe.strip("-") or "build"


def state_path(root: Path) -> Path:
    return Path(root) / "installed.json"


def read_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {"schema_version": 1, "active": None, "versions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "active": None, "versions": []}
    data.setdefault("versions", [])
    data.setdefault("active", None)
    return data


def write_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_binaries(directory: Path, system: str) -> dict[str, str]:
    """Locate the known llama binaries anywhere under ``directory``."""
    exe = ".exe" if system.lower().startswith("win") else ""
    wanted = {f"{name}{exe}".lower(): name for name in KNOWN_BINARIES}
    found: dict[str, str] = {}
    for path in Path(directory).rglob("*"):
        if not path.is_file():
            continue
        key = path.name.lower()
        if key in wanted and wanted[key] not in found:
            found[wanted[key]] = str(path)
    return found


def register_version(
    root: Path,
    *,
    tag: str,
    variant: str,
    extracted_dir: Path,
    system: str,
    source_url: str | None = None,
    activate_now: bool = True,
) -> dict[str, Any]:
    """Move an extracted build into versions/<id>/ and record it in state."""
    root = Path(root)
    vid = version_id(tag, variant)
    versions_dir = root / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    dest = versions_dir / vid
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(extracted_dir), str(dest))

    binaries = find_binaries(dest, system)
    if "llama-server" not in binaries:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"release {tag} ({variant}) contained no llama-server binary")

    version = {
        "id": vid,
        "tag": tag,
        "variant": variant,
        "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dir": str(dest),
        "binaries": binaries,
        "size_bytes": _dir_size(dest),
        "source_url": source_url,
    }

    state = read_state(root)
    state["versions"] = [v for v in state["versions"] if v.get("id") != vid] + [version]
    if activate_now or state.get("active") is None:
        state["active"] = vid
    write_state(root, state)
    prune(root)
    return version


def prune(root: Path, keep: int = KEEP_VERSIONS) -> list[str]:
    """Keep the newest ``keep`` versions; never delete the active one."""
    root = Path(root)
    state = read_state(root)
    versions = state["versions"]
    active = state.get("active")
    if len(versions) <= keep:
        return []

    ordered = sorted(versions, key=lambda v: v.get("installed_at") or "", reverse=True)
    # Cap total at `keep`, but the active build always claims a slot first so it
    # survives even when it is not among the newest.
    keep_ids: list[str] = [active] if any(v.get("id") == active for v in versions) else []
    for v in ordered:
        if len(keep_ids) >= keep:
            break
        if v["id"] not in keep_ids:
            keep_ids.append(v["id"])
    removed = []
    for v in versions:
        if v["id"] not in keep_ids:
            shutil.rmtree(v.get("dir", ""), ignore_errors=True)
            removed.append(v["id"])
    state["versions"] = [v for v in versions if v["id"] in keep_ids]
    write_state(root, state)
    return removed


def activate(root: Path, vid: str) -> dict[str, Any]:
    state = read_state(root)
    if not any(v.get("id") == vid for v in state["versions"]):
        raise ValueError(f"unknown llama version: {vid}")
    state["active"] = vid
    write_state(root, state)
    return active_version(root)


def remove_version(root: Path, vid: str) -> None:
    state = read_state(root)
    if state.get("active") == vid:
        raise ValueError("cannot remove the active llama version; activate another first")
    target = next((v for v in state["versions"] if v.get("id") == vid), None)
    if target is None:
        raise ValueError(f"unknown llama version: {vid}")
    shutil.rmtree(target.get("dir", ""), ignore_errors=True)
    state["versions"] = [v for v in state["versions"] if v.get("id") != vid]
    write_state(root, state)


def active_version(root: Path) -> dict[str, Any] | None:
    state = read_state(root)
    return next((v for v in state["versions"] if v.get("id") == state.get("active")), None)


def _dir_size(directory: Path) -> int:
    return sum(p.stat().st_size for p in Path(directory).rglob("*") if p.is_file())


# --------------------------------------------------------------------- network

def _http_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers=_gh_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https GitHub API
        return json.loads(resp.read().decode("utf-8"))


def _gh_headers() -> dict[str, str]:
    headers = {"User-Agent": "HFabric-llama-manager", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_latest_release() -> dict[str, Any]:
    return _http_json(f"{RELEASES_API}/latest")


def fetch_release_by_tag(tag: str) -> dict[str, Any]:
    return _http_json(f"{RELEASES_API}/tags/{tag}")


def download(url: str, dest: Path, progress_cb: Callable[[int, int], None] | None = None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "HFabric-llama-manager"})
    with urllib.request.urlopen(req, timeout=60.0) as resp:  # noqa: S310 - https release asset
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with dest.open("wb") as handle:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    return dest


def install(
    root: Path,
    *,
    system: str,
    machine: str,
    variant: str,
    tag: str | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Network entrypoint: resolve a release, download + extract, register it."""
    release = fetch_release_by_tag(tag) if tag else fetch_latest_release()
    resolved_tag = str(release.get("tag_name") or tag or "unknown")
    selection = select_assets(
        release.get("assets") or [], system=system, machine=machine, variant=variant
    )
    primary = selection["primary"]
    if not primary:
        raise ValueError(selection["reason"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        staging = tmp_path / "extract"
        staging.mkdir()
        for asset in [primary, *selection["extras"]]:
            name = str(asset["name"])
            archive = tmp_path / name
            download(
                asset["browser_download_url"],
                archive,
                progress_cb=(lambda d, t, n=name: progress_cb(n, d, t)) if progress_cb else None,
            )
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)
        version = register_version(
            root, tag=resolved_tag, variant=variant, extracted_dir=staging,
            system=system, source_url=primary.get("browser_download_url"),
        )
    version["variant_matched"] = selection["variant_matched"]
    version["selection_reason"] = selection["reason"]
    return version
