"""Advanced model-source setting specifications."""

from .schema import choice, choices, integer, path, text

_SOURCES = "sources"

SOURCE_SPECS = (
    path("anima_support_dir", "Anima support dir", _SOURCES, restart_required=True),
    path("anima_text_encoder_path", "Anima text encoder", _SOURCES, restart_required=True),
    path("anima_qwen_config_dir", "Anima Qwen config", _SOURCES, restart_required=True),
    path("anima_t5_tokenizer_dir", "Anima T5 tokenizer", _SOURCES, restart_required=True),
    path("anima_vae_dir", "Anima VAE dir", _SOURCES, restart_required=True),
    text("flux_config_repo", "FLUX config repo", _SOURCES, restart_required=True),
    text("flux_t5_nunchaku", "FLUX T5 nunchaku", _SOURCES, restart_required=True),
    path("flux2_nunchaku_dir", "FLUX.2 nunchaku dir", _SOURCES, restart_required=True),
    path("flux2_nunchaku_base_dir", "FLUX.2 base dir", _SOURCES, restart_required=True),
    text("flux2_klein_repo", "FLUX.2 klein repo", _SOURCES, restart_required=True),
    path("qwen_image_base_repo", "Qwen base repo", _SOURCES, restart_required=True),
    integer(
        "qwen_image_nunchaku_blocks_on_gpu",
        "Qwen blocks on GPU",
        _SOURCES,
        minimum=1,
        maximum=60,
        step=1,
    ),
    choice(
        "qwen_image_nunchaku_text_encoder_quant",
        "Qwen text encoder quant",
        _SOURCES,
        choices(("bnb-nf4", "bnb-fp4", "none")),
    ),
    path("z_image_base_repo", "Z-Image base repo", _SOURCES, restart_required=True),
    choice("z_image_nunchaku_offload", "Z-Image nunchaku offload", _SOURCES, choices(("model", "none"))),
    text("upscaler_model_id", "Upscaler model id", _SOURCES, restart_required=True),
    text("upscaler_model_name", "Upscaler model name", _SOURCES, restart_required=True),
    path("upscaler_model_path", "Upscaler weights", _SOURCES, restart_required=True),
)

__all__ = ["SOURCE_SPECS"]
