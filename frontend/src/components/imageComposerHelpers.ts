// Image-composer persistence, model ranking, defaults, and LoRA compatibility.

import { storage } from "../lib/storage";
import type { ComposerApply, ImageItem, Lora, Model } from "../types";

export const STORE_KEY = "hfabric.image.composer";
export const PROMPT_HISTORY_KEY = "hfabric.image.promptHistory";
export const promptHistoryLimit = 14;

export const DEFAULT_STEPS = 28;
export const DEFAULT_GUIDANCE = 3.5;
export const DEFAULT_SIZE = 1024;
const ANIMA_STEPS = 30;
const ANIMA_GUIDANCE = 4.0;
const ANIMA_SIZE = 1024;
const FLUX2_STEPS = 6;
const FLUX2_GUIDANCE = 4.0;
const FLUX2_SIZE = 768;
const QWEN_IMAGE_STEPS = 50;
const QWEN_IMAGE_GUIDANCE = 4.0;
const QWEN_IMAGE_SIZE = 1328;
const Z_IMAGE_TURBO_STEPS = 9;
const Z_IMAGE_TURBO_GUIDANCE = 0.0;
const Z_IMAGE_BASE_STEPS = 50;
const Z_IMAGE_BASE_GUIDANCE = 4.0;
const Z_IMAGE_SIZE = 1024;

export type ImageFamilyDefaults = { steps: number; guidance: number; width: number; height: number };
export type ImageDefaultSettings = {
  default_steps: number;
  default_guidance: number;
  default_width: number;
  default_height: number;
  anima_default_steps: number;
  anima_default_guidance: number;
  anima_default_width: number;
  anima_default_height: number;
  flux2_default_steps: number;
  flux2_default_guidance: number;
  flux2_default_width: number;
  flux2_default_height: number;
  qwen_image_default_steps: number;
  qwen_image_default_guidance: number;
  qwen_image_default_width: number;
  qwen_image_default_height: number;
  qwen_image_edit_default_steps: number;
  qwen_image_edit_default_guidance: number;
  flux_kontext_default_steps: number;
  flux_kontext_default_guidance: number;
  z_image_default_steps: number;
  z_image_default_guidance: number;
  z_image_base_default_steps: number;
  z_image_base_default_guidance: number;
  z_image_default_width: number;
  z_image_default_height: number;
};

export const DEFAULT_IMAGE_SETTINGS: ImageDefaultSettings = {
  default_steps: DEFAULT_STEPS,
  default_guidance: DEFAULT_GUIDANCE,
  default_width: DEFAULT_SIZE,
  default_height: DEFAULT_SIZE,
  anima_default_steps: ANIMA_STEPS,
  anima_default_guidance: ANIMA_GUIDANCE,
  anima_default_width: ANIMA_SIZE,
  anima_default_height: ANIMA_SIZE,
  flux2_default_steps: FLUX2_STEPS,
  flux2_default_guidance: FLUX2_GUIDANCE,
  flux2_default_width: FLUX2_SIZE,
  flux2_default_height: FLUX2_SIZE,
  qwen_image_default_steps: QWEN_IMAGE_STEPS,
  qwen_image_default_guidance: QWEN_IMAGE_GUIDANCE,
  qwen_image_default_width: QWEN_IMAGE_SIZE,
  qwen_image_default_height: QWEN_IMAGE_SIZE,
  qwen_image_edit_default_steps: 40,
  qwen_image_edit_default_guidance: 4,
  flux_kontext_default_steps: 28,
  flux_kontext_default_guidance: 2.5,
  z_image_default_steps: Z_IMAGE_TURBO_STEPS,
  z_image_default_guidance: Z_IMAGE_TURBO_GUIDANCE,
  z_image_base_default_steps: Z_IMAGE_BASE_STEPS,
  z_image_base_default_guidance: Z_IMAGE_BASE_GUIDANCE,
  z_image_default_width: Z_IMAGE_SIZE,
  z_image_default_height: Z_IMAGE_SIZE,
};

export function mergeImageDefaultSettings(
  values: Record<string, unknown> | undefined,
  current: ImageDefaultSettings = DEFAULT_IMAGE_SETTINGS,
): ImageDefaultSettings {
  const next = { ...current };
  if (!values) return next;
  for (const key of Object.keys(next) as (keyof ImageDefaultSettings)[]) {
    const value = values[key];
    if (typeof value === "number" && Number.isFinite(value)) next[key] = value;
  }
  return next;
}

