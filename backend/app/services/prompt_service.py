"""Helpers for the LLM->image workflow: turn a short idea into a rich image
prompt. The system template is intentionally diffusion-oriented (tags, quality
boosters, no chit-chat) so output drops straight into an image job."""

from __future__ import annotations

SYSTEM_TEMPLATE = (
    "You are a prompt engineer for text-to-image diffusion models. "
    "Expand the user's idea into ONE vivid, richly detailed image prompt. "
    "Use concrete visual nouns, composition, lighting, style and quality terms. "
    "Output ONLY the prompt text — no preamble, no quotes, no explanation."
)


def build_expansion_params(
    idea: str,
    *,
    style: str | None = None,
    temperature: float = 0.8,
    max_tokens: int = 300,
) -> dict:
    user = idea.strip()
    if style:
        user = f"{user}\n\nPreferred style: {style}"
    return {
        "system": SYSTEM_TEMPLATE,
        "prompt": user,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
