import type { Model } from "../types";
import {
  boundedNumberParam,
  isModelAvailable,
  normalizeImageRequest,
  type LoraSelection,
} from "./imageComposerHelpers";

export type EditMode = "img2img" | "inpaint" | "outpaint" | "instruction" | "controlnet";
export type OutpaintMargins = { left: number; right: number; top: number; bottom: number };
export type EditDraft = {
  mode: EditMode;
  prompt: string;
  negative: string;
  steps: number;
  guidance: number;
  width: number;
  height: number;
  seed: number;
  batch: number;
  strength: number;
  resizeMode: string;
  maskBlur: number;
  maskGrow: number;
  maskInvert: boolean;
  paddingCrop: number;
  outpaint: OutpaintMargins;
  controlType: string;
  controlScale: number;
  controlMask: boolean;
  selectedLoras: LoraSelection[];
};

export const EDIT_MODE_LABELS: Record<EditMode, string> = {
  img2img: "Img2img",
  inpaint: "Inpaint",
  outpaint: "Outpaint",
  instruction: "Instruction",
  controlnet: "ControlNet",
};

export const DEFAULT_EDIT_DRAFT: EditDraft = {
  mode: "img2img",
  prompt: "",
  negative: "",
  steps: 28,
  guidance: 3.5,
  width: 1024,
  height: 1024,
  seed: -1,
  batch: 1,
  strength: 0.6,
  resizeMode: "crop",
  maskBlur: 6,
  maskGrow: 0,
  maskInvert: false,
  paddingCrop: 32,
  outpaint: { left: 128, right: 128, top: 128, bottom: 128 },
  controlType: "canny",
  controlScale: 0.75,
  controlMask: false,
  selectedLoras: [],
};

const resizeModes = new Set(["crop", "pad", "stretch"]);
const controlTypes = new Set([
  "canny",
  "depth",
  "pose",
  "scribble",
  "union-canny",
  "union-depth",
  "union-pose",
  "union-scribble",
]);

export function editModeFromParams(params: Record<string, unknown>): EditMode {
  const candidate = typeof params.edit_mode === "string" ? params.edit_mode : "img2img";
  return candidate in EDIT_MODE_LABELS ? candidate as EditMode : "img2img";
}

export function supportsEditMode(model: Model, mode: EditMode): boolean {
  if (!isModelAvailable(model) || model.job_type !== "image") return false;
  if (mode === "instruction") return model.family === "qwen-image-edit" || model.family === "flux-kontext";
  if (mode === "controlnet") return model.family === "sdxl";
  if (mode === "inpaint" || mode === "outpaint") {
    return ["sdxl", "flux", "flux2", "qwen-image", "z-image"].includes(model.family);
  }
  return ["sdxl", "flux", "flux2", "qwen-image", "z-image", "anima"].includes(model.family);
}

