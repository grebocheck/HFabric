# HFabric — Shipped history

The forward-looking plan lives in [`ROADMAP.md`](../ROADMAP.md); user-facing
release notes live in [`CHANGELOG.md`](../CHANGELOG.md). This file is the terse
record of **completed** phases, kept so the roadmap stays focused on what's left
without losing the history. Detailed run logs live in `data/runtime/*.json`.

## Foundation & memory

- **M0 — GPU bring-up.** torch 2.11+cu128 (cap 12.0) · diffusers 0.38 ·
  transformers <5 · bitsandbytes · llama.cpp CUDA · nunchaku 1.3 (fp4). Validated
  end-to-end.

  | Model | Speed | VRAM |
  |-------|-------|------|
  | SDXL (NoobAI) | ~5.6 s / 1024² | 11 GB |
  | FLUX (Nunchaku fp4) | ~18.7 s / 1024² | 9.8 GB |
  | gpt-oss-20B (llama-server) | streaming | 12.5 GB |

- **M1 — Real-GPU validation** (RTX 5070 Ti). Swap-loop steady-state stable; one
  swap per mixed batch; SDXL-turbo warm ~1.67 s/image; FLUX nunchaku fp4 12-step
  768² ~16 s with first-block cache.
- **P0 — Memory hygiene.** Nunchaku FLUX without the 16 GB encoder read; RAM/VRAM
  telemetry + pre-load guard (`sysmon.py`); swap-loop leak runner.
- **P7 — Memory arbiter depth.** Structured `arbiter.note` events; learned per-model
  RAM/VRAM profiles (`model_profiles`) preferred over static heuristics; pressure
  sparkline; swap-plan preview via shared `scheduler.select_in_tier`.

## Speed & generation

- **P1 — Speed & live UX.** Guarded `torch.compile` + warmup; FLUX step cache
  (fb/teacache/off); SDXL turbo LoRA; live phase-batching; denoise preview; presets;
  queue reorder; gallery metadata.
- **P2 — Optional.** Keep-warm (RAM-guarded, off by default); attention backend;
  LoRA management + validation; history/search/export; quality A/B.
- **P3 — FLUX.2 [klein].** `ModelFamily.FLUX2` (Qwen3 encoder, bnb-nf4 + offload) +
  experimental nunchaku fp4 sidecar. FLUX.2 [dev] out of scope.
- **P3.4 — Qwen/Z-Image families.** Multi-file Diffusers repos detected by
  `model_index.json`; Qwen bnb-nf4 / 1328² / 50 steps; Z-Image 1024² / 9 steps.
- **P8 / P9 / P13 — Generation pages.** Reproduce/vary; measured-VRAM model & LoRA
  picker cards; img2img + inpainting (mask editor, SDXL validated); selectable llama
  backend + KV-cache type (incl. TurboQuant); two-column composer; lightbox;
  responsive history grid with combinable filters, favorites/tags, bulk delete + ZIP.
- **P19 — Generation features.** FLUX/FLUX.2 img2img + inpaint (smoke-passed on
  RTX 5070 Ti); upscaler as an arbiter job (Real-ESRGAN fast path, PIL fallback);
  SDXL canny ControlNet; DB-backed prompt library shared by composer + chat.
- **Long-session image stabilization.** Per-job gc/`empty_cache`/`ipc_collect`,
  bounded LoRA cache, CUDA-drift soft-recycle. Runner: `sdxl_resident_drift_test.py`.

## Superapp shell

- **P4 — Chat & shell.** Persistent streaming chat (sampling, personas, tok/s, TTFT,
  stop/regenerate/edit); chat→image bridge + `generate_image`/`search_documents`
  tools; command palette; declarative workspace registry; Notes/TTS/Code/Transcribe/
  RAG workspaces (model-gated, CPU-first, arbiter-safe).
- **P5 — UX polish.** Brand mark; Tailwind 4 `@theme` tokens; theme toggle; activity
  indicator + header VRAM bar; animated denoise preview; Thinking panel; shared
  keyboard-navigable control kit; packaged window icon.
- **P6R — Native voice engine.** In-process RVC v2 (vendored MIT, ~2400 lines) +
  RMVPE + ContentVec; offline `convert()` + realtime session (SOLA seam, stateful
  resamplers, pinned latent noise, DTLN denoise, idle squelch); CUDA realtime at
  every benched chunk size; UI rewired to `/api/voice/engine/*`. Real-mic validation
  confirmed (user, 2026-06-14): jobs park during a session and resume after.
