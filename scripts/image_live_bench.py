#!/usr/bin/env python3
"""Direct, server-less smoke/benchmark for one local image model.

Drives ``DiffusersImageBackend`` straight from the registry so we can measure
real load time, generation time and peak VRAM/RAM for a single model without
booting the whole FastAPI server. Samples memory via the same NVML/psutil path
the app uses (``sysmon``), so numbers match the running app.

    .venv\\Scripts\\python.exe scripts/image_live_bench.py z-image-turbo
    .venv\\Scripts\\python.exe scripts/image_live_bench.py qwen-image-2512 --steps 20

It writes the produced PNG under data/outputs/<day>/ like the real app.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("HFAB_STUB_MODE", "false")


class MemSampler:
    """Background NVML/psutil sampler -> peak VRAM/RAM, min free VRAM/RAM."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.samples: list[dict] = []

    def _run(self) -> None:
        from app.util import sysmon  # noqa: PLC0415

        while not self._stop.is_set():
            self.samples.append(sysmon.snapshot())
            self._stop.wait(self.interval)

    def __enter__(self) -> "MemSampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _peak(self, *path: str) -> float:
        vals = [self._dig(s, path) for s in self.samples]
        vals = [v for v in vals if isinstance(v, (int, float))]
        return max(vals) if vals else 0.0

    def _valley(self, *path: str) -> float:
        vals = [self._dig(s, path) for s in self.samples]
        vals = [v for v in vals if isinstance(v, (int, float))]
        return min(vals) if vals else 0.0

    @staticmethod
    def _dig(sample: dict, path: tuple[str, ...]):
        cur = sample
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    def report(self) -> dict:
        return {
            "peak_vram_used_gb": round(self._peak("vram", "used_gb"), 2),
            "min_vram_free_gb": round(self._valley("vram", "free_gb"), 2),
            "peak_ram_used_gb": round(self._peak("ram", "used_gb"), 2),
            "peak_process_rss_gb": round(self._peak("ram", "process_rss_gb"), 2),
            "min_ram_available_gb": round(self._valley("ram", "available_gb"), 2),
            "n_samples": len(self.samples),
        }


async def main(args: argparse.Namespace) -> int:
    from app.backends.registry import ModelRegistry  # noqa: PLC0415

    reg = ModelRegistry()
    reg.scan()
    ids = [d.id for d in reg.descriptors()]
    if args.model not in ids:
        print(f"Unknown model id {args.model!r}. Available: {ids}", file=sys.stderr)
        return 2

    desc = reg.get_descriptor(args.model)
    backend = reg.get_backend(args.model)
    print(f"== {desc.id}  family={desc.family.value}  quant={desc.quant}  "
          f"size={desc.size_bytes / 1e9:.1f} GB ==", flush=True)

    last_note = {"v": ""}

    async def progress(frac: float, note: str | None) -> None:
        if note and note != last_note["v"]:
            last_note["v"] = note
            print(f"  [{frac * 100:5.1f}%] {note}", flush=True)

    with MemSampler() as mem:
        t0 = time.monotonic()
        try:
            await backend.load()
        except Exception as exc:  # noqa: BLE001
            print(f"\nLOAD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            import traceback  # noqa: PLC0415
            traceback.print_exc()
            print(json.dumps({"phase": "load", "mem": mem.report()}, indent=2))
            return 1
        t_load = time.monotonic() - t0
        print(f"loaded in {t_load:.1f}s", flush=True)

        params = {
            "prompt": args.prompt,
            "negative": args.negative or None,
            "steps": args.steps,
            "guidance": args.guidance,
            "width": args.width,
            "height": args.height,
            "seed": args.seed,
            "batch_size": 1,
        }
        # drop Nones so family defaults kick in
        params = {k: v for k, v in params.items() if v is not None}

        t1 = time.monotonic()
        try:
            results = await backend.generate(params, progress)
        except Exception as exc:  # noqa: BLE001
            print(f"\nGENERATE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            import traceback  # noqa: PLC0415
            traceback.print_exc()
            print(json.dumps({"phase": "generate", "load_seconds": round(t_load, 1),
                              "mem": mem.report()}, indent=2))
            return 1
        t_gen = time.monotonic() - t1

    rec = results[0]
    steps = rec["params"].get("steps", args.steps)
    summary = {
        "model": desc.id,
        "family": desc.family.value,
        "quant": desc.quant,
        "load_seconds": round(t_load, 1),
        "generate_seconds": round(t_gen, 1),
        "seconds_per_step": round(t_gen / max(1, steps), 2),
        "effective_steps": steps,
        "width": rec["width"],
        "height": rec["height"],
        "output": rec["path"],
        "mem": mem.report(),
        "acceleration": (backend.load_report or {}).get("acceleration"),
        "active_features": {k: v for k, v in (rec["params"].get("acceleration") or {}).items()
                            if k in ("qwen_image", "z_image", "attention")},
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))

    await backend.unload()
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("model", help="model id, e.g. z-image-turbo or qwen-image-2512")
    p.add_argument("--prompt", default="A photorealistic portrait of a red fox sitting in autumn leaves, soft morning light, shallow depth of field")
    p.add_argument("--negative", default="")
    p.add_argument("--steps", type=int, default=0, help="0 = family default")
    p.add_argument("--guidance", type=float, default=-1.0, help="<0 = family default")
    p.add_argument("--width", type=int, default=0, help="0 = family default")
    p.add_argument("--height", type=int, default=0, help="0 = family default")
    p.add_argument("--seed", type=int, default=20260608)
    args = p.parse_args()
    # 0/negative sentinels -> omit so the backend's family defaults apply
    if args.steps <= 0:
        args.steps = None
    if args.guidance < 0:
        args.guidance = None
    if args.width <= 0:
        args.width = None
    if args.height <= 0:
        args.height = None
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parse_args())))
