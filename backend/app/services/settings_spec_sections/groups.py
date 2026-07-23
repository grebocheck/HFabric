"""UI metadata for settings sections."""

GROUPS: tuple[dict[str, str], ...] = (
    {
        "id": "runtime",
        "label": "Runtime mode",
        "description": "Global execution mode and startup-level behavior.",
    },
    {
        "id": "paths",
        "label": "Model and binary paths",
        "description": "Local model folders and llama.cpp executable locations.",
    },
    {
        "id": "llm",
        "label": "LLM runtime",
        "description": ("llama.cpp launch defaults for chat, code, embeddings, and multimodal tools."),
    },
    {
        "id": "image_defaults",
        "label": "Image defaults",
        "description": "Composer defaults used when creating new image jobs.",
    },
    {
        "id": "family_defaults",
        "label": "Image model families",
        "description": ("Family-specific defaults for FLUX.2, Qwen-Image, and Z-Image."),
    },
    {
        "id": "acceleration",
        "label": "Acceleration",
        "description": ("Attention, compile, cache, cleanup, and LoRA runtime tuning."),
    },
    {
        "id": "memory",
        "label": "Memory policy",
        "description": ("RAM guards, keep-warm behavior, and learned profile margins."),
    },
    {
        "id": "tools",
        "label": "Speech, RAG, attachments",
        "description": "CPU/GPU placement and upload limits for local tools.",
    },
    {
        "id": "voice",
        "label": "Voice defaults",
        "description": ("Defaults used by the native voice engine before per-session changes."),
    },
    {
        "id": "sources",
        "label": "Advanced model sources",
        "description": ("Repo IDs and base folders used by specialized image pipelines."),
    },
)

__all__ = ["GROUPS"]
