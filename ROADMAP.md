# HFabric — Roadmap & Backlog

> **Status:** working app at **v0.3.0** (tags `v0.1.0`/`v0.2.0`/`v0.3.0` shipped),
> real-GPU validated on NVIDIA/Windows, with a green CI safety net on every push/PR
> (ruff + eslint + `tsc` + build + pytest@68% floor + vitest). The audit-driven
> foundation (P0–P24), the unified Model Manager (P25), the Edit workspace (P26),
> and CivitAI integration have all shipped — see [`docs/history.md`](docs/history.md)
> for the full record and [`CHANGELOG.md`](CHANGELOG.md) for release notes.
>
> **The beta is launched; the next chapter is paying down the debt that velocity
> bought.** Five feature workstreams landed back-to-back (P25 → P26 → P27) and the
> codebase now shows it: a coverage floor sitting flush against the actual number,
> four service modules with no test file, several files too large to review safely,
> and an in-flight video workspace (P27) still uncommitted. So this plan leads with a
> **code-quality & stability track (Q1–Q7)** ahead of new features, then finishes the
> genuinely-remaining feature/validation work (FramePack, non-NVIDIA breadth).
>
> This file is the **forward plan only** — completed phases move to
> `docs/history.md` so the plan stays legible.
>
> Marking: `[ ]` not started · `[~]` in progress / partially done · `[x]` done.
>
> **Audit basis (2026-06-30):** all gates green — ruff/eslint/tsc clean,
> vitest 98 green, pytest 420 green at **69.07%** coverage (floor 68%); Alembic at
> revision `0005`; frontend type-safety strong (`types.ts` now derives from the
> OpenAPI-generated `types.generated.ts`; 0 stray `console.*`). Findings below cite
> exact files and metrics so each item is checkable.

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

## Next up

1. **P27 feature breadth.** FramePack long-video support and the non-NVIDIA fallback
   remain the real P27 feature work after the LTX/Wan surface proved out.
2. **P24.7 clean tester audit.** Re-run first-run/resilience on a clean Windows
   tester machine when one is available.
3. **P21.4 external hardware breadth.** Recruit ROCm and Apple Silicon testers for
   real install + GPU smoke validation.

Then the long-pole items that need other people/hardware: **P21.4** (ROCm + Apple
testers), and the **P24.7** resilience audit on a clean tester machine.

## Active backlog

### Q — Code quality & stability hardening *(lead priority)*

> **Why this is the lead track:** the app works and ships, but P25→P26→P27 added
> ~7k lines fast and the seams show. None of these are user-visible bugs today; each
> is a place where the *next* change is more likely to break something or where a
> failure would be hard to debug. Ordered by risk-reduction per hour.

- [x] **Q1 — Get the coverage floor off the tripwire.** Done 2026-06-30:
  added focused stub/unit coverage for `chat_attachments.py`, `chat_service.py`,
  `rag_service.py`, `video_service.py`, `embedding_service.py`, plus adjacent
  scheduler/event/queue/media safety paths. CI now enforces
  `--cov-fail-under=68`; local verification: **420 passed, 69.07%**.
- [x] **Q2 — Decompose the highest-churn monolith first.** Done 2026-06-30:
  `image_diffusers.py::_generate_real` is now a thin metadata/persistence wrapper
  over `image_diffusers_parts/generation.py`, with dispatcher tests for txt2img /
  img2img / inpaint / controlnet family branches. Follow-up split the next backend
  tier too: settings schema metadata lives in `settings_specs.py` (`settings_overrides.py`
  is now 159 lines), and the realtime voice chunk core lives in `realtime_processor.py`
  (`voice_engine/realtime.py` is now 561 lines).
- [x] **Q3 — Frontend monolith split (resume P17).** Done 2026-06-30:
  `ChatPanel.tsx` is down to **854** after moving send/edit/attachment/manual-image
  workflow actions into `ChatPanelHooks.ts`; `VoicePanel.tsx` is down to **985** after
  moving Live Console / Tuning / Routing / Presets / Offline Convert / Diagnostics into
  `VoicePanelSections.tsx`. `types.ts` (946) is **not** in scope — it is now mostly thin
  re-exports over the generated schema.
