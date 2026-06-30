# Known issues & limitations (beta)

HFabric is **pre-release** software. This page is an honest list of what's rough,
what's by-design, and what to expect — so a tester knows whether something is a bug
worth reporting or a known limitation. If you hit something that isn't here, please
[open an issue](https://github.com/grebocheck/HFabric/issues/new/choose).

The deeper engineering rationale for several of these lives in the
[ROADMAP "hard-won facts"](ROADMAP.md#hard-won-facts-load-bearing-constraints--dont-relearn-the-hard-way).

## Platform support

- **Only NVIDIA CUDA on Windows 11 is validated end-to-end** (RTX 5070 Ti / 16 GB /
  Blackwell, 32 GB RAM). Everything else is less travelled.
- **AMD ROCm (Linux) and Apple Silicon (MPS) are experimental** — implemented and
  unit-tested with fake hardware probes, but **never run on real hardware**. They
  run SDXL-only and hide CUDA-only fast paths. If you try one, the
  [GPU smoke checklist](docs/gpu-smoke.md) has steps and a log to fill in — that's
  the single most useful thing a non-NVIDIA tester can contribute.
- Non-Blackwell NVIDIA tiers (8/12 GB) are capability-gated but **not yet validated**
  on real silicon; fast paths auto-disable below the required compute capability.

## Image generation

- **FLUX.2 [klein] is pinned to 768²** on a 16 GB GPU; 1024² is not safe by default.
- **FLUX.2 nunchaku-int4 is broken on Blackwell (sm_120)** — use **fp4** (bnb-nf4 is
  the practical fallback). **Image-GGUF is unsupported** (this is separate from the
  LLM GGUF path, which works).
- **`torch.compile` fails on the nunchaku transformer** (Inductor `aten.addmm`); the
  backend auto-rolls-back to the original transformer and continues — so you may see
  a compile warning in the log that is safe to ignore.
- **Qwen-Image is a large bf16 repo (~54 GB)** — keep the `bnb-nf4` variant unless
  you're deliberately testing full bf16. **Z-Image-Turbo is distilled** — use
  guidance 0.0.
- **FLUX (full, non-nunchaku) and FLUX.2 [dev] are out of scope** by design.

## Memory & model switching

- **Exactly one heavy model is resident at a time** (the VRAM arbiter). A mixed
  LLM↔image batch incurs **one model swap** — that swap is a visible pause, not a
  hang.
- **Cold-start RSS of ~5.5–8.8 GB is expected, not a leak** — one-time
  torch/diffusers/nunchaku imports.
- A load is **refused up front** if the predicted peak wouldn't fit RAM (it won't
  silently spill to the pagefile) — you'll see a clear "won't fit" message rather
  than an OOM crash. That's intended.

## Video generation

- **LTX-Video and Wan 2.2 currently require NVIDIA CUDA.** Their local Diffusers
  repositories load in 4-bit with tiled VAE decode; 480p / 49-frame LTX T2V+I2V and
  Wan T2V are validated on the RTX 5070 Ti reference box. Non-NVIDIA fallback families
  remain a P27 follow-up.
- **Wan is measured in minutes, not seconds.** A 720p clip can take several minutes
  on one consumer GPU. Start at 480p with 49 frames while tuning a prompt.
- Video output is silent MP4. Longer/high-resolution clips are refused before load
  when the predicted model + latent + decode peak would exceed safe RAM/VRAM.
- Switching between LLM, image, and video models unloads the previous heavy resident,
  so the first clip after another workspace includes a visible model-swap pause.

## LLM / chat

- Reliable native tool-calling depends on the model supporting it; models without
  tool support fall back to a prompt-based protocol, which is less robust.
- Multimodal (vision) needs a model with a paired `mmproj` projector; without one,
  image attachments can't be read.

## Voice changer

- **Realtime conversion needs CUDA** to keep up; on CPU it's only realtime at the
  smallest chunk size. Validated with a real microphone on the reference machine.

## General / rough edges

- Single-developer beta: expect rough edges in first-run/empty states and error
  messages outside the happy path (tracked as ROADMAP **P24.7**).
- Documentation can lag the code in spots; the [audit](docs/audit-2026-06-30.md) is
  the most candid status snapshot.
- The app is built for a **single local user**. Don't expose it on a hostile
  network without `HFAB_API_TOKEN` (see [SECURITY.md](SECURITY.md)).
