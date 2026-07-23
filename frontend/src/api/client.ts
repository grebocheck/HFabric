import type { CapabilityProfile, ChatAttachment, ChatConversation, ChatConversationDetail, ChatConversationImport, ChatImportResult, ChatSendBody, ChatSendResult, CivitaiAuthStatus, CivitaiSearchResponse, CivitaiVersionFiles, CodeFile, CodeFileContent, CustomDownloadItem, GpuStatus, HealthStatus, HfRepoFiles, HfSearchResponse, ImageItem, ImageStats, InstalledModelsState, Job, JobCreate, JobType, LlamaInstallStatus, LlamaState, LlamaUpdateInfo, LlamaVerifyResult, LlmApiServerStatus, LlmConfig, Lora, Model, ModelDownloadState, ModelDownloadStatus, ModelProfile, Note, PromptSnippet, Preset, PresetImportItem, PresetImportResult, QueuePlan, RagDocument, RagSearchResponse, RagStatus, RuntimeSettings, SettingsOverrides, TranscriptionResult, TranscriptionStatus, TtsGenerateBody, TtsGenerateResult, TtsStatus, VideoItem, VoiceEngineConvertResult, VoiceEnginePreset, VoiceEngineSettingsUpdate, VoiceEngineStatus } from "../types";
import type { components } from "../types.generated";
import { storage } from "../lib/storage";

type Api = components["schemas"];

const JSON_HEADERS = { "Content-Type": "application/json" };
const TOKEN_KEY = "hfabric.apiToken";

type AuthEvent = { token: string; unauthorized: boolean };
type AuthListener = (event: AuthEvent) => void;
const authListeners = new Set<AuthListener>();

function readToken(): string {
  return storage.get(TOKEN_KEY)?.trim() ?? "";
}

function emitAuth(unauthorized = false) {
  const event = { token: readToken(), unauthorized };
  for (const listener of authListeners) listener(event);
}

function authHeaders(headers?: HeadersInit): Headers {
  const next = new Headers(headers);
  const token = readToken();
  if (token) next.set("Authorization", `Bearer ${token}`);
  return next;
}

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const res = await globalThis.fetch(input, {
    ...init,
    credentials: init.credentials ?? "same-origin",
    headers: authHeaders(init.headers),
  });
  if (res.status === 401) emitAuth(true);
  return res;
}

const fetch = apiFetch;

export function apiAssetUrl(url: string | null | undefined): string {
  return url ?? "";
}

function withImageAuth(image: ImageItem): ImageItem {
  return {
    ...image,
    url: apiAssetUrl(image.url),
    thumb_url: image.thumb_url ? apiAssetUrl(image.thumb_url) : null,
  };
}

function withVideoAuth(video: VideoItem): VideoItem {
  return {
    ...video,
    url: apiAssetUrl(video.url),
    poster_url: video.poster_url ? apiAssetUrl(video.poster_url) : null,
    thumb_url: video.thumb_url ? apiAssetUrl(video.thumb_url) : null,
  };
}

function withTtsAuth(result: TtsGenerateResult): TtsGenerateResult {
  return { ...result, url: apiAssetUrl(result.url) };
}

function withAttachmentAuth(attachment: ChatAttachment): ChatAttachment {
  return { ...attachment, url: attachment.url ? apiAssetUrl(attachment.url) : attachment.url };
}

type ErrorShape = Partial<
  Pick<Api["ErrorOut"], "code" | "detail" | "details" | "message" | "request_id">
>;