- [x] **Q4 — Stabilize & land the P27 video WIP.** Done 2026-06-30: P27's family
  defaults, bnb offload selection, guidance clamping, decode/encode progress phases,
  LTX I2V dtype fix, app-path smoke script, richer presets, and History filters are
  covered by STUB/unit/frontend tests. Real-GPU CLI smoke passed for LTX T2V, LTX I2V,
  and Wan T2V; live app-path smoke passed for range replay, cancel, and
  Video -> LLM -> Video swap. The WIP was landed as part of this quality pass.
- [x] **Q5 — Exception-handling observability sweep.** 278 `except` blocks across 52
  files; most are deliberate best-effort (annotated `# noqa: BLE001`), but a handful
  swallow with a bare `pass` and **no log** — `core/events.py` (L44, L61, the event
  bus itself) and `voice_engine/realtime.py` (L597, L608, stream teardown). For the
  "debuggable after a crash" promise, every swallow should at least `logger.debug(...,
  exc_info=True)`. Make the convention enforceable: require the `noqa: BLE001` to carry
  a reason comment (most already do). Done: event bus and realtime teardown now log
  debug exceptions with reason comments and tests cover event-bus failure paths.
- [x] **Q6 — Cover the load-bearing safety paths explicitly.** The arbiter/scheduler
  invariants are the product's core promise; confirm each recovery branch has a named
  STUB test and add the gaps: RAM-budget refusal + warm-evict ladder
  (`arbiter._guard_budget`), resident-pin park/resume (`scheduler._pick_next`), and
  orphan requeue on restart (`scheduler._requeue_orphans`). These must never silently
  regress. Done: the RAM guard tests already existed; resident-pin and orphan-requeue
  tests were added 2026-06-30.
- [x] **Q7 — Truth-in-docs cadence.** The roadmap had drifted three releases (claimed
  pre-`v0.1.0` while `v0.3.0` was tagged) and `docs/audit-2026-06-14.md` predates
  P25/P26/P27. Adopt a one-line rule: **refresh the audit snapshot + prune this
  roadmap on every minor release.** Fold a fresh `docs/audit-2026-06-30.md` (this
  pass) in as the current baseline. Done for this pass.

### P27 — Video generation workspace (text-to-video / image-to-video)

> **Why it's feasible now:** the REAL stack already carries it — `diffusers 0.38`
> ships `LTXPipeline`/`WanPipeline`/`HunyuanVideoFramepackPipeline`/`CogVideoX*` +
> `export_to_video`, on torch 2.11+cu128 / Blackwell / `nunchaku 1.3`. This is
> integration, not new ML. **Full investigation + the 16 GB model matrix:**
> [`docs/video-research.md`](docs/video-research.md).
>
> **Hardware fit (the non-negotiable):** a video model is *one heavy resident*
> under the existing arbiter — same one-at-a-time rule, no new concurrency. The new
> cost is **latent volume**: VAE decode of N frames spikes VRAM *and* RAM, so
> **`vae.enable_tiling()` + chunked decode is mandatory** and the sysmon guard must
> budget that decode peak and refuse a too-long/too-large clip up front (≤16 GB VRAM,
> ≤26 GB RAM peak). fp8 / bnb-nf4 transformer + `enable_model_cpu_offload` is how a
> 5B-class model fits 16 GB (fp16 ≈ 27 GB does not). Nunchaku-fp4 for video stays
> *track-upstream / experimental*, like the FLUX.2 nunchaku sidecar.
>
> **Recommended model order:** LTX-Video (fast default that fits with room) →
> Wan 2.2 TI2V-5B (quality tier, fp8/bnb + offload, minutes/clip) → FramePack
> (memory-flat long clips). AnimateDiff-SDXL is the lightweight + non-NVIDIA fallback.

