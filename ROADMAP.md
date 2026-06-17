# HFabric — Roadmap & Backlog

> **Status:** working app, real-GPU validated on NVIDIA/Windows (M0/M1), with a CI
> safety net (ruff + eslint + pytest with a coverage floor + `tsc` + build + vitest
> on every push/PR). The audit-driven foundation (P0–P20) and the beta-prep phases
> (P21–P24) have largely shipped — see [`docs/history.md`](docs/history.md) for the
> full shipped record and [`CHANGELOG.md`](CHANGELOG.md) for release notes.
>
> The remaining work is **cutting and standing behind a public `0.1` beta**: push the
> first `v0.1.0` tag (the launch), make the repo worth trying at first glance, close
> the last observability/first-run gaps, and validate the non-NVIDIA paths once
> testers exist. This file is the **forward plan only** — completed phases move to
> `docs/history.md` so the plan stays legible.
>
> Marking: `[ ]` not started · `[~]` in progress / partially done.

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

1. **P24.1 — push the `v0.1.0` tag.** The pipeline is built and statically verified;
   the only thing left is the deliberate tag push that *is* the launch.
2. **P24.6 — invite-readiness.** Screenshots/GIF + a tight repo description so a
   stranger sees it work before deciding to clone. *(Needs the user for assets.)*
3. **P24.10 — topbar GPU visibility** for voice/TTS/transcribe lanes. Self-contained
   and the next thing implementable solo.

Then the long-pole items that need other people/hardware: **P21.4** (ROCm + Apple
testers) and the **P24.7** resilience audit.

## Active backlog

### P24 — Release pipeline & public v0.1 beta

- [~] **P24.1 — Release CI workflow (tag → GitHub pre-release).** *(P1 — load-bearing.)*
  `.github/workflows/release.yml` triggers on `v*` tags: reuses `ci.yml` via
  `workflow_call` as a required precondition, assembles a `git archive` source bundle,
  generates the body from the matching `CHANGELOG.md` section + `docs/release-footer.md`,
  attaches a SHA-256 checksum, and publishes with `--prerelease`. **Authored &
  statically verified;** the one remaining check is the first real `v0.1.0` tag push —
  the actual launch moment.
- [ ] **P24.6 — Invite-readiness / first impression.** *(P1/P2 — what makes someone
  actually try it.)* README hero with screenshots or a short demo GIF (chat + image
  gen + the live VRAM bar — the differentiator is "two heavy models, one 16 GB GPU, no
  OOM"); a concise above-the-fold feature list; a tight GitHub repo description +
  topics. The README is honest but long and text-only — a stranger needs to *see* it
  work before they'll `git clone`.
- [~] **P24.7 — First-run experience & resilience.** *(P2 — the newcomer's first ten
  minutes.)* **Done:** Welcome modal, dismissible STUB-mode banner, no-image-models
  nudge, chat empty-state hint; friendly model-load failure messages (P17.6) clear the
  spinner on error. **Remaining:** a deeper audit of the OOM-guarded / missing-binary
  paths and any Setup-Doctor cross-links, revisited if testers hit them.
- [ ] **P24.10 — Surface non-arbiter GPU consumers in status + topbar (voice, TTS,
  transcribe).** *(P2 — observability gap from tester feedback.)* `arbiter.status()`
  ([`arbiter.py`](backend/app/core/arbiter.py) ~L262) reports only the resident LLM/
  image backend; during a realtime voice-changer session (RVC/ContentVec on CUDA) the
  topbar shows "idle" and a flat VRAM bar even though the GPU is busy. Voice already
  parks the job lane, so the invariant holds — this is purely **visibility**. Register
  these GPU "lanes" so `status()` / `gpu.status` + `mem.status` report an active label
  (e.g. "voice session") and the real VRAM, and the topbar reflects it. Don't introduce
  a second resident heavy model — just report what's actually running.

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
