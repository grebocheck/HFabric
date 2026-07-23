export const WORKSPACES = [
  { id: "images", label: "Images" },
  { id: "video", label: "Video" },
  { id: "history", label: "History" },
  { id: "llm", label: "LLM" },
  { id: "notes", label: "Notes" },
  { id: "tts", label: "TTS" },
  { id: "transcription", label: "Transcribe" },
  { id: "code", label: "Code" },
  { id: "rag", label: "RAG" },
  { id: "voice", label: "Voice" },
  { id: "models", label: "Models" },
  { id: "system", label: "System" },
  { id: "settings", label: "Settings" },
] as const;

export type View = (typeof WORKSPACES)[number]["id"];

export const VIEW_IDS = WORKSPACES.map(({ id }) => id) as readonly View[];
