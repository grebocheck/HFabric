# HFabric — Roadmap & Backlog

> **Status:** working app, real-GPU validated on NVIDIA/Windows (M0/M1), with a
> CI safety net (ruff + eslint + pytest with a coverage floor + `tsc` + build +
> vitest on every push/PR). The P14–P20 audit-driven phases have shipped: token
> auth, Alembic migrations, rotating logs, backups, production serving, and a
> universal hardware-aware installer + capability profile.
>
> The work now is **release readiness** — preparing the app for testing by other
> people. See the [release-readiness audit (2026-06-14)](docs/audit-2026-06-14.md)
> for the current weaknesses and plan; the original [2026-06-11 audit](docs/audit-2026-06.md)
> is kept as the origin of phases P14–P20.
>
> Marking: `[ ]` not started · `[~]` in progress / partially done · `[x]` done.

## Objectives (priority order)

1. **RAM frugality** — every load must fit so the app never OOMs, hangs, or spills
   to the pagefile. Hard budget: peak ≈ **≤ 26 GB of 32 GB**.
2. **VRAM frugality** — exactly **one resident heavy model** at a time (≤ 16 GB)
   with a safety margin; never overflow into shared/system VRAM.
3. **Speed on Blackwell** — fp4/fp8 compute, `torch.compile`, step-caching.
4. **Trustworthy by default** — safe to leave running: not reachable by strangers,
   debuggable after a crash, restorable after a disk failure.
5. **Usable beyond this machine** *(release goal)* — the installer makes the hard
   choices; a normal user sees "Recommended", not CUDA/ROCm wheel archaeology.

## Memory invariants (do not break these)

- VRAM: exactly one resident heavy model (LLM **or** one image model).
- RAM: a guard checks predicted peak vs. available RAM **before** a load; if it
  wouldn't fit it reports clearly and waits/queues — never pushes the OS into the
  pagefile. Killing is **not** a routine memory tactic.
- Switching frees the previous model cleanly: llama-server is shut down; diffusers
  pipelines are `del` + `gc.collect()` + `empty_cache()` + `ipc_collect()`.
- Telemetry: process RSS + system available RAM + VRAM are surfaced in
  `/api/health` and over the WebSocket (`mem.status`).

Code anchors: `backend/app/core/arbiter.py`, `backend/app/util/sysmon.py`.

---

## Active backlog

### P22 — Voice realtime quality & observability (NEW — from the RVC research doc)

> Derived from [`docs/RVC_realtime_audio_pipeline_HFabric_research_UA.docx`](docs/RVC_realtime_audio_pipeline_HFabric_research_UA.docx)
> (2026-06-15). The doc statically audited this engine; most of its advice is
> **already shipped** in P6R (streaming-stateful chain, SOLA + equal-power
> crossfade, pinned latent noise, frame-repeat upsample, FCPE default / RMVPE for
> quality, `protect` 0.33, gate off by default, 80 Hz streaming HPF, ContentVec on
> CUDA EP, per-stage timings). Below is only the **residual high-value delta** that
> is not yet done. Defaults are not changed blind — anything touching audio is A/B'd
> on the RTX 5070 Ti with the sibilant test phrase first.

