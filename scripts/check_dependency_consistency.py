"""Fail when canonical dependency profiles, sources, and locks drift apart."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from install_profiles import (
    DEPENDENCY_MANIFEST,
    PROFILE_DEFS,
    PYTORCH_VERSION,
    TORCHAUDIO_VERSION,
    TORCHVISION_VERSION,
    lock_fingerprint,
    read_lock_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;\\]+)")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked_versions(path: Path) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = PIN_RE.match(raw.strip().lstrip("\ufeff"))
        if match:
            pins.setdefault(_normalise(match.group(1)), set()).add(match.group(2))
    return pins


def _requirement_files(path: Path, seen: set[Path] | None = None) -> set[Path]:
    path = path.resolve()
    visited = seen if seen is not None else set()
    if path in visited:
        return set()
    visited.add(path)
    result = {path}
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.split("#", 1)[0].strip().lstrip("\ufeff")
        if not value:
            continue
        if value.startswith(("-r ", "--requirement ")):
            relative = value.split(maxsplit=1)[1]
            result.update(_requirement_files(path.parent / relative, visited))
    return result


def _direct_requirements(
    path: Path,
    seen: set[Path] | None = None,
) -> list[Requirement]:
    path = path.resolve()
    visited = seen if seen is not None else set()
    if path in visited:
        return []
    visited.add(path)
    requirements: list[Requirement] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.split("#", 1)[0].strip().lstrip("\ufeff")
        if not value:
            continue
        if value.startswith(("-r ", "--requirement ")):
            relative = value.split(maxsplit=1)[1]
            requirements.extend(_direct_requirements(path.parent / relative, visited))
            continue
        if value.startswith("-"):
            raise ValueError(f"unsupported active requirement option in {path}: {value}")
        try:
            requirements.append(Requirement(value))
        except InvalidRequirement:
            raise ValueError(f"invalid requirement in {path}: {value}") from None
    return requirements


def _marker_environment(spec: dict[str, Any]) -> dict[str, str] | None:
    if spec.get("universal"):
        return None
    environment = default_environment()
    environment.update({
        "python_version": str(DEPENDENCY_MANIFEST["python_version"]),
        "python_full_version": f"{DEPENDENCY_MANIFEST['python_version']}.0",
    })
    platform = str(spec.get("python_platform") or "")
    if "windows" in platform:
        environment.update({
            "os_name": "nt",
            "sys_platform": "win32",
            "platform_machine": "AMD64",
            "platform_system": "Windows",
        })
    elif "apple" in platform or "macos" in platform:
        environment.update({
            "os_name": "posix",
            "sys_platform": "darwin",
            "platform_machine": "arm64" if "aarch64" in platform else "x86_64",
            "platform_system": "Darwin",
        })
    elif "linux" in platform:
        environment.update({
            "os_name": "posix",
            "sys_platform": "linux",
            "platform_machine": "aarch64" if "aarch64" in platform else "x86_64",
            "platform_system": "Linux",
        })
    return environment


def _satisfies(requirement: Requirement, version: str) -> bool:
    try:
        return not requirement.specifier or Version(version) in requirement.specifier
    except InvalidVersion:
        return False


def _unhashed_pins(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    missing: list[str] = []
    for index, raw in enumerate(lines):
        match = PIN_RE.match(raw.strip().lstrip("\ufeff"))
        if not match:
            continue
        end = index + 1
        while end < len(lines) and not PIN_RE.match(lines[end].strip().lstrip("\ufeff")):
            end += 1
        if not any("--hash=sha256:" in line for line in lines[index:end]):
            missing.append(_normalise(match.group(1)))
    return missing


def _check_manifest(errors: list[str]) -> None:
    locks: dict[str, dict[str, Any]] = DEPENDENCY_MANIFEST["locks"]
    outputs: set[str] = set()
    for lock_id, spec in locks.items():
        output = str(spec.get("output") or "")
        if not output:
            errors.append(f"{lock_id}: lock output is missing")
        elif output in outputs:
            errors.append(f"{lock_id}: duplicate lock output {output}")
        outputs.add(output)

        input_path = ROOT / str(spec.get("input") or "")
        if not input_path.is_file():
            errors.append(f"{lock_id}: missing lock input {spec.get('input')}")
            continue
        try:
            discovered = {
                str(path.relative_to(ROOT)).replace("\\", "/")
                for path in _requirement_files(input_path)
            }
        except OSError as exc:
            errors.append(f"{lock_id}: cannot read requirement include: {exc}")
            continue
        declared = {str(value).replace("\\", "/") for value in spec.get("source_files") or []}
        if discovered != declared:
            missing = sorted(discovered - declared)
            extra = sorted(declared - discovered)
            if missing:
                errors.append(f"{lock_id}: unhashed source files: {', '.join(missing)}")
            if extra:
                errors.append(f"{lock_id}: unrelated source files declared: {', '.join(extra)}")

        target = ROOT / output
        if not target.is_file():
            errors.append(f"{lock_id}: missing compiled lock {output}")
            continue
        actual_fingerprint = read_lock_fingerprint(target)
        expected_fingerprint = lock_fingerprint(lock_id)
        if actual_fingerprint != expected_fingerprint:
            errors.append(
                f"{lock_id}: stale input fingerprint "
                f"({actual_fingerprint or 'missing'} != {expected_fingerprint})"
            )
        unhashed = _unhashed_pins(target)
        if unhashed:
            errors.append(f"{lock_id}: pins without sha256 hashes: {', '.join(sorted(set(unhashed)))}")

    referenced_locks: set[str] = set()
    for profile_id, profile in DEPENDENCY_MANIFEST["profiles"].items():
        if profile_id not in PROFILE_DEFS:
            errors.append(f"{profile_id}: profile is absent from derived definitions")
        for target in profile.get("targets") or []:
            lock_id = target.get("lock")
            if lock_id:
                referenced_locks.add(str(lock_id))
                if lock_id not in locks:
                    errors.append(f"{profile_id}/{target.get('id')}: unknown lock {lock_id}")
                    continue
            backend = str(target.get("torch_backend") or "")
            index_url = target.get("torch_index_url")
            if backend.startswith("cu") and (
                not index_url or not str(index_url).rstrip("/").endswith(f"/{backend}")
            ):
                errors.append(f"{profile_id}/{target.get('id')}: CUDA backend/index mismatch")
            if backend.startswith("rocm") and (
                not index_url or not str(index_url).rstrip("/").endswith(f"/{backend}")
            ):
                errors.append(f"{profile_id}/{target.get('id')}: ROCm backend/index mismatch")
            if backend == "cpu" and (
                not index_url or not str(index_url).rstrip("/").endswith("/cpu")
            ):
                errors.append(f"{profile_id}/{target.get('id')}: CPU backend/index mismatch")
            if backend == "pypi" and index_url is not None:
                errors.append(f"{profile_id}/{target.get('id')}: PyPI backend must not set an index")
            if lock_id and backend.startswith("cu"):
                if locks[lock_id].get("torch_backend") != backend:
                    errors.append(f"{profile_id}/{target.get('id')}: CUDA lock backend mismatch")
            if lock_id and backend.startswith("rocm"):
                if locks[lock_id].get("torch_preinstalled_backend") != backend:
                    errors.append(f"{profile_id}/{target.get('id')}: ROCm lock backend mismatch")

    expected_profile_locks = set(locks) - {"foundation", "development"}
    if referenced_locks != expected_profile_locks:
        errors.append(
            "profile lock references differ from manifest locks: "
            f"referenced={sorted(referenced_locks)}, expected={sorted(expected_profile_locks)}"
        )


def _check_lock_requirements(errors: list[str]) -> dict[str, dict[str, set[str]]]:
    lock_pins: dict[str, dict[str, set[str]]] = {}
    locks: dict[str, dict[str, Any]] = DEPENDENCY_MANIFEST["locks"]
    for lock_id, spec in locks.items():
        lock_path = ROOT / spec["output"]
        input_path = ROOT / spec["input"]
        if not lock_path.is_file() or not input_path.is_file():
            continue
        pins = _locked_versions(lock_path)
        lock_pins[lock_id] = pins
        omitted = {_normalise(value) for value in spec.get("omit_packages") or []}
        environment = _marker_environment(spec)
        try:
            requirements = _direct_requirements(input_path)
        except (OSError, ValueError) as exc:
            errors.append(f"{lock_id}: {exc}")
            continue
        for requirement in requirements:
            if requirement.marker and environment is not None and not requirement.marker.evaluate(environment):
                continue
            package = _normalise(requirement.name)
            if package in omitted:
                if package in pins:
                    errors.append(f"{lock_id}: omitted package {package} was emitted")
                continue
            versions = pins.get(package)
            if not versions:
                errors.append(f"{lock_id}: direct dependency {package} is missing")
                continue
            if not any(_satisfies(requirement, version) for version in versions):
                errors.append(
                    f"{lock_id}: {package} expects {requirement.specifier}, "
                    f"lock pins {', '.join(sorted(versions))}"
                )
    return lock_pins


def _check_shared_versions(
    errors: list[str],
    lock_pins: dict[str, dict[str, set[str]]],
) -> None:
    foundation = lock_pins.get("foundation", {})
    # Development is constrained to the universal foundation graph and must
    # therefore preserve every shared transitive pin. Accelerator graphs can
    # legitimately choose another version inside a foundation range (NumPy is
    # capped by numba, for example); their direct source constraints are checked
    # separately above.
    for lock_id in ("development",):
        pins = lock_pins.get(lock_id, {})
        for package in sorted(foundation.keys() & pins.keys()):
            if not pins[package].issubset(foundation[package]):
                errors.append(
                    f"{lock_id}: shared package {package} pins "
                    f"{sorted(pins[package])}, foundation pins {sorted(foundation[package])}"
                )

    expected_torch = {
        "torch": PYTORCH_VERSION,
        "torchvision": TORCHVISION_VERSION,
        "torchaudio": TORCHAUDIO_VERSION,
    }
    for lock_id, spec in DEPENDENCY_MANIFEST["locks"].items():
        if lock_id in {"foundation", "development"}:
            continue
        pins = lock_pins.get(lock_id, {})
        omitted = {_normalise(value) for value in spec.get("omit_packages") or []}
        for package, expected in expected_torch.items():
            versions = pins.get(package, set())
            if package in omitted:
                if versions:
                    errors.append(f"{lock_id}: preinstalled {package} must be omitted")
                continue
            if not versions:
                errors.append(f"{lock_id}: missing {package}")
                continue
            if any(Version(version).base_version != expected for version in versions):
                errors.append(
                    f"{lock_id}: {package} expects base {expected}, pins {sorted(versions)}"
                )

    for lock_id in ("rocm-linux-x86_64", "mps-macos-arm64"):
        forbidden = sorted(
            package
            for package in lock_pins.get(lock_id, {})
            if (
                package.startswith("nvidia-")
                and package != "nvidia-ml-py"
            )
            or package == "triton"
        )
        if forbidden:
            errors.append(f"{lock_id}: CUDA-only packages leaked into lock: {', '.join(forbidden)}")
    linux_cuda = lock_pins.get("cuda-linux-x86_64", {})
    if linux_cuda and ("triton" not in linux_cuda or not any(name.startswith("nvidia-") for name in linux_cuda)):
        errors.append("cuda-linux-x86_64: CUDA runtime packages or triton are missing")
    windows_cuda = lock_pins.get("cuda-windows-x86_64", {})
    leaked_windows = sorted(
        package
        for package in windows_cuda
        if package.startswith("nvidia-") and package != "nvidia-ml-py"
    )
    if leaked_windows:
        errors.append(
            "cuda-windows-x86_64: Linux CUDA packages leaked into lock: "
            + ", ".join(leaked_windows)
        )


def check() -> list[str]:
    errors: list[str] = []
    try:
        _check_manifest(errors)
        lock_pins = _check_lock_requirements(errors)
        _check_shared_versions(errors, lock_pins)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    errors = check()
    if errors:
        print("dependency consistency check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("dependency profiles, source fingerprints, and platform locks are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
