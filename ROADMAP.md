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
2. **P25.1/P25.2 — visual polish + first-class light theme.** The 2K workspace
   composition is acceptable; the visible product risk is micro-detail debt:
   dark-mode utility leakage, uneven state colors, and a light theme that feels
   patched instead of designed.
3. **P24.6 — invite-readiness.** Screenshots/GIF + a tight repo description so a
   stranger sees it work before deciding to clone. *(Needs the user for assets.)*

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
  spinner on error; first-run dependency audit tightened Python/Node/version checks,
  launcher self-repair of missing foundation/REAL stack packages, in-app model downloads
  as a foundation dependency, managed voice/DTLN asset downloads, advanced full-model
  catalog entries, and `update.*` scripts for git+dependency refresh. **Remaining:**
  re-run the audit on a clean tester Windows machine and revisit any OOM-guarded /
  missing-binary paths testers still hit.

### P25 — Visual polish, color system & first-class light theme

Audit notes (2026-06-19): the overall 2K workspace composition is broadly right for a
local AI production tool. The debt is in micro-finish: color roles, control states,
small text contrast, hover/focus behavior, badge tones, popovers, and light-theme
surfaces. Code confirms the pattern: hundreds of component-level `text-white`,
`bg-black`, and `border-white` utilities are acting as a dark-theme design language,
while light mode currently patches low-alpha black backgrounds into white surfaces.
That makes light mode usable, but not beautiful or trustworthy.

Design direction: keep the dense workstation layout, keep dark media canvases where
image inspection benefits from them, but make **Light** a designed "Studio" theme:
paper-like chrome, graphite text, crisp cool-gray borders, restrained blue/violet
accent use, and warmer semantic feedback colors that are tuned separately from dark
mode. Do not make the app a pale copy of the black theme.

Implementation pass (2026-06-19): semantic tokens, Studio light palette, tone bridge,
shared controls, key workspace polish, themed overlays, and `docs/theme-qa.md` are in
place. Keep P25 active until a manual screenshot sweep across real data states is
complete, then move the shipped record to `docs/history.md`.

- [~] **P25.1 — Semantic UI color tokens.** *(P1 — foundation for every polish pass.)*
  Add real UI roles in `frontend/src/index.css`: `ui-strong`, `ui`, `ui-muted`,
  `ui-subtle`, `ui-inverse`, `canvas`, `panel`, `raised`, `sunken`, `stage`,
  `overlay`, `border`, `border-strong`, `control`, `control-hover`,
  `control-active`, and tone pairs for
  success/warn/error/info/accent. Acceptance: common text/control classes no longer
  encode a dark palette; `text-white/*`, `bg-black/*`, and `border-white/*` remain
  only for true overlays, media lightboxes, image gradients, and intentionally dark
  inspection canvases.
- [~] **P25.2 — Redesign the light theme as a first-class Studio theme.** *(P1.)*
  Replace the current light palette with a cohesive one: near-white app canvas,
  white panels, slightly blue-gray raised/sunken surfaces, graphite foreground,
  darker muted text, visible but quiet borders, and restrained shadows. Preserve a
  neutral/dark checker or charcoal stage behind generated images so artwork still
  reads with contrast. Acceptance: Images, History, LLM, Voice, Models, and System
  all look intentionally light; no "white text on white card", washed-out badges, or
  invisible disabled states.
- [~] **P25.3 — Light-mode state/tone palette.** *(P1.)* Define separate light/dark
  recipes for badges, notices, queue states, model-family chips, RAM/VRAM indicators,
  security/STUB banners, destructive buttons, and inline errors. Current saturated
  dark-mode tones such as emerald/amber/red-on-tint should map to legible light
  alternatives instead of relying on Tailwind defaults. Acceptance: every semantic
  tone passes contrast in light mode for small text, and status chips are visually
  distinct without looking candy-colored.
- [~] **P25.4 — Shared micro-control kit pass.** *(P1/P2.)* Consolidate repeated
  local constants for `field`, `label`, `subtleButton`, mini buttons, cards, and
  status tiles into shared primitives/recipes. Add variants for primary, secondary,
  quiet, danger, success, icon, and compact controls with stable heights. Acceptance:
  inputs, selects, sliders, toggles, file fields, popover search boxes, and command
  palette rows share one radius, border, hover, focus, disabled, and placeholder
  language across themes.
