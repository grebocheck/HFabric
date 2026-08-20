import { describe, expect, it } from "vitest";

import type { Model } from "../types";
import {
  buildEditJobParams,
  DEFAULT_EDIT_DRAFT,
  editDraftPatchFromParams,
  editModeFromParams,
  round64,
  supportsEditMode,
} from "./editWorkspaceHelpers";

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

  it("restores a bounded edit draft in one pass", () => {
    expect(editDraftPatchFromParams({
      edit_mode: "controlnet",
      prompt: "  recolor the jacket  ",
      width: 1000,
      height: 1080,
      steps: 0,
      strength: 4,
      control_type: "invalid",
      outpaint_left: -20,
    }, { width: 1024, height: 1024 }, "sdxl")).toMatchObject({
      mode: "controlnet",
      prompt: "recolor the jacket",
      width: 1024,
      height: 1088,
      steps: 1,
      strength: 1,
      controlType: "canny",
      outpaint: { left: 0 },
    });
  });

  it("builds mode-specific queue params from the draft", () => {
    const params = buildEditJobParams({
      ...DEFAULT_EDIT_DRAFT,
      mode: "controlnet",
      prompt: "  add dramatic light  ",
      width: 1000,
      selectedLoras: [{ id: "detail", weight: 3 }],
    }, { sourceToken: "a".repeat(32), maskToken: "b".repeat(32), family: "sdxl" });

    expect(params).toMatchObject({
      prompt: "add dramatic light",
      width: 1024,
      edit_mode: "controlnet",
      init_image: "a".repeat(32),
      mask_image: "b".repeat(32),
      control_image: "a".repeat(32),
      control_type: "canny",
      loras: [{ id: "detail", weight: 2 }],
    });
  });
});
