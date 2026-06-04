"""Background fetcher for ungated enabler models.

Downloads the models that unblock model-gated roadmap items (RAG embeddings, TTS,
vision) into the right local folders. Gated repos (e.g. FLUX.2 klein) are NOT
fetched here — they need the user's license acceptance + HF token.

    python scripts/fetch_models.py
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

# (repo_id, filename, destination_dir)
JOBS = [
    # SDXL turbo validation / optional acceleration
    ("ByteDance/SDXL-Lightning", "sdxl_lightning_4step_lora.safetensors", MODELS / "lora"),
    # RAG embeddings (served via llama-server --embeddings)
    ("nomic-ai/nomic-embed-text-v1.5-GGUF", "nomic-embed-text-v1.5.f16.gguf", MODELS / "embed"),
    # TTS workspace: OuteTTS model + WavTokenizer vocoder
    ("OuteAI/OuteTTS-0.2-500M-GGUF", "OuteTTS-0.2-500M-Q8_0.gguf", MODELS / "tts"),
    ("ggml-org/WavTokenizer", "WavTokenizer-Large-75-F16.gguf", MODELS / "tts"),
    # Vision (multimodal): Qwen2.5-VL-3B + its mmproj projector
    ("ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf", MODELS / "vision"),
    ("ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf", MODELS / "vision"),
]


def main() -> None:
    for repo, fname, dest in JOBS:
        dest.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] {repo}/{fname} -> {dest}", flush=True)
        try:
            path = hf_hub_download(repo_id=repo, filename=fname, local_dir=str(dest))
            print(f"[done]  {path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL]  {repo}/{fname}: {type(exc).__name__}: {exc}", flush=True)
    print("[all done]", flush=True)


if __name__ == "__main__":
    main()
