# Configuration reference

HFabric keeps two configuration surfaces, deliberately separated:

- **`.env`** — only system-startup posture that must exist *before* the app
  boots: bind host/port, optional API token, and how the frontend is served.
- **Settings tab** — everything else (model paths, acceleration, memory policy,
  LLM runtime, speech/RAG/chat-native vision placement, voice defaults). Changes are typed,
  validated, persisted to `data/settings-overrides.json`, and applied live.

If a knob isn't in the table below, it's in the Settings tab.

## Environment variables (`.env`)

Copy `.env.example` to `.env` and edit only what you need.

| Var | Default | Meaning |
|-----|---------|---------|
| `HFAB_HOST` | `127.0.0.1` | Backend bind host. Use a LAN address **only** together with `HFAB_API_TOKEN`. |
| `HFAB_PORT` | `8260` | Backend port. |
| `HFAB_API_TOKEN` | unset | Optional bearer token. Leave unset for local-only use without authentication. |
| `HFAB_SERVE_FRONTEND` | `false` | Serve the built frontend from FastAPI (production, one port) instead of the Vite dev server. |
| `HFAB_FRONTEND_HOST` | unset | Optional Vite dev-server bind host. |
| `HFAB_FRONTEND_PORT` | `5173` | Optional Vite dev-server port. |
| `HFAB_STUB_MODE` | auto | Force STUB (`true`) or REAL (`false`). When unset, the launcher probes hardware and chooses. |

`HFAB_STUB_MODE` and the per-feature `HFAB_*` runtime knobs can also be set in the
environment for development, but the supported path is the Settings tab. Anything
you pin in the environment is respected by the autotune pass (see below) and not
overwritten.

## Security model

HFabric is a local, single-user app by default. The backend binds to
`127.0.0.1:8260`, which keeps the API on the local machine. If you deliberately
bind it to a LAN interface (`HFAB_HOST=0.0.0.0`), set `HFAB_API_TOKEN` and enter
that token in the UI when prompted.

- CORS is **not** an authentication layer — without a token, LAN clients can call
  the API directly.
- `/api/health` stays open so the UI can report security posture even before a
  token is entered.
- Desktop-reaching actions (e.g. "Show in folder", which spawns the OS file
  manager) are **loopback-only regardless of token** — a remote caller can never
  drive the local desktop.

## Capability profile & autotune

At startup the backend resolves a `CapabilityProfile` (vendor, backend
`cuda`/`rocm`/`mps`/`cpu`, VRAM, supported dtypes/attention, available binaries,
known-unsafe features) from the same hardware probe the installer uses. It is
exposed at `/api/capabilities` and shown in the Settings and System tabs (and the
Setup Doctor).

The autotune pass then moves *safe* acceleration defaults to match the detected
hardware — but only for knobs you did **not** pin via env or a saved override:

- `attention_backend` → `math` below Ampere / on non-CUDA backends.
- `flux_step_cache` → `off` when the fp4 fast path isn't available.
- `attention_allow_tf32` → on only for NVIDIA Ampere+.
- CUDA-only voice defaults → CPU on ROCm/MPS/CPU-safe.

Autotune only ever tunes *toward* safety, never auto-enables `torch.compile`, is
disabled in STUB mode, and never blocks startup.

`/api/models` marks each model with `available`, `runtime_mode`,
`unavailable_reason`, and a `recommendation` bucket so the UI can label or hide
models that won't fit the active hardware before they're queued. Hidden buckets
are enforced server-side, so a UI-hidden family can't sneak through a direct API
call.

## LLM runtime (llama.cpp)

The LLM backend starts `llama-server` as a subprocess with `-ngl` from
**Settings → LLM runtime → GPU layers** and `--fit off`. The default `999` keeps
the GGUF fully offloaded to VRAM; `--fit off` prevents llama.cpp from silently
reducing offload when another process has touched CUDA.

mmap is left enabled (no `--no-mmap`), so the GGUF stays disk-backed and process
RSS stays low. When the arbiter switches to an image model it **terminates**
`llama-server` — that is the expected, complete way to release llama.cpp VRAM.

The `llama-server` / `llama-tts` / `llama-mtmd-cli` binaries are managed: the
**Settings → LLM runtime** panel installs the right prebuilt build for your
host + accelerator, supports in-app updates with rollback, and verifies each
build with `--version`. You no longer hand-place these binaries.

## Image acceleration

All under **Settings → Acceleration**:

