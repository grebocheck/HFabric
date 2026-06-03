# ImageFabric

Local app that pairs an **LLM (prompt generation)** with **diffusion image
generation**, built to be frugal with memory on a single 16 GB GPU. Its core is a
**VRAM arbiter**: only one heavy model lives in VRAM at a time, and a
**phase-batching scheduler** swaps LLM ↔ image models as few times as possible
(ideally once per batch).

Target hardware: **RTX 5070 Ti 16 GB (Blackwell), 32 GB RAM, Windows 11**.

## Status

**Architectural foundation — complete and verified in STUB mode.**
The whole pipeline (model discovery → queue → arbiter swap → live progress over
WebSocket → gallery with reproducible metadata) runs today **without** torch or
llama.cpp. Real model loading is wired but lazy, and is turned on in milestone M0
by flipping `IMGFAB_STUB_MODE=false` after the GPU stack is installed.

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

## Run (dev)

```powershell
.\scripts\run.ps1
```

First run bootstraps the Python venv + npm deps, then starts the backend
(`:8260`) and the Vite dev server (`:5173`). Open <http://localhost:5173>.

Models are read in place from `models/image/` and `models/llm/` — nothing is
copied. See [models/README.md](models/README.md).

## Configuration

Env vars (prefix `IMGFAB_`, or a `.env` file in repo root). Highlights:

| Var | Default | Meaning |
|-----|---------|---------|
| `IMGFAB_STUB_MODE` | `true` | Run without GPU/ML stack (foundation mode). |
| `IMGFAB_PORT` | `8260` | Backend port. |
| `IMGFAB_LLAMA_SERVER_BIN` | `bin/llama/llama-server.exe` | CUDA(sm_120) llama.cpp build. |
| `IMGFAB_LLAMA_NGL` | `-1` | GPU layers to offload (-1 = all). |

## Next: milestone M0 (GPU bring-up)

1. Install the Blackwell GPU stack:
   ```powershell
   .\.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   .\.venv\Scripts\pip install -r backend\requirements-gpu.txt
   ```
   Verify: `python -c "import torch; print(torch.cuda.get_device_capability())"` → `(12, 0)`.
2. Drop a CUDA(sm_120) `llama-server.exe` into `bin/llama/`.
3. Set `IMGFAB_STUB_MODE=false` and generate one image with FLUX, one with SDXL,
   and one LLM completion — the same UI, now backed by real models.
```
