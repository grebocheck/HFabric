"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .core.enums import JobStatus, JobType, ModelFamily


# --------------------------------------------------------------------- models
class ModelOut(BaseModel):
    id: str
    name: str
    family: ModelFamily
    job_type: JobType
    size_bytes: int
    loaded: bool
    warm: bool = False
    quant: str | None = None
    multimodal: bool = False
    mmproj_path: str | None = None
    mmproj_size_bytes: int = 0
    estimated_vram_gb: float | None = None
    # True when estimated_vram_gb comes from a real measurement, not the
    # static heuristic — the UI labels it "measured".
    vram_measured: bool = False
    # True for models that are slow / memory-heavy on 16 GB (raw fp8 FLUX) so the
    # UI can warn before a click triggers a long, VRAM-overflowing run.
    slow: bool = False
    available: bool = True
    runtime_mode: str = "real"
    unavailable_reason: str | None = None
    compatibility_warnings: list[str] = Field(default_factory=list)
    # Hardware-fit hint from the capability profile's model_policy:
    # "recommended" | "advanced" | "hidden" | "neutral".
    recommendation: str = "neutral"


class ModelProfileOut(BaseModel):
    model_id: str
    model: str
    family: str
    quant: str | None = None
    ram_gb: float | None = None
    vram_gb: float | None = None
    samples: int
    updated_at: datetime


class GpuStatusOut(BaseModel):
    resident: str | None = None
    model_id: str | None = None
    model: str | None = None
    family: str | None = None
    warm: list[dict[str, str]] = Field(default_factory=list)
    # Active non-arbiter GPU consumers (voice / TTS / transcribe): [{id, label}].
    lanes: list[dict[str, str]] = Field(default_factory=list)
    # Optional resident pin, e.g. the LLM API server keeping a model in VRAM.
    pin: dict[str, str] | None = None


class LoraOut(BaseModel):
    id: str
    name: str
    family: ModelFamily | None = None
    size_bytes: int


