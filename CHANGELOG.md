# Changelog

All notable changes to HFabric are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/). Until 1.0.0, minor versions may
include breaking changes — this is pre-release software.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.3.0] — 2026-06-19

### Added
- **OpenAI-compatible LLM API server toggle** in the Chat workspace:
  `/api/llm/server` can pin a selected GGUF model in VRAM, expose the local
  llama endpoint metadata, and show/copy the `/v1` base URL for external clients.
- **Resident GPU pinning for long-lived serving**: the arbiter now reports a
  resident pin in GPU status, keeps the pinned LLM loaded until explicitly
  released, and makes queued work for other models wait with a clear queue note.

### Changed
- **First-class Studio light theme polish**: semantic UI tokens now drive common
  surfaces, controls, popovers, badges, telemetry, chat, gallery, model, voice, and
  system panels so light mode reads as an intentional design instead of a patched
  dark theme.
- **Shared micro-control styling** is applied across selects, toggles, sliders,
  model settings, command palette, prompt library, result previews, and diagnostics
  surfaces for more consistent hover, focus, disabled, and state colors.
- **LLM launch settings are protected while API serving is pinned**: context/backend
  changes now return a conflict until the API server is turned off, preventing
  hidden resident-model swaps.

### Deprecated

### Removed

### Fixed
- **LoRA generation no longer fails with "PEFT backend is required"** after a
  real-mode setup: `peft` is now installed with every accelerator profile, the
  launchers detect older half-upgraded environments, and runtime LoRA errors point
  users back to setup/update instead of surfacing a raw Diffusers exception.

### Security


## [0.2.0] — 2026-06-18

### Added
- **Hugging Face model catalog in the Models tab**: search Hub model repos in-app,
  sort by downloads/likes/updated/trending, inspect model-card metadata, open repo
  files, auto-select weight-like files, and download selected files or whole repos
  into the right `models/<kind>/` folder. New `GET /api/downloads/hf/search`.
- **Self-contained Windows setup/update path**: setup can provision local portable
  Python and Node.js under `.tools/`, build the project virtualenv from those local
  runtimes, and `update.ps1` can bring the checkout forward while preserving local
  generated/runtime state.

### Changed
- **Theme polish**: the default dark theme is now a true black theme, while `Dim`
  remains the softer gray dark mode. Light mode now uses crisp light panels and
  controls instead of dark translucent fields.
- **HF partial-repo downloads** keep multi-file selections together under a repo
  folder, while single top-level weight files still land flat for the common GGUF /
  SafeTensors case.

### Fixed
- **Voice changer first-run assets**: ContentVec and RMVPE can be fetched from the
  app/setup path into `models/voice/pretrain/`, with ContentVec accepting the ONNX
  layout used by the working upstream model.


## [0.1.0] — 2026-06-17

First public beta. Real-GPU validated on NVIDIA / RTX 5070 Ti / Windows 11; AMD
ROCm and Apple Silicon MPS are implemented but experimental (unvalidated on real
hardware). The foundation — a **VRAM arbiter** (at most one resident heavy model,
with a RAM-budget guard), a phase-batching scheduler, a persisted SQLite queue with
live WebSocket progress, chat **LLM** + diffusion **image generation**, and the
RAG / TTS / Transcribe / Notes / Code / native RVC Voice workspaces (model-gated,
CPU-first) — together with everything below.

### Added
- **Prompt library** (P19.4): save, search, tag, and reuse image-prompt snippets
  from the composer; export/import as JSON. New `/api/prompts` + `prompt_snippets`
  table.
- **Release pipeline** (P24): a tag-triggered GitHub Actions workflow
  (`.github/workflows/release.yml`) that reuses the CI gates and publishes a
  **pre-release** with a `git archive` source bundle + SHA-256 checksum and notes
  drawn from this changelog. New `scripts/release.py` handles version/tag/changelog
  discipline (`check-tag` guards that a tag matches `app.__version__`).
- **Beta framing & feedback loop** (P24.4/.5): a public-beta README status block,
  `KNOWN_ISSUES.md`, `SECURITY.md` (private vulnerability reporting), and GitHub
  issue templates (bug · feature · hardware-validation) with security reports routed
  to private advisories.
- **Export diagnostics** (P24.5): System tab → Diagnostics bundles logs +
  health/capability/settings + version/platform stamps into a zip
  (`GET /api/diagnostics/export`) with secrets scrubbed — produced locally, never
  uploaded — so a bug report can be one attachment.
- **First-run experience** (P24.7): a one-time Welcome naming the core surfaces, a
  dismissible STUB-mode banner, a no-image-models nudge in the Result pane that
  deep-links to Model downloads, and a friendlier chat empty state.
- **Hot model rescan** (P24.8): `POST /api/models/rescan` re-reads the model dirs
  without a restart, a "Rescan models" button in System tab → Model downloads, and
  an automatic rescan when an in-app download completes — so a model dropped on disk
  or just downloaded is usable immediately.
