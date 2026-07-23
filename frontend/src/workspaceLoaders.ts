import type { View } from "./workspaces";

export const loadChat = () => import("./components/ChatPanel");
export const loadCode = () => import("./components/CodePanel");
export const loadEdit = () => import("./components/EditWorkspace");
export const loadImages = () => import("./components/ImageComposer");
export const loadGallery = () => import("./components/Gallery");
export const loadModels = () => import("./components/ModelManager");
export const loadNotes = () => import("./components/NotesPanel");
export const loadQueue = () => import("./components/QueuePanel");
export const loadResult = () => import("./components/ResultPreview");
export const loadRag = () => import("./components/RagPanel");
export const loadSettings = () => import("./components/SettingsPanel");
export const loadSystem = () => import("./components/SystemPanel");
export const loadTranscription = () => import("./components/TranscriptionPanel");
export const loadTts = () => import("./components/TtsPanel");
export const loadVoice = () => import("./components/VoicePanel");
export const loadVideo = () => import("./components/VideoComposer");

const workspaceLoaders: Partial<Record<View, () => Promise<unknown>>> = {
  images: async () => Promise.all([loadImages(), loadResult(), loadQueue(), loadEdit()]),
  video: async () => Promise.all([loadVideo(), loadQueue()]),
  history: async () => Promise.all([loadGallery(), loadVideo()]),
  llm: loadChat,
  notes: loadNotes,
  tts: loadTts,
  transcription: loadTranscription,
  code: loadCode,
  rag: loadRag,
  voice: loadVoice,
  models: loadModels,
  system: loadSystem,
  settings: loadSettings,
};

export function prefetchWorkspace(view: View) {
  const loader = workspaceLoaders[view];
  if (!loader) return;
  void loader().catch((error: unknown) => {
    console.warn(`Could not prefetch ${view} workspace`, error);
  });
}