# ----------------------------------------------------------------------- jobs
class ImageLoraIn(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    weight: float = Field(default=1.0, ge=-2.0, le=2.0)

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class ImageParamsIn(BaseModel):
    """Validated public image-generation parameters.

    Extra fields are preserved for forward compatibility and for internal chat
    correlation metadata, while every value that can materially affect image
    resource use is bounded here before the worker acquires a model.
    """

    prompt: str = Field(default="", max_length=20_000)
    negative: str | None = Field(default=None, max_length=20_000)
    steps: int | None = Field(default=None, ge=1, le=150)
    guidance: float | None = Field(default=None, ge=0.0, le=30.0)
    # The public grid is 16 px. Qwen's native 1328 px resolution lives on this
    # grid, while stricter runtimes (currently Anima) snap to their own grid.
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=16)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=16)
    seed: int | None = Field(default=None, ge=-1, le=2**31 - 1)
    batch_size: int | None = Field(default=None, ge=1, le=16)
    loras: list[ImageLoraIn | str] | None = Field(default=None, max_length=8)
    init_image: str | None = Field(default=None, min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")
    mask_image: str | None = Field(default=None, min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")
    control_image: str | None = Field(default=None, min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")
    edit_mode: Literal["img2img", "inpaint", "outpaint", "instruction", "controlnet"] | None = None
    resize_mode: Literal["crop", "pad", "stretch"] | None = None
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    mask_blur: float | None = Field(default=None, ge=0.0, le=128.0)
    mask_grow: int | None = Field(default=None, ge=-128, le=128)
    mask_invert: bool | None = None
    padding_mask_crop: int | None = Field(default=None, ge=0, le=512)
    outpaint_left: int | None = Field(default=None, ge=0, le=1024)
    outpaint_right: int | None = Field(default=None, ge=0, le=1024)
    outpaint_top: int | None = Field(default=None, ge=0, le=1024)
    outpaint_bottom: int | None = Field(default=None, ge=0, le=1024)
    control_type: (
        Literal[
            "canny",
            "depth",
            "pose",
            "scribble",
            "union-canny",
            "union-depth",
            "union-pose",
            "union-scribble",
        ]
        | None
    ) = None
    control_scale: float | None = Field(default=None, ge=0.0, le=2.0)
    turbo: bool | None = None
    assistant_message_id: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)


def validate_image_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate known image fields and retain compatible extension metadata."""

    parsed = ImageParamsIn.model_validate(params)
    return parsed.model_dump(exclude_none=True, exclude_unset=True)


class JobCreate(BaseModel):
    type: JobType
    model_id: str = Field(min_length=1, max_length=512)
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)

    @model_validator(mode="after")
    def validate_typed_params(self) -> JobCreate:
        if self.type is JobType.IMAGE:
            self.params = validate_image_params(self.params)
            if not str(self.params.get("prompt") or "").strip():
                raise ValueError("params.prompt must not be empty for image jobs")
        return self


class JobOut(BaseModel):
    id: str
    type: JobType
    status: JobStatus
    priority: int
    model_id: str
    params: dict[str, Any]
    progress: float
    result: dict[str, Any] | None = None
    error: str | None = None
    request_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("params", mode="before")
    @classmethod
    def hide_internal_params(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items() if not str(key).startswith("_")}


class PriorityUpdate(BaseModel):
    priority: int


# --------------------------------------------------------------------- images
class ImageOut(BaseModel):
    id: str
    job_id: str | None
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    family: str | None = None
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    params: dict[str, Any]
    created_at: datetime
    url: str
    thumb_url: str | None = None

    model_config = {"from_attributes": True}


class ImageUpdateIn(BaseModel):
    favorite: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=32)


class ImageExportIn(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=500)


# --------------------------------------------------------------------- videos
class VideoOut(BaseModel):
    id: str
    job_id: str | None
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    fps: float | None = None
    duration_s: float | None = None
    family: str | None = None
    params: dict[str, Any]
    created_at: datetime
    url: str
    poster_url: str | None = None
    thumb_url: str | None = None

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------------- chat
class ChatAttachmentIn(BaseModel):
    token: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")


class ChatAttachmentOut(BaseModel):
    token: str
    filename: str
    content_type: str
    kind: str
    size_bytes: int
    url: str | None = None
    extracted_chars: int | None = None
    included_chars: int | None = None
    truncated: bool = False
    notice: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)
    error: bool = False
    job_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    title: str
    model_id: str | None = None
    system: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str | None = None
    model_id: str | None = None
    system: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ConversationUpdate(BaseModel):
    title: str | None = None
    model_id: str | None = None
    system: str | None = None
    params: dict[str, Any] | None = None


class MessageImport(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = ""
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)
    error: bool = False
    created_at: datetime | None = None


class ConversationImport(BaseModel):
    title: str | None = None
    model_id: str | None = None
    system: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[MessageImport] = Field(default_factory=list)


class ChatImportIn(BaseModel):
    conversations: list[ConversationImport] = Field(default_factory=list)


class ChatImportOut(BaseModel):
    imported: int
    conversations: list[ConversationDetailOut] = Field(default_factory=list)


class ChatSend(BaseModel):
    content: str = ""
    model_id: str
    attachments: list[ChatAttachmentIn] = Field(default_factory=list, max_length=12)
    system: str | None = None
    temperature: float = 0.8
    max_tokens: int = 4096
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None
    seed: int | None = None
    stop: list[str] | None = None
    image_tool: bool = False
    image_model_id: str | None = None
    document_tool: bool = False
    rag_top_k: int = 5


class ChatSendOut(BaseModel):
    job_id: str
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut


class ImageChatSend(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    model_id: str = Field(min_length=1, max_length=512)
    negative: str | None = Field(default=None, max_length=20_000)
    steps: int | None = Field(default=None, ge=1, le=150)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=16)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=16)
    seed: int | None = Field(default=None, ge=-1, le=2**31 - 1)


# -------------------------------------------------------------------- presets
class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: JobType
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("preset name must not be empty")
        return value

    @model_validator(mode="after")
    def validate_typed_params(self) -> PresetCreate:
        if self.type is JobType.IMAGE:
            self.params = validate_image_params(self.params)
        return self


class PresetOut(BaseModel):
    id: str
    name: str
    type: JobType
    params: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class PresetImportItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: JobType
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("preset name must not be empty")
        return value

    @model_validator(mode="after")
    def validate_typed_params(self) -> PresetImportItem:
        if self.type is JobType.IMAGE:
            self.params = validate_image_params(self.params)
        return self


class PresetImportIn(BaseModel):
    presets: list[PresetImportItem] = Field(default_factory=list, max_length=500)
    on_conflict: Literal["rename", "skip"] = "rename"


class PresetImportOut(BaseModel):
    imported: int
    skipped: int = 0
    presets: list[PresetOut] = Field(default_factory=list)


# ---------------------------------------------------------------------- notes
class NoteCreate(BaseModel):
    title: str | None = None
    content: str = ""


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class NoteOut(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------- prompt library
def _clean_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        clean = tag.strip()[:48]
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out[:24]


class PromptSnippetCreate(BaseModel):
    name: str | None = None
    body: str = ""
    negative: str | None = None
    tags: list[str] = Field(default_factory=list)


class PromptSnippetUpdate(BaseModel):
    name: str | None = None
    body: str | None = None
    negative: str | None = None
    tags: list[str] | None = None


class PromptSnippetOut(BaseModel):
    id: str
    name: str
    body: str
    negative: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptSnippetImportItem(BaseModel):
    name: str | None = None
    body: str = ""
    negative: str | None = None
    tags: list[str] = Field(default_factory=list)


class PromptSnippetImportIn(BaseModel):
    prompts: list[PromptSnippetImportItem] = Field(default_factory=list)


class PromptSnippetImportOut(BaseModel):
    imported: int
    prompts: list[PromptSnippetOut] = Field(default_factory=list)
