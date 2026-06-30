# GPU Smoke Checklist

Run this checklist after any torch, diffusers, accelerator driver/runtime,
nunchaku, llama.cpp, image-loader, or native voice-engine change. Also run it before and
after large GPU refactors such as the planned `image_diffusers.py` split.

## Installer profile smoke (P20.8)

Before the perf checks below, confirm the universal installer picked the right
backend for this machine. The resolver decisions are covered on every push by
fake-probe unit tests (`backend/tests/test_install_profiles.py`,
`test_capability_profile.py`, `test_model_compatibility.py`,
`test_install_smoke.py`) — those run in CI without a GPU. On a *real* CUDA,
ROCm, or Apple Silicon MPS box, also run the live smoke, which probes the machine, resolves the
profile, and cross-checks it against `torch` visibility:

```
python scripts/install_smoke.py            # probe + resolve + run verify snippet
python scripts/install_smoke.py --no-verify # skip torch import (pre-install)
python scripts/install_smoke.py --json      # machine-readable checks
```

Pass: `Overall: PASS` — the selected profile's backend matches what torch sees
(CUDA build for `nvidia-cuda`, HIP build for `amd-rocm-linux`, MPS availability
for `apple-mps`, no accelerator for `cpu-safe`), no `nunchaku_cuda` is offered on a pre-Ampere/non-CUDA card,
and the profile verify snippet runs clean. Paste the printed summary block into
the validation log below.

### Real-machine validation log

Record every real GPU the installer path is validated on. Keep failures here too.

| Date | GPU | VRAM | Driver | OS | Profile | torch | Result | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-14 | RTX 5070 Ti | 16 GB | 610.47 | Win 11 | nvidia-cuda | 2.11.0+cu128 | PASS | `.\.venv\Scripts\python.exe scripts\install_smoke.py`; verify snippet reported `(12, 0)` |
| 2026-06-?? | AMD ROCm GPU | TODO | TODO | Linux | amd-rocm-linux | TODO | TODO | run `install_smoke.py`; SDXL-only until real-ROCm validation |
| 2026-06-?? | Apple Silicon | unified | — | macOS | apple-mps | TODO | TODO | run `install_smoke.py`; SDXL-only until real-Mac validation |

Record the date, GPU, driver, torch/diffusers/nunchaku versions, and any changed
environment knobs with the results. A pass means every step finishes without OOM
or fallback, the resident-model invariant is preserved, and the observed numbers
are close to the baselines below.

### Managed llama.cpp runtime smoke

| Date | Host | Variant | Command | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-06-14 | Windows / RTX 5070 Ti | cuda | `.\.venv\Scripts\python.exe scripts\fetch_llama.py --force` | PASS | installed `b9631-cuda` under `bin/llama/versions/`; `llama-server --version` returned `version: 9631` |

## Preflight

1. Stop the normal backend if it is running.
2. Activate the verified GPU environment.
3. Set real mode: `HFAB_STUB_MODE=false`.
4. Confirm `/api/health` or the script output reports the expected accelerator
   profile and enough free RAM/VRAM/unified memory for the run. The performance
   checks below are CUDA-baseline checks unless a step explicitly says otherwise.

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

5. Run the P26 image-edit matrix through the Edit workspace or `/api/jobs`:
   - SDXL and FLUX: one img2img and one inpaint job.
   - Qwen-Image and Z-Image: one img2img and one inpaint job for every locally
     installed BnB/Nunchaku variant; verify `mem.status` still reports one resident
     heavy model because edit pipes share components.
   - FLUX.2 [klein]: one reference-conditioned source job (metadata contains
     `flux2_reference: true` and no fake strength) and one inpaint job.
   - Anima: one img2img job; masks must remain unavailable.
   - If installed, run one Qwen-Image-Edit or FLUX.1-Kontext instruction edit and
     one SDXL ControlNet combined img2img/inpaint job.
   - Pass: gallery output is valid, masks remain localized, requested/effective
     strength and edit operations are reproducible from metadata, and no job spills
     into shared VRAM or pagefile pressure.

6. Run the P27 Video workspace matrix:
   - LTX-Video: one 480p/49-frame T2V job and one I2V job from an uploaded frame.
   - Wan 2.2 TI2V-5B: one 480p/49-frame T2V job, then the same prompt at 720p only
     if `mem.status` still leaves the configured safety margin.
   - Seek through each result in the browser (the mp4 endpoint must return HTTP 206
     for byte ranges), cancel one running denoise, and swap Video -> LLM -> Video.
   - Repeatable app-path check: against a live backend, run
     `python scripts/video_app_smoke.py`. It asserts websocket events, HTTP 206
     range replay, poster/thumb fetches, cancel during denoise, and
     Video -> LLM -> Video resident swap. STUB mode is acceptable for this app-path
     check after the real-GPU model matrix above has passed.
   - Pass: one heavy resident throughout, no shared-VRAM/pagefile spill, tiled VAE
     decode completes, poster/animated thumbnail exist, and History replays the mp4.