- **P22 — Voice realtime quality & observability.** `protect ≥ 0.5` slider guardrail;
  denoise wet/dry mix; output soft-limiter + peak meter; ContentVec/F0 provider-EP
  surfacing; rolling-p95 latency headroom hint; re-tuned + labelled +12 preset
  (validated 2026-06-15: `index_ratio=0.30`, `noise_scale=0.50`, RMVPE).
- **P23 — LLM workspace.** Composer attachments (drag/drop/paste, chips, token
  meter); **chat-native multimodal** via `llama-server --mmproj` (GPU-resident,
  arbiter-coordinated; validated 2026-06-15 with Qwen2.5-VL-3B); document
  attachments (extract → context / conversation-scoped RAG); **native OpenAI
  tool-calling** with grammar-constrained output replacing the JSON-emit hack; the
  standalone Vision tab + `llama-mtmd-cli` engine removed; inline attachment render +
  persistence, per-conversation tool toggles.

## Trust, data, distribution (2026-06-11 audit response)

- **P14 — Security.** Default `127.0.0.1` bind; optional `HFAB_API_TOKEN` bearer auth
  (REST + WS); desktop-reaching endpoints loopback-gated regardless of token; upload
  caps + Pillow re-encode; threat model documented.
- **P15 — Reliability & data.** Alembic migrations (baseline + raw-SQL upgrade test);
  rotating `data/logs/hfabric.log`; `scripts/backup.py` (SQLite backup API +
  retention); llama-server pidfile reap of orphans on startup.
- **P16 — Test depth & quality gates.** Coverage floor in CI (`--cov-fail-under`);
  stub-mode router tests; frontend eslint + prettier + `npm run lint`; frontend flow
  tests (ChatPanel/Gallery/QueuePanel); the `docs/gpu-smoke.md` checklist.
- **P17 — Code health round 2.** Hard splits done: `VoicePanel`, `image_diffusers`
  (→ `image_diffusers_parts/`), `ChatPanel`, `ImageComposer`/`Gallery`; generated API
  types from OpenAPI (`types.generated.ts` + CI freshness checks); repo hygiene
  (friendly job errors, full traces to the rotating log); `requirements-gpu.lock`.
- **P18 — Distribution.** Production serving (`HFAB_SERVE_FRONTEND=true`, SPA
  fallback, one port); `--prod` one-command launcher; first-class Settings tab with
  validated overrides persisted to `data/settings-overrides.json`; in-app model
  download manager (hardware-aware, disk-guarded).
- **P11 / P12 — Code health & arbiter loose ends.** Helper extraction + vitest;
  committed ruff/pytest config; learned-profile management UI; per-job arbiter
  attribution; inline swap-plan previews; memory-timeline depth.

## Universal install (P20 — usable beyond this machine)

- **P20.1–.2 — Probe + resolver.** `scripts/hardware_probe.py` emits one JSON report;
  `scripts/install_profiles.py` picks `nvidia-cuda` / `amd-rocm-linux` / `apple-mps` /
  `cpu-safe` with package index, verify command, runtime defaults, warnings.
- **P20.3 — NVIDIA tiers.** Capability-aware runtime defaults (architecture from
  compute cap); VRAM-tiered model policy (8/12/16 GB).
- **P20.4 — AMD ROCm (Linux).** First-class profile; CUDA-only features auto-disabled;
  SDXL-safe until real-ROCm validation. *(Unvalidated → ROADMAP P21.4.)*
- **P20.5 — Capability gates.** `CapabilityProfile` drives model/feature gating;
  `/api/models` marks availability; server-side enforcement; startup autotune.
- **P20.6–.7 — Setup Doctor + recommendations.** Plain-language detected-hardware
  page; per-hardware model recommendation buckets; profile-aware starter plan.
- **P20.8 — CI matrix without owning every GPU.** Fake-probe unit tests +
  `scripts/install_smoke.py` real-machine grader.
- **P20.9 — Device abstraction + Apple MPS.** `accelerator_runtime.py` replaces
  hard-coded `.to("cuda")`; `apple-mps` profile. *(Unvalidated → ROADMAP P21.4.)*