- [~] **P25.5 — Header/nav micro-polish.** *(P2.)* Refine the top chrome without
  changing its density: stronger active tab state, calmer inactive tabs, clearer
  theme switch affordance, polished `Ctrl K` keycap, more readable active-model chip,
  and a VRAM meter that works on light backgrounds. Acceptance: the header feels like
  one toolbar, not mixed badges and plain buttons; no tab/status text disappears in
  light mode.
- [~] **P25.6 — Image workspace detail polish.** *(P2.)* Keep the three-column 2K
  layout, but tune the details: prompt textarea contrast, section dividers, model
  family chip, notices, LoRA empty states, footer action bar, thumbnail rail, selected
  thumbnail border, and the result-stage background. Replace text-heavy secondary
  actions with a more consistent compact action style where practical. Acceptance:
  the generated image remains the visual hero, while surrounding controls feel crisp
  and less improvised in both themes.
- [~] **P25.7 — History/gallery finish pass.** *(P2.)* Polish filter inputs, chips,
  favorites, selection checkmarks, bulk action bar, "Load more", image hover captions,
  and detail-modal metadata. Use dark gradients only over thumbnails/media, not as
  generic light-theme chrome. Acceptance: gallery filters feel like a media library,
  selected/favorited states are unmistakable, and light mode keeps thumbnail contrast.
- [~] **P25.8 — Chat/Code/RAG reading polish.** *(P2.)* Tune long-message typography,
  message bubbles, markdown/code backgrounds, attachment chips, sidebars, model
  settings controls, and inline tool states. Acceptance: text-heavy workspaces are
  easier to scan in light mode, code blocks keep enough contrast, and accent color is
  reserved for selection/action instead of sprinkling.
- [~] **P25.9 — Voice/System telemetry polish.** *(P2.)* Give meters, sliders,
  diagnostic tiles, timelines, provider-health rows, and warning panels dedicated
  light/dark recipes. Voice can keep a console/mixer feel, but its off/disabled/live
  states need clearer visual separation in light mode. Acceptance: telemetry remains
  dense but readable, and warning/safe/running states are distinguishable at a glance.
- [~] **P25.10 — Popovers, modals, and overlays.** *(P2.)* Theme command palette,
  select menus, welcome/auth modals, prompt library, model browser, zoom controls, and
  image detail overlays. Keep true image lightboxes dark in every theme; make app
  dialogs theme-aware. Acceptance: no light theme popover uses hardcoded `bg-zinc-950`
  or dark-only text unless it is intentionally a media overlay.
- [~] **P25.11 — Visual QA gate for themes.** *(P1/P2.)* Add a repeatable theme QA
  checklist or screenshot harness for at least Images, History, LLM, Voice, System,
  Welcome/Auth, and Command Palette at desktop and mobile widths. Acceptance: a PR
  touching shared UI tokens includes before/after screenshots or an automated visual
  capture, plus a quick contrast pass for small text and disabled states.

### P26 — img2img / image-edit coverage (research first)

- [ ] **P26.1 — Extend img2img/inpaint beyond SDXL·FLUX·FLUX.2 (research, then go/no-go).**
  Today `image_diffusers.py` gates editing to `{SDXL, FLUX, FLUX.2}` and rejects an
  `init_image`/`mask_image` for **Qwen-Image, Z-Image, and Anima** with a hard
  `ValueError`. Known rough edges to fold into the research: FLUX.2 [klein] takes a
  *reference* image but exposes **no denoise-strength** knob (its `_pipe(image=…)` path
  ignores `strength`), so it's image-conditioning, not true img2img; ControlNet is
  SDXL-only and can't be combined with img2img/inpaint; diffusers floors
  `steps×strength` when picking timesteps. **To research before any code:** (a) do
  Qwen-Image / Z-Image / Anima ship diffusers Img2Img/Inpaint pipeline classes — or can
  the base pipe accept `image`+`strength` directly? (b) memory cost of a second
  lazily-built edit pipe under bnb-fp4 / nunchaku on the 16 GB GPU; (c) can klein expose
  a real strength control or does it stay reference-only? (d) quality at low VRAM plus
  sane per-family default strengths. **Output:** a support matrix + a go/no-go per family,
  then implement only the green ones. Code anchors:
  `backend/app/backends/image_diffusers.py` (`edit_families` gate),
  `backend/app/backends/image_diffusers_parts/pipelines.py` (`_*_img2img_pipe`).

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
