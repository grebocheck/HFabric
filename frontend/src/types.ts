import type { components } from "./types.generated";

type Api = components["schemas"];
type JsonRecord = Record<string, unknown>;

// Canonical API enums and payloads. Keep aliases here so UI code has stable,
// readable names while the backend OpenAPI schema remains the source of truth.
export type JobType = Api["JobType"];
export type ModelFamily = Api["ModelFamily"];
export type AppTheme = "dark" | "dim" | "light";

export type Model = Api["ModelOut"];
export type Lora = Api["LoraOut"];
export type InstalledModel = Api["InstalledModelOut"];
export type InstalledModelsState = Api["InstalledModelsOut"];

// GpuStatusOut deliberately uses generic dictionaries for runtime-specific
// entries. These refinements document the fields consumed by the UI.
interface WarmModel {
  resident: string;
  model_id: string;
  model: string;
  family: string;
}

interface GpuLane {
  id: string;
  label: string;
}

export type GpuStatus = {
  resident: string | null;
  model_id: string | null;
  model: string | null;
  family: string | null;
  warm?: WarmModel[];
  lanes?: GpuLane[];
  pin?: (WarmModel & { id: string; label: string }) | null;
};

// The custom downloader accepts a heterogeneous, intentionally extensible
// request that is not represented by a named backend model yet.
export interface CustomDownloadItem {
  source: "hf" | "hf-repo" | "url" | "civitai";
  kind: string;
  repo?: string;
  filename?: string;
  subdir?: string;
  url?: string;
  label?: string;
  sha256?: string;
}

export type CivitaiSearchResult = Api["CivitaiSearchResultOut"];
export type CivitaiSearchResponse = Api["CivitaiSearchOut"];
export type CivitaiAuthStatus = Api["CivitaiAuthOut"];
export type CivitaiVersionFiles = Api["CivitaiVersionFilesOut"];

export type HfRepoFile = Api["HfRepoFileOut"];
export type HfRepoFiles = Api["HfRepoFilesOut"];
export type HfSearchResult = Api["HfSearchResultOut"];
export type HfSearchResponse = Api["HfSearchOut"];

type RamStats = Api["RamStatusOut"];
type VramStats = Api["VramStatusOut"];
export type MemSnapshot = {
  ram: RamStats | null;
  vram: VramStats | null;
};
type CapabilityGpu = Api["CapabilityGpuOut"] & {
  rocm?: JsonRecord | null;
  mps?: JsonRecord | null;
};

// model_policy and starter_models are extensible capability-manifest sections.
// They remain domain refinements until the backend gives them named contracts.
interface ModelPolicy {
  tier: string;
  image: {
    recommended: ModelFamily[];
    advanced: ModelFamily[];
    hidden: ModelFamily[];
  };
  video?: {
    recommended: ModelFamily[];
    advanced: ModelFamily[];
    hidden: ModelFamily[];
    fallback_candidates?: ModelFamily[];
  };
  llm: {
    max_recommended_params_b: number;
  };
  notes: string[];
}

interface StarterModelJob {
  repo: string;
  filename: string;
  dest: string;
  label: string;
  reason: string;
  feature?: string;
}

interface StarterModelPlan {
  profile: string;
  jobs: StarterModelJob[];
  command: string;
  dry_run_command: string;
}

type CapabilityCandidate = Pick<
  Api["CapabilityCandidateOut"],
  "confidence" | "id" | "reason" | "warnings"
> & {
  gpu?: CapabilityGpu | null;
};

export type CapabilityProfile = Pick<
  Api["CapabilityProfileOut"],
  | "active_profile"
  | "backend"
  | "confidence"
  | "configured_stub_mode"
  | "disabled_features"
  | "effective_stub_mode"
  | "features"
  | "hardware_tier"
  | "label"
  | "reason"
  | "runtime_defaults"
  | "schema_version"
  | "selected_profile"
  | "sources"
  | "warnings"
> & {
  primary_gpu?: CapabilityGpu | null;
  model_policy?: ModelPolicy | null;
  starter_models?: StarterModelPlan | null;
  candidates: CapabilityCandidate[];
};

export type PromptSnippet = Api["PromptSnippetOut"];
export type ModelDownloadItem = Api["ModelDownloadItemOut"];
export type ModelDownloadStatus = Api["DownloadStatusOut"];
export type ModelDownloadState = Api["DownloadStateOut"];

export type LlamaVerifyResult = Api["LlamaVerifyOut"];
export type LlamaInstallStatus = Api["LlamaInstallStatusOut"];
export type LlamaUpdateInfo = Api["LlamaUpdateOut"];
export type LlamaState = Api["LlamaStateOut"];