- **FLUX step cache** — `fb` (nunchaku's native first-block cache, default),
  `teacache` (TeaCache context manager), or `off` to compare baseline.
- **Attention backend** — `auto` leaves SDPA backend selection to PyTorch; force
  `flash` / `efficient` / `math` / `cudnn` when the installed torch + device
  expose it. The load report records available native SDPA backends, float8
  support, and whether external `flash_attn`/`xformers` are installed.
- **Allow TF32** and **Matmul precision** — set the CUDA matmul/precision policy
  before generation.
- **torch.compile** — wraps the FLUX transformer with the selected compile mode +
  a 1-step warmup. Best-effort: if compile/warmup fails (e.g. the nunchaku
  transformer in Inductor), the backend rolls back to the original transformer,
  records the failure in `load_report`, and continues.
- **SDXL turbo LoRA** — point at a local `.safetensors`, folder, or HF repo id to
  load an SDXL turbo LoRA; untouched default steps/guidance are replaced by the
  turbo steps/guidance settings.

**Long-session stabilization** runs by default after each image job:
`gc.collect()` + `empty_cache()` + `ipc_collect()`, bounded runtime LoRA cleanup,
and an adaptive soft-recycle if CUDA allocated memory drifts above the loaded
baseline. Tune with **Cleanup after each job**, **LoRA cache max**, **Recycle CUDA
growth GB**, and **Recycle min jobs**.

## LoRA management

Drop SDXL/FLUX LoRA files under `models/lora` (or change **Settings → Model and
binary paths → LoRA models**). The backend scans `.safetensors`, `.pt`, and `.bin`
on startup, exposes them at `/api/loras`, and validates queued `params.loras`
against the selected image model. The composer filters compatible LoRAs and stores
only public `{id,name,family,weight}` metadata in jobs/presets; local file paths
are resolved by the worker right before generation.

## Keep-warm policy

**Settings → Memory policy → Keep models warm** lets the arbiter park up to the
configured limit of models in CPU RAM when switching to a different model. Parked
models are not VRAM residents; `/api/gpu` and the header show them as `CPU warm`,
and `/api/gpu/free` unloads them. Parking is skipped unless available RAM can
satisfy the model estimate plus the configured warm RAM headroom, so it should not
push the OS toward the pagefile. Off by default.

## Speech, chat-native vision, and RAG workspaces

These are model-gated and CPU-first by default, so they never quietly steal VRAM
from the shared arbiter.

- **TTS tab** — scans `models/tts` for `.gguf` and calls the managed `llama-tts`
  binary. `HFAB_TTS_GPU_LAYERS=0` (CPU-only) by default.
- **Transcribe tab** — `/api/transcription/status` reports local Whisper engines
  (`faster-whisper` / `openai-whisper`) and scans `models/transcribe`. Transcription
  is accepted only when both an engine and a local model are present; output
  metadata lands under `data/outputs/<date>/`.
- **Chat-native vision** — the LLM tab accepts image attachments when the selected
  GGUF has a paired `mmproj*.gguf` projector. HFabric launches the persistent
  `llama-server` with `--mmproj` and sends OpenAI `image_url` content parts, so
  image understanding is multi-turn and arbiter-resident. The legacy
  `llama-mtmd-cli` `/api/vision/*` path remains as an internal fallback.
- **RAG tab** — scans `models/embed` for GGUF embedding models and starts a
  dedicated `llama-server` on `HFAB_LLAMA_EMBED_PORT` (default 8262) in
  `--embeddings` mode. `HFAB_EMBED_GPU_LAYERS=0` keeps it CPU-only by default.
  Documents are chunked into SQLite `rag_documents` / `rag_chunks` with normalized
  vectors; search returns top chunks by cosine score. The chat tab's **Document
  tool** toggle lets the model emit a `search_documents` call that runs local RAG
  and feeds the retrieved context back into the same assistant message.

## Voice workspace

The Voice tab uses HFabric's native in-process RVC engine. Pretrain assets live
under `models/voice/pretrain`; voice slots under `models/voice`. The UI calls
`/api/voice/engine/*` for status, settings, offline conversion, and live sessions.
A live session frees the current arbiter resident and parks queued image/LLM jobs
until it stops. See [voice-routing.md](voice-routing.md) for output routing
(VB-CABLE / VoiceMeeter) on Windows.

Optional neural microphone denoise uses breizhn/DTLN ONNX weights under
`models/voice/pretrain/denoise`. HFabric never downloads them implicitly:

```powershell
python scripts/fetch_dtln.py
```

When DTLN is enabled, the Voice tab exposes a wet/dry denoise mix so full
suppression is not the only option. Live diagnostics also report output peak,
limiter reduction, rolling p95 latency/headroom, and the actual ContentVec/F0
provider selected by the runtime.

The `Female +12 RMVPE` quality profile is tuned for clarity rather than maximum
voice imprint: `index_ratio=0.30`, `noise_scale=0.50`, `protect=0.33`, and RMVPE.

## History, export, settings APIs

- `/api/images?q=...` searches across image ids, job ids, seeds, prompts, models,
  and JSON metadata. Each image has a PNG download endpoint and
  `/api/images/{id}/metadata` for reproducibility export.
- `/api/settings` exposes a runtime snapshot (model paths, memory guards,
  acceleration knobs, model/LoRA counts, GPU status, memory telemetry, active
  capability profile). Writable settings are served by `/api/settings/overrides`
  and stored in `data/settings-overrides.json`.
- `/api/capabilities` exposes the capability profile directly for diagnostics and
  UI gating.
