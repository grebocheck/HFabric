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

### P21 — Release readiness (NEW — prep for external testers)

> Derived from the 2026-06-14 audit. Most of these are cheap and unblock a first
> external test build. Sequenced from cheapest/highest-trust to broadest.

- [~] **P21.1 — Truth-in-docs pass.** Fix drifted docs so a new reader trusts
  them: stale test counts, stale `[~]` markers, the hardcoded dev path, and
  Windows-centric residue. *Mostly done* by the README/ROADMAP/audit rewrite;
  remaining tail is the tracked build artifact (→ P17.6).
- [ ] **P21.2 — Version stamp + changelog + contributing.** Add a single source of
  truth `__version__`, surface it in `/api/health` and the UI footer, add
  `CHANGELOG.md` (so testers know what changed between drops), and a short
  `CONTRIBUTING.md` / "how to report a bug" (the developer guide already has the
  bug-report template to link). Tag the first external build.
- [ ] **P21.3 — Label experimental paths in the UI.** The README support matrix is
  honest about ROCm/MPS being unvalidated; the Setup Doctor should say the same in
  plain language ("Experimental — help us validate") and the first-run experience
  should not silently imply parity with the NVIDIA path.
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

- [ ] **P17.1 — Split `VoicePanel.tsx` (1651, now the worst monolith).** Promoted to
  the top of P17: the P6R rework doubled it. Extract the session/state machine and
  the tuning/audio control blocks (`VoicePanelParts.tsx`/`VoiceMeters.tsx` exist as
  a start).
- [ ] **P17.2 — Split `backends/image_diffusers.py` (1461, GPU).** One module per
  family loader (`sdxl`/`flux`/`flux2`/`qwen_z`) + shared `memory.py` /
  `pipelines.py`. Pure import-shuffle commits, each followed by a smoke run.
- [ ] **P17.3 — Split `ChatPanel.tsx` (1070).** `useConversation` + `useChatStream`
  hooks + `MessageList` / `MessageComposer`.
- [ ] **P17.4 — Split `ImageComposer.tsx` (732) and `Gallery.tsx` (632).** Extract
  the mask/source block + param form; filter bar + detail modal.
- [ ] **P17.5 — Generate API types from OpenAPI.** Replace the hand-maintained
  `types.ts` (825) with `openapi-typescript` output + a CI freshness check. Kills
  the backend↔frontend drift class.
- [ ] **P17.6 — Repo hygiene.** Untrack `frontend/tsconfig.tsbuildinfo` (gitignore
  it — it churns every diff) and add a friendly-message layer over raw `repr(exc)`
  job errors while the full trace goes to `data/logs/`.
- [ ] **P17.7 — Environment lockfile.** Freeze the verified GPU stack
  (`pip freeze > requirements-gpu.lock`) so M0/M1 can be rebuilt after a disk
  failure without archaeology.

### P19 — Generation features (growth — after the foundation)

- [ ] **P19.1 — FLUX / FLUX.2 img2img + inpaint.** Wire both families through the
  existing `init_image`/`mask_image` plumbing (currently SDXL-only); validate on
  hardware; respect the klein 768² pin.
- [ ] **P19.2 — Upscaler as an arbiter job.** Real-ESRGAN/SwinIR behind a new job
  type loaded through the arbiter; "Upscale 2×/4×" on `ResultPreview` + History.
- [ ] **P19.3 — ControlNet for SDXL.** One vetted ControlNet (canny or depth) as an
  optional composer input, with VRAM cost measured into the model profile first.
- [ ] **P19.4 — Prompt library.** Named, taggable, DB-backed prompt/style snippets
  insertable from the composer and the chat `/image` bridge.

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
