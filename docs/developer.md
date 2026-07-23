# Developer guide

How to test, debug, migrate, back up, and contribute to HFabric. For end-user
install/run see the [README](../README.md); for runtime knobs see
[configuration.md](configuration.md).

## Layout

```
backend/app/
  core/        arbiter, scheduler, planning, results, events, enums
               (the GPU-correctness core)
  backends/    registry (model scan), image_diffusers, llm_llamacpp
  api/         FastAPI routers + named response contracts + ws
  services/    capability_profile, model_compatibility, runtime_tuning,
               chat/rag/embedding/gallery/queue services, llama_manager,
               voice_engine/ (native RVC engine)
  db/          SQLAlchemy models + async session + Alembic wiring
  util/        sysmon, security, async files, uploads, logging, pidfiles
frontend/src/  React + Tailwind 4; one component per workspace tab
scripts/       hardware probe, installer resolver, model/llama fetchers,
               GPU smoke runners, backup
docs/          this guide + configuration, audits, gpu-smoke, voice-routing
```

Design rules worth keeping:

- **Everything GPU goes through the arbiter.** Never load a model directly — call
  `arbiter.ensure(...)` / `free_all()` and let the `sysmon` budget guard run
  first. The single worker serializes GPU work so correctness is structural.
- **A new workspace tab** = one entry in the `workspaces` array + a component
  using the shared control kit (`Select`/`Toggle`/`Badge`/`Slider`) and chrome.
- **New runtime knobs** follow the `HFAB_*` convention and are surfaced through
  `/api/settings` and the Settings tab schema.

## Testing

The whole pipeline runs in **STUB mode** (no GPU/ML stack), so the memory-budget
logic, the phase-batching scheduler, and the queue → arbiter swap → gallery flow
are all testable on a plain machine. CI runs both suites on every push/PR
(`.github/workflows/ci.yml`): ruff + pytest (with a coverage floor) on the
backend, eslint + `tsc -b` + `npm run build` + vitest on the frontend.

**Backend** (pytest, stub mode — hermetic temp DB + dummy model files):

```powershell
python -m venv .venv
.\.venv\Scripts\pip install --require-hashes -r backend\requirements-dev.lock
.\.venv\Scripts\ruff check backend scripts
.\.venv\Scripts\python -m pytest backend\tests
```

Anchor coverage: `tests/test_scheduler.py` (the *one-swap-per-mixed-batch*
invariant), `tests/test_sysmon.py` (the RAM budget guard), the per-router stub
tests (`test_chat_api.py`, `test_rag_api.py`, …), and `test_stub_integration.py`
(the full queue → swap → gallery flow over an ASGI client). The installer/
capability layer is covered by fake-probe tests (`test_install_profiles.py`,
`test_capability_profile.py`, `test_model_compatibility.py`,
`test_install_smoke.py`, `test_fetch_models.py`) so resolver decisions are
verified in CI without owning every GPU.

Coverage uses real branch instrumentation. Hardware-only model-construction
adapters listed in `backend/.coveragerc` are validated by the real-GPU smoke
matrix; scheduler, arbiter, registry, generation callbacks, persistence and API
control flow remain in the CI scope.

**Frontend** (Vitest + Testing Library + Playwright):

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test:coverage
npm run build
npx playwright install chromium  # once per machine
npm run test:e2e
```

The browser suite intercepts the API and runs without a GPU. It covers first
run, token authentication, critical workspace flows, accessibility checks and
narrow viewports. Generated API types must stay synchronized:

```powershell
.\.venv\Scripts\python backend\scripts\export_openapi.py frontend\openapi.json
cd frontend
npm run openapi:generate
npm run openapi:check
```

To inspect reproducible caches/build output without touching models, user data,
credentials, managed runtimes, or dependencies:

```powershell
python scripts/clean_dev.py          # dry run
python scripts/clean_dev.py --apply  # remove only the printed allowlist
```

Flow tests cover the high-value screens: ChatPanel (send → streamed reply →
thinking split), Gallery (filter chips + bulk select), QueuePanel (job states +
cancel), plus the Select control and model-picker helpers.

## Dependency profiles and locks

`backend/dependency-profiles.json` is the single source for Python 3.12,
resolver version, torch versions, platform targets and lock outputs. The
installer selects one of the universal foundation/development locks or the
Windows CUDA, Linux CUDA, Linux ROCm and macOS arm64 MPS locks.

```powershell
# after intentionally editing an input/manifest
python scripts/install_profiles.py --compile-locks

