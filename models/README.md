# Models

Model weights are **not** tracked in git because they are huge. By default, keep
every local model file, model repo, and LoRA under this `models/` folder so the
app has one predictable place to scan and validate.

These model files are not part of HFabric's MIT-licensed application code.
Every model, LoRA, tokenizer, dataset, voice, and checkpoint keeps its own
license and provider terms. See [`../MODEL_NOTICE.md`](../MODEL_NOTICE.md).

```text
models/
|- image/   *.safetensors or model folders (FLUX, FLUX.2, Qwen, Z-Image, SDXL)
|- lora/    *.safetensors/.pt/.bin        (SDXL/FLUX LoRA adapters, SDXL turbo)
|- llm/     *.gguf                        (llama.cpp GGUF models)
|- tts/     *.gguf                        (llama-tts voice/acoustic models)
|- transcribe/ Whisper model folders/.pt  (local transcription models)
|- embed/   *.gguf embedding models       (RAG workspace)
|- vision/  *.gguf + mmproj GGUF          (chat-native multimodal LLMs)
`- voice/   RVC slots + pretrain assets   (native voice engine)
```

The backend scans these folders on startup:

| Folder | Extensions / marker | Detected families |
|--------|---------------------|-------------------|
| `image/` | `.safetensors` | `flux`, `sdxl` |
| `image/<repo>/` | `model_index.json` | `flux2`, `qwen-image`, `z-image` |
| `lora/` | `.safetensors`, `.pt`, `.bin` | `flux`, `sdxl`, or unknown |
| `llm/` | `.gguf` | `gguf` (llama.cpp) |
| `tts/` | `.gguf` | TTS models for `llama-tts` |
| `transcribe/` | local faster-whisper folders or `.pt`/`.pth` | Whisper transcription models |
| `embed/` | `.gguf` | RAG embedding models for llama.cpp `--embeddings` |
| `vision/` | model `.gguf` + `mmproj*.gguf` | Multimodal LLMs for chat-native `llama-server --mmproj` |
| `voice/` | RVC checkpoint slots, `pretrain/*.onnx`, `pretrain/*.pt`, optional `pretrain/denoise/*.onnx` | Native RVC voice conversion |

For a first REAL-mode run, prefer the profile-aware starter downloader instead
of hand-picking CUDA-only models:

```powershell
python scripts/fetch_models.py --dry-run
python scripts/fetch_models.py --profile apple-mps --dry-run
python scripts/fetch_models.py
```

It downloads SDXL Lightning 4-step into `models/image/` for CUDA, ROCm, and
Apple Silicon MPS, plus starter GGUFs for chat/RAG/TTS/vision. CUDA profiles
also get the Nunchaku FLUX fp4 checkpoint when the `nunchaku_cuda` feature is
available. The `--dry-run --profile ...` form is planner-only, so it can show
an AMD/MPS plan from another machine without installing or downloading anything.

The in-app **Models** tab also exposes larger whole-repo image downloads under
**Advanced**. These are not part of the starter set because they are large and
may have provider-specific terms, but the downloader can place them directly:
`FLUX.2-klein-9b/`, `z-image-turbo/`, and `qwen-image-2512/`.

FLUX.2 klein is a multi-file diffusers repo, not a single `.safetensors`; put the
downloaded folder under `models/image/`, for example:

```powershell
huggingface-cli download black-forest-labs/FLUX.2-klein-9B --local-dir models/image/flux2-klein-9b
```

The working local FLUX.2 klein runtime layout is:

```text
models/image/flux2-klein-9b/
|- model_index.json
|- scheduler/
|- text_encoder/
|- tokenizer/
|- transformer/
`- vae/
```

If you also keep an original-format `flux-2-klein-9b.safetensors` transformer in
`models/image/`, HFabric treats the repo folder as the runtime model and the
single file as a conversion/source artifact.

The experimental FLUX.2 nunchaku fast path uses a separate local folder:

```text
models/image/flux2-klein-9b-nunchaku/
|- svdq-fp4_r32-FLUX.2-klein-9B-Nunchaku.safetensors
|- transformer_flux2.py
`- torch_transfer_utils.py
```

Those sidecar Python files are loaded dynamically from the model folder; they are
not copied into `.venv`. The nunchaku transformer is used with the existing
`models/image/flux2-klein-9b/` diffusers repo and a bitsandbytes 4-bit Qwen3
text encoder.

On Blackwell GPUs, FLUX.2 nunchaku int4 is kept as a local file if downloaded
but is hidden from the runtime model list because nunchaku requires fp4 for this
GPU family.

Qwen-Image-2512 and Z-Image-Turbo are also multi-file Diffusers repos. Put them
under `models/image/` so HFabric can auto-detect their `model_index.json`:

```powershell
huggingface-cli download Qwen/Qwen-Image-2512 --local-dir models/image/qwen-image-2512
huggingface-cli download Tongyi-MAI/Z-Image-Turbo --local-dir models/image/z-image-turbo --exclude "assets/*"
```

Or run `python scripts/fetch_qwen_z_image.py` from the repository root to fetch
both public repos.

### Voice changer pretrain assets

Voice models you drop into `models/voice/` (RVC `.pth` files) all share a
**ContentVec** encoder and, for the quality pitch path, **RMVPE**. Windows
`setup.bat` / `run.bat` fetch these required shared assets automatically for REAL
mode; this script is the same fallback action the Voice tab uses:

```powershell
python scripts/fetch_voice_assets.py
```

```text
models/voice/pretrain/
|- vec-768-layer-12.onnx  (required ContentVec, ~360 MB)
`- rmvpe.pt               (RMVPE pitch path, ~181 MB)
```

The in-app **Voice** tab also has a one-click **"Download voice assets"** button
when they're missing. These assets are not committed to the repository; setup
downloads them from upstream into the user's local `models/` directory and they
keep their upstream licenses.

Optional DTLN neural input denoise weights are stored as:

```text
models/voice/pretrain/denoise/
|- dtln_model_1.onnx
`- dtln_model_2.onnx
```

Fetch them explicitly with:

```powershell
python scripts/fetch_dtln.py
```

The DTLN weights are from `breizhn/DTLN` and keep their upstream MIT license.

Qwen-Image-2512 defaults to the backend's bitsandbytes 4-bit path
(`HFAB_QWEN_IMAGE_QUANT=bnb-nf4`) because the bf16 repo is large. Z-Image-Turbo
defaults to 1024x1024, 9 steps, and guidance 0.0.

Environment variables like `HFAB_IMAGE_MODELS_DIR`, `HFAB_LORA_MODELS_DIR`,
`HFAB_LLM_MODELS_DIR`, and `HFAB_TTS_MODELS_DIR` exist for development, but
the project default is to keep model storage inside `models/`.

TTS output WAV files and their JSON sidecars are runtime artifacts, so they are
written under `data/outputs/<date>/`, not under `models/`.
