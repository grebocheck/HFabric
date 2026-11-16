import { afterEach, describe, expect, it } from "vitest";

import {
  chatSampling,
  conversationSettings,
  createChatSettings,
  DEFAULTS_KEY,
  loadDefaults,
  loadPromptHistory,
  modelTitle,
  numOrUndef,
  parseImportBundle,
  parseStop,
  pickImageModel,
  personaSettings,
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
    expect(numOrUndef(Number.NaN)).toBeUndefined();
    expect(numOrUndef(Infinity)).toBeUndefined();
  });

  it("parseStop splits on commas/newlines and trims, else undefined", () => {
    expect(parseStop("")).toBeUndefined();
    expect(parseStop("  ")).toBeUndefined();
    expect(parseStop("</s>, ###\nEND")).toEqual(["</s>", "###", "END"]);
  });
});

describe("chat settings drafts", () => {
  afterEach(() => localStorage.clear());

  it.each(["null", "[]", '"text"', "42", "{invalid"])(
    "recovers safe defaults from %s in browser storage",
    (raw) => {
      localStorage.setItem(DEFAULTS_KEY, raw);
      expect(createChatSettings()).toMatchObject({
        modelId: "",
        temperature: 0.8,
        maxTokens: 4096,
        imageTool: false,
      });
    },
  );

  it("filters invalid saved fields while keeping valid preferences", () => {
    localStorage.setItem(
      DEFAULTS_KEY,
      JSON.stringify({
        model_id: 4,
        temperature: "hot",
        max_tokens: 2048,
        image_tool: "false",
        document_tool: true,
        rag_top_k: null,
      }),
    );
    expect(loadDefaults()).toMatchObject({ max_tokens: 2048, document_tool: true });
    expect(createChatSettings()).toMatchObject({
      modelId: "",
      temperature: 0.8,
      maxTokens: 2048,
      imageTool: false,
      documentTool: true,
      ragTopK: 5,
    });
  });

  it("restores conversation-specific advanced settings without inheriting the previous seed", () => {
    const current = { ...createChatSettings(), seed: 91, topP: 0.7, stop: "previous" };
    const next = conversationSettings(current, {
      id: "next",
      title: "Next",
      model_id: "llm",
      system: "System",
      params: { top_k: 12, stop: ["END", 7], document_tool: true },
      created_at: "",
      updated_at: "",
    });
    expect(next).toMatchObject({
      modelId: "llm",
      system: "System",
      seed: "",
      topP: "",
      topK: 12,
      stop: "END",
      imageTool: false,
      documentTool: true,
    });
    expect(chatSampling(next).seed).toBeUndefined();
  });

  it("round-trips persona sampling, including a zero seed, without changing model or tool choices", () => {
    const original = {
      ...createChatSettings(),
      modelId: "chosen",
      system: "  concise  ",
      seed: 0,
      topP: 0.9,
      topK: 15,
      minP: 0.05,
      repeatPenalty: 1.1,
      stop: "END, STOP",
      imageTool: true,
    };
    const payload = chatSampling(original);
    const restored = personaSettings({ ...createChatSettings(), modelId: "other", imageTool: true }, payload);
    expect(chatSampling(restored)).toEqual(payload);
    expect(restored).toMatchObject({ modelId: "other", seed: 0, imageTool: true });
    expect(personaSettings(restored, {}).seed).toBe("");
  });
});

describe("model labelling", () => {
  it("modelTitle appends quant / vram / state hints", () => {
    expect(modelTitle(model({ name: "SDXL", quant: "fp16", estimated_vram_gb: 11, loaded: true }))).toBe(
      "SDXL | fp16 / ~11.0 GB / loaded",
    );
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