export function editDraftPatchFromParams(
  params: Record<string, unknown>,
  fallbackSize: { width: number; height: number },
  family?: string,
): Partial<EditDraft> {
  const mode = editModeFromParams(params);
  const base = normalizeImageRequest({
    prompt: params.prompt,
    negative: params.negative,
    steps: params.steps ?? DEFAULT_EDIT_DRAFT.steps,
    guidance: params.guidance ?? DEFAULT_EDIT_DRAFT.guidance,
    width: params.width ?? fallbackSize.width,
    height: params.height ?? fallbackSize.height,
    seed: params.seed ?? DEFAULT_EDIT_DRAFT.seed,
    batch: params.batch_size ?? DEFAULT_EDIT_DRAFT.batch,
    loras: [],
  }, family);
  const margins = typeof params.outpaint === "object" && params.outpaint
    ? params.outpaint as Record<string, unknown>
    : params;
  const resizeMode = typeof params.resize_mode === "string" && resizeModes.has(params.resize_mode)
    ? params.resize_mode
    : DEFAULT_EDIT_DRAFT.resizeMode;
  const controlType = typeof params.control_type === "string" && controlTypes.has(params.control_type)
    ? params.control_type
    : DEFAULT_EDIT_DRAFT.controlType;
  return {
    mode,
    prompt: base.prompt,
    negative: base.negative ?? "",
    steps: base.steps,
    guidance: base.guidance,
    width: base.width,
    height: base.height,
    seed: base.seed,
    batch: base.batch_size,
    strength: boundedNumberParam(
      params.requested_strength ?? params.strength,
      DEFAULT_EDIT_DRAFT.strength,
      0.05,
      1,
    ),
    resizeMode,
    maskBlur: boundedNumberParam(params.mask_blur, DEFAULT_EDIT_DRAFT.maskBlur, 0, 128),
    maskGrow: boundedNumberParam(params.mask_grow, DEFAULT_EDIT_DRAFT.maskGrow, -128, 128, { integer: true }),
    maskInvert: Boolean(params.mask_invert),
    paddingCrop: boundedNumberParam(params.padding_mask_crop, DEFAULT_EDIT_DRAFT.paddingCrop, 0, 512, {
      integer: true,
    }),
    outpaint: {
      left: margin(margins.left ?? params.outpaint_left),
      right: margin(margins.right ?? params.outpaint_right),
      top: margin(margins.top ?? params.outpaint_top),
      bottom: margin(margins.bottom ?? params.outpaint_bottom),
    },
    controlType,
    controlScale: boundedNumberParam(params.control_scale, DEFAULT_EDIT_DRAFT.controlScale, 0, 2),
    controlMask: mode === "controlnet" && Boolean(params.mask_image ?? params.inpaint),
  };
}

export function buildEditJobParams(
  draft: EditDraft,
  context: { sourceToken: string; maskToken?: string; family?: string },
): Record<string, unknown> {
  const base = normalizeImageRequest({
    prompt: draft.prompt,
    negative: draft.negative,
    steps: draft.steps,
    guidance: draft.guidance,
    width: draft.width,
    height: draft.height,
    seed: draft.seed,
    batch: draft.batch,
    loras: draft.selectedLoras,
  }, context.family);
  const strength = draft.mode === "instruction" || (context.family === "flux2" && draft.mode === "img2img")
    ? undefined
    : boundedNumberParam(draft.strength, DEFAULT_EDIT_DRAFT.strength, 0.05, 1);
  return {
    ...base,
    edit_mode: draft.mode,
    init_image: context.sourceToken,
    mask_image: context.maskToken,
    strength,
    resize_mode: resizeModes.has(draft.resizeMode) ? draft.resizeMode : DEFAULT_EDIT_DRAFT.resizeMode,
    mask_blur: boundedNumberParam(draft.maskBlur, DEFAULT_EDIT_DRAFT.maskBlur, 0, 128),
    mask_grow: boundedNumberParam(draft.maskGrow, DEFAULT_EDIT_DRAFT.maskGrow, -128, 128, { integer: true }),
    mask_invert: draft.maskInvert,
    padding_mask_crop: boundedNumberParam(draft.paddingCrop, DEFAULT_EDIT_DRAFT.paddingCrop, 0, 512, {
      integer: true,
    }),
    outpaint_left: margin(draft.outpaint.left),
    outpaint_right: margin(draft.outpaint.right),
    outpaint_top: margin(draft.outpaint.top),
    outpaint_bottom: margin(draft.outpaint.bottom),
    control_image: draft.mode === "controlnet" ? context.sourceToken : undefined,
    control_type: draft.mode === "controlnet" && controlTypes.has(draft.controlType) ? draft.controlType : undefined,
    control_scale: draft.mode === "controlnet"
      ? boundedNumberParam(draft.controlScale, DEFAULT_EDIT_DRAFT.controlScale, 0, 2)
      : undefined,
  };
}

export function round64(value: number): number {
  return Math.max(64, Math.round(value / 64) * 64);
}

function margin(value: unknown): number {
  return boundedNumberParam(value, 128, 0, 1024, { integer: true });
}
