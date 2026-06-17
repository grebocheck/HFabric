# Changelog

All notable changes to HFabric are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/). Until 1.0.0, minor versions may
include breaking changes — this is pre-release software.

## [Unreleased]

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

_Toward the first public `0.1` beta (see [ROADMAP](ROADMAP.md) phase P24): the
release pipeline, beta framing, feedback loop, and first-run polish are in place;
the remaining nicety is the visual README hero + repo topics (P24.6)._

## [0.1.0] — pre-release

First version prepared for testing by people other than the author. Real-GPU
validated on NVIDIA / RTX 5070 Ti / Windows 11; AMD ROCm and Apple Silicon MPS
are implemented but experimental (unvalidated on real hardware).

### Core
- VRAM arbiter: at most one resident heavy model, with a RAM-budget guard that
  refuses a load before it can spill to the pagefile.
- Phase-batching scheduler: a mixed LLM/image batch drains with a single model swap.
- Persisted SQLite queue that resumes on restart; live progress over WebSocket.

### Generation & workspaces
- Image: SDXL, FLUX (Nunchaku fp4), FLUX.2 [klein], Qwen-Image, Z-Image; img2img
  and inpainting (SDXL); reproduce/vary; measured-VRAM model & LoRA pickers.
- Chat LLM via llama.cpp: streaming, personas, sampling control,
  stop/regenerate/edit, `/image` bridge, `generate_image`/`search_documents` tools.
- Workspaces: RAG, TTS, Transcribe, Notes, Code, and a native RVC Voice changer
  (validated with a real mic) — all model-gated and CPU-first by default. Image
  understanding is chat-native (attach an image to a multimodal LLM).
- History: responsive grid, combinable filters, favorites/tags, bulk delete + ZIP.

### Trust, data, distribution
- Optional `HFAB_API_TOKEN` bearer auth (REST + WS); desktop-reaching endpoints
  loopback-gated regardless of token; default bind `127.0.0.1`.
- Alembic migrations; rotating `data/logs/hfabric.log`; `scripts/backup.py`.
- Production serving (`HFAB_SERVE_FRONTEND=true`) and a `--prod` one-command launcher.
- First-class Settings tab with validated overrides persisted to
  `data/settings-overrides.json`.

### Universal install
- Hardware probe + install-profile resolver (`nvidia-cuda`, `amd-rocm-linux`,
  `apple-mps`, `cpu-safe`) used by both setup and launcher.
- Capability profile gates models/features per GPU; startup autotune toward safe
  acceleration defaults; per-model availability in `/api/models`.
- Setup Doctor (plain-language detected hardware) and a managed, updatable
  llama.cpp runtime with rollback and `--version` verification.
- In-app **Model downloads** manager: hardware-aware curated catalog with
  size/license/target-dir, Recommended preselected, disk-budget guard, and live
  progress.

[Unreleased]: https://github.com/grebocheck/HFabric/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/grebocheck/HFabric/releases/tag/v0.1.0
