"""Emit a machine capability report for HFabric setup/runtime decisions.

This script intentionally uses only the Python standard library: it must run
before a virtual environment or ML packages exist. Optional tools such as
``nvidia-smi``, ``rocminfo``, ``rocm-smi``, and PowerShell CIM are used when
available and skipped when absent.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Any

SCHEMA_VERSION = 1

AMD_OFFICIAL_ROCM_TARGETS = {
    "gfx908",   # MI100
    "gfx90a",   # MI200
    "gfx942",   # MI300
    "gfx950",   # MI350
    "gfx1030",  # RDNA2 workstation / selected Radeon
    "gfx1100",  # RDNA3 high-end
    "gfx1101",  # RDNA3 workstation / selected Radeon
    "gfx1201",  # RDNA4 workstation / selected Radeon
}


def _run(args: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    if not shutil.which(args[0]):
        return 127, "", f"{args[0]} not found"
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _round_gb(bytes_value: int | float | None) -> float | None:
    if bytes_value is None:
        return None
    return round(float(bytes_value) / 1024**3, 2)


def _memory_info() -> dict[str, float | None]:
    if platform.system().lower() == "windows":
        return _windows_memory_info()
    return _posix_memory_info()


def _windows_memory_info() -> dict[str, float | None]:
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {
                "total_gb": _round_gb(status.ullTotalPhys),
                "available_gb": _round_gb(status.ullAvailPhys),
            }
    except Exception:
        pass
    return {"total_gb": None, "available_gb": None}


def _posix_memory_info() -> dict[str, float | None]:
    meminfo = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in {"MemTotal", "MemAvailable"}:
                    meminfo[key] = int(value.strip().split()[0]) * 1024
    except OSError:
        pass
    if meminfo:
        return {
            "total_gb": _round_gb(meminfo.get("MemTotal")),
            "available_gb": _round_gb(meminfo.get("MemAvailable")),
        }
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return {"total_gb": _round_gb(pages * page_size), "available_gb": None}
    except (ValueError, OSError, AttributeError):
        return {"total_gb": None, "available_gb": None}


def _disk_info(path: str) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": os.path.abspath(path),
        "total_gb": _round_gb(usage.total),
        "free_gb": _round_gb(usage.free),
    }


def _parse_compute_capability(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.search(r"(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _gpu_key(gpu: dict[str, Any]) -> tuple[str, str]:
    return str(gpu.get("vendor", "")).lower(), str(gpu.get("name", "")).lower()


def _merge_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for gpu in gpus:
        key = _gpu_key(gpu)
        if key in seen:
            target = seen[key]
            for field, value in gpu.items():
                if value not in (None, "", [], {}) and target.get(field) in (None, "", [], {}):
                    target[field] = value
                elif field == "sources":
                    target.setdefault("sources", [])
                    target["sources"] = sorted(set(target["sources"]) | set(value))
            continue
        gpu.setdefault("sources", [gpu.pop("source", "unknown")])
        seen[key] = gpu
        merged.append(gpu)
    return merged


def probe_nvidia_smi() -> list[dict[str, Any]]:
    query = "index,name,memory.total,driver_version,compute_cap"
    code, stdout, _stderr = _run([
        "nvidia-smi",
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    ])
    has_compute = code == 0
    if code != 0:
        query = "index,name,memory.total,driver_version"
        code, stdout, _stderr = _run([
            "nvidia-smi",
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ])
    if code != 0 or not stdout:
        return []

    rows = csv.reader(stdout.splitlines())
    gpus: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 4:
            continue
        index, name, memory_mb, driver = [item.strip() for item in row[:4]]
        compute = row[4].strip() if has_compute and len(row) >= 5 else None
        gpus.append({
            "index": _safe_int(index),
            "vendor": "nvidia",
            "name": name,
            "vram_mb": _safe_int(memory_mb),
            "driver_version": driver,
            "compute_capability": compute,
            "compute_capability_tuple": list(_parse_compute_capability(compute) or ()),
            "source": "nvidia-smi",
        })
    return gpus


def probe_windows_video() -> list[dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []
    code, stdout, _stderr = _run([
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM,PNPDeviceID,DriverVersion | ConvertTo-Json -Compress"
        ),
    ])
    if code != 0 or not stdout:
        return []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    gpus = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "").strip()
        vendor = _vendor_from_text(" ".join([name, str(row.get("PNPDeviceID") or "")]))
        if vendor == "unknown":
            continue
        adapter_ram = _safe_int(row.get("AdapterRAM"))
        gpus.append({
            "vendor": vendor,
            "name": name,
            "vram_mb": round(adapter_ram / 1024**2) if adapter_ram else None,
            "driver_version": row.get("DriverVersion"),
            "source": "win32_video_controller",
        })
    return gpus


def probe_lspci() -> list[dict[str, Any]]:
    code, stdout, _stderr = _run(["lspci", "-nn"])
    if code != 0 or not stdout:
        return []
    gpus = []
    for line in stdout.splitlines():
        lower = line.lower()
        if not any(kind in lower for kind in ("vga compatible controller", "3d controller", "display controller")):
            continue
        vendor = _vendor_from_text(line)
        if vendor == "unknown":
            continue
        name = line.split(":", 2)[-1].strip()
        gpus.append({
            "vendor": vendor,
            "name": name,
            "vram_mb": None,
            "source": "lspci",
        })
    return gpus


def probe_apple_silicon() -> list[dict[str, Any]]:
    if platform.system().lower() != "darwin":
        return []
    machine = platform.machine().lower()
    if machine not in {"arm64", "aarch64"}:
        return []
    return [{
        "vendor": "apple",
        "name": "Apple Silicon GPU",
        "vram_mb": None,
        "architecture": "apple-silicon",
        "mps": {"potential": True},
        "source": "platform",
    }]


def probe_rocm() -> dict[str, Any]:
    targets: list[str] = []
    code, stdout, _stderr = _run(["rocminfo"], timeout=12)
    if code == 0 and stdout:
        for match in re.finditer(r"\bgfx[0-9a-fA-F]+", stdout):
            target = match.group(0).lower()
            if target not in targets:
                targets.append(target)
    return {
        "rocminfo_found": code == 0,
        "llvm_targets": targets,
        "official_targets": [target for target in targets if target in AMD_OFFICIAL_ROCM_TARGETS],
        "support": (
            "official"
            if any(target in AMD_OFFICIAL_ROCM_TARGETS for target in targets)
            else ("community_experimental" if targets else "unsupported")
        ),
    }


def probe_torch() -> dict[str, Any]:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        return {"installed": False, "error": str(exc)}

    devices = []
    cuda_available = False
    cuda_error = None
    try:
        cuda_available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if cuda_available else 0
        for index in range(count):
            props = torch.cuda.get_device_properties(index)
            cap = None
            try:
                cap = list(torch.cuda.get_device_capability(index))
            except Exception:
                cap = None
            devices.append({
                "index": index,
                "name": props.name,
                "total_memory_mb": round(int(props.total_memory) / 1024**2),
                "compute_capability_tuple": cap,
            })
    except Exception as exc:
        cuda_error = str(exc)

    mps_built = False
    mps_available = False
    try:
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None:
            is_built = getattr(mps, "is_built", None)
            is_available = getattr(mps, "is_available", None)
            mps_built = bool(is_built()) if is_built else False
            mps_available = bool(is_available()) if is_available else False
    except Exception:
        pass

    info = {
        "installed": True,
        "version": getattr(torch, "__version__", None),
        "cuda_available": cuda_available,
        "device_count": len(devices),
        "devices": devices,
        "torch_cuda_version": getattr(torch.version, "cuda", None),
        "torch_hip_version": getattr(torch.version, "hip", None),
        "mps_built": mps_built,
        "mps_available": mps_available,
    }
    if cuda_error:
        info["cuda_error"] = cuda_error
    return info


def _vendor_from_text(value: str) -> str:
    lower = value.lower()
    if "nvidia" in lower or "ven_10de" in lower or "10de:" in lower:
        return "nvidia"
    if "amd" in lower or "advanced micro devices" in lower or "radeon" in lower or "ven_1002" in lower or "1002:" in lower:
        return "amd"
    if "intel" in lower or "8086:" in lower or "ven_8086" in lower:
        return "intel"
    return "unknown"


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _attach_rocm(gpus: list[dict[str, Any]], rocm: dict[str, Any]) -> None:
    targets = rocm.get("llvm_targets") or []
    official = rocm.get("official_targets") or []
    for gpu in gpus:
        if gpu.get("vendor") != "amd":
            continue
        gpu["rocm"] = {
            "visible": bool(targets),
            "llvm_targets": targets,
            "official_targets": official,
            "support": "official" if official else ("community_experimental" if targets else "unsupported"),
        }


def _attach_torch_devices(gpus: list[dict[str, Any]], torch_info: dict[str, Any]) -> None:
    if torch_info.get("mps_available"):
        apple = [gpu for gpu in gpus if gpu.get("vendor") == "apple"]
        if apple:
            apple[0].setdefault("mps", {})
            apple[0]["mps"].update({"torch_visible": True, "available": True})
        else:
            gpus.append({
                "vendor": "apple",
                "name": "Apple Silicon GPU",
                "vram_mb": None,
                "architecture": "apple-silicon",
                "mps": {"torch_visible": True, "available": True},
                "source": "torch",
            })

    devices = torch_info.get("devices") or []
    if not devices:
        return
    vendor = "amd" if torch_info.get("torch_hip_version") else "nvidia"
    existing = [gpu for gpu in gpus if gpu.get("vendor") == vendor]
    for index, device in enumerate(devices):
        if index < len(existing):
            gpu = existing[index]
            gpu.setdefault("torch", {})
            gpu["torch"].update({
                "visible": True,
                "name": device.get("name"),
                "total_memory_mb": device.get("total_memory_mb"),
            })
            if device.get("total_memory_mb") and not gpu.get("vram_mb"):
                gpu["vram_mb"] = device["total_memory_mb"]
            if device.get("compute_capability_tuple") and not gpu.get("compute_capability_tuple"):
                gpu["compute_capability_tuple"] = device["compute_capability_tuple"]
            continue
        gpus.append({
            "index": index,
            "vendor": vendor,
            "name": device.get("name") or f"torch device {index}",
            "vram_mb": device.get("total_memory_mb"),
            "compute_capability_tuple": device.get("compute_capability_tuple"),
            "torch": {"visible": True},
            "source": "torch",
        })


def collect_report(path: str | None = None) -> dict[str, Any]:
    root = path or os.getcwd()
    gpus = []
    gpus.extend(probe_nvidia_smi())
    gpus.extend(probe_windows_video())
    gpus.extend(probe_lspci())
    gpus.extend(probe_apple_silicon())
    rocm = probe_rocm()
    torch_info = probe_torch()
    gpus = _merge_gpus(gpus)
    _attach_rocm(gpus, rocm)
    _attach_torch_devices(gpus, torch_info)
    gpus = _merge_gpus(gpus)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "memory": _memory_info(),
        "disk": _disk_info(root),
        "gpus": gpus,
        "rocm": rocm,
        "torch": torch_info,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit HFabric hardware capability JSON.")
    parser.add_argument("--output", "-o", help="Write JSON to this file instead of stdout.")
    parser.add_argument("--path", default=os.getcwd(), help="Path used for disk-free reporting.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    args = parser.parse_args(argv)

    report = collect_report(args.path)
    data = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(data)
    else:
        sys.stdout.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
