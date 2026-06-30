# Video generation — feasibility research (P27)

> Research artifact behind ROADMAP **P27 — Video generation workspace**. The
> question this answers: *can we add a text-to-video / image-to-video tab that
> actually runs on the reference machine (RTX 5070 Ti, 16 GB VRAM / 32 GB RAM,
> Blackwell sm_120) without breaking the memory invariants?* Short answer: **yes**,
> the pieces are already installed — `diffusers 0.38` ships every pipeline we'd
> use, plus `export_to_video`. The work is integration, not new ML.

## What's already on disk (verified)

`.venv` (the REAL stack) already exposes the full video lineup, so no new heavy
dependency is required to start:

- **torch 2.11.0+cu128**, compute capability 12.0 (Blackwell), `nunchaku 1.3` (fp4).
- **diffusers 0.38.0** with: `LTXPipeline` / `LTXImageToVideoPipeline` /
  `LTXConditionPipeline` / `LTXLatentUpsamplePipeline` (+ `LTX2*`), `WanPipeline` /
  `WanImageToVideoPipeline` / `WanVideoToVideoPipeline` / `Wan22*` modular /
  `WanVACEPipeline`, `HunyuanVideoPipeline` / `HunyuanVideoImageToVideoPipeline` /
  **`HunyuanVideoFramepackPipeline`**, `CogVideoX{,ImageToVideo,VideoToVideo}Pipeline`,
  `AnimateDiff*`, plus `Mochi`/`Allegro`/`EasyAnimate`/`SkyReelsV2`/`StableVideoDiffusion`.
- `diffusers.utils.export_to_video` (frames → mp4) is importable.

The memory levers we already rely on for images all apply to these transformers:
`enable_model_cpu_offload()`, `enable_sequential_cpu_offload()`,
`vae.enable_tiling()` / `vae.enable_slicing()`, group offloading, plus
`BitsAndBytesConfig` (bnb-nf4/fp4) and `GGUFQuantizationConfig` for the DiT.

## The 16 GB problem and the levers that solve it

Video DiTs are not dramatically bigger than our image models — the cost is the
**latent volume**: a clip is `frames × H × W` latents, so attention and (above all)
**VAE decode** scale with length. Two consequences drive every decision below:

1. **fp16 of a 5B+ video model overflows 16 GB** at useful resolution/length
   (Wan 2.2 TI2V-5B at fp16, 25 frames @ 768×512 ≈ **27 GB**). The fix is the same
   one the image path uses: **fp8 / bnb-nf4 transformer + `enable_model_cpu_offload`**
   so the text encoder/VAE live in RAM and only the DiT holds VRAM during denoise.
2. **VAE decode of N frames spikes both VRAM and RAM** at the end of the run.
   **`vae.enable_tiling()` + chunked/temporal decode is mandatory**, not optional —
   it is what keeps the RAM peak under the **≤26 GB** invariant when decoding a
   720p, 5-second clip.

## Model tiers for *this* box (the heart of "runs on my hardware")

Ordered by how comfortably each fits 16 GB. Resolutions/lengths are the proposed
defaults, chosen to fit — all are tunable.

