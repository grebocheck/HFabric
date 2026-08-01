import { afterEach, describe, expect, it } from "vitest";

import {
  boundedNumberParam,
  DEFAULT_IMAGE_SETTINGS,
  formatSize,
  formatVram,
  imageFamilyDefaults,
  imageModelRank,
  inferTouched,
  isKnownGuidanceDefault,
  isKnownSizeDefault,
  isKnownStepDefault,
  isLoraCompatible,
  isModelAvailable,
  isNunchaku,
  isZImageTurbo,
  mergeImageDefaultSettings,
  numberParam,
  parseLoraSelections,
  pickDefaultImageModel,
  readSaved,
  STORE_KEY,
} from "./imageComposerHelpers";
import type { Lora, Model } from "../types";

function model(over: Partial<Model> = {}): Model {
  return {
    id: "m", name: "M", family: "sdxl", job_type: "image",
    size_bytes: 0, loaded: false, warm: false, slow: false, ...over,
  } as Model;
}

describe("formatters", () => {
  it("formatSize switches MB/GB and blanks zero", () => {
    expect(formatSize(0)).toBe("");
    expect(formatSize(5 * 1024 ** 2)).toBe("5 MB");
    expect(formatSize(2 * 1024 ** 3)).toBe("2.0 GB");
  });

  it("formatVram marks slow models with >=", () => {
    expect(formatVram(model({ estimated_vram_gb: 9.8 }))).toBe("~9.8 GB");
    expect(formatVram(model({ estimated_vram_gb: 16, slow: true }))).toBe(">=16.0 GB");
    expect(formatVram(model({}))).toBe("");
  });

  it("numberParam falls back on non-finite input", () => {
    expect(numberParam("3", 0)).toBe(3);
    expect(numberParam("nope", 7)).toBe(7);
    expect(numberParam(undefined, 1)).toBe(1);
    expect(numberParam(null, 2)).toBe(2);
    expect(numberParam("", 3)).toBe(3);
  });

  it("boundedNumberParam normalizes values to the API contract", () => {
    expect(boundedNumberParam(129, 1024, 256, 2048, { integer: true, multipleOf: 64 })).toBe(256);
    expect(boundedNumberParam(1080, 1024, 256, 2048, { integer: true, multipleOf: 64 })).toBe(1088);
    expect(boundedNumberParam("bad", 28, 1, 150, { integer: true })).toBe(28);
  });
});

