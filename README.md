# HFabric

A **local** AI workspace that pairs a chat **LLM** with **diffusion image
generation** on a single consumer GPU — without fighting over VRAM. Its core is a
**VRAM arbiter**: at most one heavy model is resident at a time, and a
phase-batching scheduler swaps LLM ↔ image models as rarely as possible (ideally
once per batch). Everything runs on your machine; nothing is sent to a cloud
service.

Beyond chat and image generation, the same shell hosts RAG (chat-with-documents),
vision (multimodal image analysis), text-to-speech, transcription, and a native
real-time voice changer — all gated through the same GPU arbiter so they never
collide.

> **Project status: pre-release (B+ / 8.0).** Solid for the author's own daily use
> and being prepared for testing by others. The core pipeline is real-GPU
> validated; some platforms and features are still experimental. See
> [Platform support](#platform-support) and the
> [release-readiness audit](docs/audit-2026-06-14.md) for an honest picture.

## Table of contents

- [What you can run](#what-you-can-run)
- [Platform support](#platform-support)
- [Requirements](#requirements)
- [Quick start (no GPU)](#quick-start-no-gpu)
- [Full install (GPU)](#full-install-gpu)
- [Getting models](#getting-models)
- [Running the app](#running-the-app)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [License and models](#license-and-models)

## What you can run

The full pipeline (model discovery → queue → arbiter swap → live progress over
WebSocket → gallery with reproducible metadata) is validated on the GPU today:

- **Image:** SDXL, FLUX (Nunchaku fp4), FLUX.2 [klein], Qwen-Image, Z-Image.
- **Chat LLM:** any GGUF model via `llama-server`, with streaming, personas,
  sampling control, stop/regenerate/edit, and a `/image` bridge.
- **Workspaces:** RAG, Vision, TTS, Transcribe, Notes, Code, and a native RVC
  Voice changer — all model-gated and CPU-first by default.

The same pipeline also runs **without** torch or llama.cpp in **STUB mode**
(`HFAB_STUB_MODE=true`), which returns mock results. STUB mode is how the UI is
developed and how CI tests the whole queue→swap→gallery flow without a GPU.

## Platform support

The launcher probes your hardware and picks an install profile automatically. Be
aware of what's actually been validated:

| Platform | Profile | Status |
|----------|---------|--------|
| **NVIDIA CUDA (Windows)** | `nvidia-cuda` | ✅ **Validated** end-to-end on RTX 5070 Ti 16 GB (Blackwell), 32 GB RAM, Windows 11. The reference path. |
| NVIDIA CUDA (other tiers) | `nvidia-cuda` | ⚠️ Capability-aware (8 GB = SDXL/small-LLM safe mode, 12 GB +quantized LLMs, 16 GB+ richer set). Fast paths auto-disable below the required compute capability. Not yet validated on non-Blackwell silicon. |
| **AMD ROCm (Linux)** | `amd-rocm-linux` | 🧪 **Experimental** — implemented and unit-tested, but never run on real ROCm hardware. SDXL-only until validated. CUDA-only features (Nunchaku, etc.) auto-disable. Testers welcome. |
| **Apple Silicon (MPS)** | `apple-mps` | 🧪 **Experimental** — implemented and unit-tested, never run on a real Mac. SDXL + llama.cpp Metal, fp4 families hidden. Testers welcome. |
| Unsupported / no GPU | `cpu-safe` / STUB | ✅ Always works. CPU-safe falls back gracefully; STUB needs no ML stack at all. |

If you're on ROCm or Apple Silicon and willing to help validate, the
[GPU smoke checklist](docs/gpu-smoke.md) has the steps and a log to fill in.

## Requirements

| | |
|---|---|
| **GPU** | NVIDIA CUDA with 8+ GB VRAM recommended (16+ GB for the full image set). AMD ROCm (Linux) and Apple MPS supported conservatively. No supported GPU → CPU-safe/STUB. |
| **RAM** | 32 GB recommended (≈16 GB for models + 16 GB for OS/processes). |
| **OS** | Windows 11 (validated CUDA path), Linux (ROCm), macOS Apple Silicon (MPS). |
| **Disk** | 40+ GB for the starter set; 150 GB for the larger FLUX/SDXL/LLM workspace. |
| **Python** | 3.12+ — `python --version` |
| **Node.js** | 18+ (20 recommended) — `node --version` |
| **Git** | optional, used by `huggingface-cli` for model downloads |

A recent GPU driver is needed for acceleration (`nvidia-smi` should report your
GPU on NVIDIA). Without one, setup still works in CPU-safe/STUB mode.

## Quick start (no GPU)

The fastest way to see the app: STUB mode runs the entire pipeline with mock
results and no ML libraries (~1–2 min first run).

```bat
:: Windows
run.bat stub
```

```bash
# Linux/macOS
./run.sh stub
```

```powershell
# PowerShell
.\scripts\run.ps1 -Stub
```

This bootstraps the Python venv + npm deps on first run, starts the backend
(`:8260`) and the Vite dev server (`:5173`), and opens
<http://localhost:5173>. **Ctrl+C** stops both. Try the chat/image forms — you'll
see mock responses. This is the right mode for UI work and for confirming the
foundation before adding a GPU.

## Full install (GPU)

**REAL mode** loads actual LLMs and diffusion models onto your accelerator. Use
the setup script for your platform — it probes hardware and picks the recommended
profile (`nvidia-cuda`, `amd-rocm-linux`, `apple-mps`, or `cpu-safe`):

```bat
:: Windows
setup.bat          :: auto setup
setup.bat all      :: auto setup + download a profile-aware starter model set
```

```bash
# Linux/macOS
./setup.sh         # auto setup
./setup.sh all     # auto setup + starter models
```

```powershell
# PowerShell
.\setup.ps1            # auto setup
.\setup.ps1 -DownloadAll  # auto setup + starter models
```

The setup script: checks Python/Node, probes hardware and selects a profile,
creates the venv, installs the profile's PyTorch wheels + Python deps, installs
npm packages, installs the managed `llama.cpp` build for your accelerator,
installs Nunchaku when the CUDA profile supports it, and (with `all`) downloads
the starter models. When finished, run the app with `run.bat` / `./run.sh`.

<details>
<summary><b>Manual GPU install (advanced)</b></summary>

Start from the same resolver the installer uses, then install the emitted
packages:

```powershell
python scripts/hardware_probe.py --pretty     # machine report
python scripts/install_profiles.py --pretty    # chosen profile + packages
```

The current profiles map to:

```powershell
# NVIDIA CUDA
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r backend/requirements-gpu.txt

# Linux AMD ROCm
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/rocm7.2
pip install -r backend/requirements-rocm.txt

# Apple Silicon MPS (standard PyPI wheels, no --index-url)
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0
pip install -r backend/requirements-mps.txt
```

Verify with `python scripts/install_smoke.py`. For faster FLUX on CUDA, install
the Nunchaku wheel **only** when `/api/capabilities` lists `nunchaku_cuda` in
`optional_features`:

```bash
pip install https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-win_amd64.whl
```

</details>

## Getting models

Models are **not** included in this repo and are not covered by its license — they
are user-supplied with their own provider terms (see
[MODEL_NOTICE.md](MODEL_NOTICE.md)). They live under `models/` and are read in
place; nothing is copied into the venv.

**Easiest:** once the app is running, open the **System** tab → **Model
downloads**. It lists curated starter models that fit your hardware (Recommended
preselected), shows each model's size, license, and target folder, guards against
filling the disk, and downloads with a progress bar — no terminal needed.

From the command line, the equivalent is the hardware-aware starter downloader
(also run by `setup … all`):

```bash
python scripts/fetch_models.py --dry-run                 # show the plan for this machine
python scripts/fetch_models.py --profile apple-mps --dry-run   # plan for another profile
python scripts/fetch_models.py                            # download
```

It fetches a safe SDXL Lightning starter + GGUFs for chat/RAG/TTS/vision on CUDA,
ROCm, and MPS, plus the Nunchaku FLUX fp4 checkpoint on CUDA when supported.
CPU-safe/STUB downloads nothing.

For the full curated list, folder layout, and per-family notes (FLUX.2 klein,
Qwen-Image, Z-Image, voice/DTLN assets), see **[models/README.md](models/README.md)**.

## Running the app

```bat
run.bat            :: auto-select REAL/STUB from the hardware profile
run.bat stub       :: STUB mode: full pipeline, no GPU/ML stack
run.bat --prod     :: production: one FastAPI port serves the built frontend
```

```bash
./run.sh           # same options on Linux/macOS
```

```powershell
.\scripts\run.ps1 [-Stub] [-Prod]
```

On first run it bootstraps the venv + npm deps, frees any stale ports left by an
earlier run, then runs the backend (`:8260`) and the Vite dev server (`:5173`)
together in one window and opens <http://localhost:5173>. Ctrl+C stops both.

`--prod` builds the frontend and serves it from FastAPI on a single port (no Node
at runtime) — simpler for daily use and a smaller surface to secure.

After submitting a generation job, watch your GPU monitor (`nvidia-smi -l 1`,
`rocm-smi`, or Activity Monitor) fill and empty as the arbiter loads and frees the
model. The backend console (and `data/logs/hfabric.log`) shows timing, memory
snapshots, and load/unload events.

## Architecture

```
                       ┌───────────────── FastAPI (app.main) ─────────────────┐
  React + Tailwind ──► │  REST /api/*          WebSocket /ws (event stream)    │
  (Vite, :5173)        │     │                        ▲                        │
                       │     ▼                        │ events                 │
                       │  Queue (SQLite) ─► Worker ─► EventBus                  │
                       │                      │                                │
                       │                      ▼  phase-batching                │
                       │                 GpuArbiter  ── at most ONE resident   │
                       │                   /     \                             │
                       │     DiffusersImageBackend   LlamaCppBackend           │
                       │     (FLUX / SDXL / …)       (llama-server subprocess) │
                       └───────────────────────────────────────────────────────┘
```

Key backend modules:

- `app/core/arbiter.py` — the VRAM arbiter (load/unload, one resident max, RAM
  budget guard before every load).
- `app/core/scheduler.py` — single GPU worker + phase-batching select.
- `app/core/events.py` — in-process pub/sub, streamed over `/ws`.
- `app/backends/` — `registry` (scan model files), `image_diffusers`,
  `llm_llamacpp`.
- `app/services/capability_profile.py` — resolves what the detected hardware can
  safely run; gates models and features.
- `app/db/` — SQLAlchemy models; the queue is persisted (Alembic-migrated) and
  resumes on restart.

A full design walk-through is in the [developer guide](docs/developer.md).

## Configuration

Two surfaces, deliberately separated:

- **`.env`** — only system-startup posture (bind host/port, optional API token,
  frontend serving). Copy `.env.example` to `.env`.
- **Settings tab** — everything else (model paths, acceleration, memory policy,
  LLM runtime, speech/RAG/vision/voice), typed and saved to
  `data/settings-overrides.json`, applied live.

```env
HFAB_HOST=127.0.0.1
HFAB_PORT=8260
# HFAB_API_TOKEN=change-me     # required before binding to a LAN address
HFAB_SERVE_FRONTEND=false
```

**Security model in one line:** HFabric is a local single-user app bound to
`127.0.0.1` by default; exposing it on a LAN (`HFAB_HOST=0.0.0.0`) requires
`HFAB_API_TOKEN`, and desktop-reaching actions stay loopback-only regardless.

The full env/Settings/knob reference (acceleration, llama.cpp, LoRA, keep-warm,
speech/RAG/vision/voice, capability autotune) is in
**[docs/configuration.md](docs/configuration.md)**.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **`WinError 10013: socket forbidden`** | A previous run still holds port 8260/5173. Re-run `run.bat` (it auto-kills stale processes), or `netstat -ano \| findstr :8260` then `taskkill /PID <pid> /F`. |
| **`ModuleNotFoundError: torch`** | venv not active or torch not installed. Delete `backend\.venv` and re-run `run.bat`, or `pip install -r backend/requirements-gpu.txt`. |
| **CUDA out of memory** | Lower **Settings → LLM runtime → GPU layers**, disable **torch.compile**, reduce resolution, try a smaller model, or check **Settings → Memory policy**. |
| **"No image models discovered"** | Models are missing or in the wrong folder. Confirm files under `models/image/`, `models/llm/`, etc., or run `python scripts/fetch_models.py`. |
| **Vite dev server won't start** | Port 5173 conflict (`run.bat` frees it automatically) or `npm install` in `frontend/` failed. |
| **Backend crashes after first request** | A REAL-mode code path with no ML stack installed. Install GPU deps, or use `run.bat stub`. |

More detail and logs: the backend console and `data/logs/hfabric.log` are the
first places to look. Hardware/profile diagnostics:

```powershell
python scripts/hardware_probe.py --pretty
python scripts/install_profiles.py --pretty
```

## Documentation

| Doc | What's in it |
|-----|--------------|
| [docs/configuration.md](docs/configuration.md) | All env vars + Settings knobs + security model |
| [docs/developer.md](docs/developer.md) | Layout, testing, migrations, backup/restore, contributing |
| [docs/gpu-smoke.md](docs/gpu-smoke.md) | Real-GPU validation checklist + the validation log |
| [models/README.md](models/README.md) | Model folder layout + curated download list |
| [docs/voice-routing.md](docs/voice-routing.md) | Routing the voice changer into Discord/OBS/etc. |
| [docs/audit-2026-06-14.md](docs/audit-2026-06-14.md) | Current release-readiness audit (weaknesses + plan) |
| [ROADMAP.md](ROADMAP.md) | Shipped milestones + active backlog |

## License and models

HFabric application code is free and open-source software under the
[MIT License](LICENSE).

AI model weights, LoRA adapters, GGUF files, checkpoints, tokenizers, datasets,
and voices are **not included** in this repository and are **not** licensed by the
HFabric MIT License. They are user-supplied runtime inputs with their own provider
licenses and terms. See [MODEL_NOTICE.md](MODEL_NOTICE.md) for the full notice.