7. `python scripts/voice_engine_smoke.py`
   - Expected:
     - Strict RVC state-dict load: `457/0/0`.
     - RMVPE median on a 220 Hz tone: about 220 Hz.
     - Converted output spectral flatness is much greater than the sine baseline
       (historical converted flatness 0.17-0.23 vs sine baseline about 0.0008).
   - Pass: all three gates match, output is finite audio, and the script does not
     use any fake synth or silent fallback.

8. `python scripts/voice_realtime_bench.py`
   - Expected CUDA hot-path numbers for chunk sizes 96/133/192:
     - 96: mean/p95 about 224.6/374.7 ms vs 256.0 ms chunk budget.
     - 133: mean/p95 about 129.3/140.8 ms vs 354.7 ms chunk budget.
     - 192: mean/p95 about 125.5/141.4 ms vs 512.0 ms chunk budget.
   - Pass: CUDA mean is realtime at all three sizes, p95 is realtime at 133 and
     192, stitched output is finite and exact-length, and no sustained overrun
     pattern appears. Use CUDA for live sessions.

### P26 real-machine edit validation log

| Date | GPU | Family / variant | Paths | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-06-21 | RTX 5070 Ti 16 GB | SDXL NoobAI | inpaint + mask ops | PASS | 512², 4 steps; grow/blur and `padding_mask_crop` exercised. Existing img2img path remained covered by the full regression suite. |
| 2026-06-21 | RTX 5070 Ti 16 GB | Qwen-Image Nunchaku fp4 | img2img + inpaint | PASS | Both views reused the resident transformer. A standalone BnB row was not present locally: the slim Qwen repo has no transformer weights. |
| 2026-06-21 | RTX 5070 Ti 16 GB | Z-Image Nunchaku fp4 | img2img + inpaint | PASS | 512², 4 effective steps, guidance 0. |
| 2026-06-21 | RTX 5070 Ti 16 GB | Z-Image BnB fp4 | img2img + inpaint | PASS | Cold process required for the RAM guard; warm process correctly refused after another heavy model occupied RAM. |
| 2026-06-21 | RTX 5070 Ti 16 GB | FLUX.1-dev Nunchaku fp4 | img2img + inpaint | PASS | 512², 4 steps. |
| 2026-06-21 | RTX 5070 Ti 16 GB | FLUX.2 klein 9B Nunchaku fp4 | reference + inpaint | PASS | First on-device validation of `Flux2KleinInpaintPipeline`; 512², 4 steps. Full 34.7 GB BnB install exceeds this host's safe RAM budget. |
| 2026-06-21 | RTX 5070 Ti 16 GB | Anima | img2img | PASS | Custom VAE encode/noise/timestep latent-init path, 512², 4 steps. |

Optional ControlNet depth/pose/scribble/Union and instruction-edit rows require
their separate model weights; this host did not have those assets installed. Their
routing, family gating, memory guards, and stub-mode acceptance paths are covered by
the automated suite rather than being reported here as real-GPU passes.

### P27 real-machine video validation log

| Date | GPU | Family / variant | Path | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-06-30 | RTX 5070 Ti 16 GB | LTX-Video | T2V 832x480 / 49f / 8 steps | PASS | `MODEL=ltx-video MODE=t2v W=832 H=480 FRAMES=49 STEPS=8 scripts/video_vram_probe.py`; peak 6.00 GB VRAM; mp4, poster, thumbnail, metadata written. |
| 2026-06-30 | RTX 5070 Ti 16 GB | LTX-Video | I2V 832x480 / 49f / 8 steps | PASS | Source upload token `079fb1d04add4d5aa91f77c985c82c2c`; peak 6.76 GB VRAM. This caught and fixed the LTX I2V VAE dtype mismatch. |
| 2026-06-30 | RTX 5070 Ti 16 GB | Wan 2.2 TI2V-5B | T2V 832x480 / 49f / 8 steps | PASS | `MODEL=wan2.2-ti2v-5b MODE=t2v W=832 H=480 FRAMES=49 STEPS=8 scripts/video_vram_probe.py`; peak 7.83 GB VRAM; tiled VAE decode and mp4 encode completed. |

### P27 live app-path validation log

| Date | Host | Mode | Command | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-06-30 | Windows / RTX 5070 Ti | STUB live backend | `python scripts/video_app_smoke.py --base-url http://127.0.0.1:8274 --api-token ... --timeout 120` | PASS | Isolated temp DB/outputs; validated websocket `job.*`/`video.ready`, HTTP `Accept-Ranges` + `206`, poster/thumb fetches, running-job cancel, and Video -> LLM -> Video resident swap. |

P27.6 app-path and UI polish are covered. Remaining P27 feature breadth is tracked
in the roadmap: FramePack long-video support and non-NVIDIA fallback validation.

## Fail Handling

Do not accept a run that silently falls back to CPU, shared VRAM, fake output, or
missing models. Keep the failing log, note the exact command and environment
knobs, and stop before changing unrelated code.
