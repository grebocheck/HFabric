"""Image composer and model-family setting specifications."""

from .schema import SettingSpec, choice, choices, integer, number, text

_IMAGE = "image_defaults"
_FAMILY = "family_defaults"


def _steps(key: str, label: str) -> SettingSpec:
    return integer(key, label, _FAMILY, minimum=1, maximum=150, step=1)


def _guidance(key: str, label: str) -> SettingSpec:
    return number(key, label, _FAMILY, minimum=0, maximum=30, step=0.1)


def _dimension(
    key: str,
    label: str,
    *,
    minimum: int = 256,
    maximum: int = 2048,
    multiple_of: int = 64,
) -> SettingSpec:
    return integer(
        key,
        label,
        _FAMILY,
        minimum=minimum,
        maximum=maximum,
        step=multiple_of,
        multiple_of=multiple_of,
    )


def _family_choice(key: str, label: str, values: tuple[str, ...]) -> SettingSpec:
    return choice(key, label, _FAMILY, choices(values))


IMAGE_SPECS = (
    integer("default_steps", "Steps", _IMAGE, minimum=1, maximum=150, step=1),
    number("default_guidance", "Guidance", _IMAGE, minimum=0, maximum=30, step=0.1),
    integer(
        "default_width",
        "Width",
        _IMAGE,
        minimum=256,
        maximum=2048,
        step=64,
        multiple_of=64,
    ),
    integer(
        "default_height",
        "Height",
        _IMAGE,
        minimum=256,
        maximum=2048,
        step=64,
        multiple_of=64,
    ),
    number("img2img_default_strength", "img2img strength", _IMAGE, minimum=0, maximum=1, step=0.01),
    number(
        "qwen_image_img2img_strength",
        "Qwen edit strength",
        _IMAGE,
        minimum=0.05,
        maximum=1,
        step=0.01,
    ),
    number(
        "z_image_img2img_strength",
        "Z-Image edit strength",
        _IMAGE,
        minimum=0.05,
        maximum=1,
        step=0.01,
    ),
    number(
        "anima_img2img_strength",
        "Anima edit strength",
        _IMAGE,
        minimum=0.05,
        maximum=1,
        step=0.01,
    ),
    integer(
        "img2img_min_effective_steps",
        "Minimum edit steps",
        _IMAGE,
        minimum=1,
        maximum=20,
        step=1,
    ),
    choice("image_edit_resize_mode", "Edit resize mode", _IMAGE, choices(("crop", "pad", "stretch"))),
    integer(
        "inpaint_padding_mask_crop",
        "Inpaint crop padding",
        _IMAGE,
        minimum=0,
        maximum=512,
        step=8,
    ),
    number("inpaint_mask_blur", "Mask blur", _IMAGE, minimum=0, maximum=128, step=1),
    integer("inpaint_mask_grow", "Mask grow", _IMAGE, minimum=-128, maximum=128, step=1),
    integer("image_upload_max_mb", "Image upload MB", _IMAGE, minimum=1, maximum=2048, step=1),
    text(
        "sdxl_controlnet_canny_repo",
        "SDXL ControlNet canny",
        _IMAGE,
        "Local folder or Hugging Face repo id.",
        nullable=True,
        restart_required=True,
    ),
    number(
        "sdxl_controlnet_default_scale",
        "ControlNet scale",
        _IMAGE,
        minimum=0,
        maximum=2,
        step=0.05,
    ),
    text(
        "sdxl_controlnet_depth_repo",
        "SDXL ControlNet depth",
        _IMAGE,
        nullable=True,
        restart_required=True,
    ),
    text(
        "sdxl_controlnet_pose_repo",
        "SDXL ControlNet pose",
        _IMAGE,
        nullable=True,
        restart_required=True,
    ),
    text(
        "sdxl_controlnet_scribble_repo",
        "SDXL ControlNet scribble",
        _IMAGE,
        nullable=True,
        restart_required=True,
    ),
    text(
        "sdxl_controlnet_union_repo",
        "SDXL ControlNet Union",
        _IMAGE,
        nullable=True,
        restart_required=True,
    ),
    _steps("anima_default_steps", "Anima steps"),
    _guidance("anima_default_guidance", "Anima guidance"),
    _dimension("anima_default_width", "Anima width", minimum=512, maximum=1536),
    _dimension("anima_default_height", "Anima height", minimum=512, maximum=1536),
    _family_choice("flux2_quant", "FLUX.2 quant", ("bnb-nf4", "bnb-fp4", "none")),
    _family_choice("flux2_offload", "FLUX.2 offload", ("model", "sequential", "none")),
    _steps("flux2_default_steps", "FLUX.2 steps"),
    _guidance("flux2_default_guidance", "FLUX.2 guidance"),
    _dimension("flux2_default_width", "FLUX.2 width"),
    _dimension("flux2_default_height", "FLUX.2 height"),
    _family_choice("qwen_image_quant", "Qwen quant", ("bnb-nf4", "bnb-fp4", "none")),
    _family_choice("qwen_image_offload", "Qwen offload", ("model", "sequential", "none")),
    _steps("qwen_image_default_steps", "Qwen steps"),
    _guidance("qwen_image_default_guidance", "Qwen guidance"),
    _dimension("qwen_image_default_width", "Qwen width", multiple_of=16),
    _dimension("qwen_image_default_height", "Qwen height", multiple_of=16),
    _family_choice("qwen_image_edit_quant", "Qwen Edit quant", ("bnb-nf4", "bnb-fp4", "none")),
    _family_choice("qwen_image_edit_offload", "Qwen Edit offload", ("model", "sequential", "none")),
    _steps("qwen_image_edit_default_steps", "Qwen Edit steps"),
    _guidance("qwen_image_edit_default_guidance", "Qwen Edit guidance"),
    _family_choice("flux_kontext_quant", "FLUX Kontext quant", ("bnb-nf4", "bnb-fp4", "none")),
    _family_choice("flux_kontext_offload", "FLUX Kontext offload", ("model", "sequential", "none")),
    _steps("flux_kontext_default_steps", "FLUX Kontext steps"),
    _guidance("flux_kontext_default_guidance", "FLUX Kontext guidance"),
    _family_choice("z_image_quant", "Z-Image quant", ("bnb-nf4", "bnb-fp4", "none")),
    _family_choice("z_image_offload", "Z-Image offload", ("model", "sequential", "none")),
    _steps("z_image_default_steps", "Z-Image Turbo steps"),
    _guidance("z_image_default_guidance", "Z-Image Turbo guidance"),
    _steps("z_image_base_default_steps", "Z-Image base steps"),
    _guidance("z_image_base_default_guidance", "Z-Image base guidance"),
    _dimension("z_image_default_width", "Z-Image width"),
    _dimension("z_image_default_height", "Z-Image height"),
)

__all__ = ["IMAGE_SPECS"]