- **GPU activity visibility for voice/TTS/transcribe** (P24.10): the topbar now shows
  an active label (e.g. "voice session") instead of "Active model: idle" while a live
  voice session, GPU TTS, or GPU transcribe is using the card. These run outside the
  one-resident-model arbiter, so they register an observability-only "lane" — no
  second heavy model is loaded; the VRAM bar already reflects the real usage.
- **Unified Model Manager tab** (P25): a dedicated **Models** tab to get models for
  every workspace and manage what's installed. A left **sidebar** lists each model
  type with its count and total size and filters the installed view; "All" and a disk
  free/used footer round it out. Download from the curated catalog, **browse a
  HuggingFace repo** (list its files with sizes and pick specific file(s) or the whole
  repo), or paste a **direct URL** — each lands in the right `models/<kind>/` folder.
  See everything installed across all model types with sizes and **delete** to reclaim
  disk (guarded against deleting a model that's loaded on the GPU). New
  `GET/DELETE /api/models/installed`, `POST /api/downloads/custom`, and
  `GET /api/downloads/hf/files`. Model downloads moved here out of the System tab.
- **One-click voice pretrain assets** (tester feedback): dropping an RVC voice model
  into `models/voice/` isn't enough — every voice model needs the shared ContentVec
  encoder (and RMVPE for the quality pitch path), which weren't bundled or documented,
  so the Voice tab just showed "missing" with no way forward. The Voice tab now
  explains this and offers a **"Download voice assets"** button
  (`POST /api/voice/engine/assets/fetch` → `models/voice/pretrain/`), with live
  progress and a manual fallback; `scripts/fetch_voice_assets.py` is the terminal
  equivalent.

### Fixed
- **Image composer no longer resets steps/guidance/size on tab switch**: the
  composer tracked "is this field still a default?" by comparing the value to a small
  set of magic numbers shared across model families, so a user-chosen value that
  happened to collide (e.g. 50 steps on SDXL, which equals the Qwen-Image default)
  was treated as untouched and reset to the default every time the Images tab
  remounted. It now records an explicit per-field "touched" flag (persisted with the
  rest of the composer state), so a customized value survives tab switches, family
  changes, and default changes.
- **Windows launcher fails clearly when Node.js/npm is missing** (tester feedback):
  `run.bat`/`run.ps1` used to die with a raw `CommandNotFoundException` at
  `npm install`. A shared `scripts/_windows_prereqs.ps1` now preflights Python and
  Node/npm in both `run.ps1` and `setup.ps1` — it refreshes PATH from the registry
  to catch the common "installed but stale PATH" case, offers a one-shot
  `winget install`, and otherwise prints actionable steps instead of a stack trace.
- **`npm install` failures no longer cascade into "'vite' is not recognized"**
  (tester feedback): `run.ps1` ignored npm's exit code and skipped reinstall when a
  *partial* `node_modules` existed, so a failed download (e.g.
  `ERR_SSL_CIPHER_OPERATION_FAILED`) or an `EPERM` cleanup left a broken tree and
  the launcher marched on to a missing-vite crash. `Install-FrontendDeps` now checks
  the exit code, retries once after `npm cache clean --force`, and on failure prints
  targeted help (TLS interception by VPN/proxy/AV; `EPERM` from OneDrive-synced
  folders; update npm) instead of continuing. A completeness sentinel
  (`Test-FrontendReady`) treats a vite-less `node_modules` as "needs reinstall".
- **`run.bat` now installs the full accelerator stack on first run** (P24.9, tester
  feedback): previously `run.bat` installed only foundation deps but auto-selected
  REAL on a CUDA GPU, leaving torch/diffusers/sounddevice/llama uninstalled (the root
  cause of the voice/image 500s). A shared `Install-AcceleratorStack` now installs
  PyTorch + backend requirements + the llama.cpp runtime; `run.ps1` invokes it when
  REAL is selected but the stack is absent, and `setup.ps1` uses the same function so
  `setup.bat` and `run.bat` install identically — no `real`/`-Real` flag needed.
- **`/api/voice/engine/status` no longer 500s when `sounddevice` is missing**
  (tester feedback): a REAL-mode run that skipped the GPU install has no
  `sounddevice` (it's an accelerator-stack dep), and audio-device enumeration threw
  `ModuleNotFoundError`, breaking the whole voice-status endpoint. `audio_devices()`
  now degrades to an empty device list (warned once in the log) so the endpoint stays
  healthy and the Voice tab simply shows no devices.

[Unreleased]: https://github.com/grebocheck/HFabric/compare/v0.3.0...HEAD
[0.1.0]: https://github.com/grebocheck/HFabric/releases/tag/v0.1.0
[0.2.0]: https://github.com/grebocheck/HFabric/releases/tag/v0.2.0
[0.3.0]: https://github.com/grebocheck/HFabric/releases/tag/v0.3.0
