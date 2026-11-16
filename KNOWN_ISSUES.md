# Known issues and validated limits

HFabric is beta software. This file lists current, reproducible limitations;
completed engineering work and the remaining validation matrix live in
[ROADMAP.md](ROADMAP.md). If you find behavior not listed here, please
[open an issue](https://github.com/grebocheck/HFabric/issues/new/choose).

## Platform validation

- NVIDIA CUDA on Windows 11 is the only path previously validated end-to-end
  (RTX 5070 Ti, 16 GB VRAM, 32 GB RAM). Lifecycle, dependency and security code
  has changed since that run, so the release candidate still requires a repeat
  of the recorded [GPU smoke matrix](docs/gpu-smoke.md).
- AMD ROCm on Linux and Apple Silicon MPS have reproducible, hashed dependency
  profiles and fake-hardware control-flow tests, but no real-hardware sign-off.
  They remain experimental until a clean install and full smoke run are recorded.
- Non-Blackwell NVIDIA tiers are capability-gated but have not been validated on
  representative 8 GB and 12 GB cards.

## Model and hardware constraints

- FLUX.2 [klein] defaults to 768×768 on the 16 GB reference GPU. Full FLUX.2
  [dev] and image-GGUF are not supported.
- FLUX.2 Nunchaku on Blackwell should use the fp4 path. `torch.compile` can be
  rejected by the Nunchaku transformer; HFabric rolls back to the uncompiled
  pipeline and reports the fallback.
- Qwen-Image full bf16 is a very large download; the quantized profile is the
  practical default. Z-Image-Turbo expects guidance `0.0`.
- LTX-Video, Wan and FramePack fast paths require NVIDIA CUDA. ROCm/MPS expose
  only their conservative fallback policy until real-hardware validation.
- Video generation is compute-heavy and produces silent MP4. Large jobs may be
  refused before load when their RAM/VRAM estimate exceeds the configured guard.
- Realtime RVC normally needs CUDA. CPU remains suitable for offline conversion
  and only the smallest realtime configuration may keep pace.

## Runtime behavior by design

- Exactly one incompatible heavy GPU resident is allowed. Switching between LLM,
  image and video models therefore includes a visible unload/load pause.
- A predicted unsafe model load is rejected rather than spilling into swap or
  risking an out-of-memory crash.
- HFabric is a single-user local application. Non-loopback startup without an API
  token fails closed unless the operator explicitly enables the insecure-LAN
  escape hatch; that escape hatch is not suitable for an untrusted network.

## GPU dependency audit

The GPU graph retains the PyTorch/Nunchaku/Diffusers combination used by the
current loaders. The 2026-11-16 audit reported 12 findings in transformers
4.57.6 and setuptools 81.0.0. These remain unresolved; removing the automatic
GPU audit gate does not fix them. GPU audit is now a manual profile-upgrade
check alongside the [hardware smoke matrix](docs/gpu-smoke.md).

CI audits the foundation and development graphs and reproduces every platform
lock. Run the standard scanner for any accelerator lock when reviewing an
upgrade; no application-specific allowlist changes its result:

```powershell
python -m pip_audit -r backend/requirements-gpu.lock --no-deps --disable-pip
```
