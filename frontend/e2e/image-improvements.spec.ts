import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { installApiStub } from "./support/apiStub";

const pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jIYQAAAAASUVORK5CYII=";
const model = { id: "klein", name: "FLUX.2 Klein", family: "flux2", job_type: "image", size_bytes: 1, loaded: false,
  quant: "bnb-nf4", quant_options: ["none", "bnb-nf4", "bnb-fp4"], available: true };
const job = { type: "image", priority: 0, model_id: model.id, progress: 0, created_at: "2026-11-16T10:00:00Z", params: { prompt: "Queued image" } };
const images = ["First result", "Second result"].map((prompt, index) => ({
  id: `image-${index}`, job_id: `done-${index}`, family: "flux2", params: { prompt }, created_at: "2026-11-16T10:00:00Z",
  url: pixel, thumb_url: pixel, width: 768, height: 768, seed: index, tags: [],
}));

test("image precision is queued explicitly and completed queue images can be selected repeatedly", async ({ page }) => {
  await installApiStub(page, { welcomeSeen: true, routes: {
    "/api/models": { body: [model] }, "/api/images": { body: images },
    "/api/jobs": { body: [
      { ...job, id: "running", status: "running", progress: 0.42, progress_note: "Step 4 / 10" },
      { ...job, id: "queued-a", status: "queued", params: { prompt: "Queued A" } },
      { ...job, id: "queued-b", status: "queued", params: { prompt: "Queued B" } },
      { ...job, id: "done-1", status: "done", params: { prompt: "Second result" } },
    ] },
    "/api/jobs/plan": { body: { queued: 2, swaps: 0, current_model: model.name, steps: [
      { model_id: model.id, model: model.name, type: "image", count: 2, job_ids: ["queued-b", "queued-a"] },
    ] } },
    "POST /api/jobs": { body: [] },
    "POST /api/jobs/reorder": { body: { updated: 2 } },
  } });
  await page.goto("/");
  const precision = page.getByRole("combobox", { name: "Weight precision" });
  await precision.selectOption("none");
  await page.locator("#image-prompt").fill("New native-precision sample");
  const queued = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname === "/api/jobs");
  await page.getByRole("button", { name: "Queue generation" }).click();
  expect((await queued).postDataJSON()[0].params.image_quant).toBe("none");
  const queue = page.getByRole("region", { name: "Generation queue" });
  await expect(queue.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  await expect(queue.getByText("Step 4 / 10")).toBeVisible();
  const reorder = page.waitForRequest("**/api/jobs/reorder");
  await queue.getByRole("button", { name: "Move job 2 up" }).click();
  expect((await reorder).postDataJSON()).toEqual({ job_ids: ["queued-a", "queued-b"] });
  await queue.getByText("Completed · 1", { exact: true }).click();
  await queue.getByRole("button", { name: "Show result: Second result" }).click();
  const resultHeader = page.getByRole("heading", { name: "Result", exact: true }).locator("..");
  await expect(resultHeader.getByText("Second result", { exact: true })).toBeVisible();
  await page.getByTitle("First result", { exact: true }).click();
  await expect(resultHeader.getByText("First result", { exact: true })).toBeVisible();
  await queue.getByRole("button", { name: "Show result: Second result" }).click();
  await expect(resultHeader.getByText("Second result", { exact: true })).toBeVisible();
  const scan = await new AxeBuilder({ page }).include("#workspace-panel-images").analyze();
  expect(scan.violations.filter(({ impact }) => impact === "serious" || impact === "critical")).toEqual([]);
});

test("image controls, queue and grouped settings fit narrow and wide screens", async ({ page }) => {
  const values: Record<string, string | number> = { flux2_quant: "bnb-nf4", flux2_default_steps: 6, flux2_offload: "model" };
  const familyFields = [["anima", "Anima"], ["qwen_image", "Qwen Image"], ["qwen_image_edit", "Qwen Image Edit"], ["flux_kontext", "FLUX Kontext"], ["z_image", "Z-Image"]]
    .flatMap(([prefix, label]) => ["steps", "guidance", "width", "height"].map((field) => {
      const key = `${prefix}_default_${field}`;
      values[key] = field === "steps" ? 20 : field === "guidance" ? 4 : 1024;
      return { key, label: `${label} ${field}`, group: "family_defaults", kind: "integer", min: 1, max: 2048 };
    }));
  await installApiStub(page, { welcomeSeen: true, routes: {
    "/api/models": { body: [model] },
    "/api/jobs": { body: [{ ...job, id: "queued", status: "queued" }] },
    "/api/settings": { body: { stub_mode: true, counts: {}, acceleration: {}, memory: {} } },
    "/api/settings/overrides": { body: { values, path: "settings.json", groups: [{ id: "family_defaults", label: "Model defaults" }], schema: [
      { key: "flux2_quant", label: "FLUX.2 quant", group: "family_defaults", kind: "choice", choices: [] },
      { key: "flux2_default_steps", label: "FLUX.2 steps", group: "family_defaults", kind: "integer", min: 1, max: 150 },
      { key: "flux2_offload", label: "FLUX.2 offload", group: "family_defaults", kind: "choice", choices: [{ value: "model", label: "Model offload" }] },
      ...familyFields,
    ] } },
  } });
  for (const width of [360, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await page.getByRole("tab", { name: "Images", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Weight precision" })).toBeVisible();
    await page.getByRole("button", { name: "Move job 1 up" }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "Move job 1 up" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.getByRole("tab", { name: "Settings", exact: true }).click();
    await expect(page.getByRole("group", { name: "FLUX.2", exact: true })).toBeVisible();
    await expect(page.getByRole("spinbutton", { name: /FLUX.2 steps/ })).toBeVisible();
    await expect(page.getByText("FLUX.2 quant", { exact: true })).toHaveCount(0);
    const fields = page.getByRole("region", { name: "Setting fields", exact: true });
    await fields.hover();
    await page.mouse.wheel(0, 5000);
    await expect(page.getByRole("spinbutton", { name: /Z-Image height/ })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
});
