"""Named response contracts shared by the REST routers.

The API used to expose many ``dict[str, Any]`` responses.  FastAPI represents
those as anonymous ``object`` schemas, which makes generated clients fall back
to ``Record<string, unknown>``.  These models keep every public 2xx JSON
response named while deliberately allowing forward-compatible extra fields for
hardware probes and third-party catalog payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schemas import GpuStatusOut


class ApiContract(BaseModel):
    """Forward-compatible base for payloads that evolve with local runtimes."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ValidationIssueOut(ApiContract):
    loc: list[str | int] = Field(default_factory=list)
    msg: str
    type: str


class ErrorOut(ApiContract):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None
    # Kept during the compatibility window for existing local clients that
    # still read FastAPI's historical ``detail`` field.
    detail: str | list[ValidationIssueOut] | dict[str, Any] | None = None
    gpu: GpuStatusOut | None = None


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorOut, "description": description}
    for status, description in {
        400: "Invalid request",
        401: "Authentication required",
        403: "Operation forbidden",
        404: "Resource not found",
        409: "Resource or runtime conflict",
        413: "Payload too large",
        415: "Unsupported media type",
        422: "Request validation failed",
        500: "Internal server error",
        502: "Upstream service error",
        503: "Service unavailable",
        504: "Operation timed out",
    }.items()
}


