# HFabric

Local app that pairs an **LLM (prompt generation)** with **diffusion image
generation**, built to be frugal with memory on a single 16 GB GPU. Its core is a
**VRAM arbiter**: only one heavy model lives in VRAM at a time, and a
**phase-batching scheduler** swaps LLM ↔ image models as few times as possible
(ideally once per batch).

Validated baseline: **RTX 5070 Ti 16 GB (Blackwell), 32 GB RAM, Windows 11**.
The installer now also has conservative profiles for other NVIDIA CUDA GPUs,
Linux AMD ROCm systems, Apple Silicon MPS, and CPU-safe/STUB mode.

## Status

**Working app — real-GPU validated (M0/M1).**
The full pipeline (model discovery → queue → arbiter swap → live progress over
WebSocket → gallery with reproducible metadata) runs on the GPU today: SDXL,
FLUX (Nunchaku fp4), FLUX.2 [klein], and GGUF LLMs via llama-server, plus the
chat / history / RAG / voice workspaces. See the [ROADMAP](ROADMAP.md) for the
shipped milestones and the active backlog.

The same pipeline also runs **without** torch or llama.cpp in **STUB mode**
(`HFAB_STUB_MODE=true`) — used for UI work and as the basis for CI (see
[Testing](#testing)). The launcher probes hardware by default: supported
NVIDIA/ROCm/MPS systems run REAL mode when their profile is supported, while
unsupported systems fall back to CPU-safe/STUB. `run.bat stub` still forces STUB
explicitly.

## License And Models

HFabric application code is free and open-source software under the [MIT License](LICENSE).

AI model weights, LoRA adapters, GGUF files, checkpoints, tokenizers, datasets,
and voices are **not included** in this repository and are not licensed by the
HFabric MIT License. They are user-supplied runtime inputs with their own
provider licenses and terms. See [MODEL_NOTICE.md](MODEL_NOTICE.md) for the
full model notice.

## Installation

### System Requirements

| Requirement | Specification |
|---|---|
| **GPU** | Recommended: NVIDIA CUDA GPU with 8+ GB VRAM (16+ GB for the full image set). Also supported conservatively: Linux AMD ROCm and Apple Silicon MPS. Unsupported GPUs fall back to CPU-safe/STUB. |
| **RAM** | 32 GB minimum (16 GB for models, 16 GB for OS + processes). |
| **OS** | Windows 11 for the validated CUDA path; Linux for ROCm; macOS Apple Silicon for MPS. |
| **Disk** | 40+ GB for the profile starter set; 150 GB recommended for the larger FLUX/SDXL/LLM workspace. |

### Prerequisites

1. **Python 3.12+** ([download](https://www.python.org/downloads/))
   - Ensure `python` and `pip` are in your PATH
   - Verify: `python --version`

2. **Node.js 18+** ([download](https://nodejs.org/))
   - Includes npm
   - Verify: `node --version` and `npm --version`

3. **GPU driver/runtime** (optional, for acceleration)
   - NVIDIA: install a recent NVIDIA driver; `nvidia-smi` should report your GPU.
   - AMD: Linux ROCm is the first supported AMD path; unsupported cards fall back to CPU-safe mode.
   - Apple Silicon: macOS uses PyTorch MPS with the standard PyPI torch wheels.
   - No supported GPU: setup still works in CPU-safe/STUB mode.

4. **Git** (optional, for model downloads)
   - Used by `huggingface-cli` to pull models
   - Verify: `git --version`

### Automated Setup (Recommended)

**Use the setup script for your platform**. It probes hardware and chooses the
recommended profile automatically (`nvidia-cuda`, `amd-rocm-linux`,
`apple-mps`, or `cpu-safe`):

```bat
setup.bat          # Windows auto setup
setup.bat stub     # STUB mode (no GPU, ~1 min)
setup.bat real     # force accelerator setup when available
setup.bat all      # accelerator setup + profile starter models
```

```bash
./setup.sh          # Linux/macOS auto setup
./setup.sh stub     # STUB mode (no GPU)
./setup.sh real     # force accelerator setup when available
./setup.sh all      # accelerator setup + profile starter models
```

Or from PowerShell on Windows:
```powershell
.\setup.ps1        # Auto setup
.\setup.ps1 -Stub  # STUB mode
.\setup.ps1 -Real  # force accelerator setup when available
.\setup.ps1 -DownloadAll  # accelerator setup + profile starter models
```

**What the setup script does:**
1. Checks Python 3.12+ and Node.js 18+
2. Probes hardware and selects an install profile automatically
3. Creates and activates Python venv
4. Installs pip dependencies (`requirements.txt` plus profile-specific accelerated deps)
5. Installs npm packages (`frontend/package.json`)
6. Optionally installs Nunchaku when the selected CUDA profile supports it
7. Optionally downloads a profile-aware starter model set

After setup finishes, run `run.bat` (or `run.ps1`) to start the app.

---

### Quick Start (STUB Mode — No GPU)

**STUB mode runs the entire pipeline without GPU/ML libraries.** Perfect for UI testing, debugging, and verifying the foundation.

#### Step 1: Clone & enter the repo
```bash
cd d:\VSCode\ImageFabric
```

#### Step 2: Run (one command)
```bat
run.bat stub
```

Or on PowerShell:
```powershell
.\scripts\run.ps1 -Stub
```

**What happens:**
- First run: bootstraps Python virtual environment and npm dependencies (~1–2 min).
- Backend starts at `http://localhost:8260`
- Frontend dev server starts at `http://localhost:5173`
- Browser opens automatically
- **Ctrl+C** stops both servers

#### Step 3: Verify
1. Open <http://localhost:5173> in your browser
2. Try the chat/image form — you'll see mock responses (no real GPU calls)
3. Check the backend console for any errors

---

### GPU Setup (REAL Mode)

**REAL mode loads actual LLMs and diffusion models onto your accelerator.** The
recommended path is still `setup.bat` / `setup.sh`; manual setup should start
from the same resolver the installer uses:

```powershell
python scripts\hardware_probe.py --pretty
python scripts\install_profiles.py --pretty
```

Use the emitted `install.torch` packages/index and requirements. The current
profiles map to:

```powershell
# NVIDIA CUDA
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r backend/requirements-gpu.txt

# Linux AMD ROCm
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/rocm7.2
pip install -r backend/requirements-rocm.txt

# Apple Silicon MPS
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0
pip install -r backend/requirements-mps.txt
```

Verify with:

```powershell
python scripts\install_smoke.py
```

This adds diffusers, transformers, accelerate, bitsandbytes, and related libraries.

#### Step 2: (Optional) Install Nunchaku for FLUX

For faster FLUX generation (~18 s/1024px on RTX 5070 Ti with SVDQuant fp4),
install the Nunchaku wheel only when `/api/capabilities` or
`scripts/install_profiles.py` lists `nunchaku_cuda` in `optional_features`:

```bash
pip install https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-win_amd64.whl
```

Then download the fp4 FLUX model:

```bash
huggingface-cli download nunchaku-tech/nunchaku-flux.1-dev svdq-fp4_r32-flux.1-dev.safetensors --local-dir models/image
```

#### Step 3: Download models

Models live in `models/` and are **not copied** into the venv or elsewhere. HFabric reads them in place.

The no-manual starter path is hardware-aware and matches the same profile the
installer selected:

```bash
python scripts/fetch_models.py --dry-run
python scripts/fetch_models.py --profile apple-mps --dry-run
python scripts/fetch_models.py
```

`setup.bat all`, `./setup.sh all`, and `.\setup.ps1 -DownloadAll` run this
downloader automatically. CUDA profiles get the shared starter set plus the
Nunchaku FLUX fp4 checkpoint when the `nunchaku_cuda` feature is available;
ROCm and Apple Silicon get the safe SDXL/GGUF set without CUDA-only models.
The `--dry-run --profile ...` form is planner-only, so it is safe for showing
the AMD/MPS starter plan from another machine.

**Image models** (FLUX/SDXL/Qwen/Z-Image - goes in `models/image/`):

```bash
# SDXL Lightning 4-step checkpoint (safe starter for CUDA, ROCm, and Apple MPS)
huggingface-cli download ByteDance/SDXL-Lightning sdxl_lightning_4step.safetensors --local-dir models/image

# Optional SDXL Lightning LoRA for other SDXL checkpoints
huggingface-cli download ByteDance/SDXL-Lightning sdxl_lightning_4step_lora.safetensors --local-dir models/lora

# FLUX ComfyUI checkpoint (fp8, CUDA-oriented baseline reference)
huggingface-cli download black-forest-labs/FLUX.1-dev flux_dev.safetensors --local-dir models/image

# Qwen-Image-2512 (multi-file Diffusers repo)
huggingface-cli download Qwen/Qwen-Image-2512 --local-dir models/image/qwen-image-2512

# Z-Image-Turbo (multi-file Diffusers repo; assets are optional)
huggingface-cli download Tongyi-MAI/Z-Image-Turbo --local-dir models/image/z-image-turbo --exclude "assets/*"
```

Or fetch both public Diffusers repos with:

```bash
python scripts/fetch_qwen_z_image.py
```

**LLM models** (GGUF format — goes in `models/llm/`):

```bash
# Example: Gemma 3 12B quantized
huggingface-cli download Gron1-ai/Gemma-3-12B-it-Heretic-v2-GGUF gemma-3-12b-it-heretic-v2-Q4_K_M.gguf --local-dir models/llm
```

See [models/README.md](models/README.md) for the full curated list and setup hints.

#### Step 4: Run in REAL mode

```bat
run.bat
```

Or PowerShell:
```powershell
.\scripts\run.ps1
```

**Environment file (optional):**

Copy `.env.example` to `.env` only for system-level settings such as host,
port, optional API token, or production frontend serving:

```env
HFAB_HOST=127.0.0.1
HFAB_PORT=8260
# HFAB_API_TOKEN=change-me
HFAB_SERVE_FRONTEND=false
```

Generation defaults, model paths, acceleration, memory policy, LLM runtime,
RAG/vision/speech, and voice defaults are managed from the app's Settings tab.

Hardware/profile diagnostics:

```powershell
python scripts\hardware_probe.py --pretty
python scripts\install_profiles.py --pretty
```

The first command emits a machine report; the second chooses the recommended
install profile (`nvidia-cuda`, `amd-rocm-linux`, `apple-mps`, or `cpu-safe`) with package
index, verification command, disabled features, and warnings.

Official references used by the profile resolver:
[PyTorch install](https://pytorch.org/get-started/locally/),
[PyTorch MPS notes](https://pytorch.org/docs/stable/notes/mps.html),
[NVIDIA compute capability](https://developer.nvidia.com/cuda/gpus),
[AMD ROCm system requirements](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html), and
[AMD ROCm PyTorch install](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/3rd-party/pytorch-install.html).

#### Step 5: Verify accelerator usage

1. Open another terminal and watch the matching monitor: `nvidia-smi -l 1` on NVIDIA, `rocm-smi` on ROCm, or Activity Monitor on macOS.
2. In the app, submit a generation job
3. Watch your GPU memory fill up, then empty after completion
4. Backend console shows timing, memory snapshots, and model load/unload events

---

### Troubleshooting

#### **"WinError 10013: socket forbidden"**
Ports 8260 or 5173 are already in use by a previous run:
- Run `run.bat` or `run.ps1` again — they auto-kill stale processes
- Or manually: `netstat -ano | findstr :8260` and `taskkill /PID <pid> /F`

#### **"ModuleNotFoundError: No module named 'torch'"**
PyTorch not installed or virtual environment not activated:
- Delete `backend\.venv` and re-run `run.bat` to bootstrap from scratch
- Or manually: `pip install -r backend/requirements-gpu.txt`

#### **"CUDA out of memory"**
Model is too large for your GPU, or swap settings need tuning:
- Reduce Settings -> LLM runtime -> GPU layers (for example, `32` to offload only 32 layers to GPU)
- Disable Settings -> Acceleration -> torch.compile
- Try smaller models or lower resolution requests
- Check Settings -> Memory policy for memory tuning knobs

#### **Models not found / "No image models discovered"**
Models are in the wrong folder or not yet downloaded:
- Ensure files exist in `models/image/`, `models/llm/`, `models/lora/`, etc.
- Verify paths in Settings -> Model and binary paths
- Re-run `huggingface-cli download` commands above

#### **Vite dev server won't start**
Port 5173 conflict or npm dependencies not installed:
- Kill any process on 5173: `netstat -ano | findstr :5173`
- Or let `run.bat` do it automatically (it frees ports before starting)
- Check `npm install` in `frontend/` ran successfully

#### **Backend crashes after first request**
Usually STUB mode reaching a code path that requires ML libraries:
- Ensure you ran `pip install -r backend/requirements-gpu.txt` for REAL mode
- Or use STUB mode (`run.bat stub`) if you're not ready for GPU

#### **Get help**
- Check backend logs (printed to terminal where `run.bat` runs)
- Check browser console (F12 in Firefox/Chrome)
- Search existing issues or documentation in the repo

---

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
                       │     (FLUX fp8 / SDXL)       (llama-server subprocess) │
                       └───────────────────────────────────────────────────────┘
```

Key modules (backend):
- `app/core/arbiter.py` — the VRAM arbiter (load/unload, one resident max).
- `app/core/scheduler.py` — single GPU worker + phase-batching select.
- `app/core/events.py` — in-process pub/sub, streamed over `/ws`.
- `app/backends/` — `registry` (scan model files), `image_diffusers`, `llm_llamacpp`.
- `app/db/` — SQLAlchemy models; the queue is persisted and resumes on restart.

## Run

Easiest — double-click **`run.bat`** (or from a terminal):

```bat
run.bat          REM auto-select REAL/STUB from the hardware profile
run.bat stub     REM STUB mode: full pipeline, no GPU/ML stack
```

It bootstraps the venv + npm deps on first run, frees any stale ports left by an
earlier run, then runs the backend (`:8260`) and the Vite dev server (`:5173`)
**together in one window** and opens <http://localhost:5173> for you. Ctrl+C
stops both.

PowerShell equivalent:

```powershell
.\scripts\run.ps1          # auto-select REAL/STUB from the hardware profile
.\scripts\run.ps1 -Stub    # STUB mode
```

> **Note:** the launcher kills whatever is holding ports 8260/8261/5173 before
> starting. A leftover backend from a previous run holding port 8260 is what
> caused the `WinError 10013` "socket forbidden" failure; freeing it first fixes
> that.

Models are read in place from `models/`: image checkpoints/repos under
`models/image/`, LoRAs under `models/lora/`, and GGUF LLMs under `models/llm/`.
Nothing is copied. See [models/README.md](models/README.md).

### Security model

HFabric is a local, single-user app by default. The backend binds to
`127.0.0.1:8260`, which keeps the API on the local machine. If you deliberately
bind it to a LAN interface such as `HFAB_HOST=0.0.0.0`, set `HFAB_API_TOKEN` and
enter that token in the UI when prompted. CORS is not an authentication layer:
without a token, LAN clients could call local APIs directly. `/api/health`
stays open so the UI can report the security posture, and desktop-reaching
actions such as "Show in folder" are loopback-only regardless of token.

## Configuration

Use `.env` for system settings that need to exist before the app starts.
Most day-to-day runtime knobs are edited in the app's **Settings** tab and
persisted to `data/settings-overrides.json`.

| Var | Default | Meaning |
|-----|---------|---------|
| `HFAB_HOST` | `127.0.0.1` | Backend bind host. Use a LAN address only with `HFAB_API_TOKEN`. |
| `HFAB_PORT` | `8260` | Backend port. |
| `HFAB_API_TOKEN` | unset | Optional bearer token. Leave unset for local-only use without API authentication. |
| `HFAB_SERVE_FRONTEND` | `false` | Serve the built frontend from FastAPI instead of using Vite. |
| `HFAB_FRONTEND_HOST` | unset | Optional Vite dev-server bind host. |
| `HFAB_FRONTEND_PORT` | `5173` | Optional Vite dev-server port. |

The Settings tab covers the former `.env` tuning surface: `HFAB_STUB_MODE`,
model/bin paths, `HFAB_LLAMA_*`, image defaults, acceleration, memory guards,
keep-warm policy, speech/RAG/vision placement, and voice defaults.

### llama.cpp memory knobs

The LLM backend starts `llama-server` as a subprocess with `-ngl`
from Settings -> LLM runtime -> GPU layers and `--fit off`. The default `999` keeps the GGUF fully
offloaded to VRAM, while `--fit off` prevents llama.cpp from silently reducing
offload when another process has touched CUDA.

HFabric leaves llama.cpp's mmap default enabled (it does not pass
`--no-mmap`), so the GGUF file stays disk-backed and process RSS remains low.
When the arbiter switches to an image model, it terminates `llama-server`; that
is the expected way to release llama.cpp VRAM completely.

### Image acceleration knobs

Settings -> Acceleration -> FLUX step cache enables nunchaku's native
first-block cache for FLUX pipelines. Use `teacache` for the TeaCache context
manager, or `off` to compare baseline quality/speed.

Settings -> Acceleration -> Attention backend leaves scaled-dot-product
attention backend selection to PyTorch when set to `auto`. Set it to `flash`,
`efficient`, `math`, or `cudnn` to force a native
`torch.nn.attention.sdpa_kernel` backend when the installed torch build and CUDA
device expose it. The load report records available native SDPA backends,
float8 dtype support, and whether external `flash_attn`/`xformers` packages are
installed; the local environment currently uses PyTorch native SDPA rather than
those external packages.

Settings -> Acceleration -> Allow TF32 and Matmul precision set the CUDA
matmul/precision policy before image generation.

Settings -> Acceleration -> torch.compile wraps the FLUX transformer with
`torch.compile` using the selected compile mode and runs a 1-step warmup.
The `model.loaded` WebSocket event includes a `load_report` with RAM/VRAM before
and after compile/warmup. Compile is best-effort: if the installed torch/nunchaku
combination fails during compile or warmup, the backend rolls back to the
original transformer, records the failure in `load_report`, and continues
generation without compile.

Set Settings -> Acceleration -> SDXL turbo LoRA to a local `.safetensors`,
folder, or Hugging Face repo id to load an SDXL turbo LoRA. When active,
untouched default steps/guidance are replaced by the SDXL turbo steps and
guidance settings.

Long image sessions run a lightweight post-job stabilization pass by default:
`gc.collect()`, `torch.cuda.empty_cache()`, `torch.cuda.ipc_collect()`, bounded
runtime LoRA adapter cleanup, and an adaptive soft-recycle if CUDA allocated
memory drifts above the loaded baseline. Tune with
Settings -> Acceleration -> Cleanup after each job, LoRA cache max, Recycle
CUDA growth GB, and Recycle min jobs.
Use `python scripts\sdxl_resident_drift_test.py --jobs 8` against a running
REAL backend to validate repeated same-model SDXL generations without unloading.

### LoRA management

Drop SDXL/FLUX LoRA files under `models/lora` or change Settings -> Model and
binary paths -> LoRA models. The backend scans `.safetensors`, `.pt`, and
`.bin` files on startup, exposes them at `/api/loras`, and validates queued
`params.loras` against the selected image model. The composer filters compatible
LoRAs and stores only public `{id,name,family,weight}` metadata in jobs/presets;
local file paths are resolved by the worker right before generation.

### Speech workspaces

The TTS tab scans `models/tts` for local `.gguf` files and calls
`bin/llama/llama-tts.exe`. It defaults to `HFAB_TTS_GPU_LAYERS=0`, so speech
generation stays CPU-only unless explicitly changed.

The Transcribe tab is similarly gated. `/api/transcription/status` reports local
Whisper engines (`faster-whisper` or `openai-whisper`) and scans
`models/transcribe` for model folders/files. `/api/transcription/transcribe`
accepts an audio upload only when both an engine and a local model are present;
it writes transcript metadata under `data/outputs/<date>/`.

The Vision tab scans `models/vision` for a local multimodal GGUF and `mmproj`
pair, then calls `bin/llama/llama-mtmd-cli.exe` for PNG/JPEG analysis. It
defaults to `HFAB_VISION_GPU_LAYERS=0`, and stores JSON result sidecars under
`data/outputs/<date>/`.

The Voice tab uses HFabric's native in-process RVC engine. Pretrain assets live
under `models/voice/pretrain` and voice slots live under `models/voice`; the UI
calls `/api/voice/engine/*` for status, settings, offline conversion, and live
sessions. A live session frees the current arbiter resident and parks queued
image/LLM jobs until the session stops.

Optional neural microphone denoise uses breizhn/DTLN (MIT) ONNX weights under
`models/voice/pretrain/denoise`. HFabric never downloads these implicitly; run
the explicit fetch script when you want the `DTLN (neural)` input mode:

```powershell
python .\scripts\fetch_dtln.py
```

### RAG workspace

The RAG tab scans `models/embed` for local GGUF embedding models and starts a
dedicated `llama-server` on `HFAB_LLAMA_EMBED_PORT` (default 8262) in
`--embeddings` mode on first use. `HFAB_EMBED_GPU_LAYERS=0` keeps it CPU-only
by default, so document indexing/search does not take VRAM from the shared
arbiter.

Indexed documents are chunked into SQLite `rag_documents` / `rag_chunks` rows
with normalized embedding vectors. Search returns top chunks by cosine score,
and the RAG tab can create an LLM conversation with the retrieved context
inserted into the user turn.

The LLM chat tab also has a **Document tool** toggle. When enabled, the model may
emit a structured `search_documents` call; HFabric runs local RAG search,
then queues a child LLM turn with the retrieved context so the final response
streams into the same assistant message.

### History, export, settings

The gallery history supports `/api/images?q=...` search across image ids, job ids,
seeds, prompts, models, and JSON metadata. Each image has a PNG download endpoint
and `/api/images/{id}/metadata` for reproducibility export.

`/api/settings` exposes a runtime snapshot for the Settings tab: model paths,
memory guard values, acceleration knobs, model/LoRA counts, GPU status, and
current memory telemetry. It also includes the active capability profile
(`nvidia-cuda`, `amd-rocm-linux`, `apple-mps`, or `cpu-safe`); `/api/capabilities` exposes the
same object directly for diagnostics and UI gating. Writable settings are served
by `/api/settings/overrides` and stored in `data/settings-overrides.json`.
`/api/models` includes per-model compatibility metadata (`available`,
`runtime_mode`, `unavailable_reason`) so the UI can label models that do not fit
the active hardware profile before they are queued.

### Keep-warm policy

Settings -> Memory policy -> Keep models warm lets the arbiter park up to the
configured warm model limit in CPU RAM when switching to a
different model. Parked models are not VRAM residents; `/api/gpu` and the header
show them as `CPU warm`, and `/api/gpu/free` unloads them.

Parking is skipped unless available RAM can satisfy the model estimate plus
the configured warm RAM headroom, so this feature should not push Windows
toward the pagefile. It is off by default.

### Runtime checks

With the backend running in real GPU mode:

```powershell
python .\scripts\swap_leak_test.py --cycles 3
```

The test forces `LLM -> FLUX(nunchaku) -> SDXL -> LLM`, frees the GPU after each
cycle, then checks that process RSS and VRAM return close to a warm baseline.
Use `--strict-cold-baseline` only when diagnosing one-time import/cache growth.

To validate live phase-batching against the running app:

```powershell
python .\scripts\phase_batch_check.py
```

It queues `LLM -> image -> LLM -> image` in one batch and asserts that the worker
starts jobs as `LLM -> LLM -> image -> image`, producing exactly one model-family
swap.

To queue a same-seed quality A/B across image models:

```powershell
python .\scripts\quality_ab.py --family flux --limit 2 --free-gpu-first --json-out data\runtime\quality-ab.json
```

The runner prints the job ids, image ids, and `/api/images/{id}/file` URLs. It
uses the model metadata exposed by `/api/models`, including `nunchaku-fp4` and
`nunchaku-int4` quant labels when those filenames are present. Pass
`--continue-on-error` when the comparison should record incompatible candidates
and continue.

For SDXL turbo validation, put a Lightning/DMD2 LoRA in `models/lora` and start
the backend with `HFAB_SDXL_TURBO_LORA=<path>`. The local M1 run used
`models/lora/sdxl_lightning_4step_lora.safetensors`, `HFAB_SDXL_TURBO_STEPS=4`,
and `HFAB_SDXL_TURBO_GUIDANCE=1.0`.

### Database migrations

The backend runs Alembic `upgrade head` during startup. Migration files live in
`backend/migrations/versions/`; `0000_current_schema` is the baseline schema and
later revisions carry incremental changes.

To add a column:

1. Update the SQLAlchemy model in `backend/app/db/models.py`.
2. Add a new Alembic revision under `backend/migrations/versions/` with the next
   revision id and `down_revision` set to the current head.
3. In `upgrade()`, add the column with a server default if existing rows need a
   non-null value.
4. Add or update a test that boots a fresh DB and, when relevant, upgrades a
   legacy raw-SQL DB.

## Backup & restore

Run a local backup from the repo root:

```powershell
python .\scripts\backup.py --keep 10
```

The script writes `data/backups/hfabric-<timestamp>/hfabric.db` using SQLite's
live-safe backup API and `outputs-manifest.json`, a manifest of `data/outputs/`
with relative paths, sizes, and mtimes. It does not copy output image/audio
bytes; keep `data/outputs/` in your normal file backup if you need to restore
artifacts.

Restore order:

1. Stop HFabric.
2. Copy the saved `hfabric.db` back to `data/hfabric.db`.
3. Restore `data/outputs/` from your file backup, preserving relative paths from
   `outputs-manifest.json`.
4. Start HFabric; startup migrations will bring the restored DB to the current
   schema if needed.

## Testing

The whole pipeline runs in STUB mode (no GPU/ML stack), so the memory-budget
logic, the phase-batching scheduler, and the queue → arbiter swap → gallery flow
are all testable on a plain machine. CI runs both suites on every push/PR
(`.github/workflows/ci.yml`).

**Backend** (pytest, stub mode — hermetic temp DB + dummy model files):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt pytest pytest-asyncio ruff
.\.venv\Scripts\ruff check app tests
.\.venv\Scripts\python -m pytest
```

Key coverage: `tests/test_scheduler.py` (the *one-swap-per-mixed-batch* invariant),
`tests/test_sysmon.py` (the RAM budget guard), `tests/test_model_profile.py`
(learned-profile running max), and `tests/test_stub_integration.py` (the full
queue → swap → gallery flow over an ASGI client).

**Frontend** (vitest + Testing Library):

```powershell
cd frontend
npm install
npx tsc -b      # typecheck
npm test        # vitest run
```

The runtime GPU checks above (`scripts/swap_leak_test.py`,
`scripts/phase_batch_check.py`, `scripts/quality_ab.py`) complement these — they
validate the *real* GPU path against a running backend.
