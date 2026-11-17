import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Model, Preset } from "../types";
import { DEFAULT_IMAGE_SETTINGS } from "./imageComposerHelpers";
import { useImageComposerController } from "./useImageComposerController";

const mocks = vi.hoisted(() => ({ createJobs: vi.fn() }));
vi.mock("../api/client", () => ({ api: mocks }));
vi.mock("./useImageDefaultSettings", () => ({ useImageDefaultSettings: () => DEFAULT_IMAGE_SETTINGS }));
afterEach(cleanup);
beforeEach(() => { localStorage.clear(); mocks.createJobs.mockReset().mockResolvedValue([]); });

const models = ["small", "large"].map((id) => ({
  id, name: id, family: "flux2", job_type: "image", loaded: false, size_bytes: 1,
  quant: "bnb-nf4", quant_options: ["none", "bnb-nf4", "bnb-fp4"],
} as Model));
const props = { models, loras: [], presets: [] as Preset[], onPresetsChanged: vi.fn(), promptDraft: "mountains", setPromptDraft: vi.fn() };

it("remembers precision per model and snapshots it into each queued request", async () => {
  const { result } = renderHook(() => useImageComposerController(props));
  act(() => result.current.setImgModel("small"));
  act(() => result.current.setImageQuant("none"));
  await act(() => result.current.generate());
  expect(mocks.createJobs.mock.lastCall?.[0][0].params.image_quant).toBe("none");
  act(() => result.current.setImgModel("large"));
  expect(result.current.imageQuant).toBe("");
  act(() => result.current.setImageQuant("bnb-fp4"));
  await act(() => result.current.generate());
  expect(mocks.createJobs.mock.lastCall?.[0][0].params.image_quant).toBe("bnb-fp4");
  act(() => result.current.setImgModel("small"));
  expect(result.current.imageQuant).toBe("none");
});

it("restores precision from a preset without changing another model", async () => {
  const { result } = renderHook(() => useImageComposerController({ ...props, presets: [{
    id: "preset", name: "Native", type: "image", params: { model_id: "small", image_quant: "none", prompt: "forest" },
  } as Preset] }));
  act(() => result.current.setPresetId("preset"));
  act(() => result.current.applyPreset());
  expect(result.current.imgModel).toBe("small");
  expect(result.current.imageQuant).toBe("none");
  act(() => result.current.setImgModel("large"));
  expect(result.current.imageQuant).toBe("");
});
