import { expect, test } from "@playwright/test";
import { installApiStub } from "./support/apiStub";

test("Chat sampling and editor parameters survive reload without being replaced by initial defaults", async ({
  page,
}) => {
  const conversation = {
    id: "chat",
    title: "Saved chat",
    model_id: "llm",
    params: { seed: 41 },
    system: null,
    messages: [],
  };
  await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/models": {
        body: [
          { id: "image-a", name: "Image A", family: "sdxl", job_type: "image", available: true },
          { id: "image-b", name: "Image B", family: "sdxl", job_type: "image", available: true },
          { id: "llm", name: "LLM", family: "gguf", job_type: "llm", available: true },
        ],
      },
      "/api/chat/conversations": { body: [conversation] },
      "/api/chat/conversations/chat": { body: conversation },
      "/api/llm/config": { body: { ctx: 8192, backend: "default", backends: [], context_types: [] } },
      "/api/llm/server": { body: { enabled: false } },
    },
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Edit", exact: true }).click();
  const model = page.getByRole("combobox", { name: "Model", exact: true });
  await model.click();
  await page.getByRole("option", { name: /Image B/ }).click();
  await page.getByRole("spinbutton", { name: "Steps", exact: true }).fill("47");
  await page.getByPlaceholder("Describe what should change...").fill("Retained edit instruction");
  await page.reload();
  await expect(model).toContainText("Image B");
  await expect(page.getByRole("spinbutton", { name: "Steps", exact: true })).toHaveValue("47");
  await expect(page.getByPlaceholder("Describe what should change...")).toHaveValue(
    "Retained edit instruction",
  );
  await page.getByRole("tab", { name: "LLM", exact: true }).click();
  await page.getByRole("button", { name: "Advanced sampling" }).click();
  await expect(page.getByLabel("seed", { exact: true })).toHaveValue("41");
  await page.getByLabel("seed", { exact: true }).fill("0");
  await page.getByLabel("top_p", { exact: true }).fill("0.7");
  await page.getByPlaceholder("optional — sets the assistant's behavior").fill("Retained system instruction");
  await page.reload();
  await expect(page.getByLabel("seed", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("top_p", { exact: true })).toHaveValue("0.7");
  await expect(page.getByPlaceholder("optional — sets the assistant's behavior")).toHaveValue(
    "Retained system instruction",
  );
});

test("Voice restores the selected model and unapplied tuning after navigation and reload", async ({
  page,
}) => {
  const models = ["first", "second"].map((id) => ({
    id,
    name: `Voice ${id}`,
    slot: id,
    type: "rvc",
    f0: true,
    has_index: true,
  }));
  const status = {
    settings: {},
    models,
    ready: true,
    stub: true,
    live: false,
    assets: [],
    metrics: {},
    audio_devices: { inputs: [], outputs: [] },
    recording: { active: false },
    loaded_model: null,
  };
  const observed = await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/voice/engine/status": { body: status },
      "/api/voice/engine/presets": { body: [] },
    },
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Voice", exact: true }).click();
  const model = page.getByRole("combobox", { name: "Voice model", exact: true });
  await model.click();
  await page.getByRole("option", { name: /Voice second/ }).click();
  const pitch = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Tuning", exact: true }) })
    .getByRole("slider", { name: "Pitch", exact: true });
  await pitch.fill("11");
  await expect(page.getByText("unsaved tuning", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Images", exact: true }).click();
  await page.getByRole("tab", { name: "Voice", exact: true }).click();
  await expect(pitch).toHaveValue("11");
  await page.reload();
  await expect(page.getByRole("tab", { name: "Voice", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(pitch).toHaveValue("11");
  await expect(model).toContainText("Voice second");
  await expect(page.getByText("unsaved tuning", { exact: true })).toBeVisible();
  expect(observed.filter(({ method, path }) => method === "POST" && path.startsWith("/api/voice/"))).toEqual(
    [],
  );
});

test("Video, TTS and Transcribe retain parameters and drafts through reload", async ({ page }) => {
  await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/models": {
        body: [{ id: "ltx", name: "LTX", family: "ltx-video", job_type: "video", available: true }],
      },
      "/api/tts/status": { body: { models: [], ready: false } },
      "/api/transcription/status": { body: { models: [], engines: {}, ready: false } },
    },
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Video", exact: true }).click();
  await page.getByRole("textbox", { name: "Video prompt" }).fill("Retained video draft");
  await page.getByRole("spinbutton", { name: "Steps", exact: true }).fill("23");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Video prompt" })).toHaveValue("Retained video draft");
  await expect(page.getByRole("spinbutton", { name: "Steps", exact: true })).toHaveValue("23");
  await page.getByRole("tab", { name: "TTS", exact: true }).click();
  const text = page.locator("#workspace-panel-tts textarea");
  await text.fill("Retained narration");
  await page.reload();
  await expect(text).toHaveValue("Retained narration");
  await page.getByRole("tab", { name: "Transcribe", exact: true }).click();
  await page.getByRole("textbox", { name: "Language", exact: true }).fill("uk");
  await page.getByRole("textbox", { name: "Prompt", exact: true }).fill("Retained transcription context");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Language", exact: true })).toHaveValue("uk");
  await expect(page.getByRole("textbox", { name: "Prompt", exact: true })).toHaveValue(
    "Retained transcription context",
  );
});