export type HealthStatus = Pick<
  Api["HealthOut"],
  "mem" | "models" | "security" | "status" | "stub_mode"
> & {
  gpu: GpuStatus;
  version?: string;
};

// UI-only event projections.
export interface MemPoint {
  ts: number;
  ram: RamStats | null;
  vram: VramStats | null;
  resident: string | null;
}

type QueuePlanStep = Pick<
  Api["QueuePlanStepOut"],
  "count" | "model" | "model_id"
> & {
  type: JobType;
};

export type QueuePlan = Pick<
  Api["QueuePlanOut"],
  "current_model" | "current_model_id" | "queued" | "swaps"
> & {
  steps: QueuePlanStep[];
};

export interface ArbiterNote {
  reason: string;
  message: string;
  model_id?: string;
  model?: string;
  family?: string;
  target_model_id?: string;
  target_model?: string;
  target_family?: string;
  unload_model_id?: string;
  unload_model?: string;
  predicted_gb?: number;
  available_gb?: number;
  ts: number;
}

export type ModelProfile = Api["ModelProfileOut"];
export type SettingsValue = string | number | boolean | null;
export type SettingsOverrideValues = Api["SettingsOverridesOut"]["values"] & {
  default_steps: number;
  default_guidance: number;
  default_width: number;
  default_height: number;
  keep_warm_models: boolean;
  keep_warm_max_models: number;
};

type SettingsChoice = Api["SettingsChoiceOut"];
export type SettingsSchemaEntry = Pick<
  Api["SettingsSchemaEntryOut"],
  | "group"
  | "key"
  | "label"
> & {
  kind: "boolean" | "integer" | "number" | "text" | "choice" | "path";
  description?: string;
  min?: number;
  max?: number;
  step?: number;
  multiple_of?: number;
  choices?: SettingsChoice[];
  nullable?: boolean;
  restart_required?: boolean;
};
export type SettingsGroup = Api["SettingsGroupOut"];
export type SettingsOverrides = Pick<
  Api["SettingsOverridesOut"],
  "groups" | "path" | "persistence_warnings" | "writable_keys"
> & {
  values: SettingsOverrideValues;
  schema: SettingsSchemaEntry[];
};

export type RuntimeSettings = Pick<
  Api["RuntimeSettingsOut"],
  | "acceleration"
  | "counts"
  | "generation_defaults"
  | "mem"
  | "memory"
  | "paths"
  | "stub_mode"
> & {
  capability?: CapabilityProfile;
  gpu: GpuStatus;
};

export type Job = Api["JobOut"] & {
  progress_note?: string | null;
};
export type ImageItem = Api["ImageOut"] & { tags: string[] };
export type VideoItem = Api["VideoOut"];
export type ImageStats = Api["ImageStatsOut"];

// UI-only hand-off messages between workspaces.
export interface ComposerApply {
  model_id?: string;
  params: JsonRecord;
  nonce: number;
}

export interface EditApply extends ComposerApply {
  image_id?: string;
  source_url?: string;
  width?: number;
  height?: number;
}

export type Preset = Api["PresetOut"];
export type JobCreate = Api["JobCreate"];

export interface BusEvent {
  type: string;
  ts: number;
  [key: string]: unknown;
}

type ChatRole = "user" | "assistant" | "system";
export type ChatAttachment = Api["ChatAttachmentOut"];
export type ChatMessage = Omit<Api["MessageOut"], "created_at" | "role"> & {
  role: ChatRole;
  // Optimistic/streaming messages exist before the server assigns a timestamp.
  created_at?: string;
};

export type ChatConversation = Api["ConversationOut"];
export type ChatConversationDetail = Omit<Api["ConversationDetailOut"], "messages"> & {
  messages: ChatMessage[];
};
export type ChatImportMessage = Omit<Api["MessageImport"], "role"> & {
  role: ChatRole;
};
export type ChatConversationImport = Omit<Api["ConversationImport"], "messages"> & {
  messages?: ChatImportMessage[];
};
export type ChatImportResult = Omit<Api["ChatImportOut"], "conversations"> & {
  conversations: ChatConversationDetail[];
};
export type ChatSendResult = Omit<
  Api["ChatSendOut"],
  "assistant_message" | "conversation" | "user_message"
> & {
  conversation: ChatConversation;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
};
export type ChatSendBody = Api["ChatSend"];

export type LlmConfig = Api["LlmConfigOut"];
export type LlmApiServerStatus = Api["LlmApiServerStatus"];

export type PresetImportItem = Api["PresetImportItem"];
export type PresetImportResult = Api["PresetImportOut"];
export type Note = Api["NoteOut"];

