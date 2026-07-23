"""Speech, RAG, attachment, and voice setting specifications."""

from .schema import choice, choices, integer, number

_TOOLS = "tools"
_VOICE = "voice"

TOOL_SPECS = (
    integer("tts_gpu_layers", "TTS GPU layers", _TOOLS, minimum=0, maximum=999, step=1),
    integer("tts_timeout_seconds", "TTS timeout seconds", _TOOLS, minimum=30, maximum=7200, step=30),
    choice("transcription_device", "Transcription device", _TOOLS, choices(("cpu", "cuda", "auto"))),
    choice(
        "transcription_compute_type",
        "Transcription compute",
        _TOOLS,
        choices(("int8", "int8_float16", "float16", "float32")),
    ),
    integer(
        "transcription_timeout_seconds",
        "Transcription timeout seconds",
        _TOOLS,
        minimum=60,
        maximum=7200,
        step=60,
    ),
    integer(
        "transcription_max_upload_mb",
        "Transcription upload MB",
        _TOOLS,
        minimum=1,
        maximum=4096,
        step=1,
    ),
    integer("embed_gpu_layers", "Embedding GPU layers", _TOOLS, minimum=0, maximum=999, step=1),
    integer(
        "embed_timeout_seconds",
        "Embedding timeout seconds",
        _TOOLS,
        minimum=10,
        maximum=1800,
        step=10,
    ),
    integer("rag_chunk_chars", "RAG chunk chars", _TOOLS, minimum=200, maximum=8000, step=50),
    integer("rag_chunk_overlap", "RAG chunk overlap", _TOOLS, minimum=0, maximum=2000, step=10),
    integer("chat_upload_max_mb", "Chat upload MB", _TOOLS, minimum=1, maximum=1024, step=1),
    choice("voice_device", "Voice device", _VOICE, choices(("cuda", "cpu"))),
    integer(
        "voice_timeout_seconds",
        "Voice timeout seconds",
        _VOICE,
        minimum=60,
        maximum=7200,
        step=60,
    ),
    integer("voice_max_upload_mb", "Voice upload MB", _VOICE, minimum=1, maximum=1024, step=1),
    integer("voice_pitch", "Pitch", _VOICE, minimum=-24, maximum=24, step=1),
    integer("voice_speaker_id", "Speaker ID", _VOICE, minimum=0, maximum=255, step=1),
    number("voice_index_ratio", "Index ratio", _VOICE, minimum=0, maximum=1, step=0.01),
    number("voice_protect", "Protect", _VOICE, minimum=0, maximum=1, step=0.01),
    number("voice_noise_scale", "Noise scale", _VOICE, minimum=0, maximum=1, step=0.01),
    number("voice_f0_smoothing", "F0 smoothing", _VOICE, minimum=0, maximum=1, step=0.01),
    choice(
        "voice_f0_detector",
        "F0 detector",
        _VOICE,
        choices(("fcpe", "rmvpe", "crepe_tiny", "crepe_full")),
    ),
    integer(
        "voice_input_highpass_hz",
        "Input high-pass Hz",
        _VOICE,
        minimum=0,
        maximum=300,
        step=5,
    ),
    number("voice_input_gate_db", "Input gate dB", _VOICE, minimum=-90, maximum=-20, step=1),
    number("voice_input_formant", "Input formant", _VOICE, minimum=-2, maximum=2, step=0.1),
    choice("voice_input_denoise", "Input denoise", _VOICE, choices(("off", "dtln"))),
    number("voice_input_denoise_mix", "Input denoise mix", _VOICE, minimum=0, maximum=1, step=0.01),
)

__all__ = ["TOOL_SPECS"]