export function imageFamilyDefaults(
  family: string | undefined,
  model?: Model,
  settings: ImageDefaultSettings = DEFAULT_IMAGE_SETTINGS,
): ImageFamilyDefaults | undefined {
  if (family === "anima") {
    return {
      steps: settings.anima_default_steps,
      guidance: settings.anima_default_guidance,
      width: settings.anima_default_width,
      height: settings.anima_default_height,
    };
  }
  if (family === "flux2") {
    return {
      steps: settings.flux2_default_steps,
      guidance: settings.flux2_default_guidance,
      width: settings.flux2_default_width,
      height: settings.flux2_default_height,
    };
  }
  if (family === "qwen-image") {
    return {
      steps: settings.qwen_image_default_steps,
      guidance: settings.qwen_image_default_guidance,
      width: settings.qwen_image_default_width,
      height: settings.qwen_image_default_height,
    };
  }
  if (family === "qwen-image-edit") {
    return {
      steps: settings.qwen_image_edit_default_steps,
      guidance: settings.qwen_image_edit_default_guidance,
      width: settings.qwen_image_default_width,
      height: settings.qwen_image_default_height,
    };
  }
  if (family === "flux-kontext") {
    return {
      steps: settings.flux_kontext_default_steps,
      guidance: settings.flux_kontext_default_guidance,
      width: settings.default_width,
      height: settings.default_height,
    };
  }
  if (family === "z-image") {
    if (model && !isZImageTurbo(model)) {
      return {
        steps: settings.z_image_base_default_steps,
        guidance: settings.z_image_base_default_guidance,
        width: settings.z_image_default_width,
        height: settings.z_image_default_height,
      };
    }
    return {
      steps: settings.z_image_default_steps,
      guidance: settings.z_image_default_guidance,
      width: settings.z_image_default_width,
      height: settings.z_image_default_height,
    };
  }
  return undefined;
}

const knownStepDefaults = [
  DEFAULT_STEPS,
  ANIMA_STEPS,
  FLUX2_STEPS,
  QWEN_IMAGE_STEPS,
  Z_IMAGE_TURBO_STEPS,
  Z_IMAGE_BASE_STEPS,
];
const knownGuidanceDefaults = [
  DEFAULT_GUIDANCE,
  ANIMA_GUIDANCE,
  FLUX2_GUIDANCE,
  QWEN_IMAGE_GUIDANCE,
  Z_IMAGE_TURBO_GUIDANCE,
  Z_IMAGE_BASE_GUIDANCE,
];
const knownSizeDefaults = [DEFAULT_SIZE, ANIMA_SIZE, FLUX2_SIZE, QWEN_IMAGE_SIZE, Z_IMAGE_SIZE];

export const isKnownStepDefault = (value: number): boolean => knownStepDefaults.includes(value);
export const isKnownGuidanceDefault = (value: number): boolean => knownGuidanceDefaults.includes(value);
export const isKnownSizeDefault = (value: number): boolean => knownSizeDefaults.includes(value);

export type LoraSelection = { id: string; weight: number };

// Which of the auto-managed numeric fields the user has explicitly edited.
// Untouched fields follow the selected family / server defaults; touched fields
// are preserved across remounts (tab switches), family changes, and default
// changes. This replaces the old "value equals a known default number" guess,
// which mis-fired whenever a user-chosen value collided with another family's
// default (e.g. 50 steps on SDXL == QWEN_IMAGE_STEPS) and got reset on remount.
export type TouchedFields = { steps?: boolean; guidance?: boolean; width?: boolean; height?: boolean };

export type SavedComposer = {
  imgModel?: string;
  negative?: string;
  steps?: number;
  guidance?: number;
  width?: number;
  height?: number;
  seed?: number;
  batch?: number;
  count?: number;
  selectedLoras?: LoraSelection[];
  presetId?: string;
  touched?: TouchedFields;
};

// Migration for state saved before touch-tracking existed: if a saved value is
// not one of the known defaults it must have been customized, so treat it as
// touched. Magic-number customizations can't be recovered (one-time snap to the
// default), which matches the previous behavior anyway.
export function inferTouched(saved: SavedComposer): TouchedFields {
  if (saved.touched) return saved.touched;
  return {
    steps: saved.steps !== undefined && !isKnownStepDefault(saved.steps),
    guidance: saved.guidance !== undefined && !isKnownGuidanceDefault(saved.guidance),
    width: saved.width !== undefined && !isKnownSizeDefault(saved.width),
    height: saved.height !== undefined && !isKnownSizeDefault(saved.height),
  };
}