- [x] **P27.1 — Plumbing + STUB end-to-end.** Shipped & tested in STUB: `JobType.VIDEO`,
  per-architecture video `ModelFamily` entries, `video_models_dir`, a `VideoBackend`
  (STUB writes a placeholder mp4), a `Video` DB row, `/api/videos/{id}/file` with **HTTP
  range**, a **Video** tab (`VideoComposer` + mp4 player) and video History items.
  Real-GPU CLI smoke and the live app-path smoke passed on 2026-06-30.
- [x] **P27.2 — First real model: LTX-Video.** T2V + I2V via `LTX{,ImageToVideo}Pipeline`,
  `export_to_video`, `vae.enable_tiling()` + `enable_model_cpu_offload`, learned RAM/VRAM
  profile — wired and real-GPU validated 2026-06-30 at 832x480 / 49f / 8 steps
  (T2V peak 6.00 GB, I2V peak 6.76 GB). The I2V smoke caught and fixed the VAE dtype
  mismatch in the LTX image-conditioning path.
- [x] **P27.3 — Quality tier: Wan 2.2 TI2V-5B** (fp8 / bnb-nf4 + offload + VAE tiling),
  Wan 2.1 T2V-1.3B as the lightweight variant. Video families + the VAE-decode peak are in
  `sysmon.estimate_*` and the "minutes per clip" note is in `KNOWN_ISSUES.md`;
  Wan 2.2 real-GPU T2V validated 2026-06-30 at 832x480 / 49f / 8 steps, peak 7.83 GB.
- [ ] **P27.4 — Long video: FramePack (HunyuanVideo).** `HunyuanVideoFramepackPipeline`
  for memory-flat I2V clips (10 s+) on 16 GB — slow but constant-VRAM. Not started.
- [~] **P27.5 — Capability gating + non-NVIDIA.** CUDA gating shipped. *Remaining:* the
  fp8/Blackwell fast-path gate and the CPU/ROCm/MPS lightest-path fallback
  (AnimateDiff-SDXL / CogVideoX-2B), mirroring today's SDXL-only posture there.
- [x] **P27.6 — Maintenance & polish.** Shipped: in-app download catalog, STUB / range /
  classification / budget + composer/player tests, docs, History, and CLI real-GPU
  video smoke log; `scripts/video_app_smoke.py` now validates live HTTP range replay,
  websocket events, cancel during denoise, and Video -> LLM -> Video resident swap.
  Richer clip presets and Video History filters landed 2026-06-30.

### P24 — Release pipeline & first-impression (post-launch residual)

> The release pipeline is **proven, not theoretical:** `v0.1.0`, `v0.2.0`, and
> `v0.3.0` have all been tagged and published via `.github/workflows/release.yml`
> (tag → CI precondition → source bundle + SHA-256 → GitHub pre-release). P24.1 is
> **done.** What remains is presentation and the clean-machine resilience pass.

- [x] **P24.6 — Invite-readiness / first impression.** Done 2026-06-30: README now
  opens with a concise local/private AI value proposition, screenshots for image
  generation + live VRAM, chat, history, and voice, an above-the-fold feature list,
  current `v0.3.0` status/audit links, and explicit image/edit/video/model-manager
  scope. GitHub repo metadata is set too: description
  "Local private AI workspace for LLM chat, image/edit/video generation, RAG and
  voice on one GPU with a VRAM arbiter" plus topics `local-ai`, `llm`,
  `image-generation`, `video-generation`, `diffusers`, `llama-cpp`, `rag`,
  `voice-changer`, `cuda`, `private-ai`.
