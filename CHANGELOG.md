# Changelog

All notable changes to HFabric are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/). Until 1.0.0, minor versions may
include breaking changes — this is pre-release software.

## [Unreleased]

### Added
- **Prompt library** (P19.4): save, search, tag, and reuse image-prompt snippets
  from the composer; export/import as JSON. New `/api/prompts` + `prompt_snippets`
  table.
- **Release pipeline** (P24): a tag-triggered GitHub Actions workflow
  (`.github/workflows/release.yml`) that reuses the CI gates and publishes a
  **pre-release** with a `git archive` source bundle + SHA-256 checksum and notes
  drawn from this changelog. New `scripts/release.py` handles version/tag/changelog
  discipline (`check-tag` guards that a tag matches `app.__version__`).

_Toward the first public `0.1` beta (see [ROADMAP](ROADMAP.md) phase P24): the
release pipeline above is in place; remaining are the beta framing, a feedback/
bug-report loop, and first-impression polish._

## [0.1.0] — pre-release

First version prepared for testing by people other than the author. Real-GPU
validated on NVIDIA / RTX 5070 Ti / Windows 11; AMD ROCm and Apple Silicon MPS
are implemented but experimental (unvalidated on real hardware).

### Core
- VRAM arbiter: at most one resident heavy model, with a RAM-budget guard that
  refuses a load before it can spill to the pagefile.
- Phase-batching scheduler: a mixed LLM/image batch drains with a single model swap.
- Persisted SQLite queue that resumes on restart; live progress over WebSocket.

### Generation & workspaces
- Image: SDXL, FLUX (Nunchaku fp4), FLUX.2 [klein], Qwen-Image, Z-Image; img2img
  and inpainting (SDXL); reproduce/vary; measured-VRAM model & LoRA pickers.
- Chat LLM via llama.cpp: streaming, personas, sampling control,
  stop/regenerate/edit, `/image` bridge, `generate_image`/`search_documents` tools.
- Workspaces: RAG, TTS, Transcribe, Notes, Code, and a native RVC Voice changer
  (validated with a real mic) — all model-gated and CPU-first by default. Image
  understanding is chat-native (attach an image to a multimodal LLM).
- History: responsive grid, combinable filters, favorites/tags, bulk delete + ZIP.

### Trust, data, distribution
- Optional `HFAB_API_TOKEN` bearer auth (REST + WS); desktop-reaching endpoints
  loopback-gated regardless of token; default bind `127.0.0.1`.
- Alembic migrations; rotating `data/logs/hfabric.log`; `scripts/backup.py`.
- Production serving (`HFAB_SERVE_FRONTEND=true`) and a `--prod` one-command launcher.
- First-class Settings tab with validated overrides persisted to
  `data/settings-overrides.json`.

### Universal install
- Hardware probe + install-profile resolver (`nvidia-cuda`, `amd-rocm-linux`,
  `apple-mps`, `cpu-safe`) used by both setup and launcher.
- Capability profile gates models/features per GPU; startup autotune toward safe
  acceleration defaults; per-model availability in `/api/models`.
- Setup Doctor (plain-language detected hardware) and a managed, updatable
  llama.cpp runtime with rollback and `--version` verification.
- In-app **Model downloads** manager: hardware-aware curated catalog with
  size/license/target-dir, Recommended preselected, disk-budget guard, and live
  progress.

[Unreleased]: https://github.com/grebocheck/HFabric/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/grebocheck/HFabric/releases/tag/v0.1.0
