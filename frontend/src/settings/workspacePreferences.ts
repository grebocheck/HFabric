import { createPreferences, inRange, oneOf, optionalNumber, stringList } from "../lib/preferences";
import { readStoredEnum, storage } from "../lib/storage";
import { VIEW_IDS, type View } from "../workspaces";
import type { AppTheme } from "../types";
import { createChatSettings, DEFAULT_CHAT_SETTINGS } from "../components/chatHelpers";
import { DEFAULT_EDIT_DRAFT } from "../components/editWorkspaceHelpers";
import { DEFAULT_PRESET, type VideoMode } from "../components/video/videoPresets";
import { nativeSettingsToVoiceState } from "../components/voiceHelpers";

const voiceDefaults = nativeSettingsToVoiceState({});

// Defaults and validation live beside the workspace domains; storage and React
// subscriptions have no knowledge of API calls, models, or component lifecycles.
export const preferences = {
  app: createPreferences(
    "hfabric.preferences.app",
    {
      view: "images" as View,
      theme: "dark" as AppTheme,
      imageMode: "generate" as "generate" | "edit",
      historyMode: "images" as "images" | "videos",
      promptDraft: "",
      chatDraft: "",
    },
    {
      rules: {
        view: oneOf(...VIEW_IDS),
        theme: oneOf("dark", "dim", "light"),
        imageMode: oneOf("generate", "edit"),
        historyMode: oneOf("images", "videos"),
      },
      migrate: () => ({
        view: readStoredEnum("hfabric.view", VIEW_IDS, "images"),
        theme: readStoredEnum<AppTheme>("hfabric.theme", ["dark", "dim", "light"], "dark"),
      }),
    },
  ),
  chat: createPreferences("hfabric.preferences.chat", DEFAULT_CHAT_SETTINGS, {
    rules: {
      temperature: inRange(0, 2),
      maxTokens: inRange(1, 131072),
      ragTopK: inRange(1, 50),
      topP: optionalNumber,
      topK: optionalNumber,
      minP: optionalNumber,
      repeatPenalty: optionalNumber,
      seed: optionalNumber,
    },
    migrate: createChatSettings,
  }),
  chatUi: createPreferences("hfabric.preferences.chat-ui", {
    showAdvanced: false,
    personaId: "",
    convQuery: "",
    conversationId: "",
  }),
  edit: createPreferences(
    "hfabric.preferences.edit",
    {
      draft: DEFAULT_EDIT_DRAFT,
      modelId: "",
      presetId: "",
      viewMode: "source" as "source" | "result" | "compare",
    },
    {
      rules: { viewMode: oneOf("source", "result", "compare") },
    },
  ),
  video: createPreferences(
    "hfabric.preferences.video",
    {
      modelId: "",
      mode: "t2v" as VideoMode,
      prompt: "",
      negative: "",
      presetId: DEFAULT_PRESET.id,
      width: DEFAULT_PRESET.width,
      height: DEFAULT_PRESET.height,
      frames: DEFAULT_PRESET.frames,
      fps: DEFAULT_PRESET.fps,
      steps: DEFAULT_PRESET.steps,
      guidance: DEFAULT_PRESET.guidance,
      seed: -1,
    },
    {
      rules: {
        mode: oneOf("t2v", "i2v"),
        width: inRange(64, 4096),
        height: inRange(64, 4096),
        frames: inRange(1, 1000),
        fps: inRange(1, 120),
        steps: inRange(1, 150),
        guidance: inRange(0, 30),
        seed: inRange(-1, 2 ** 31 - 1),
      },
    },
  ),
  voice: createPreferences("hfabric.preferences.voice", { draft: voiceDefaults, confirmed: voiceDefaults }),
  voiceUi: createPreferences("hfabric.preferences.voice-ui", {
    modelId: "",
    selectedPresetId: "",
    voicesOpen: false,
  }),
  voiceOffline: createPreferences(
    "hfabric.preferences.voice-offline",
    { offlineModelId: "", offlinePitch: 0 },
    { rules: { offlinePitch: inRange(-24, 24) } },
  ),
  tts: createPreferences("hfabric.preferences.tts", {
    text: "Hello from HFabric.",
    modelId: "",
    vocoderId: "",
    useGuideTokens: false,
  }),
  transcription: createPreferences(
    "hfabric.preferences.transcription",
    { modelId: "", language: "", task: "transcribe", initialPrompt: "" },
    { rules: { task: oneOf("transcribe", "translate") } },
  ),
  code: createPreferences(
    "hfabric.preferences.code",
    { modelId: "", query: "", prompt: "", selected: [] as string[], activePath: "" },
    { rules: { selected: stringList } },
  ),
  rag: createPreferences(
    "hfabric.preferences.rag",
    { embedModelId: "", llmModelId: "", query: "", topK: 5, docQuery: "", title: "", content: "" },
    { rules: { topK: inRange(1, 50) } },
  ),
  gallery: createPreferences(
    "hfabric.preferences.gallery",
    { q: "", model: "", family: "", size: "", lora: "", favorite: false, tag: "", range: "all" },
    {
      rules: {
        range: oneOf("all", "today", "7d", "30d"),
        size: oneOf("", "square", "landscape", "portrait", "large", "small"),
      },
    },
  ),
  videoHistory: createPreferences(
    "hfabric.preferences.video-history",
    { query: "", family: "all", mode: "all" as VideoMode | "all" },
    { rules: { mode: oneOf("all", "t2v", "i2v") } },
  ),
  hf: createPreferences("hfabric.preferences.hf", {
    query: "",
    sort: "downloads",
    focus: "all",
    repo: "",
    fileQuery: "",
  }),
  civitai: createPreferences(
    "hfabric.preferences.civitai",
    { query: "", sort: "downloads", focus: "all", nsfw: false },
    { migrate: () => ({ nsfw: storage.get("imagefabric.civitai.nsfw") === "true" }) },
  ),
  models: createPreferences("hfabric.preferences.models", { pane: "all" }),
  downloads: createPreferences(
    "hfabric.preferences.downloads",
    {
      showAdvanced: false,
      installedOpen: false,
      source: "hf" as "hf" | "civitai" | "url",
      kind: "llm",
      filename: "",
      url: "",
    },
    {
      rules: {
        source: oneOf("hf", "civitai", "url"),
        kind: oneOf("llm", "image", "lora", "vision", "embed", "tts", "transcribe", "voice"),
      },
    },
  ),
  settings: createPreferences("hfabric.preferences.settings", { activeGroup: "", query: "" }),
  mask: createPreferences(
    "hfabric.preferences.mask",
    { tool: "brush" as "brush" | "lasso" | "erase", brush: 36, feather: 6 },
    { rules: { tool: oneOf("brush", "lasso", "erase"), brush: inRange(1, 512), feather: inRange(0, 128) } },
  ),
  system: createPreferences("hfabric.preferences.system", { showRss: false, showAdvanced: false }),
  notes: createPreferences("hfabric.preferences.notes", { query: "", selectedId: "" }),
  promptLibrary: createPreferences("hfabric.preferences.prompt-library", { query: "" }),
};
