import { describe, expect, it } from "vitest";

import type { Model } from "../types";
import { editModeFromParams, round64, supportsEditMode } from "./EditWorkspace";

function model(family: Model["family"]): Model {
  return {
    id: family,
    name: family,
    family,
    job_type: "image",
    size_bytes: 0,
    loaded: false,
    warm: false,
    available: true,
    runtime_mode: "stub",
    compatibility_warnings: [],
    recommendation: "neutral",
  };
}

describe("Edit workspace support matrix", () => {
  it("gates latent, mask, instruction, and ControlNet modes by family", () => {
    expect(supportsEditMode(model("qwen-image"), "img2img")).toBe(true);
    expect(supportsEditMode(model("z-image"), "inpaint")).toBe(true);
    expect(supportsEditMode(model("anima"), "inpaint")).toBe(false);
    expect(supportsEditMode(model("qwen-image-edit"), "instruction")).toBe(true);
    expect(supportsEditMode(model("flux-kontext"), "instruction")).toBe(true);
    expect(supportsEditMode(model("sdxl"), "controlnet")).toBe(true);
    expect(supportsEditMode(model("flux"), "controlnet")).toBe(false);
  });

  it("rounds source and outpaint dimensions to VAE-safe multiples", () => {
    expect(round64(33)).toBe(64);
    expect(round64(1000)).toBe(1024);
  });

  it("restores valid edit modes from History metadata", () => {
    expect(editModeFromParams({ edit_mode: "controlnet" })).toBe("controlnet");
    expect(editModeFromParams({ edit_mode: "instruction" })).toBe("instruction");
    expect(editModeFromParams({ edit_mode: "unknown" })).toBe("img2img");
  });
});
