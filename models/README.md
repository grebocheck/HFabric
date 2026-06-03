# Models

Model weights are **not** tracked in git (they are huge). Drop your files here:

```
models/
├─ image/   *.safetensors   (FLUX, SDXL, … checkpoints)
└─ llm/     *.gguf          (llama.cpp GGUF models)
```

The backend scans these folders on startup (reading only the safetensors
*header*, so it is instant) and classifies each file automatically:

| Folder | Extensions | Detected families |
|--------|-----------|-------------------|
| `image/` | `.safetensors` | `flux`, `sdxl` |
| `llm/`   | `.gguf` | `gguf` (llama.cpp) |

Override the locations with `IMGFAB_IMAGE_MODELS_DIR` / `IMGFAB_LLM_MODELS_DIR`
if you keep weights elsewhere (e.g. a different drive).