export type TtsStatus = Api["TtsStatusOut"];
export type TtsGenerateBody = Api["TtsGenerateIn"];
export type TtsGenerateResult = Api["TtsGenerateOut"];

export type TranscriptionStatus = Api["TranscriptionStatusOut"];
export type TranscriptionResult = Api["TranscriptionResultOut"];

export type RagStatus = Api["RagStatusOut"];
export type RagDocument = Api["RagDocumentOut"];
export type RagSearchResponse = Api["RagSearchOut"];

export type VoiceModel = Api["VoiceModelOut"] & {
  f0: boolean;
  sampling_rate: number | null;
};
export type VoiceAudioDevice = Api["VoiceAudioDeviceOut"] & {
  default_sample_rate: number | null;
};
export type VoiceEngineAsset = Api["VoiceAssetOut"];

// The voice status endpoint intentionally keeps these runtime dictionaries
// extensible. These are the stable fields rendered and edited by the UI.
export interface VoiceEngineSettings {
  pitch: number;
  speaker_id: number;
  index_ratio: number;
  protect: number;
  noise_scale: number;
  f0_smoothing: number;
  f0_detector: string;
  input_highpass_hz: number;
  input_gate_db: number;
  input_formant: number;
  input_denoise: "off" | "dtln";
  input_denoise_mix: number;
  silence_threshold_db: number;
  silence_hold_ms: number;
  server_input_device_id: number | null;
  server_output_device_id: number | null;
  server_monitor_device_id: number | null;
  server_input_gain: number;
  server_output_gain: number;
  server_monitor_gain: number;
  server_audio_sample_rate: number;
  server_read_chunk_size: number;
  cross_fade_overlap_size: number;
  extra_convert_size: number;
  pass_through: boolean;
  device_missing?: {
    input: boolean;
    output: boolean;
    monitor: boolean;
  };
}

export type VoiceEngineSettingsUpdate = Api["VoiceEngineSettingsUpdate"];
export type VoiceEnginePreset = Pick<
  Api["VoiceEnginePresetOut"],
  "created_at" | "id" | "model_id" | "name" | "updated_at"
> & {
  settings: VoiceEngineSettingsUpdate;
};

export interface VoiceProviderHealth {
  name?: string | null;
  requested?: string | null;
  actual?: string | null;
  loaded?: boolean;
  error?: string | null;
}

interface VoiceEngineMetrics {
  input_vu: number;
  output_vu: number;
  output_peak: number;
  output_peak_dbfs: number | null;
  limiter_reduction_db: number;
  timings_ms: Record<string, number>;
  total_ms: number | null;
  total_p95_ms: number | null;
  chunk_ms: number | null;
  latency_headroom_ms: number | null;
  latency_warning: string | null;
  estimated_latency_ms: number | null;
  measured_latency_ms: number | null;
  measured_latency_p95_ms: number | null;
  callback_transport_ms: number | null;
  clock_drift_ppm: number | null;
  input_stream_latency_ms: number | null;
  output_stream_latency_ms: number | null;
  input_queue_ms: number;
  output_queue_ms: number;
  provider_health: {
    content_vec?: VoiceProviderHealth | null;
    f0?: VoiceProviderHealth | null;
  };
  overruns: number;
  underruns: number;
  squelched: boolean;
}

interface VoiceEngineSessionConfig {
  server_input_device_id: number | null;
  server_output_device_id: number | null;
  server_monitor_device_id: number | null;
  server_audio_sample_rate: number;
  server_read_chunk_size: number;
}

export type VoiceEngineRecordingResult = Api["VoiceRecordingResultOut"];
export type VoiceEngineStatus = Pick<
  Api["VoiceEngineStatusOut"],
  | "asset_download"
  | "assets"
  | "device"
  | "engine"
  | "live"
  | "loaded_model"
  | "ready"
  | "recording"
  | "recording_result"
  | "session_error"
  | "stub"
> & {
  models: VoiceModel[];
  audio_devices: {
    inputs: VoiceAudioDevice[];
    outputs: VoiceAudioDevice[];
  };
  settings: VoiceEngineSettings;
  metrics: VoiceEngineMetrics;
  session_config: VoiceEngineSessionConfig | null;
};
export type VoiceEngineConvertResult = Api["VoiceConvertOut"] & {
  params: {
    pitch: number;
    speaker_id: number;
    index_ratio: number;
    protect: number;
    noise_scale: number;
    f0_smoothing: number;
    f0_detector: string;
    input_highpass_hz: number;
    input_gate_db: number;
    input_formant: number;
    input_denoise: "off" | "dtln";
    input_denoise_mix: number;
  };
};

export type CodeFile = Api["CodeFileOut"];
export type CodeFileContent = Api["CodeFileContentOut"];