# byte-for-byte freshness + hash/index/backend/drift validation
python scripts/install_profiles.py --check-locks
python scripts/check_dependency_consistency.py
```

Never edit a compiled lock directly. ROCm installs its pinned torch trio from
the official ROCm index first; the hashed shared dependency lock deliberately
omits that trio so it cannot replace the accelerator wheels.

## Real-GPU validation

CI cannot exercise the real GPU path. After any torch/diffusers/driver/nunchaku/
llama.cpp bump, run the ordered checklist in **[gpu-smoke.md](gpu-smoke.md)** with
its expected M1 numbers. The individual runners (against a running REAL backend):

```powershell
python scripts/swap_leak_test.py --cycles 3   # RSS/VRAM return to warm baseline
python scripts/phase_batch_check.py            # exactly one swap for a mixed batch
python scripts/sdxl_resident_drift_test.py --jobs 8
python scripts/quality_ab.py --family flux --limit 2 --free-gpu-first
python scripts/install_smoke.py                # probe + resolve + verify torch visibility
```

Record every real machine (date, GPU, driver, package profile, pass/fail) in the
validation tables in `gpu-smoke.md`. **Do not accept a run that silently falls
back to CPU, shared VRAM, fake output, or missing models.**

## Database migrations

The backend runs Alembic `upgrade head` during startup. Migration files live in
`backend/migrations/versions/`; `0000_current_schema` is the baseline.

To add a column:

1. Update the SQLAlchemy model in `backend/app/db/models.py`.
2. Add a new revision under `backend/migrations/versions/` with the next revision
   id and `down_revision` set to the current head.
3. In `upgrade()`, add the column with a server default if existing rows need a
   non-null value.
4. Add/update a test that boots a fresh DB and, when relevant, upgrades a legacy
   raw-SQL DB.

## Backup & restore

```powershell
python scripts/backup.py --keep 10
```

Writes `data/backups/hfabric-<timestamp>/hfabric.db` using SQLite's live-safe
backup API plus `outputs-manifest.json` (a manifest of `data/outputs/` with
relative paths, sizes, mtimes). It does **not** copy output image/audio bytes —
keep `data/outputs/` in your normal file backup.

Restore order:

1. Stop HFabric.
2. Copy the saved `hfabric.db` back to `data/hfabric.db`.
3. Restore `data/outputs/` from your file backup, preserving relative paths.
4. Start HFabric; startup migrations bring the restored DB to the current schema.

## Logs

A rotating file handler writes `data/logs/hfabric.log` (~5 × 10 MB): startup
config summary, every arbiter note (swap / refusal / warm-evict with numbers),
job start/done/error with duration, `llama-server` stderr tail on failure, and
unhandled exceptions. This is the first place to look for an "it hung overnight"
report.

## Contributing & reporting issues

This is pre-release software under active development; expect rough edges,
especially outside the validated NVIDIA/Windows path.

When reporting a problem, include:

- OS + GPU + VRAM, and the **profile** the app selected (System tab → Setup
  Doctor, or `python scripts/hardware_probe.py --pretty`).
- Whether you were in REAL or STUB mode.
- The relevant tail of `data/logs/hfabric.log` and the backend console.
- Exact steps and the model(s) involved.

Before opening a PR: `ruff check`, `pytest`, `npm run lint`, `tsc -b`, and
`npm run test:coverage`, `npm run test:e2e`, and `npm run build` should all
pass, and GPU-path changes should be smoke-tested per
`gpu-smoke.md`.