export function readSaved(): SavedComposer {
  try {
    const raw = storage.get(STORE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const value = parsed as Record<string, unknown>;
    const saved: SavedComposer = {};
    if (typeof value.imgModel === "string") saved.imgModel = value.imgModel;
    if (typeof value.negative === "string") saved.negative = value.negative;
    for (const key of ["steps", "guidance", "width", "height", "seed", "batch", "count"] as const) {
      if (typeof value[key] === "number" && Number.isFinite(value[key])) saved[key] = value[key];
    }
    if (Array.isArray(value.selectedLoras)) {
      saved.selectedLoras = value.selectedLoras.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const selection = item as Record<string, unknown>;
        if (typeof selection.id !== "string" || !selection.id) return [];
        const weight = numberParam(selection.weight, 1);
        return [{ id: selection.id, weight: Math.max(-2, Math.min(2, weight)) }];
      });
    }
    if (typeof value.presetId === "string") saved.presetId = value.presetId;
    if (value.touched && typeof value.touched === "object" && !Array.isArray(value.touched)) {
      const touched = value.touched as Record<string, unknown>;
      saved.touched = Object.fromEntries(
        ["steps", "guidance", "width", "height"]
          .filter((key) => typeof touched[key] === "boolean")
          .map((key) => [key, touched[key]]),
      ) as TouchedFields;
    }
    return saved;
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

export function isNunchaku(model: Model | undefined): boolean {
  return Boolean(model?.quant?.startsWith("nunchaku"));
}

export function isZImageTurbo(model: Model | undefined): boolean {
  if (model?.family !== "z-image") return false;
  const text = `${model.id} ${model.name}`.toLowerCase();
  return isNunchaku(model) || text.includes("turbo");
}

export function isModelAvailable(model: Model | undefined): boolean {
  return Boolean(model && model.available !== false);
}

export function isLoraCompatible(lora: Lora, model: Model | undefined): boolean {
  return !model || !lora.family || lora.family === model.family;
}

export function formatSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

export function formatVram(model: Model): string {
  if (!model.estimated_vram_gb) return "";
  const prefix = model.slow ? ">=" : "~";
  return `${prefix}${model.estimated_vram_gb.toFixed(1)} GB`;
}

export function familyColor(family: string): string {
  if (family === "anima") return "bg-fuchsia-700/50 text-fuchsia-100";
  if (family === "flux2") return "bg-sky-700/50 text-sky-100";
  if (family === "qwen-image") return "bg-violet-700/50 text-violet-100";
  if (family === "qwen-image-edit") return "bg-violet-700/50 text-violet-100";
  if (family === "flux-kontext") return "bg-accent/55 text-accent-fg";
  if (family === "z-image") return "bg-cyan-700/50 text-cyan-100";
  if (family === "flux") return "bg-accent/55 text-accent-fg";
  if (family === "sdxl") return "bg-emerald-700/55 text-emerald-100";
  if (family === "gguf") return "bg-amber-700/50 text-amber-100";
  if (family === "ltx-video") return "bg-cyan-700/50 text-cyan-100";
  if (family === "wan-video") return "bg-violet-700/50 text-violet-100";
  if (family === "hunyuan-video") return "bg-indigo-700/50 text-indigo-100";
  if (family === "cogvideo") return "bg-sky-700/50 text-sky-100";
  return "bg-white/10 text-white/65";
}

export function numberParam(value: unknown, fallback: number): number {
  if (value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function boundedNumberParam(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
  { integer = false, multipleOf }: { integer?: boolean; multipleOf?: number } = {},
): number {
  let next = numberParam(value, fallback);
  if (integer) next = Math.trunc(next);
  if (multipleOf) next = Math.round(next / multipleOf) * multipleOf;
  return Math.max(minimum, Math.min(maximum, next));
}

export function parseLoraSelections(
  value: unknown,
  loras: Lora[],
  model: Model | undefined,
): LoraSelection[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const selections: LoraSelection[] = [];
  for (const item of value) {
    const id =
      typeof item === "string"
        ? item
        : item && typeof item === "object" && "id" in item && typeof item.id === "string"
          ? item.id
          : "";
    if (!id || seen.has(id)) continue;
    const lora = loras.find((candidate) => candidate.id === id);
    if (!lora || !isLoraCompatible(lora, model)) continue;
    const rawWeight = item && typeof item === "object" && "weight" in item ? item.weight : 1;
    const weight = Math.max(-2, Math.min(2, numberParam(rawWeight, 1)));
    selections.push({ id, weight });
    seen.add(id);
  }
  return selections;
}

export function imageModelRank(model: Model): number {
  if (!isModelAvailable(model)) return 99;
  if (model.family === "flux2" && isNunchaku(model)) return -1;
  if (model.family === "flux2") return 0;
  if (model.family === "flux" && isNunchaku(model)) return 0;
  if (model.family === "z-image") return 0;
  if (model.family === "qwen-image") return 1;
  if (!model.slow) return 1;
  return 2;
}

export function pickDefaultImageModel(models: Model[]): Model | undefined {
  const available = models.filter(isModelAvailable);
  return (
    available.find((m) => m.family === "flux" && isNunchaku(m)) ??
    available.find((m) => m.family === "z-image") ??
    available.find((m) => !m.slow) ??
    available[0]
  );
}

export function buildComposerApply(
  image: ImageItem,
  models: Model[],
  opts: { keepSeed: boolean; nonce?: number },
): ComposerApply {
  const modelName = typeof image.params?.model === "string" ? image.params.model : "";
  const model = models.find((m) => m.job_type === "image" && m.name === modelName);
  return {
    model_id: model?.id,
    params: { ...image.params, seed: opts.keepSeed ? (image.seed ?? -1) : -1 },
    nonce: opts.nonce ?? Date.now(),
  };
}
