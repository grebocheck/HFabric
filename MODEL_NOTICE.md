# Model Notice

HFabric is licensed as open-source application code under the MIT License.

This repository does not include, redistribute, sublicense, or grant rights to
any AI model weights, LoRA adapters, checkpoints, GGUF files, tokenizers,
datasets, voices, or third-party model repositories.

Model files are user-supplied runtime inputs. The application can discover and
load compatible local files from folders such as `models/image`, `models/lora`,
`models/llm`, `models/tts`, `models/transcribe`, `models/embed`, `models/vision`,
and `models/voice`, but those files are not part of this software distribution.

Using a model with HFabric does not change the license of HFabric, and the MIT
License for HFabric does not change or override the license, terms of use,
acceptable-use policy, export controls, or other restrictions that apply to any
third-party model, dataset, voice, tokenizer, or generated asset.

Before downloading, storing, running, fine-tuning, sharing, or publishing outputs
from a model, users are responsible for reviewing and complying with that
model's own license and terms from its provider.

Anima-specific note:

- Anima checkpoints and derivatives use CircleStone Labs' non-commercial model
  license. The upstream model card separately permits commercial use of generated
  outputs. Review the current terms at `https://huggingface.co/circlestone-labs/Anima`
  before using, modifying, or distributing the weights.
- The companion Qwen3 encoder, T5 tokenizer, and Qwen-Image VAE downloaded by
  `scripts/fetch_anima_support.py` remain governed by their respective upstream
  licenses and are not redistributed by HFabric.

Native voice engine (P6R):

- RVC synthesizer interface code is vendored from
  `RVC-Project/Retrieval-based-Voice-Conversion-WebUI` (MIT License) and trimmed
  to inference-only modules under `backend/app/services/voice_engine/rvc/`.
- ContentVec (`content_vec_500.onnx` / fp16 variant) and RMVPE (`rmvpe.pt`) are
  user-supplied local runtime assets discovered from `models/voice/pretrain` or
  a local w-okada install fallback. They are not redistributed by HFabric.
- Optional DTLN denoise weights (`dtln_model_1.onnx`, `dtln_model_2.onnx`) are
  user-supplied local runtime assets from `breizhn/DTLN` (MIT License),
  discovered from `models/voice/pretrain/denoise`. They are not redistributed by
  HFabric.
- RVC voice checkpoints and faiss indexes under `models/voice` or
  `MMVCServerSIO/model_dir` are user-supplied voice/model assets and remain
  governed by their own licenses and consent terms.