- [~] **P24.7 — First-run experience & resilience.** *(P2 — the newcomer's first ten
  minutes.)* **Done:** Welcome modal, dismissible STUB-mode banner, no-image-models
  nudge, chat empty-state hint; friendly model-load failure messages (P17.6) clear the
  spinner on error; first-run dependency audit tightened Python/Node/version checks,
  launcher self-repair of missing foundation/REAL stack packages, in-app model downloads
  as a foundation dependency, managed voice/DTLN asset downloads, advanced full-model
  catalog entries, and `update.*` scripts for git+dependency refresh. **Remaining:**
  re-run the audit on a clean tester Windows machine and revisit any OOM-guarded /
  missing-binary paths testers still hit.

### P22 — Voice realtime quality (optional residual)

- [ ] **P22.7 — *(optional)* High-band detail preserve + one-click A/B capture.** Only
  if the denoise wet/dry mix isn't enough for noisy rooms: re-inject raw > 3.5 kHz at
  low gain (risk: brings back keyboard hiss). A/B capture = a 10 s "raw + output +
  params JSON" button to make preset tuning objective.

### P21 — Release readiness (needs external hardware)

- [ ] **P21.4 — Real-hardware validation breadth.** Recruit ROCm and Apple Silicon
  testers; run `scripts/install_smoke.py` + the GPU smoke checklist on each and fill
  the validation log in `docs/gpu-smoke.md`. Promote a profile from experimental to
  supported only after a clean real run. *(Blocks the "supported" claim for the
  `amd-rocm-linux` and `apple-mps` profiles shipped in P20.4 / P20.9.)*

---

## Declined / out of scope (recorded so we don't relitigate)

**Distribution**
- **A frozen single-file installer (PyInstaller / Electron / one `.exe`).** REAL mode's
  torch + CUDA/ROCm + llama.cpp stack is platform- and accelerator-specific and tens of
  GB; the hardware-aware setup script + managed llama runtime is the correct shape for a
  beta. Revisit only after 1.0 if demand is real.
- **Publishing to package registries (PyPI / winget / Homebrew / Docker Hub).**
  Premature for a single-author local-GPU beta; the GitHub release is the one channel.
- **Telemetry / crash phone-home — even anonymised.** The privacy promise is that
  nothing leaves the machine; diagnostics are export-on-demand (P24.5), never auto-sent.

**Video generation** *(see [`docs/video-research.md`](docs/video-research.md))*
- **fp16 of a 5B-class video model, or the Wan 2.2 14B (A14B MoE) / HunyuanVideo full
  13B at fp16** — all overflow 16 GB at useful length/resolution. 14B is GGUF-Q4 +
  block-swap only, and very slow; keep it experimental, never a default.
- **Audio-coupled variants, Mochi (10B), Allegro, EasyAnimate, SkyReelsV2,
  StableVideoDiffusion** — too heavy, too slow, or redundant with the LTX/Wan/FramePack
  tiers we ship.
- **Nunchaku/SVDQuant fp4 for Wan** — track upstream as experimental (like the FLUX.2
  nunchaku sidecar); GGUF-Q4 and bnb-nf4 are the validated 16 GB quant routes for video.

**LLM workspace & vision**
- **A generic multi-tool agent / arbitrary tool plugins** — keep the two vetted tools
  (`generate_image`, `search_documents`) plus native calling; no open-ended execution.
- **Two parallel vision engines** — chat-native `llama-server --mmproj` is the single
  surface; the `llama-mtmd-cli` engine was removed, not kept as a fallback.
- **Vision on the heavy image-generation models** — understanding stays on the LLM +
  mmproj path; image *generation* stays the diffusers path. Don't conflate.

**Voice (from the RVC research doc)**
- **DTLN on a CUDA EP** — DTLN is tiny; H2D/D2H transfer would add jitter while
  ContentVec is already ~4.5 ms on GPU. Keep it on CPU.
- **CUDA Graphs / TensorRT / ONNX IO-binding / fp16 synth** — warm per-chunk is ~46 ms
  against a ~355 ms budget; these optimize a bottleneck we don't have.
- **Full ASR WER/CER + automated sibilant-energy benchmark** — too heavy for a
  single-user app; keep the cheap subjective AB phrase + `scripts/voice_realtime_bench.py`.

---

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
