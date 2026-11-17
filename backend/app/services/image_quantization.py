"""Per-job precision for image loaders that can quantize original weights."""

from dataclasses import replace

from ..backends.base import ModelDescriptor
from ..core.enums import ModelFamily

_FAMILIES = frozenset({
    ModelFamily.FLUX2,
    ModelFamily.QWEN_IMAGE,
    ModelFamily.QWEN_IMAGE_EDIT,
    ModelFamily.Z_IMAGE,
    ModelFamily.FLUX_KONTEXT,
})


def image_quant_options(desc: ModelDescriptor) -> tuple[str, ...]:
    # Nunchaku files contain prequantized weights. Loading them at another
    # precision requires a different checkpoint, not a runtime toggle.
    if desc.family not in _FAMILIES or str(desc.quant or "").startswith("nunchaku"):
        return ()
    return ("none", "bnb-nf4", "bnb-fp4")


def image_quant_descriptor(desc: ModelDescriptor, quant: str) -> ModelDescriptor:
    if quant not in image_quant_options(desc):
        raise ValueError(f"Image precision {quant!r} is not supported by {desc.name}")
    return replace(desc, quant=quant)


def default_image_quant(desc: ModelDescriptor) -> str:
    quant = (desc.quant or "none").lower().strip()
    return "none" if quant in ("", "bf16") else quant