| Tier | Model | Pipeline(s) | Mode | Default | Fit strategy | ~VRAM | Feel |
|------|-------|-------------|------|---------|--------------|-------|------|
| **1 (default)** | **LTX-Video 2B (0.9.x)** | `LTXPipeline`, `LTXImageToVideoPipeline` | T2V+I2V | 768×512, ~97f (~4 s) | bf16, light/no offload | ~8–10 GB | fast, few-step distilled — instant feedback |
| **1+** | **LTX-Video 13B-distilled (fp8)** | same | T2V+I2V | 768×512 | fp8 + model offload (Blackwell fp8 kernels) | ~12–14 GB | higher quality, still quick |
| **2 (quality)** | **Wan 2.2 TI2V-5B** | `WanPipeline` / `Wan22*` | T2V+I2V | 1280×720, 121f (5 s@24) | **fp8 or bnb-nf4 + model offload + VAE tiling** | ~14–16 GB | the headline; minutes/clip; fp16 won't fit |
| **2-light** | **Wan 2.1 T2V-1.3B** | `WanPipeline` | T2V | 832×480, 81f (~5 s) | bf16 + offload | ~8 GB | lightweight, reliable |
| **3 (long)** | **FramePack (HunyuanVideo)** | `HunyuanVideoFramepackPipeline` | I2V | 10 s+, 480–720p | **constant-VRAM frame-packing** + offload | ~6–8 GB | long clips on 16 GB; slow but memory-flat |
| **4 (fallback)** | **CogVideoX-2B** | `CogVideoXPipeline` | T2V | 720×480, 49f (6 s@8) | bf16 + offload + tiling | ~5–12 GB | proven, undemanding |
| **4-min** | **AnimateDiff (SDXL motion)** | `AnimateDiffSDXLPipeline` | T2V | 1024², 16–32f (~2 s) | reuses the existing SDXL stack | ~8–12 GB | lowest barrier; first STUB-friendly real model |

**Recommended initial set:** ship **LTX-Video** first (fast default that fits with
room to spare), then **Wan 2.2 TI2V-5B** (the quality tier), then **FramePack**
(long video). AnimateDiff-SDXL is the universal lightweight fallback and the
easiest non-NVIDIA path because it leans on the SDXL pipeline we already validate.

### Out of scope (budget-blowing or niche — declined like FLUX.2 [dev])

- **Wan 2.2 14B (A14B MoE)** at fp16 — needs >16 GB; only GGUF-Q4 + block-swap runs,
  and very slowly. Defer as experimental, not a default.
- **HunyuanVideo (full 13B) at fp16** — >16 GB except via FramePack or heavy quant.
- **Audio-coupled variants** (`LTX2*` audio, HunyuanVideo-1.5 audio), **Mochi (10B)**,
  **Allegro**, **EasyAnimate**, **SkyReelsV2**, **StableVideoDiffusion** — too heavy,
  too slow, or redundant with the tiers above.
- **Nunchaku/SVDQuant fp4 for Wan** — Nunchaku defaults to fp4 on Blackwell and is
  expanding, but its public video support is still image-focused. Treat fp4-Wan as
  *track-upstream / experimental*, exactly like the FLUX.2 nunchaku sidecar — not the
  validated path. GGUF-Q4 and bnb-nf4 are the validated 16 GB quant routes for video.

## How it maps onto the existing architecture

Video is "another heavy GPU resident that produces an artifact" — it slots into the
same spine as image generation, with a different output container. Concretely:

- **Enums** — add `JobType.VIDEO = "video"` and per-architecture families
  (`LTX_VIDEO`, `WAN_VIDEO`, `HUNYUAN_VIDEO`, `COGVIDEO`, `ANIMATEDIFF_VIDEO`), mirroring
  how image families are per-architecture so loaders stay separated. `ModelFamily.job_type`
  returns `JobType.VIDEO` for them.
- **Backend** — `backends/video_diffusers.py` (`VideoBackend`) mirroring
  `DiffusersImageBackend`: family-dispatched loaders, a `generate()` that runs the
  denoise loop with the existing step-callback cancellation pattern, then
  `export_to_video(frames, mp4, fps=...)`. **STUB mode** writes a tiny placeholder mp4
  (a few labelled frames) so queue → arbiter swap → progress → history all work with no GPU,
  exactly how the image STUB path bootstrapped P0.
- **Registry/inspect** — `classify_video_dir` (read `model_index.json._class_name` for
  `Wan`/`LTX`/FramePack/`CogVideoX`/`AnimateDiff`) + single-file detection; scan a new
  `models/video/` dir (`settings.video_models_dir`). The plain
  `HunyuanVideoPipeline` base repo is deliberately *not* exposed as runnable; the
  supported FramePack layout is
  `models/video/framepack-hunyuan-i2v/{base,transformer,redux}`:
  `base` = Hunyuan text encoders/tokenizers/VAE/scheduler with the stock transformer
  excluded, `transformer` = `lllyasviel/FramePackI2V_HY`, and `redux` =
  `lllyasviel/flux_redux_bfl` SigLIP feature extractor/image encoder.
