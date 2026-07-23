// Chat persistence, sampling-field coercion, model labelling, and defensive
// import-bundle parsing.

import { storage } from "../lib/storage";
import type { ChatConversationImport, ChatImportMessage, Model, PresetImportItem } from "../types";

export type NumOrEmpty = number | "";
export type ImportBundle = { conversations: ChatConversationImport[]; presets: PresetImportItem[] };

export const DEFAULTS_KEY = "hfabric.chat.defaults";
export const PROMPT_HISTORY_KEY = "hfabric.chat.promptHistory";
export const promptHistoryLimit = 14;

export function loadDefaults(): {
  model_id?: string;
  temperature?: number;
  max_tokens?: number;
  image_tool?: boolean;
  document_tool?: boolean;
  rag_top_k?: number;
} {
  try {
    return JSON.parse(storage.get(DEFAULTS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function loadPromptHistory(): string[] {
  try {
    const parsed = JSON.parse(storage.get(PROMPT_HISTORY_KEY) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, promptHistoryLimit)
      : [];
  } catch {
    return [];
  }
}

export const numOrUndef = (v: NumOrEmpty): number | undefined => (v === "" ? undefined : Number(v));

export const parseStop = (s: string): string[] | undefined => {
  const items = s
    .split(/[\n,]/)
    .map((x) => x.trim())
    .filter(Boolean);
  return items.length ? items : undefined;
};

function modelHint(model: Model): string | undefined {
  const tags = [
    model.multimodal ? "vision" : "",
    model.quant ?? "",
    model.estimated_vram_gb ? `~${model.estimated_vram_gb.toFixed(1)} GB` : "",
    model.loaded ? "loaded" : model.warm ? "warm" : "",
  ].filter(Boolean);
  return tags.length ? tags.join(" / ") : undefined;
}

export function modelTitle(model: Model): string {
  const hint = modelHint(model);
  return hint ? `${model.name} | ${hint}` : model.name;
}

export function pickImageModel(models: Model[]): Model | undefined {
  const img = models.filter((m) => m.job_type === "image");
  return (
    img.find((m) => m.family === "flux2") ??
    img.find((m) => m.family === "z-image") ??
    img.find((m) => m.quant?.startsWith("nunchaku")) ??
    img.find((m) => !m.slow) ??
    img[0]
  );
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function stringOrNull(v: unknown): string | null | undefined {
  return typeof v === "string" ? v : v === null ? null : undefined;
}

function asRecord(v: unknown): Record<string, unknown> {
  return isRecord(v) ? v : {};
}

function isPresent<T>(v: T | null | undefined): v is T {
  return v != null;
}

export function hasActiveSelection(): boolean {
  const selection = window.getSelection?.();
  return Boolean(selection && !selection.isCollapsed && selection.toString());
}

function asMessageImport(v: unknown): ChatImportMessage | null {
  if (!isRecord(v)) return null;
  const role = v.role;
  if (role !== "user" && role !== "assistant" && role !== "system") return null;
  return {
    role,
    content: typeof v.content === "string" ? v.content : "",
    error: typeof v.error === "boolean" ? v.error : false,
    created_at: typeof v.created_at === "string" ? v.created_at : undefined,
  };
}

function asConversationImport(v: unknown): ChatConversationImport | null {
  if (!isRecord(v)) return null;
  const hasConversationShape =
    Array.isArray(v.messages) ||
    typeof v.title === "string" ||
    typeof v.system === "string" ||
    typeof v.model_id === "string";
  if (!hasConversationShape) return null;
  return {
    title: typeof v.title === "string" ? v.title : undefined,
    model_id: stringOrNull(v.model_id),
    system: stringOrNull(v.system),
    params: asRecord(v.params),
    created_at: typeof v.created_at === "string" ? v.created_at : undefined,
    updated_at: typeof v.updated_at === "string" ? v.updated_at : undefined,
    messages: Array.isArray(v.messages) ? v.messages.map(asMessageImport).filter(isPresent) : [],
  };
}

function asPresetImport(v: unknown): PresetImportItem | null {
  if (!isRecord(v)) return null;
  if (typeof v.name !== "string" || (v.type !== "llm" && v.type !== "image")) return null;
  return { name: v.name, type: v.type, params: asRecord(v.params) };
}

export function parseImportBundle(data: unknown): ImportBundle {
  if (Array.isArray(data)) {
    return {
      conversations: data.map(asConversationImport).filter(isPresent),
      presets: data.map(asPresetImport).filter(isPresent),
    };
  }

  if (!isRecord(data)) return { conversations: [], presets: [] };

  const conversations = Array.isArray(data.conversations)
    ? data.conversations.map(asConversationImport).filter(isPresent)
    : Array.isArray(data.messages)
      ? [asConversationImport(data)].filter(isPresent)
      : [];
  const presets = Array.isArray(data.presets)
    ? data.presets.map(asPresetImport).filter(isPresent)
    : [asPresetImport(data)].filter(isPresent);

  return { conversations, presets };
}

export function downloadJson(filename: string, payload: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
