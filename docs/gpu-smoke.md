# GPU Smoke Checklist

Run this 15-minute checklist after any torch, diffusers, CUDA driver, nunchaku,
llama.cpp, image-loader, or native voice-engine change. Also run it before and
after large GPU refactors such as the planned `image_diffusers.py` split.

Record the date, GPU, driver, torch/diffusers/nunchaku versions, and any changed
environment knobs with the results. A pass means every step finishes without OOM
or fallback, the resident-model invariant is preserved, and the observed numbers
are close to the baselines below.

## Preflight

1. Stop the normal backend if it is running.
2. Activate the verified GPU environment.
3. Set real mode: `HFAB_STUB_MODE=false`.
4. Confirm `/api/health` or the script output reports one RTX 5070 Ti-class CUDA
   device and enough free RAM/VRAM for the run.

## Ordered Checks

1. `python scripts/swap_leak_test.py`
   - Expected: warm-baseline steady state after the initial unmeasured cycles.
   - Pass: no monotonic RSS/VRAM creep, no pagefile pressure, peak RAM remains
     comfortably under the 32 GB machine budget (target peak <= 26 GB), and only
     one heavy model is resident at a time.

2. `python scripts/phase_batch_check.py`
   - Expected: a mixed LLM/image batch drains by phase.
   - Pass: exactly one model swap for the mixed batch, all jobs finish, and the
     queue/arbiter events agree with the plan preview.

3. `python scripts/sdxl_resident_drift_test.py`
   - Expected: repeated SDXL jobs keep the resident pipeline stable.
   - Pass: no CUDA OOM, no unbounded reserved-memory drift, and any soft recycle
     happens only at the configured drift threshold rather than every job.

4. `python scripts/image_live_bench.py`
   - Expected M1 numbers:
     - SDXL turbo warm: about 1.7 s/image.
     - FLUX nunchaku fp4, 12 steps, 768^2: about 16 s/image with first-block cache.
   - Pass: both families produce valid gallery images, no hidden CPU/shared-VRAM
     fallback appears, and timings stay within normal variance. Investigate a
     repeatable regression above roughly 25%.

5. `python scripts/voice_engine_smoke.py`
   - Expected:
     - Strict RVC state-dict load: `457/0/0`.
     - RMVPE median on a 220 Hz tone: about 220 Hz.
     - Converted output spectral flatness is much greater than the sine baseline
       (historical converted flatness 0.17-0.23 vs sine baseline about 0.0008).
   - Pass: all three gates match, output is finite audio, and the script does not
     use any fake synth or silent fallback.

6. `python scripts/voice_realtime_bench.py`
   - Expected CUDA hot-path numbers for chunk sizes 96/133/192:
     - 96: mean/p95 about 224.6/374.7 ms vs 256.0 ms chunk budget.
     - 133: mean/p95 about 129.3/140.8 ms vs 354.7 ms chunk budget.
     - 192: mean/p95 about 125.5/141.4 ms vs 512.0 ms chunk budget.
   - Pass: CUDA mean is realtime at all three sizes, p95 is realtime at 133 and
     192, stitched output is finite and exact-length, and no sustained overrun
     pattern appears. Use CUDA for live sessions.

## Fail Handling

Do not accept a run that silently falls back to CPU, shared VRAM, fake output, or
missing models. Keep the failing log, note the exact command and environment
knobs, and stop before changing unrelated code.
