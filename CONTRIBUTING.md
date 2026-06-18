# Contributing to HFabric

Thanks for trying HFabric — it's pre-release software, so bug reports and rough-edge
notes are genuinely useful. This is a single-developer project; expect things to be
roughest outside the validated **NVIDIA / Windows** path (AMD ROCm and Apple
Silicon are experimental — see the [README support matrix](README.md#platform-support)).

## Reporting a bug

Please include:

- **OS + GPU + VRAM**, and the **profile** the app selected — System tab → Setup
  doctor, or `python scripts/hardware_probe.py --pretty`.
- Whether you were in **REAL** or **STUB** mode.
- The relevant tail of `data/logs/hfabric.log` and the backend console output.
- Exact steps to reproduce and the model(s) involved.

If you're on AMD ROCm or Apple Silicon and a real run works (or doesn't), that's
high-value: note it on the validation log in [docs/gpu-smoke.md](docs/gpu-smoke.md).

## Development setup

See the [developer guide](docs/developer.md) for the full layout and design rules.
Quick start:

```bash
# backend (stub mode, no GPU needed)
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt

# frontend
cd frontend && npm install
```

## Before opening a PR

All of these should pass (CI runs them on every push):

```bash
# backend
.venv/Scripts/ruff check backend scripts
.venv/Scripts/python -m pytest backend/tests

# frontend
npm run lint
npx tsc -b
npm test
```

GPU-path changes (anything under `backends/image_diffusers.py`, the voice engine,
or model loading) can't be covered by CI — smoke-test them on real hardware per
[docs/gpu-smoke.md](docs/gpu-smoke.md) and record the result.

## Guidelines

- Keep changes scoped; match the surrounding code's style and altitude.
- Anything touching model loading goes through the arbiter — never load a model
  directly (see the developer guide).
- New runtime knobs use the `HFAB_*` convention and surface in `/api/settings`.
- Models, weights, and datasets are never committed — they are user-supplied
  ([MODEL_NOTICE.md](MODEL_NOTICE.md)).

## License

By contributing you agree your contributions are licensed under the project's
[MIT License](LICENSE).