describe("model ranking & selection", () => {
  it("isNunchaku detects the quant prefix", () => {
    expect(isNunchaku(model({ quant: "nunchaku-fp4" }))).toBe(true);
    expect(isNunchaku(model({ quant: "fp16" }))).toBe(false);
    expect(isNunchaku(undefined)).toBe(false);
  });

  it("isZImageTurbo detects turbo names and Nunchaku Z-Image fast paths", () => {
    expect(isZImageTurbo(model({ family: "z-image", name: "Z-Image-Turbo" }))).toBe(true);
    expect(isZImageTurbo(model({ family: "z-image", quant: "nunchaku-fp4" }))).toBe(true);
    expect(isZImageTurbo(model({ family: "z-image", name: "Z-Image" }))).toBe(false);
    expect(isZImageTurbo(model({ family: "sdxl", name: "Z-Image-Turbo" }))).toBe(false);
  });

  it("isModelAvailable treats only explicit false as unavailable", () => {
    expect(isModelAvailable(model())).toBe(true);
    expect(isModelAvailable(model({ available: true }))).toBe(true);
    expect(isModelAvailable(model({ available: false }))).toBe(false);
    expect(isModelAvailable(undefined)).toBe(false);
  });

  it("imageModelRank orders flux2-nunchaku first and slow last", () => {
    expect(imageModelRank(model({ family: "flux2", quant: "nunchaku-fp4" }))).toBe(-1);
    expect(imageModelRank(model({ family: "flux2" }))).toBe(0);
    expect(imageModelRank(model({ family: "flux", quant: "nunchaku-fp4" }))).toBe(0);
    expect(imageModelRank(model({ family: "z-image" }))).toBe(0);
    expect(imageModelRank(model({ family: "qwen-image" }))).toBe(1);
    expect(imageModelRank(model({ family: "sdxl" }))).toBe(1);
    expect(imageModelRank(model({ family: "sdxl", slow: true }))).toBe(2);
  });

  it("pickDefaultImageModel prefers flux-nunchaku, then non-slow, then first", () => {
    const fluxNun = model({ id: "fn", family: "flux", quant: "nunchaku-fp4" });
    const slow = model({ id: "s", slow: true });
    expect(pickDefaultImageModel([slow, fluxNun])?.id).toBe("fn");
    expect(pickDefaultImageModel([slow, model({ id: "ok" })])?.id).toBe("ok");
    expect(pickDefaultImageModel([slow])?.id).toBe("s");
    expect(pickDefaultImageModel([model({ id: "off", available: false }), model({ id: "ok" })])?.id).toBe("ok");
    expect(pickDefaultImageModel([model({ id: "off", available: false })])).toBeUndefined();
  });

  it("isLoraCompatible matches family or passes when unconstrained", () => {
    const sdxlLora = { id: "l", name: "L", family: "sdxl" } as Lora;
    const anyLora = { id: "a", name: "A", family: null } as unknown as Lora;
    expect(isLoraCompatible(sdxlLora, model({ family: "sdxl" }))).toBe(true);
    expect(isLoraCompatible(sdxlLora, model({ family: "flux" }))).toBe(false);
    expect(isLoraCompatible(anyLora, model({ family: "flux" }))).toBe(true);
    expect(isLoraCompatible(sdxlLora, undefined)).toBe(true);
  });

  it("exposes family defaults for Anima, Qwen and Z-Image", () => {
    expect(imageFamilyDefaults("anima")).toMatchObject({ steps: 30, guidance: 4, width: 1024 });
    expect(imageFamilyDefaults("qwen-image")).toMatchObject({ steps: 50, guidance: 4, width: 1328 });
    expect(imageFamilyDefaults("z-image")).toMatchObject({ steps: 9, guidance: 0, width: 1024 });
    expect(imageFamilyDefaults("z-image", model({ family: "z-image", name: "Z-Image" }))).toMatchObject({ steps: 50, guidance: 4, width: 1024 });
    expect(imageFamilyDefaults("z-image", model({ family: "z-image", name: "Z-Image-Turbo" }))).toMatchObject({ steps: 9, guidance: 0, width: 1024 });
    expect(imageFamilyDefaults("sdxl")).toBeUndefined();
    expect(isKnownStepDefault(9)).toBe(true);
    expect(isKnownStepDefault(30)).toBe(true);
    expect(isKnownGuidanceDefault(0)).toBe(true);
    expect(isKnownSizeDefault(1328)).toBe(true);
  });

  it("uses validated server overrides for family defaults", () => {
    const settings = mergeImageDefaultSettings({
      flux2_default_steps: 11,
      flux2_default_width: 896,
      flux2_default_height: Number.NaN,
      qwen_image_default_guidance: "invalid",
    });
    expect(settings).toMatchObject({
      flux2_default_steps: 11,
      flux2_default_width: 896,
      flux2_default_height: DEFAULT_IMAGE_SETTINGS.flux2_default_height,
      qwen_image_default_guidance: DEFAULT_IMAGE_SETTINGS.qwen_image_default_guidance,
    });
    expect(imageFamilyDefaults("flux2", undefined, settings)).toEqual({
      steps: 11,
      guidance: 4,
      width: 896,
      height: 768,
    });
  });

  it("filters missing, duplicate, and incompatible LoRA selections", () => {
    const loras = [
      { id: "sdxl", name: "SDXL", family: "sdxl" },
      { id: "flux", name: "Flux", family: "flux" },
    ] as Lora[];
    expect(parseLoraSelections([
      { id: "sdxl", weight: 9 },
      { id: "sdxl", weight: 0.5 },
      { id: "flux", weight: 1 },
      "missing",
    ], loras, model({ family: "sdxl" }))).toEqual([{ id: "sdxl", weight: 2 }]);
  });
});

describe("inferTouched", () => {
  it("honors an explicit touched map when present", () => {
    expect(inferTouched({ touched: { steps: true } })).toEqual({ steps: true });
  });

  it("treats non-default saved values as touched (migration)", () => {
    // 35 steps / 2.0 guidance / 1536 px are not known defaults → user-customized.
    expect(inferTouched({ steps: 35, guidance: 2, width: 1536, height: 1536 })).toEqual({
      steps: true,
      guidance: true,
      width: true,
      height: true,
    });
  });

  it("treats known-default and absent saved values as untouched", () => {
    // 50 collides with QWEN_IMAGE_STEPS, so a pre-touch snapshot can't prove it
    // was customized; leave it untouched rather than guess wrong.
    expect(inferTouched({ steps: 50 })).toEqual({
      steps: false,
      guidance: false,
      width: false,
      height: false,
    });
    expect(inferTouched({})).toEqual({
      steps: false,
      guidance: false,
      width: false,
      height: false,
    });
  });
});

describe("readSaved", () => {
  afterEach(() => localStorage.clear());

  it("returns {} when absent or corrupt", () => {
    expect(readSaved()).toEqual({});
    localStorage.setItem(STORE_KEY, "{bad");
    expect(readSaved()).toEqual({});
  });

  it("sanitizes malformed persisted fields instead of trusting storage", () => {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      imgModel: 7,
      steps: "28",
      count: Number.POSITIVE_INFINITY,
      selectedLoras: [null, "bad", { id: "ok", weight: 9 }],
      touched: { steps: "yes", width: true },
    }));
    expect(readSaved()).toEqual({
      selectedLoras: [{ id: "ok", weight: 2 }],
      touched: { width: true },
    });
  });

  it("round-trips a saved composer snapshot", () => {
    localStorage.setItem(STORE_KEY, JSON.stringify({ imgModel: "x", steps: 12, count: 3 }));
    expect(readSaved()).toMatchObject({ imgModel: "x", steps: 12, count: 3 });
  });
});