- **Arbiter** — unchanged invariant: a video model is one heavy resident, swapped in
  like any other. No new concurrency.
- **sysmon budget** — add video families to `estimate_ram_need_gb` /
  `estimate_vram_need_gb`. The new term is **VAE-decode peak**: budget for tiled,
  chunked decode and refuse up-front (existing guard) when a requested
  length×resolution wouldn't fit. Learned profiles (P7.2) then replace the heuristic
  per model, as for images.
- **Scheduler/worker** — route `JobType.VIDEO` to `VideoBackend.generate`; phase-batching
  treats video like image (drain together, swap once). Long runs make robust
  cancellation important — the step callback already supports it.
- **Persistence/serving** — a `Video` table (path=mp4, poster_path, thumb_path=animated
  webp, frames, fps, duration_s, width, height, seed, family, params); serve
  `/api/videos/{id}/file` as `video/mp4` with **HTTP range** (seek/scrub) + a poster
  endpoint. Reuse `data/outputs/<day>/` layout.
- **Frontend** — a dedicated **Video** tab (peer to Voice/TTS, not folded into Images,
  because output and controls differ): a `VideoComposer` (prompt, negative,
  video-only model picker, T2V/I2V mode, resolution preset, frames, fps, duration,
  steps, guidance, seed, init image for I2V) + a result panel that plays mp4 in a
  `<video>` element (loop/controls) + the shared `QueuePanel`. History/Gallery gains
  video items (poster with a play overlay → player). Regenerate `types.generated.ts`.

## Maintenance surface (the "and supporting it" half of the request)

- **STUB-first** so CI and dev machines exercise the whole flow without weights.
- **Tests** — pytest for `classify_video_dir`, the sysmon video budget, STUB
  `generate`, and the `/api/videos` range serving; vitest for the player + composer.
- **Capability gating (P20.5)** — fp8/Blackwell fast paths gated to CUDA≥sm_89;
  CPU/ROCm/MPS hide them and offer only the lightest path (AnimateDiff-SDXL / CogVideoX-2B),
  consistent with the SDXL-only posture on those profiles today.
- **Model downloads** — add the chosen video models to the in-app download catalog
  (`model_download_service`) as a video category, with the same managed-download UX.
  FramePack is a three-entry composite download so the app can avoid the unused
  25 GB stock Hunyuan transformer while still scanning one runnable local model.
- **Docs** — `KNOWN_ISSUES.md` (honest limits: generation time in minutes, length/res
  caps, no audio, one-resident swap pause), a `docs/gpu-smoke.md` video checklist row,
  and `CHANGELOG.md` on ship.

## Sources

- [Wan 2.1/2.2 VRAM requirements guide — WillItRunAI](https://willitrunai.com/blog/wan-2-2-vram-requirements)
- [Wan2.2-TI2V-5B VRAM page — WillItRunAI](https://willitrunai.com/video-models/wan-video-2-2-ti2v-5b)
- [Wan-AI/Wan2.2-TI2V-5B-Diffusers — Hugging Face](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)
- [Wan-Video/Wan2.2 — GitHub (single-GPU 5 s/720p ≈ 9 min claim)](https://github.com/Wan-Video/Wan2.2)
- [Lightricks/LTX-Video-0.9.8-13B-distilled — Hugging Face](https://huggingface.co/Lightricks/LTX-Video-0.9.8-13B-distilled)
- [Lightricks/LTX-Video — GitHub (fp8 kernels, Ada+/Blackwell)](https://github.com/Lightricks/LTX-Video)
- [nunchaku-ai/nunchaku — GitHub (SVDQuant fp4, Blackwell default)](https://github.com/nunchaku-ai/nunchaku)