- **P20.10 — Managed llama.cpp runtime.** Auto-download the right prebuilt
  `llama-server`/`-tts` per host+accelerator; in-app install/update/rollback.

## Release readiness (P21 — prep for external testers)

- **P21.1 — Truth-in-docs pass.** Fixed drifted docs (test counts, stale markers,
  hardcoded paths) across README/ROADMAP/audit.
- **P21.2 — Version stamp + changelog + contributing.** `app.__version__` single
  source, surfaced in `/api/health` + System tab; `CHANGELOG.md` + `CONTRIBUTING.md`.
- **P21.3 — Label experimental paths in the UI.** Setup Doctor reads ROCm/MPS as
  "(experimental)" with an info tone and an "SDXL-only, not yet validated" line.
- **P21.5 — Packaged release.** *(Resolved by P24.3.)* Clone-and-run; tag-triggered
  GitHub pre-release with a `git archive` source zip + checksum; one-page
  "download → run" (`docs/release-footer.md`).

## Release pipeline & public v0.1 beta (P24 — done items)

- **P24.2 — Version & tag discipline.** Plain `v0.1.0` tag, "beta" carried by the
  GitHub pre-release flag; `scripts/release.py` (current/check-tag/notes/prepare)
  bumps version + rolls the changelog `[Unreleased]` block; the workflow's tag↔version
  guard calls `release.py check-tag`.
- **P24.3 — Distribution shape (closes P21.5).** Clone-and-run is the supported beta
  path; release attaches a `git archive` source zip + SHA-256 + `release-footer.md`.
- **P24.4 — Beta framing & honest expectations.** README "public beta (v0.1)" status
  block; `KNOWN_ISSUES.md`; `SECURITY.md` (private vulnerability reporting).
- **P24.5 — Feedback & bug-report loop.** GitHub issue templates (bug · feature ·
  hardware-validation) + the in-app "Export diagnostics" zip (logs + health/
  capability/settings + version stamps, secrets scrubbed, never uploaded).
- **P24.8 — Hot model rescan (no restart).** `POST /api/models/rescan`, a "Rescan
  models" button in System → Model downloads, and auto-rescan when a download
  completes — a model dropped on disk or just downloaded is usable immediately.
- **P24.9 — Zero-decision default install.** Shared `Install-AcceleratorStack`
  installs the detected profile's PyTorch + backend requirements + llama.cpp runtime;
  `run.ps1` auto-installs the full stack on a first REAL launch so a double-clicked
  `run.bat` "just works" without flags. `setup.ps1` uses the same function.
- **P24.10 — Non-arbiter GPU lanes in status + topbar.** The arbiter tracks
  observability-only "lanes" (`activate_lane`/`deactivate_lane`/`gpu_lane`) so a live
  voice session, GPU TTS, or GPU transcribe reports an active label (e.g. "voice
  session") in `status()`/`gpu.status` and the topbar — instead of "idle" — while the
  real VRAM shows via `mem.status`. No second resident heavy model; lanes are gated on
  actual GPU use (voice always; TTS when `tts_gpu_layers > 0`; transcribe when the
  device isn't CPU).

## Unified Model Manager (P25)

- **P25.1 — "Models" workspace tab.** A dedicated top-level tab (`ModelManager.tsx`),
  the one home for getting and managing models, with a live installed-count / disk-used
  / disk-free header. Model downloads moved here out of the System tab.
- **P25.2 — Installed-models manager + delete.** `services/model_storage.py` walks
  every kind folder (image/LLM/LoRA/TTS/transcribe/embed/vision/voice) and lists the
  deletable units (file or repo folder) with sizes; `GET /api/models/installed` +
  `DELETE /api/models/installed?kind=&path=` reclaim disk and rescan. Path-validated to
  stay inside the kind folder; refuses a resident/warm model (`arbiter.busy_paths()`)
  so a load can't be deleted out from under it.
- **P25.3 — Download from any source.** Alongside the curated catalog, an "Add from
  source" form pulls a HuggingFace `repo + file` or a **direct URL** into the chosen
  `models/<kind>/` folder via `POST /api/downloads/custom`, reusing the background
  progress + auto-rescan machinery (`run_blocking_custom`, httpx streaming for URLs).
