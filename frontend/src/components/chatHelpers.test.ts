import { afterEach, describe, expect, it } from "vitest";

import {
  loadPromptHistory,
  modelTitle,
  numOrUndef,
  parseImportBundle,
  parseStop,
  pickImageModel,
  PROMPT_HISTORY_KEY,
} from "./chatHelpers";
import type { Model } from "../types";

function model(over: Partial<Model> = {}): Model {
  return {
    id: "m",
    name: "M",
    family: "sdxl",
    job_type: "image",
    size_bytes: 0,
    loaded: false,
    warm: false,
    slow: false,
    ...over,
  } as Model;
}

describe("sampling field coercion", () => {
  it("numOrUndef maps empty string to undefined and keeps numbers", () => {
    expect(numOrUndef("")).toBeUndefined();
    expect(numOrUndef(0)).toBe(0);
    expect(numOrUndef(0.7)).toBe(0.7);
  });

  it("parseStop splits on commas/newlines and trims, else undefined", () => {
    expect(parseStop("")).toBeUndefined();
    expect(parseStop("  ")).toBeUndefined();
    expect(parseStop("</s>, ###\nEND")).toEqual(["</s>", "###", "END"]);
  });
});

describe("model labelling", () => {
  it("modelTitle appends quant / vram / state hints", () => {
    expect(modelTitle(model({ name: "SDXL", quant: "fp16", estimated_vram_gb: 11, loaded: true })))
      .toBe("SDXL | fp16 / ~11.0 GB / loaded");
    expect(modelTitle(model({ name: "Bare" }))).toBe("Bare");
  });

  it("pickImageModel prefers flux2 > nunchaku > non-slow > first", () => {
    const flux2 = model({ id: "f2", family: "flux2" });
    const nun = model({ id: "n", quant: "nunchaku-fp4" });
    const slow = model({ id: "s", slow: true });
    expect(pickImageModel([slow, nun, flux2])?.id).toBe("f2");
    expect(pickImageModel([slow, nun])?.id).toBe("n");
    expect(pickImageModel([slow, model({ id: "ok" })])?.id).toBe("ok");
    expect(pickImageModel([model({ job_type: "llm" })])).toBeUndefined();
  });
});

describe("parseImportBundle", () => {
  it("reads a {conversations, presets} object", () => {
    const bundle = parseImportBundle({
      conversations: [{ title: "C", messages: [{ role: "user", content: "hi" }] }],
      presets: [{ name: "P", type: "llm", params: { temperature: 0.5 } }],
    });
    expect(bundle.conversations).toHaveLength(1);
    expect(bundle.conversations[0].title).toBe("C");
    expect(bundle.conversations[0].messages[0]).toMatchObject({ role: "user", content: "hi" });
    expect(bundle.presets[0]).toMatchObject({ name: "P", type: "llm" });
  });

  it("treats a bare conversation object as a single import", () => {
    const bundle = parseImportBundle({ title: "Solo", messages: [] });
    expect(bundle.conversations).toHaveLength(1);
    expect(bundle.presets).toHaveLength(0);
  });

  it("drops malformed entries defensively", () => {
    const bundle = parseImportBundle([
      { role: "nonsense" },
      { name: "ok", type: "image", params: {} },
      42,
      null,
    ]);
    expect(bundle.presets).toHaveLength(1);
    expect(bundle.conversations).toHaveLength(0);
  });

  it("returns empty bundle for non-objects", () => {
    expect(parseImportBundle(123)).toEqual({ conversations: [], presets: [] });
    expect(parseImportBundle("x")).toEqual({ conversations: [], presets: [] });
  });
});

describe("loadPromptHistory", () => {
  afterEach(() => localStorage.clear());

  it("returns [] when empty or corrupt", () => {
    expect(loadPromptHistory()).toEqual([]);
    localStorage.setItem(PROMPT_HISTORY_KEY, "{not json");
    expect(loadPromptHistory()).toEqual([]);
  });

  it("reads strings and caps the length", () => {
    const many = Array.from({ length: 30 }, (_, i) => `p${i}`);
    localStorage.setItem(PROMPT_HISTORY_KEY, JSON.stringify(many));
    const got = loadPromptHistory();
    expect(got.length).toBe(14);
    expect(got[0]).toBe("p0");
  });
});