- [x] **P22.1 — `protect ≥ 0.5` guardrail in the UI.** *(P0, cheap.)* The code
  comment and the shipped presets already keep `protect` at 0.33, but the slider
  still lets a user walk to ≥0.5, which silently disables consonant protection (the
  #1 "картавість" footgun in the doc and in `voice-realtime-findings`). Add a
  `warn`-tone hint on the slider past 0.5; the tone infra already exists in
  `VoicePanelControls.tsx`.
- [x] **P22.2 — Denoise wet/dry mix.** *(P0/P1.)* Today denoise is binary
  `off`/`dtln` (full strength). Add a `0..1` mix (default < 1.0) so noisy-room users
  suppress noise without losing `/с/ /ш/` fricatives. `denoise.py` is already
  stateful-once on the rolling context — blend `mix·denoised + (1-mix)·raw` in the
  realtime denoise step (`realtime.py`) + a slider.
- [x] **P22.3 — Output safety: soft limiter + output peak meter.** *(P1.)* The
  output path only hard-clips (`np.clip` in `realtime.py:67`) and meters *input* RMS.
  Add a light soft-clip/limiter ceiling (~−1 dBFS) used purely as a guard (not a
  loudness tool) plus an output peak tile beside the existing RMS/overrun tiles.
- [x] **P22.4 — Provider health surfacing.** *(P1, cheap.)* `features.py` requests
  CUDA→CPU fallback for ContentVec but never logs `get_providers()`; a silent CPU
  fallback currently only shows up later as underruns. Log + surface the *actual* EP
  for ContentVec/F0 in the `hfabric` log and the Voice/System metrics.
- [x] **P22.5 — Latency headroom guard.** *(P1, cheap.)* We already collect
  `last_timings`/`_metrics`; add a rolling p95 of `total` and, when it nears the
  block budget, surface a concrete hint (reduce `extra_convert`, RMVPE→FCPE, denoise
  off, larger `read_chunk`) instead of leaving the user to discover stutter.
- [x] **P22.6 — Re-tune + label the +12 preset (validate before shipping).** *(P1.)*
  The doc argues `feminineVoicePreset` (index 0.5, `noise_scale` 0.666) is too
  aggressive for +12 clarity. A/B index 0.25–0.35 / `noise_scale` 0.45–0.55 / RMVPE
  against the current values on real hardware with the sibilant phrase; only then
  adjust. Also label safe-zone vs risk-zone ranges on the sliders.
  - Validated 2026-06-15 on RTX 5070 Ti / CUDA with SAPI sibilant phrase:
    `index_ratio=0.30`, `noise_scale=0.50`, RMVPE ranked best on sibilant
    high/mid balance without peak or full-band hiss penalty.
- [ ] **P22.7 — *(optional)* High-band detail preserve + one-click A/B capture.**
  Only if P22.2 is not enough for noisy rooms: re-inject raw > 3.5 kHz at low gain
  (risk: brings back keyboard hiss). A/B capture = a 10 s "raw + output + params
  JSON" button to make preset tuning objective.

**Declined from the doc (recorded so we don't relitigate):**
- **DTLN on a CUDA EP** — the doc *and* `voice-realtime-findings` agree DTLN is
  tiny; H2D/D2H transfer would add jitter while ContentVec is already ~4.5 ms on
  GPU. Net-negative; keep it on CPU.
- **CUDA Graphs / TensorRT / ONNX IO-binding / fp16 synth** — warm per-chunk is
  ~46 ms against a ~355 ms budget; these optimize a bottleneck we don't have. fp16
  was already assessed and declined. Revisit only if context sizes grow a lot.
- **Full ASR WER/CER + automated sibilant-energy benchmark** — too heavy for a
  single-user app; keep the cheap subjective AB phrase + protocol from the doc and
  the existing `scripts/voice_realtime_bench.py` for latency.

### P21 — Release readiness (NEW — prep for external testers)

> Derived from the 2026-06-14 audit. Most of these are cheap and unblock a first
> external test build. Sequenced from cheapest/highest-trust to broadest.

- [x] **P21.1 — Truth-in-docs pass.** Fixed drifted docs (test counts, stale `[~]`
  markers, the hardcoded dev path, Windows-centric residue) in the README/ROADMAP/
  audit rewrite; the tracked build artifact tail landed with P17.6.
- [x] **P21.2 — Version stamp + changelog + contributing.** `app.__version__` is the
  single source of truth, surfaced in `/api/health` and the System tab; `CHANGELOG.md`
  (Keep a Changelog) and `CONTRIBUTING.md` (dev setup + bug-report template) added.
  *Remaining:* tag the build (`v0.1.0`) when cutting the first external release (P21.5).
- [x] **P21.3 — Label experimental paths in the UI.** Setup Doctor now reads ROCm/MPS
  as "(experimental)" with an Experimental pill and an info (not success) tone, plus
  a plain "not yet validated on real hardware — SDXL-only" line, matching the README
  support matrix.
- [ ] **P21.4 — Real-hardware validation breadth.** Recruit ROCm and Apple Silicon
  testers; run `scripts/install_smoke.py` + the GPU smoke checklist on each and
  fill the validation log in `docs/gpu-smoke.md`. Promote a profile from
  experimental to supported only after a clean real run.
- [ ] **P21.5 — Packaged release.** Decide the distribution shape (tagged release
  zip vs. clone-and-run) and produce a one-page "download → run" path that does not
  require reading the full README. Gates on P21.2.

### P17 — Code health round 2 (carries the hard splits)

> Pure-logic helper extraction proved the pattern; the hard splits remain. Behavior
> frozen by a flow test written *first*; GPU files validated by the smoke checklist.

- [x] **P17.1 — Split `VoicePanel.tsx`.** Control/presentation helpers now live in
  `VoicePanelControls.tsx`, leaving `VoicePanel` focused on state and orchestration.
- [x] **P17.2 — Split `backends/image_diffusers.py`.** GPU family loaders now live
  under `image_diffusers_parts/` (`sdxl`/`flux`/`flux2`/`qwen_z`) with shared
  `memory.py` and `pipelines.py`; the original module is a facade.
- [x] **P17.3 — Split `ChatPanel.tsx`.** Conversation/stream hooks live in
  `ChatPanelHooks.ts`; message list/composer UI lives in `ChatPanelParts.tsx`.
- [x] **P17.4 — Split `ImageComposer.tsx` and `Gallery.tsx`.** Source/param/LoRA
  composer blocks moved to `ImageComposerParts.tsx`; gallery chips/detail modal
  moved to `GalleryParts.tsx`.
- [x] **P17.5 — Generate API types from OpenAPI.** Added generated
  `frontend/src/types.generated.ts`, the exported schema, npm generate/check
  scripts, and CI freshness checks for schema + TypeScript drift.
- [x] **P17.6 — Repo hygiene.** `*.tsbuildinfo` stays ignored, job failures now use
  friendly user-facing messages, and full exception traces go through the `hfabric`
  rotating log in `data/logs/`.
- [x] **P17.7 — Environment lockfile.** Added `backend/requirements-gpu.lock` from
  the verified CUDA stack so M0/M1 can be rebuilt after a disk failure without
  archaeology.

### P19 — Generation features (growth — after the foundation)

- [x] **P19.1 — FLUX / FLUX.2 img2img + inpaint.** `init_image`/`mask_image`
  now route through FLUX and FLUX.2 pipeline views as well as SDXL. Hardware
  smoke passed on RTX 5070 Ti: FLUX nunchaku img2img+inpaint at 512², FLUX.2
  klein nunchaku img2img+inpaint at the 768² pin.
- [x] **P19.2 — Upscaler as an arbiter job.** Added `upscale` job type,
  virtual upscaler model, worker branch, gallery persistence, and "Upscale
  2×/4×" actions in Result + History. Real-ESRGAN is an optional fast path when
  installed with weights; PIL resize keeps the queue/UI flow testable by default.
- [x] **P19.3 — ControlNet for SDXL.** Added optional SDXL canny ControlNet
  composer input, backend canny preprocessing, lazy ControlNet pipeline view,
  and model-profile refresh after lazy ControlNet load records the VRAM cost.
- [x] **P19.4 — Prompt library.** DB-backed `prompt_snippets` plus image
  composer modal remain in place; chat now has the same library trigger for
  `/image` prompts, including snippet negative text via `--negative`.

---

## Shipped (condensed)

Done and in use. Terse on purpose — detailed run logs live in `data/runtime/*.json`.

**Foundation & memory**
- **M0 — GPU bring-up.** torch 2.11+cu128 (cap 12.0) · diffusers 0.38 ·
  transformers <5 · bitsandbytes · llama.cpp CUDA · nunchaku 1.3 (fp4). Validated
  end-to-end.

  | Model | Speed | VRAM |
  |-------|-------|------|
  | SDXL (NoobAI) | ~5.6 s / 1024² | 11 GB |
  | FLUX (Nunchaku fp4) | ~18.7 s / 1024² | 9.8 GB |
  | gpt-oss-20B (llama-server) | streaming | 12.5 GB |

- **M1 — Real-GPU validation** (RTX 5070 Ti). Swap-loop steady-state stable;
  one swap per mixed batch; SDXL-turbo warm ~1.67 s/image; FLUX nunchaku fp4
  12-step 768² ~16 s with first-block cache.
- **P0 — Memory hygiene.** Nunchaku FLUX without the 16 GB encoder read; RAM/VRAM
  telemetry + pre-load guard (`sysmon.py`); swap-loop leak runner.
- **P7 — Memory arbiter depth.** Structured `arbiter.note` events; learned per-model
  RAM/VRAM profiles (`model_profiles`) preferred over static heuristics; pressure
  sparkline; swap-plan preview via shared `scheduler.select_in_tier`.

**Speed & generation**
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
- **Long-session image stabilization.** Per-job gc/`empty_cache`/`ipc_collect`,
  bounded LoRA cache, CUDA-drift soft-recycle. Runner: `sdxl_resident_drift_test.py`.

**Superapp shell**
- **P4 — Chat & shell.** Persistent streaming chat (sampling, personas, tok/s, TTFT,
  stop/regenerate/edit); chat→image bridge + `generate_image`/`search_documents`
  tools; command palette; declarative workspace registry; Notes/TTS/Code/Transcribe/
  RAG/Vision workspaces (model-gated, CPU-first, arbiter-safe).
- **P5 — UX polish.** Brand mark; Tailwind 4 `@theme` tokens; theme toggle; activity
  indicator + header VRAM bar; animated denoise preview; Thinking panel; shared
  keyboard-navigable control kit; packaged window icon.
- **P6R — Native voice engine.** In-process RVC v2 (vendored MIT, ~2400 lines) +
  RMVPE + ContentVec; offline `convert()` + realtime session (SOLA seam, stateful
  resamplers, pinned latent noise, DTLN denoise, idle squelch); CUDA realtime at
  every benched chunk size; UI rewired to `/api/voice/engine/*`. **Real-mic
  validation confirmed (user, 2026-06-14):** live conversion + monitor output work
  well; queued image/LLM jobs park during a session and resume after (closes P6R.4).

**Trust, data, distribution (the 2026-06-11 audit response)**
- **P14 — Security.** Default `127.0.0.1` bind; optional `HFAB_API_TOKEN` bearer
  auth (REST + WS); desktop-reaching endpoints loopback-gated regardless of token;
  upload caps + Pillow re-encode; threat model documented.
- **P15 — Reliability & data.** Alembic migrations (baseline + raw-SQL upgrade test);
  rotating `data/logs/hfabric.log`; `scripts/backup.py` (SQLite backup API +
  retention); llama-server pidfile reap of orphans on startup.
- **P16 — Test depth & quality gates.** Coverage floor in CI (`--cov-fail-under`);
  stub-mode router tests for the previously untested half; frontend eslint + prettier
  + `npm run lint` in CI; frontend flow tests (ChatPanel/Gallery/QueuePanel); the
  `docs/gpu-smoke.md` checklist.
- **P18 — Distribution.** Production serving (`HFAB_SERVE_FRONTEND=true`, SPA
  fallback, one port); `--prod` one-command launcher; first-class Settings tab with
  validated overrides persisted to `data/settings-overrides.json`; in-app model
  download manager (System tab → Model downloads, hardware-aware, disk-guarded).
- **P11 / P12 — Code health & arbiter loose ends.** Helper extraction + vitest;
  committed ruff/pytest config; learned-profile management UI; per-job arbiter
  attribution; inline swap-plan previews; memory-timeline depth.

**Universal install (P20 — make it usable beyond this machine)**
- **P20.1–.2 — Probe + resolver.** `scripts/hardware_probe.py` emits one JSON report
  (OS/RAM/disk/GPU/driver/compute-cap/torch visibility); `scripts/install_profiles.py`
  picks `nvidia-cuda` / `amd-rocm-linux` / `apple-mps` / `cpu-safe` with package
  index, verify command, runtime defaults, and warnings. setup + launcher both use it.
- **P20.3 — NVIDIA tiers.** Capability-aware runtime defaults (architecture from
  compute cap; attention/step-cache/nunchaku/fast-path gated per cap); VRAM-tiered
  model policy (8/12/16 GB).
- **P20.4 — AMD ROCm (Linux).** First-class profile; CUDA-only features auto-disabled;
  ROCm uses PyTorch's `cuda` alias; SDXL-safe until real-ROCm validation. *(Unvalidated
  on real hardware → P21.4.)*
- **P20.5 — Capability gates.** `CapabilityProfile` drives model/feature gating;
  `/api/models` marks `available`/`runtime_mode`/`unavailable_reason`; server-side
  enforcement of hidden buckets; startup autotune toward safe acceleration defaults.
- **P20.6–.7 — Setup Doctor + recommendations.** Plain-language detected-hardware page;
  per-hardware model recommendation buckets; profile-aware starter download plan.
- **P20.8 — CI matrix without owning every GPU.** Fake-probe unit tests for
  NVIDIA/AMD/MPS/CPU decisions + `scripts/install_smoke.py` real-machine grader.
- **P20.9 — Device abstraction + Apple MPS.** `accelerator_runtime.py` replaces
  hard-coded `.to("cuda")`; `apple-mps` profile (standard wheels, Metal llama.cpp,
  fp4 hidden, SDXL-only). *(Unvalidated on a real Mac → P21.4.)*
- **P20.10 — Managed llama.cpp runtime.** Auto-download the right prebuilt
  `llama-server`/`-tts`/`-mtmd-cli` per host+accelerator; in-app install/update/
  rollback with `--version` verification; old builds kept for rollback.

### Hard-won facts (load-bearing constraints — don't relearn the hard way)

- **FLUX.2 klein is pinned to 768²** on the 16 GB GPU: 1024² is not safe by default.
- **nunchaku-int4 FLUX.2 is broken on Blackwell (sm_120)** — use **fp4** (bnb-nf4 is
  the practical fallback). **Image-GGUF is unsupported** (separate from the LLM GGUF
  path).
- **`torch.compile` fails on the nunchaku transformer** in Inductor (`aten.addmm`);
  the backend auto-rolls-back to the original transformer and continues.
- **Cold-start RSS ~5.5–8.8 GB is not a leak** — one-time torch/diffusers/nunchaku
  imports. The leak runner takes a warm baseline after two unmeasured cycles.
- When the validated FLUX.2 repo *folder* exists, the registry hides the single-file
  `.safetensors` (it's a conversion source, not a duplicate target).
- **Qwen-Image-2512 is a large bf16 repo (~54 GB)** — keep `bnb-nf4` unless
  deliberately testing full bf16. **Z-Image-Turbo is distilled** — use guidance 0.0.
- **Voice live sessions need CUDA** to be realtime; CPU is only realtime at chunk 192.

---

## Where to add the next thing

- A new workspace tab = one entry in the `workspaces` array + a component using the
  shared control kit + chrome.
- Anything touching model loading goes through the arbiter (`ensure`/`free_all`) and
  the `sysmon` budget — never load a model directly.
- New env knobs follow the `HFAB_*` convention and are surfaced in `/api/settings`.
