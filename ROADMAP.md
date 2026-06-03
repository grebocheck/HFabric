# ImageFabric — Roadmap & Prioritized Backlog

> Rebalanced after M0: **speed is not the only goal — RAM frugality is now a
> first-class objective**, because exhausting the 32 GB of RAM makes Windows
> spill to the pagefile, and those constant pagefile *writes* wear the SSD.

## Objectives (in priority order)

1. **RAM frugality — every single model load must fit comfortably, so the app
   never OOMs, hangs, or spills to the pagefile.** Keep the working set well under
   physical RAM (hard budget: peak ≈ **≤ 26 GB of 32 GB**). Optimization (small
   quantized models, no wasteful loads) is what keeps us away from the limit —
   not aggressive process-killing. Stopping the *previous* model when the user
   **switches** models is fine and expected; the goal is that loading any one
   model on its own is always safely within budget.
2. **VRAM frugality — one resident heavy model** (the arbiter), ≤ 16 GB, with a
   safety margin so we never overflow into shared/system VRAM (that path is the
   23-min FLUX disaster from M0).
3. **Speed on Blackwell** — fp4/fp8 compute, `torch.compile`, step-caching.

## Memory invariants

- VRAM: exactly one resident heavy model at a time (LLM **or** an image model).
- RAM: a guard checks predicted peak vs. available RAM **before** a load; if a
  load wouldn't fit it reports clearly and waits/queues — it must never push the
  OS into the pagefile or leave the app hung "doing nothing because it's out of
  memory".
- Switching models frees the previous one cleanly (this is expected, and made
  rare by phase-batching): llama-server is shut down (the only way to release its
  VRAM); diffusers pipelines are `del` + `gc.collect()` + `empty_cache()` +
  `ipc_collect()`. We do **not** kill as a routine memory tactic — optimization
  keeps each load within budget so we don't have to.
- Telemetry: process RSS + system available RAM + VRAM are surfaced in
  `/api/health` and over the WebSocket so we can *see* pressure, not guess.

---

## Backlog

### P0 — Memory hygiene & correctness (do first)

- **P0.1 — Nunchaku FLUX encoders without the 16 GB read.** Today the nunchaku
  path calls `FluxPipeline.from_single_file(flux_dev_fp8)` just to borrow
  T5/CLIP/VAE — that reads 16 GB from SSD and briefly materializes the ~12 GB fp8
  transformer only to throw it away. Replace with:
  - T5 → `NunchakuT5EncoderModel` (int4, ~3 GB) from `nunchaku-tech/nunchaku-t5`,
  - CLIP-L → `openai/clip-vit-large-patch14` (~250 MB, non-gated),
  - VAE → FLUX VAE from the non-gated config repo (small).
  **Win:** ~10 GB → ~4 GB RAM, removes a 16 GB SSD read per FLUX load, lower VRAM.
- **P0.2 — RAM guard + telemetry.** Add `psutil`; report RSS / available RAM /
  VRAM in `/api/health` and as a `mem.status` WS event. Before any model load the
  arbiter checks predicted peak vs. a configurable budget and defers if it would
  breach it (prevents pagefile thrash by construction).
- **P0.3 — Swap-loop leak test.** Automated LLM→FLUX→SDXL→LLM ×N loop asserting
  RAM and VRAM return to baseline each cycle (catch leaks / fragmentation).
- **P0.4 — Default FLUX = nunchaku.** Flag the raw fp8 `flux_dev` entry as
  "slow / high-mem" (or hide it) so a click can't accidentally trigger a 23-min,
  VRAM-overflowing run. Surface quant/est-VRAM per model in the UI.
- **P0.5 — Confirm llama-server is mmap + full-offload** (disk-backed, no
  pagefile; VRAM via `-ngl 999`) and document the knobs.

### P1 — Speed & live UX

- **P1.1 — `torch.compile`** on the transformer (mode=max-autotune) + a warmup
  pass; measure RAM/VRAM *during* compile (it can spike — keep within budget).
- **P1.2 — Step-caching (TeaCache / First-Block-Cache)** for FLUX → ~1.5–2×
  fewer compute steps at near-equal quality; low memory cost.
- **P1.3 — Live phase-batching validation** in the running app: a mixed batch
  must do exactly **one** LLM↔image swap; add denoise-progress preview to the UI.
- **P1.4 — SDXL turbo** via DMD2/Lightning LoRA (4–8 steps) → ~1–2 s/image.
- **P1.5 — Frontend polish:** presets, queue drag-reorder, gallery metadata panel.

### P2 — Optional / later

- **P2.1 — Keep-warm policy** (park the hot model in CPU RAM between swaps to skip
  an SSD reload) — **OFF by default**, gated behind the RAM budget; only engages
  if there's headroom, never causes paging.
- **P2.2 — fp8 / FlashAttention** for attention blocks.
- **P2.3 — LoRA management** for SDXL + FLUX.
- **P2.4 — History/search, export, settings UI.**
- **P2.5 — Quality A/B:** nunchaku fp4 vs int4 vs a GGUF fallback.

---

## Done — M0 (GPU bring-up)

Stack: torch 2.11+cu128 (cap 12,0) · diffusers 0.38 · transformers <5 ·
bitsandbytes · llama.cpp CUDA-13.3 · nunchaku 1.3 (fp4).

| Model | Speed | VRAM |
|-------|-------|------|
| SDXL (NoobAI) | ~5.6 s / 1024² | 11 GB |
| FLUX (Nunchaku fp4) | ~18.7 s / 1024² | 9.8 GB |
| gpt-oss-20B (llama-server) | streaming | 12.5 GB |

All validated end-to-end through the worker (arbiter → backend → gallery) with
`IMGFAB_STUB_MODE=false`. Known issue addressed by this roadmap: the nunchaku
path's encoder loading is RAM-wasteful (P0.1).