function objectValue(value: unknown): ErrorShape | null {
  return value !== null && typeof value === "object" ? value as ErrorShape : null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: unknown;
  readonly requestId: string | null;
  readonly request_id: string | null;

  constructor({
    status,
    code,
    message,
    details,
    requestId,
  }: {
    status: number;
    code?: string | null;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code ?? null;
    this.details = details;
    this.requestId = requestId ?? null;
    this.request_id = this.requestId;
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    const raw = await response.text();
    let body: unknown = null;
    if (raw) {
      try {
        body = JSON.parse(raw);
      } catch {
        body = raw;
      }
    }
    const top = objectValue(body);
    const detail = objectValue(top?.detail);
    const message =
      (typeof top?.message === "string" && top.message)
      || (typeof detail?.message === "string" && detail.message)
      || (typeof top?.detail === "string" && top.detail)
      || (typeof body === "string" && body.trim())
      || response.statusText
      || `Request failed (${response.status})`;
    const code =
      (typeof top?.code === "string" && top.code)
      || (typeof detail?.code === "string" && detail.code)
      || null;
    const requestId =
      (typeof top?.request_id === "string" && top.request_id)
      || (typeof detail?.request_id === "string" && detail.request_id)
      || response.headers.get("x-request-id");
    const details = top?.details ?? detail?.details ?? (detail ? top?.detail : undefined);

    return new ApiError({
      status: response.status,
      code,
      message,
      details,
      requestId,
    });
  }
}

async function j<T>(res: Response): Promise<T> {
  if (res.status === 401) emitAuth(true);
  if (!res.ok) throw await ApiError.fromResponse(res);
  return res.json() as Promise<T>;
}

async function refreshAssetSession(): Promise<void> {
  if (!readToken()) return;
  await apiFetch("/api/auth/asset-session", {
    method: "POST",
    credentials: "include",
  }).then(j<Api["AssetSessionOut"]>);
}

async function revokeAssetSession(): Promise<void> {
  if (!readToken()) return;
  const response = await apiFetch("/api/auth/asset-session", {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok) throw await ApiError.fromResponse(response);
}

export const apiAuth = {
  getToken: readToken,
  async setToken(token: string): Promise<void> {
    const clean = token.trim();
    if (!clean) {
      await this.clearToken();
      return;
    }
    storage.set(TOKEN_KEY, clean);
    await refreshAssetSession();
    emitAuth(false);
  },
  async clearToken(): Promise<void> {
    try {
      await revokeAssetSession();
    } finally {
      storage.remove(TOKEN_KEY);
      emitAuth(false);
    }
  },
  refreshAssetSession,
  subscribe(listener: AuthListener): () => void {
    authListeners.add(listener);
    return () => authListeners.delete(listener);
  },
};

export const api = {
  health: (signal?: AbortSignal) => globalThis.fetch("/api/health", { signal }).then(j<HealthStatus>),
  listModels: (signal?: AbortSignal) => fetch("/api/models", { signal }).then(j<Model[]>),
  rescanModels: () =>
    fetch("/api/models/rescan", { method: "POST" })
      .then(j<Api["ModelRescanOut"]>),
  listLoras: (signal?: AbortSignal) => fetch("/api/loras", { signal }).then(j<Lora[]>),
  listModelProfiles: () => fetch("/api/models/profiles").then(j<ModelProfile[]>),
  resetModelProfile: (id: string) => fetch(`/api/models/profiles/${encodeURIComponent(id)}`, { method: "DELETE" }).then(j<Api["DeletedCountOut"]>),
  resetAllModelProfiles: () => fetch("/api/models/profiles", { method: "DELETE" }).then(j<Api["DeletedCountOut"]>),
  capabilities: (refresh = false) => fetch(`/api/capabilities${refresh ? "?refresh=true" : ""}`).then(j<CapabilityProfile>),
  runtimeSettings: () => fetch("/api/settings").then(j<RuntimeSettings>),
  settingsOverrides: () => fetch("/api/settings/overrides").then(j<SettingsOverrides>),
  saveSettingsOverrides: (body: Partial<SettingsOverrides["values"]>) =>
    fetch("/api/settings/overrides", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<SettingsOverrides>),
  gpuStatus: () => fetch("/api/gpu").then(j<GpuStatus>),
  freeGpu: () => fetch("/api/gpu/free", { method: "POST" }).then(j<GpuStatus>),

  llamaState: () => fetch("/api/llama").then(j<LlamaState>),
  llamaInstall: (body: { tag?: string; variant?: string } = {}) =>
    fetch("/api/llama/install", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }).then(j<LlamaInstallStatus>),
  llamaCheckUpdate: (body: { variant?: string } = {}) =>
    fetch("/api/llama/check", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }).then(j<LlamaUpdateInfo>),
  llamaVerify: () => fetch("/api/llama/verify", { method: "POST" }).then(j<LlamaVerifyResult>),
  llamaActivate: (id: string) =>
    fetch("/api/llama/activate", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }) }).then(j<LlamaState>),
  llamaRemove: (id: string) =>
    fetch(`/api/llama/${encodeURIComponent(id)}`, { method: "DELETE" }).then(j<LlamaState>),

  downloadsState: (refresh = false) =>
    fetch(`/api/downloads${refresh ? "?refresh=true" : ""}`).then(j<ModelDownloadState>),
  downloadsStart: (keys: string[]) =>
    fetch("/api/downloads/start", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ keys }) })
      .then(j<ModelDownloadStatus>),
  downloadsCustom: (items: CustomDownloadItem[]) =>
    fetch("/api/downloads/custom", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ items }) })
      .then(j<ModelDownloadStatus>),
  hfRepoFiles: (repo: string) =>
    fetch(`/api/downloads/hf/files?repo=${encodeURIComponent(repo)}`).then(j<HfRepoFiles>),
  hfSearch: (q: string, opts: { limit?: number; sort?: string; filter?: string } = {}) => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (opts.limit != null) p.set("limit", String(opts.limit));
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.filter) p.set("filter", opts.filter);
    const qs = p.toString();
    return fetch(`/api/downloads/hf/search${qs ? `?${qs}` : ""}`).then(j<HfSearchResponse>);
  },
  civitaiSearch: (
    q: string,
    opts: { types?: string; sort?: string; period?: string; baseModels?: string; nsfw?: boolean; limit?: number; page?: number } = {},
  ) => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (opts.types) p.set("types", opts.types);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.period) p.set("period", opts.period);
    if (opts.baseModels) p.set("base_models", opts.baseModels);
    if (opts.nsfw) p.set("nsfw", "true");
    if (opts.limit != null) p.set("limit", String(opts.limit));
    if (opts.page != null) p.set("page", String(opts.page));
    const qs = p.toString();
    return fetch(`/api/civitai/search${qs ? `?${qs}` : ""}`).then(j<CivitaiSearchResponse>);
  },
  civitaiVersionFiles: (versionId: number, nsfw = false) =>
    fetch(`/api/civitai/versions/${versionId}/files${nsfw ? "?nsfw=true" : ""}`).then(j<CivitaiVersionFiles>),
  civitaiAuthStatus: () => fetch("/api/civitai/auth").then(j<CivitaiAuthStatus>),
  civitaiAuthSave: (apiKey: string) =>
    fetch("/api/civitai/auth", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ api_key: apiKey }) })
      .then(j<CivitaiAuthStatus>),
  civitaiAuthSaveCookie: (cookie: string) =>
    fetch("/api/civitai/auth", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ session_cookie: cookie }) })
      .then(j<CivitaiAuthStatus>),
  civitaiAuthClear: (target: "key" | "cookie" | "all" = "all") =>
    fetch(`/api/civitai/auth?target=${target}`, { method: "DELETE" }).then(j<CivitaiAuthStatus>),
  installedModels: () => fetch("/api/models/installed").then(j<InstalledModelsState>),
  deleteInstalledModel: (kind: string, path: string) =>
    fetch(`/api/models/installed?kind=${encodeURIComponent(kind)}&path=${encodeURIComponent(path)}`, { method: "DELETE" })
      .then(j<Api["InstalledModelDeleteOut"]>),

  listJobs: (signal?: AbortSignal) => fetch("/api/jobs", { signal }).then(j<Job[]>),
  createJobs: (jobs: JobCreate[]) =>
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(jobs),
    }).then(j<Job[]>),
  uploadInitImage: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/images/upload", { method: "POST", body: fd })
      .then(j<Api["ImageUploadOut"]>)
      .then((res) => ({ ...res, url: apiAssetUrl(res.url) }));
  },
  uploadMaskImage: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/images/upload-mask", { method: "POST", body: fd })
      .then(j<Api["MaskUploadOut"]>)
      .then((res) => ({ ...res, url: apiAssetUrl(res.url) }));
  },
  queuePlan: () => fetch("/api/jobs/plan").then(j<QueuePlan>),
  getJob: (id: string) => fetch(`/api/jobs/${id}`).then(j<Job>),
  cancelJob: (id: string) => fetch(`/api/jobs/${id}`, { method: "DELETE" }).then(j<Job>),
  getLlmConfig: () => fetch("/api/llm/config").then(j<LlmConfig>),
  setLlmConfig: (body: Api["LlmConfigUpdate"]) =>
    fetch("/api/llm/config", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<LlmConfig & { changed: boolean; reloaded: boolean; note: string | null }>),
  getLlmServer: () => fetch("/api/llm/server").then(j<LlmApiServerStatus>),
  setLlmServer: (body: Api["LlmApiServerUpdate"]) =>
    fetch("/api/llm/server", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<LlmApiServerStatus>),
  stopLlm: () => fetch("/api/llm/stop", { method: "POST" }).then(j<Api["StoppedOut"]>),

  // --- chat conversations ---
  listConversations: () => fetch("/api/chat/conversations").then(j<ChatConversation[]>),
  createConversation: (body: Api["ConversationCreate"] = {}) =>
    fetch("/api/chat/conversations", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<ChatConversation>),
  getConversation: (id: string) => fetch(`/api/chat/conversations/${id}`).then(j<ChatConversationDetail>),
  updateConversation: (id: string, body: Api["ConversationUpdate"]) =>
    fetch(`/api/chat/conversations/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<ChatConversation>),
  deleteConversation: (id: string) =>
    fetch(`/api/chat/conversations/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  importConversations: (conversations: ChatConversationImport[]) =>
    fetch("/api/chat/import", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ conversations } satisfies Api["ChatImportIn"]),
    }).then(j<ChatImportResult>),
  uploadChatAttachment: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/chat/uploads", { method: "POST", body: form })
      .then(j<ChatAttachment>)
      .then(withAttachmentAuth);
  },
  sendChatMessage: (id: string, body: ChatSendBody) =>
    fetch(`/api/chat/conversations/${id}/messages`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<ChatSendResult>),
  sendChatImage: (id: string, body: Api["ImageChatSend"]) =>
    fetch(`/api/chat/conversations/${id}/image`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<ChatSendResult>),
  truncateFrom: (id: string, messageId: string) =>
    fetch(`/api/chat/conversations/${id}/messages/${messageId}`, { method: "DELETE" }).then(j<Api["RemovedOut"]>),
  setPriority: (id: string, priority: number) =>
    fetch(`/api/jobs/${id}/priority`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority } satisfies Api["PriorityUpdate"]),
    }).then(j<Job>),
  clearFinished: () => fetch("/api/jobs/clear", { method: "POST" }).then(j<Api["RemovedOut"]>),

  listImages: (q?: string, signal?: AbortSignal) => {
    const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return fetch(`/api/images${params}`, { signal }).then(j<ImageItem[]>).then((rows) => rows.map(withImageAuth));
  },
  queryImages: (opts: { q?: string; model?: string; family?: string; size?: string; lora?: string; favorite?: boolean; tag?: string; date_from?: string; date_to?: string; limit?: number; offset?: number } = {}) => {
    const p = new URLSearchParams();
    if (opts.q?.trim()) p.set("q", opts.q.trim());
    if (opts.model) p.set("model", opts.model);
    if (opts.family) p.set("family", opts.family);
    if (opts.size) p.set("size", opts.size);
    if (opts.lora) p.set("lora", opts.lora);
    if (opts.favorite != null) p.set("favorite", String(opts.favorite));
    if (opts.tag) p.set("tag", opts.tag);
    if (opts.date_from) p.set("date_from", opts.date_from);
    if (opts.date_to) p.set("date_to", opts.date_to);
    if (opts.limit != null) p.set("limit", String(opts.limit));
    if (opts.offset != null) p.set("offset", String(opts.offset));
    const qs = p.toString();
    return fetch(`/api/images${qs ? `?${qs}` : ""}`).then(j<ImageItem[]>).then((rows) => rows.map(withImageAuth));
  },
  imageStats: () => fetch("/api/images/stats").then(j<ImageStats>),
  updateImage: (id: string, body: Api["ImageUpdateIn"]) =>
    fetch(`/api/images/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<ImageItem>)
      .then(withImageAuth),
  exportImages: async (imageIds: Api["ImageExportIn"]["image_ids"]) => {
    const res = await fetch("/api/images/export", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ image_ids: imageIds } satisfies Api["ImageExportIn"]),
    });
    if (!res.ok) throw await ApiError.fromResponse(res);
    return res.blob();
  },
  exportDiagnostics: async () => {
    const res = await fetch("/api/diagnostics/export");
    if (!res.ok) throw await ApiError.fromResponse(res);
    return res.blob();
  },
  deleteImage: (id: string) => fetch(`/api/images/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  revealImage: (id: string) => fetch(`/api/images/${id}/reveal`, { method: "POST" }).then(j<Api["RevealOut"]>),
  listVideos: (signal?: AbortSignal) => fetch("/api/videos", { signal }).then(j<VideoItem[]>).then((rows) => rows.map(withVideoAuth)),
  deleteVideo: (id: string) => fetch(`/api/videos/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  listPresets: (signal?: AbortSignal) => fetch("/api/presets", { signal }).then(j<Preset[]>),
  createPreset: (name: string, type: JobType, params: Record<string, unknown>) =>
    fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, type, params } satisfies Api["PresetCreate"]),
    }).then(j<Preset>),
  importPresets: (presets: PresetImportItem[], on_conflict: "rename" | "skip" = "rename") =>
    fetch("/api/presets/import", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ presets, on_conflict } satisfies Api["PresetImportIn"]),
    }).then(j<PresetImportResult>),
  deletePreset: (id: string) => fetch(`/api/presets/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),

  // --- prompt library ---
  listPrompts: (q?: string) => {
    const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return fetch(`/api/prompts${params}`).then(j<PromptSnippet[]>);
  },
  createPrompt: (body: Api["PromptSnippetCreate"]) =>
    fetch("/api/prompts", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }).then(j<PromptSnippet>),
  updatePrompt: (id: string, body: Api["PromptSnippetUpdate"]) =>
    fetch(`/api/prompts/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) }).then(j<PromptSnippet>),
  deletePrompt: (id: string) => fetch(`/api/prompts/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  importPrompts: (prompts: Api["PromptSnippetImportIn"]["prompts"]) =>
    fetch("/api/prompts/import", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ prompts } satisfies Api["PromptSnippetImportIn"]),
    })
      .then(j<Api["PromptSnippetImportOut"]>),

  // --- notes ---
  listNotes: (q?: string) => {
    const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return fetch(`/api/notes${params}`).then(j<Note[]>);
  },
  createNote: (body: Api["NoteCreate"] = {}) =>
    fetch("/api/notes", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<Note>),
  updateNote: (id: string, body: Api["NoteUpdate"]) =>
    fetch(`/api/notes/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<Note>),
  deleteNote: (id: string) =>
    fetch(`/api/notes/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),

  ttsStatus: () => fetch("/api/tts/status").then(j<TtsStatus>),
  generateTts: (body: TtsGenerateBody) =>
    fetch("/api/tts/generate", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<TtsGenerateResult>)
      .then(withTtsAuth),

  transcriptionStatus: () => fetch("/api/transcription/status").then(j<TranscriptionStatus>),
  transcribeAudio: (body: { file: File; model_id: string; language?: string; task?: string; initial_prompt?: string }) => {
    const form = new FormData();
    form.append("file", body.file);
    form.append("model_id", body.model_id);
    if (body.language?.trim()) form.append("language", body.language.trim());
    if (body.task) form.append("task", body.task);
    if (body.initial_prompt?.trim()) form.append("initial_prompt", body.initial_prompt.trim());
    return fetch("/api/transcription/transcribe", { method: "POST", body: form }).then(j<TranscriptionResult>);
  },

  ragStatus: () => fetch("/api/rag/status").then(j<RagStatus>),
  listRagDocuments: (q?: string) => {
    const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return fetch(`/api/rag/documents${params}`).then(j<RagDocument[]>);
  },
  createRagDocument: (body: Api["RagDocumentCreate"]) =>
    fetch("/api/rag/documents", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<RagDocument>),
  uploadRagDocument: (body: { file: File; title?: string; model_id?: string }) => {
    const form = new FormData();
    form.append("file", body.file);
    if (body.title?.trim()) form.append("title", body.title.trim());
    if (body.model_id) form.append("model_id", body.model_id);
    return fetch("/api/rag/documents/upload", { method: "POST", body: form }).then(j<RagDocument>);
  },
  deleteRagDocument: (id: string) => fetch(`/api/rag/documents/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  searchRag: (body: Api["RagSearchIn"]) =>
    fetch("/api/rag/search", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<RagSearchResponse>),

  voiceEngineStatus: () => fetch("/api/voice/engine/status").then(j<VoiceEngineStatus>),
  voiceEngineFetchAssets: (body: Api["VoiceAssetFetchRequest"] = {}) =>
    fetch("/api/voice/engine/assets/fetch", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<VoiceEngineStatus>),
  voiceEngineSettings: (body: VoiceEngineSettingsUpdate) =>
    fetch("/api/voice/engine/settings", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<VoiceEngineStatus>),
  voiceEnginePresets: () => fetch("/api/voice/engine/presets").then(j<VoiceEnginePreset[]>),
  voiceEnginePresetCreate: (body: Api["VoiceEnginePresetCreate"]) =>
    fetch("/api/voice/engine/presets", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<VoiceEnginePreset>),
  voiceEnginePresetUpdate: (id: string, body: Api["VoiceEnginePresetUpdate"]) =>
    fetch(`/api/voice/engine/presets/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) })
      .then(j<VoiceEnginePreset>),
  voiceEnginePresetDelete: (id: string) =>
    fetch(`/api/voice/engine/presets/${id}`, { method: "DELETE" }).then(j<Api["DeleteOut"]>),
  voiceEngineSessionStart: (modelId: string) =>
    fetch("/api/voice/engine/session/start", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ model_id: modelId } satisfies Api["VoiceSessionStart"]),
    }).then(j<VoiceEngineStatus>),
  voiceEngineSessionStop: () => fetch("/api/voice/engine/session/stop", { method: "POST" }).then(j<VoiceEngineStatus>),
  voiceEngineRecordingStart: () => fetch("/api/voice/engine/recording/start", { method: "POST" }).then(j<VoiceEngineStatus>),
  voiceEngineRecordingStop: () =>
    fetch("/api/voice/engine/recording/stop", { method: "POST" })
      .then(j<VoiceEngineStatus>)
      .then((res) => ({
        ...res,
        recording_result: res.recording_result
          ? {
              ...res.recording_result,
              url: apiAssetUrl(res.recording_result.url),
              raw_url: res.recording_result.raw_url ? apiAssetUrl(res.recording_result.raw_url) : undefined,
              mp3_url: apiAssetUrl(res.recording_result.mp3_url),
              metadata_url: res.recording_result.metadata_url ? apiAssetUrl(res.recording_result.metadata_url) : undefined,
            }
          : undefined,
      })),
  voiceEngineConvert: (form: FormData) =>
    fetch("/api/voice/engine/convert", { method: "POST", body: form })
      .then(j<VoiceEngineConvertResult>)
      .then((res) => ({ ...res, url: apiAssetUrl(res.url), mp3_url: apiAssetUrl(res.mp3_url) })),
  listCodeFiles: (q?: string) => {
    const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    return fetch(`/api/code/files${params}`).then(j<CodeFile[]>);
  },
  getCodeFile: (path: string) => fetch(`/api/code/file?path=${encodeURIComponent(path)}`).then(j<CodeFileContent>),
  assetUrl: apiAssetUrl,
  downloadUrlBlob: async (url: string) => {
    const res = await fetch(url);
    if (!res.ok) throw await ApiError.fromResponse(res);
    return res.blob();
  },
};
