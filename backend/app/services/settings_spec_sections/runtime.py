"""Runtime, filesystem, and llama.cpp setting specifications."""

from ...config import CONTEXT_TYPES, LLAMA_BACKENDS
from .schema import boolean, choice, integer, path, text


def _labeled_options(
    values: dict[str, dict[str, object]],
) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(value["label"])) for key, value in values.items())


RUNTIME_SPECS = (
    boolean(
        "stub_mode",
        "Stub mode",
        "runtime",
        "Run without heavy GPU/ML backends.",
        restart_required=True,
    ),
    path("image_models_dir", "Image models", "paths", restart_required=True),
    path("lora_models_dir", "LoRA models", "paths", restart_required=True),
    path("llm_models_dir", "LLM models", "paths", restart_required=True),
    path("tts_models_dir", "TTS models", "paths", restart_required=True),
    path("transcription_models_dir", "Transcription models", "paths", restart_required=True),
    path("embed_models_dir", "Embedding models", "paths", restart_required=True),
    path("vision_models_dir", "Vision models", "paths", restart_required=True),
    path("voice_models_dir", "Voice models", "paths", restart_required=True),
    path("voice_pretrain_dir", "Voice pretrain assets", "paths", restart_required=True),
    path("llama_server_bin", "llama-server", "paths", restart_required=True),
    path("llama_server_bin_turbo", "Turbo llama-server", "paths", restart_required=True),
    path("llama_tts_bin", "llama-tts", "paths", restart_required=True),
    text("llama_host", "llama.cpp host", "llm", restart_required=True),
    integer(
        "llama_port",
        "Chat port",
        "llm",
        minimum=1,
        maximum=65535,
        step=1,
        restart_required=True,
    ),
    integer(
        "llama_embed_port",
        "Embedding port",
        "llm",
        minimum=1,
        maximum=65535,
        step=1,
        restart_required=True,
    ),
    integer(
        "llama_ngl",
        "GPU layers",
        "llm",
        minimum=0,
        maximum=999,
        step=1,
        description="999 means full offload.",
    ),
    integer("llama_ctx", "Context tokens", "llm", minimum=512, maximum=262144, step=512),
    choice("llama_backend", "Backend build", "llm", _labeled_options(LLAMA_BACKENDS)),
    choice("llama_context_type", "KV cache type", "llm", _labeled_options(CONTEXT_TYPES)),
)

__all__ = ["RUNTIME_SPECS"]
