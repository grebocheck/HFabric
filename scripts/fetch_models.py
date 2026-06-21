"""Download a profile-aware starter model set.

The installer calls this in ``setup all`` / ``setup.ps1 -DownloadAll`` so a new
machine gets models that match the selected accelerator profile instead of a
CUDA-centric grab bag. The pure planning helpers are intentionally separate from
the network download loop so CI can test the decisions without touching Hugging
Face.

    python scripts/fetch_models.py --dry-run
    python scripts/fetch_models.py --profile apple-mps --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

MODELS = ROOT / "models"


@dataclass(frozen=True)
class FetchJob:
    repo: str
    filename: str
    dest: Path
    label: str
    reason: str
    approx_size_mb: int = 0
    license: str = ""
    profiles: tuple[str, ...] = ("nvidia-cuda", "amd-rocm-linux", "apple-mps")
    feature: str | None = None
    source: str = "hf-file"  # hf-file | hf-repo
    local_subdir: str = ""
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    present_markers: tuple[str, ...] = ("model_index.json",)

    def target_dir(self) -> Path:
        return self.dest / self.local_subdir if self.local_subdir else self.dest

    def display_filename(self) -> str:
        return self.filename or (f"{self.local_subdir}/" if self.local_subdir else ".")

    def is_present(self) -> bool:
        if self.source == "hf-repo":
            target = self.target_dir()
            if self.present_markers:
                return all((target / marker).exists() for marker in self.present_markers)
            return target.exists() and any(target.iterdir())
        return (self.target_dir() / self.filename).exists()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "repo": self.repo,
            "filename": self.display_filename(),
            "dest": str(self.target_dir().relative_to(ROOT)),
            "label": self.label,
            "reason": self.reason,
            "approx_size_mb": self.approx_size_mb,
            "license": self.license,
            "source": self.source,
        }
        if self.feature:
            out["feature"] = self.feature
        return out


STARTER_IMAGE_JOBS = [
    FetchJob(
        "ByteDance/SDXL-Lightning",
        "sdxl_lightning_4step.safetensors",
        MODELS / "image",
        "SDXL Lightning 4-step checkpoint",
        "profile-safe starter image model for CUDA, ROCm, and Apple MPS",
        approx_size_mb=6900,
        license="OpenRAIL++",
    ),
    FetchJob(
        "nunchaku-tech/nunchaku-flux.1-dev",
        "svdq-fp4_r32-flux.1-dev.safetensors",
        MODELS / "image",
        "FLUX.1 dev Nunchaku fp4",
        "fast FLUX path when the NVIDIA CUDA/Nunchaku feature is available",
        approx_size_mb=6500,
        license="FLUX.1-dev Non-Commercial",
        profiles=("nvidia-cuda",),
        feature="nunchaku_cuda",
    ),
]

ADVANCED_IMAGE_JOBS = [
    FetchJob(
        "black-forest-labs/FLUX.2-klein-9B",
        "",
        MODELS / "image",
        "FLUX.2 klein 9B full repo",
        "full FLUX.2 [klein] diffusers repo for 16 GB+ CUDA experiments",
        approx_size_mb=22_000,
        license="see model card",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="flux2-klein-9b",
    ),
    FetchJob(
        "Tongyi-MAI/Z-Image-Turbo",
        "",
        MODELS / "image",
        "Z-Image-Turbo full repo",
        "distilled full image model; backend defaults to 1024x1024, 9 steps, guidance 0.0",
        approx_size_mb=12_000,
        license="see model card",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="z-image-turbo",
        exclude_patterns=("assets/*",),
    ),
    FetchJob(
        "Tongyi-MAI/Z-Image",
        "",
        MODELS / "image",
        "Z-Image full repo",
        "base Z-Image repo; backend defaults to 1024x1024, 50 steps, guidance 4.0, bnb-fp4",
        approx_size_mb=20_000,
        license="see model card",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="z-image",
        exclude_patterns=("assets/*",),
    ),
    FetchJob(
        "Qwen/Qwen-Image-2512",
        "",
        MODELS / "image",
        "Qwen-Image-2512 full repo",
        "large full image repo; advanced only because disk/RAM requirements are high",
        approx_size_mb=54_000,
        license="see model card",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="qwen-image-2512",
    ),
    FetchJob(
        "Qwen/Qwen-Image-Edit-2509",
        "",
        MODELS / "image",
        "Qwen-Image-Edit-2509 full repo",
        "instruction editing with a source image; separate arbiter resident",
        approx_size_mb=54_000,
        license="see model card",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="qwen-image-edit-2509",
    ),
    FetchJob(
        "black-forest-labs/FLUX.1-Kontext-dev",
        "",
        MODELS / "image",
        "FLUX.1 Kontext dev full repo",
        "instruction editing with a source image; separate arbiter resident",
        approx_size_mb=24_000,
        license="FLUX.1-dev Non-Commercial",
        profiles=("nvidia-cuda",),
        source="hf-repo",
        local_subdir="flux-kontext-dev",
    ),
]

COMMON_JOBS = [
    FetchJob(
        "ByteDance/SDXL-Lightning",
        "sdxl_lightning_4step_lora.safetensors",
        MODELS / "lora",
        "SDXL Lightning LoRA",
        "optional turbo LoRA for SDXL checkpoints",
        approx_size_mb=390,
        license="OpenRAIL++",
    ),
    FetchJob(
        "Gron1-ai/Gemma-3-12B-it-Heretic-v2-GGUF",
        "gemma-3-12b-it-heretic-v2-Q4_K_M.gguf",
        MODELS / "llm",
        "Gemma 3 12B GGUF",
        "starter local chat model for llama.cpp",
        approx_size_mb=7300,
        license="Gemma Terms of Use",
    ),
    FetchJob(
        "nomic-ai/nomic-embed-text-v1.5-GGUF",
        "nomic-embed-text-v1.5.f16.gguf",
        MODELS / "embed",
        "Nomic embedding GGUF",
        "starter RAG embedding model",
        approx_size_mb=280,
        license="Apache-2.0",
    ),
    FetchJob(
        "OuteAI/OuteTTS-0.2-500M-GGUF",
        "OuteTTS-0.2-500M-Q8_0.gguf",
        MODELS / "tts",
        "OuteTTS GGUF",
        "starter TTS acoustic model",
        approx_size_mb=530,
        license="CC-BY-NC-SA-4.0",
    ),
    FetchJob(
        "ggml-org/WavTokenizer",
        "WavTokenizer-Large-75-F16.gguf",
        MODELS / "tts",
        "WavTokenizer vocoder",
        "required vocoder pair for the starter TTS model",
        approx_size_mb=170,
        license="see model card",
    ),
    FetchJob(
        "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
        "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        MODELS / "vision",
        "Qwen2.5-VL 3B GGUF",
        "starter local vision model",
        approx_size_mb=2200,
        license="Qwen License",
    ),
    FetchJob(
        "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
        "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
        MODELS / "vision",
        "Qwen2.5-VL projector",
        "projector file paired with the starter vision model",
        approx_size_mb=850,
        license="Qwen License",
    ),
]


def synthetic_profile(profile_id: str) -> dict[str, Any]:
    """Minimal planner-only profile used for cross-device dry-run demos."""
    optional: list[str] = []
    if profile_id == "nvidia-cuda":
        optional = ["nunchaku_cuda"]
    return {
        "selected_profile": profile_id,
        "hardware_tier": "synthetic_dry_run",
        "optional_features": optional,
    }


def load_profile(profile_id: str | None = None, *, allow_synthetic: bool = False) -> dict[str, Any]:
    import hardware_probe  # noqa: PLC0415
    import install_profiles  # noqa: PLC0415

    report = hardware_probe.collect_report(str(ROOT))
    try:
        return install_profiles.resolve_profile(report, profile_id)
    except ValueError:
        if profile_id and allow_synthetic:
            return synthetic_profile(profile_id)
        raise


def plan_for_profile(profile: dict[str, Any], *, include_images: bool = True) -> list[FetchJob]:
    profile_id = str(profile.get("selected_profile") or "cpu-safe")
    if profile_id == "cpu-safe":
        return []

    optional = set(profile.get("optional_features") or [])
    jobs: list[FetchJob] = []
    if include_images:
        jobs.extend(_filter_jobs(STARTER_IMAGE_JOBS, profile_id, optional))
    jobs.extend(_filter_jobs(COMMON_JOBS, profile_id, optional))
    return _dedupe(jobs)


def _filter_jobs(jobs: list[FetchJob], profile_id: str, optional: set[str]) -> list[FetchJob]:
    selected = []
    for job in jobs:
        if profile_id not in job.profiles:
            continue
        if job.feature and job.feature not in optional:
            continue
        selected.append(job)
    return selected


def _dedupe(jobs: list[FetchJob]) -> list[FetchJob]:
    out: list[FetchJob] = []
    seen: set[tuple[str, str, Path, str]] = set()
    for job in jobs:
        key = (job.repo, job.display_filename(), job.target_dir(), job.source)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def download_jobs(jobs: list[FetchJob]) -> bool:
    try:
        from huggingface_hub import hf_hub_download, snapshot_download  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"[fetch] huggingface_hub is not installed: {exc}", flush=True)
        return False

    ok = True
    for job in jobs:
        target = job.target_dir()
        target.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] {job.label}: {job.repo}/{job.display_filename()} -> {target}", flush=True)
        try:
            if job.source == "hf-repo":
                path = snapshot_download(
                    repo_id=job.repo,
                    local_dir=str(target),
                    allow_patterns=list(job.include_patterns) or None,
                    ignore_patterns=list(job.exclude_patterns) or None,
                )
            else:
                path = hf_hub_download(repo_id=job.repo, filename=job.filename, local_dir=str(target))
            print(f"[done]  {path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[FAIL]  {job.repo}/{job.display_filename()}: {type(exc).__name__}: {exc}", flush=True)
    print("[all done]" if ok else "[done with failures]", flush=True)
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download starter models for the detected HFabric profile.")
    parser.add_argument(
        "--profile",
        choices=("nvidia-cuda", "amd-rocm-linux", "apple-mps", "cpu-safe"),
        help="Force a profile id. With --dry-run this can show a cross-device starter plan.",
    )
    parser.add_argument("--no-images", action="store_true", help="Only download LLM/RAG/TTS/Vision enabler models.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without downloading.")
    parser.add_argument("--json", action="store_true", help="Emit the plan as JSON.")
    args = parser.parse_args(argv)

    try:
        profile = load_profile(args.profile, allow_synthetic=args.dry_run)
    except ValueError as exc:
        print(f"[fetch] {exc}", file=sys.stderr, flush=True)
        return 2
    jobs = plan_for_profile(profile, include_images=not args.no_images)
    payload = {
        "profile": profile.get("selected_profile"),
        "hardware_tier": profile.get("hardware_tier"),
        "jobs": [job.as_dict() for job in jobs],
    }
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        print(f"[profile] {payload['profile']} ({payload['hardware_tier']})", flush=True)
        if not jobs:
            print("[fetch] no real-model downloads for CPU-safe/STUB profile", flush=True)
        for job in jobs:
            print(f"[plan] {job.label}: {job.reason}", flush=True)
    if args.dry_run:
        return 0
    if not jobs:
        return 0
    return 0 if download_jobs(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