def binary_response(media_type: str, description: str) -> dict[int, dict[str, Any]]:
    """OpenAPI response metadata for a streamed/downloaded file."""

    return {
        200: {
            "description": description,
            "content": {
                media_type: {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        }
    }


# ------------------------------------------------------------------ primitives
class DeleteOut(ApiContract):
    deleted: bool | str


class RemovedOut(ApiContract):
    removed: int


class StoppedOut(ApiContract):
    stopped: bool


class RevealOut(ApiContract):
    revealed: str


# --------------------------------------------------------------------- health
class RamStatusOut(ApiContract):
    total_gb: float
    available_gb: float
    used_gb: float
    percent: float
    process_rss_gb: float


class VramStatusOut(ApiContract):
    total_gb: float
    free_gb: float
    used_gb: float


class MemoryStatusOut(ApiContract):
    ram: RamStatusOut | None = None
    vram: VramStatusOut | None = None


class SecurityPostureOut(ApiContract):
    exposed: bool
    token_required: bool


class HealthOut(ApiContract):
    status: str
    version: str
    stub_mode: bool
    models: int
    gpu: GpuStatusOut
    mem: MemoryStatusOut
    security: SecurityPostureOut


# ----------------------------------------------------------------------- code
class CodeFileOut(ApiContract):
    path: str
    size_bytes: int


class CodeFileContentOut(CodeFileOut):
    content: str
    truncated: bool


# --------------------------------------------------------------- model catalog
class DiskStatusOut(ApiContract):
    free_mb: int | None = None
    models_root: str


class InstalledModelOut(ApiContract):
    kind: str
    kind_label: str
    name: str
    path: str
    size_bytes: int
    is_dir: bool
    in_use: bool


class InstalledModelsOut(ApiContract):
    items: list[InstalledModelOut]
    kinds: dict[str, str]
    total_used_bytes: int
    disk: DiskStatusOut


class InstalledModelDeleteOut(ApiContract):
    deleted: str
    freed_bytes: int
    disk: DiskStatusOut


class ModelRescanOut(ApiContract):
    models: int
    image_models: int
    video_models: int
    llm_models: int
    loras: int


class DeletedCountOut(ApiContract):
    deleted: int


class RuntimeSettingsOut(ApiContract):
    stub_mode: bool
    paths: dict[str, str]
    memory: dict[str, Any]
    generation_defaults: dict[str, Any]
    acceleration: dict[str, Any]
    counts: dict[str, int]
    gpu: GpuStatusOut
    mem: MemoryStatusOut
    capability: CapabilityProfileOut


class CapabilityGpuOut(ApiContract):
    vendor: str | None = None
    name: str | None = None
    vram_mb: int | None = None
    compute_capability_tuple: list[int] | None = None
    architecture: str | None = None


class CapabilityCandidateOut(ApiContract):
    id: str
    confidence: str | None = None
    reason: str | None = None
    gpu: CapabilityGpuOut | None = None
    warnings: list[str] = Field(default_factory=list)


class CapabilityProfileOut(ApiContract):
    schema_version: int
    selected_profile: str
    active_profile: str
    label: str | None = None
    backend: str
    configured_stub_mode: bool
    effective_stub_mode: bool
    confidence: str | None = None
    reason: str | None = None
    hardware_tier: str
    primary_gpu: CapabilityGpuOut | None = None
    runtime_defaults: dict[str, Any]
    features: dict[str, bool]
    disabled_features: list[str]
    model_policy: dict[str, Any]
    warnings: list[str]
    candidates: list[CapabilityCandidateOut]
    sources: dict[str, str]


class SettingsChoiceOut(ApiContract):
    value: str
    label: str


class SettingsSchemaEntryOut(ApiContract):
    key: str
    label: str
    group: str
    kind: str
    description: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    multiple_of: int | None = None
    choices: list[SettingsChoiceOut] | None = None
    nullable: bool | None = None
    restart_required: bool | None = None


class SettingsGroupOut(ApiContract):
    id: str
    label: str
    description: str


class SettingsOverridesOut(ApiContract):
    values: dict[str, str | int | float | bool | None]
    writable_keys: list[str]
    groups: list[SettingsGroupOut]
    settings_schema: list[SettingsSchemaEntryOut] = Field(alias="schema")
    path: str
    persistence_warnings: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------- image history
class NamedCountOut(ApiContract):
    count: int


class ModelCountOut(NamedCountOut):
    model: str


class FamilyCountOut(NamedCountOut):
    family: str


class LoraCountOut(NamedCountOut):
    id: str
    name: str


class TagCountOut(NamedCountOut):
    tag: str


class ImageStatsOut(ApiContract):
    total: int
    today: int
    by_model: list[ModelCountOut]
    by_family: list[FamilyCountOut]
    by_lora: list[LoraCountOut]
    by_tag: list[TagCountOut]


class ImageReconcileOut(ApiContract):
    recovered: int
    missing_originals: int
    broken_db_rows: int
    missing_thumbnails: int
    repaired_thumbnails: int
    thumbnail_failures: int
    orphan_sidecars: int
    orphan_files: int
    orphan_thumbnails: int


class ImageUploadOut(ApiContract):
    init_image: str
    url: str
    width: int
    height: int


class MaskUploadOut(ApiContract):
    mask_image: str
    url: str
    width: int
    height: int


# --------------------------------------------------------------- queue planner
class QueuePlanStepOut(ApiContract):
    model_id: str
    model: str
    type: str
    count: int


class QueuePlanOut(ApiContract):
    queued: int
    swaps: int
    current_model_id: str | None = None
    current_model: str | None = None
    steps: list[QueuePlanStepOut]


# ------------------------------------------------------------- download state
class DownloadProgressOut(ApiContract):
    done: int
    total: int


class DownloadCurrentOut(ApiContract):
    label: str
    filename: str


class DownloadFailureOut(ApiContract):
    label: str
    error: str


class DownloadStatusOut(ApiContract):
    state: str
    message: str
    current: DownloadCurrentOut | None = None
    progress: DownloadProgressOut
    failed: list[DownloadFailureOut]
    updated_at: float


class ModelDownloadItemOut(ApiContract):
    key: str
    repo: str
    filename: str
    dest: str
    label: str
    reason: str
    feature: str | None = None
    source: str
    approx_size_mb: int
    license: str
    repo_url: str
    present: bool
    recommended: bool


class DownloadStateOut(ApiContract):
    catalog: list[ModelDownloadItemOut]
    disk: DiskStatusOut
    status: DownloadStatusOut
    available: bool


class HfRepoFileOut(ApiContract):
    path: str
    size_bytes: int


class HfRepoFilesOut(ApiContract):
    repo: str
    files: list[HfRepoFileOut]


class HfSearchResultOut(ApiContract):
    id: str
    author: str | None = None
    sha: str | None = None
    downloads: int
    likes: int
    last_modified: str | None = None
    created_at: str | None = None
    pipeline_tag: str | None = None
    library_name: str | None = None
    tags: list[str]
    license: str | None = None
    gated: bool
    private: bool
    weight_count: int
    file_count: int
    weight_formats: list[str]
    suggested_kind: str | None = None
    url: str


class HfSearchOut(ApiContract):
    query: str
    sort: str
    limit: int
    filters: list[str]
    results: list[HfSearchResultOut]


# -------------------------------------------------------------------- CivitAI
class CivitaiPreviewOut(ApiContract):
    url: str
    nsfw_level: int | None = None
    width: int | None = None
    height: int | None = None
    type: str | None = None


class CivitaiVersionSummaryOut(ApiContract):
    id: int
    name: str
    base_model: str | None = None


class CivitaiSearchResultOut(ApiContract):
    id: int
    name: str
    type: str | None = None
    nsfw: bool
    creator: str | None = None
    downloads: int
    likes: int
    base_model: str | None = None
    tags: list[str]
    preview: CivitaiPreviewOut | None = None
    suggested_kind: str | None = None
    version_count: int
    versions: list[CivitaiVersionSummaryOut]
    url: str


class CivitaiSearchOut(ApiContract):
    query: str
    sort: str
    nsfw: bool
    limit: int
    page: int
    total_pages: int | None = None
    next_page: int | None = None
    results: list[CivitaiSearchResultOut]


class CivitaiFileOut(ApiContract):
    id: int
    name: str
    size_kb: float
    type: str | None = None
    format: str | None = None
    fp: str | None = None
    size: str | None = None
    primary: bool
    download_url: str | None = None
    sha256: str | None = None


class CivitaiVersionFilesOut(ApiContract):
    version_id: int
    name: str
    model_id: int
    model_name: str | None = None
    model_type: str | None = None
    base_model: str | None = None
    trained_words: list[str]
    suggested_kind: str | None = None
    files: list[CivitaiFileOut]


class CivitaiAuthOut(ApiContract):
    has_key: bool
    has_cookie: bool
    which: Literal["key", "cookie"] | None = None
    verified: bool | None = None
    reason: str | None = None


# ---------------------------------------------------------------- llama.cpp
class LlamaVersionOut(ApiContract):
    id: str
    tag: str
    variant: str
    installed_at: str | None = None
    size_bytes: int | None = None
    active: bool
    binaries: list[str]


class LlamaVerifyOut(ApiContract):
    ok: bool
    version: str | None = None
    error: str | None = None
    id: str | None = None
    checked_at: float | None = None


class LlamaInstallVersionOut(ApiContract):
    id: str
    tag: str
    variant: str
    installed_at: str | None = None
    size_bytes: int | None = None
    binaries: dict[str, str]


class LlamaInstallStatusOut(ApiContract):
    state: str
    tag: str | None = None
    variant: str | None = None
    message: str
    asset: str | None = None
    progress: DownloadProgressOut
    version: LlamaInstallVersionOut | None = None
    verified: LlamaVerifyOut | None = None
    updated_at: float


class LlamaUpdateOut(ApiContract):
    latest_tag: str
    active_tag: str | None = None
    variant: str
    asset_available: bool
    variant_matched: bool
    selection_reason: str
    update_available: bool
    checked_at: float


class LlamaStateOut(ApiContract):
    managed_root: str
    system: str
    machine: str
    variant: str
    active: str | None = None
    versions: list[LlamaVersionOut]
    keep_versions: int
    legacy_binary_present: bool
    install_status: LlamaInstallStatusOut
    update: LlamaUpdateOut | None = None
    active_verified: LlamaVerifyOut | None = None


# ---------------------------------------------------------------- LLM config
class LlmContextTypeOut(ApiContract):
    id: str
    label: str
    experimental: bool


class LlmBackendOut(ApiContract):
    id: str
    label: str
    available: bool
    path: str
    context_types: list[str]


class LlmDefaultsOut(ApiContract):
    temperature: float
    max_tokens: int


class LlmConfigOut(ApiContract):
    ctx: int
    ngl: int
    backend: str
    backends: list[LlmBackendOut]
    context_type: str
    context_types: list[LlmContextTypeOut]
    stub: bool
    loaded: bool
    model_id: str | None = None
    defaults: LlmDefaultsOut
    changed: bool | None = None
    unloaded: bool | None = None
    reloaded: bool | None = None
    note: str | None = None


# ------------------------------------------------------------------------- RAG
class RagModelOut(ApiContract):
    id: str
    name: str
    path: str
    size_bytes: int


class RagStatusOut(ApiContract):
    binary: str
    binary_exists: bool
    models_dir: str
    models: list[RagModelOut]
    ready: bool
    port: int
    gpu_layers: int
    chunk_chars: int
    chunk_overlap: int


class RagDocumentOut(ApiContract):
    id: str
    title: str
    source: str | None = None
    model_id: str | None = None
    chunks_count: int
    created_at: datetime
    updated_at: datetime


class RagSearchResultOut(ApiContract):
    document_id: str
    document_title: str
    chunk_id: str
    chunk_index: int
    text: str
    score: float


class RagSearchOut(ApiContract):
    query: str
    results: list[RagSearchResultOut]
    context: str


# ----------------------------------------------------------- TTS/transcription
class TtsModelOut(ApiContract):
    id: str
    name: str
    path: str
    size_bytes: int


class TtsStatusOut(ApiContract):
    binary: str
    binary_exists: bool
    models_dir: str
    models: list[TtsModelOut]
    ready: bool


class TtsGenerateOut(ApiContract):
    id: str
    url: str
    path: str
    metadata_path: str
    model_id: str
    vocoder_id: str | None = None
    duration_seconds: float


class TranscriptionModelOut(ApiContract):
    id: str
    name: str
    path: str
    size_bytes: int
    engine: Literal["faster-whisper", "openai-whisper"]


class TranscriptionStatusOut(ApiContract):
    models_dir: str
    models: list[TranscriptionModelOut]
    engines: dict[str, bool]
    device: str
    compute_type: str
    max_upload_mb: int
    ready: bool


class TranscriptionSegmentOut(ApiContract):
    start: float
    end: float
    text: str


class TranscriptionResultOut(ApiContract):
    id: str
    text: str
    segments: list[TranscriptionSegmentOut]
    detected_language: str | None = None
    language_probability: float | None = None
    metadata_url: str
    metadata_path: str
    duration_seconds: float


class TranscriptionMetadataOut(ApiContract):
    id: str
    type: str
    engine: str
    model_id: str
    model_path: str
    language: str | None = None
    task: str
    duration_seconds: float
    audio_path: str
    created_at: datetime
    text: str
    segments: list[TranscriptionSegmentOut]
    detected_language: str | None = None
    language_probability: float | None = None


# ---------------------------------------------------------------- voice engine
class VoiceAssetOut(ApiContract):
    name: str
    path: str | None = None
    found: bool
    source: str | None = None
    optional: bool | None = None


class VoiceModelOut(ApiContract):
    id: str
    slot: str
    name: str
    type: str
    version: str
    sampling_rate: int | None = None
    f0: bool | None = None
    speaker_id: int | None = None
    has_index: bool
    size_bytes: int
    source: str | None = None


class VoiceAudioDeviceOut(ApiContract):
    id: str
    index: int
    name: str
    host_api: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float | None = None


class VoiceAudioDevicesOut(ApiContract):
    inputs: list[VoiceAudioDeviceOut]
    outputs: list[VoiceAudioDeviceOut]


class VoiceEnginePresetOut(ApiContract):
    id: str
    name: str
    model_id: str | None = None
    settings: dict[str, Any]
    created_at: str
    updated_at: str


class VoiceRecordingStatusOut(ApiContract):
    active: bool
    duration_s: float
    samples: int
    sample_rate: int | None = None


class VoiceRecordingResultOut(ApiContract):
    token: str
    raw_token: str | None = None
    url: str
    raw_url: str | None = None
    mp3_url: str
    metadata_url: str | None = None
    duration_s: float
    sample_rate: int
    samples: int


class VoiceEngineStatusOut(ApiContract):
    engine: str
    stub: bool
    ready: bool
    assets: list[VoiceAssetOut]
    asset_download: DownloadStatusOut | None = None
    models: list[VoiceModelOut]
    audio_devices: VoiceAudioDevicesOut
    device: str
    settings: dict[str, Any]
    loaded_model: str | None = None
    live: bool
    session_config: dict[str, Any] | None = None
    session_error: str | None = None
    recording: VoiceRecordingStatusOut
    recording_result: VoiceRecordingResultOut | None = None
    metrics: dict[str, Any]


class VoiceConvertOut(ApiContract):
    token: str
    url: str
    mp3_url: str
    duration_s: float
    sample_rate: int
    timings_ms: dict[str, float]
    model_id: str
    params: dict[str, Any]


# Metadata written by realtime recording is deliberately extensible.
class VoiceRecordingMetadataOut(ApiContract):
    token: str
