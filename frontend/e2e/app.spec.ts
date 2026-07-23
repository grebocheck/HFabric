import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { installApiStub } from "./support/apiStub";

async function expectNoSeriousAxeViolations(page: Page, include?: string) {
  let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
  if (include) builder = builder.include(include);
  const results = await builder.analyze();
  const violations = results.violations
    .filter(({ impact }) => impact === "serious" || impact === "critical")
    .map(({ id, impact, help, nodes }) => ({
      id,
      impact,
      help,
      nodes: nodes.map(({ target, html, failureSummary }) => ({
        target,
        html,
        failureSummary,
      })),
    }));
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
}

test("first-run welcome is accessible and persists its dismissal", async ({ page }) => {
  await installApiStub(page);
  await page.goto("/");

  const welcome = page.getByRole("dialog", { name: "Welcome to HFabric" });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByText("Images", { exact: true })).toBeVisible();
  await expect(welcome.getByText("LLM", { exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page, "[role=dialog]");

  await welcome.getByRole("button", { name: "Get started" }).click();
  await expect(welcome).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem("hfabric.welcome.seen"))).toBe("1");

  await page.reload();
  await expect(page.getByRole("dialog", { name: "Welcome to HFabric" })).toBeHidden();
});

test("workspace tabs select and label the active panel", async ({ page }) => {
  await installApiStub(page, { welcomeSeen: true });
  await page.goto("/");

  const workspaceTabs = page.getByRole("tablist", { name: "Workspaces" });
  const images = workspaceTabs.getByRole("tab", { name: "Images", exact: true });
  await expect(images).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#workspace-panel-images")).toHaveAttribute(
    "aria-labelledby",
    "workspace-tab-images",
  );

  const history = workspaceTabs.getByRole("tab", { name: "History" });
  await history.click();
  await expect(history).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#workspace-panel-history")).toBeVisible();

  const notes = workspaceTabs.getByRole("tab", { name: "Notes" });
  await notes.click();
  await expect(notes).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Notes" })).toBeVisible();
  await expectNoSeriousAxeViolations(page);

  const themeButton = page.getByTitle("Cycle theme");
  for (const [theme, accent] of [
    ["dim", "rgb(15, 118, 110)"],
    ["light", "rgb(49, 95, 206)"],
  ] as const) {
    await themeButton.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect
      .poll(() => notes.evaluate((element) => window.getComputedStyle(element).backgroundColor))
      .toBe(accent);
    await expectNoSeriousAxeViolations(page);
  }
});

test("token-required posture locks the UI and authenticates after unlock", async ({ page }) => {
  const observed = await installApiStub(page, {
    tokenRequired: true,
    welcomeSeen: true,
  });
  await page.goto("/");

  const lock = page.getByRole("dialog", { name: "API token required" });
  await expect(lock).toBeVisible();
  const unlock = lock.getByRole("button", { name: "Unlock" });
  await expect(unlock).toBeDisabled();

  await lock.getByLabel("API token").fill("test-token");
  await expect(unlock).toBeEnabled();
  await unlock.click();
  await expect(lock).toBeHidden();
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("hfabric.apiToken")))
    .toBe("test-token");
  await expect
    .poll(() => observed.some(({ authorization }) => authorization === "Bearer test-token"))
    .toBe(true);
});

test("welcome and workspace do not overflow a narrow mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await installApiStub(page);
  await page.goto("/");

  const welcome = page.getByRole("dialog", { name: "Welcome to HFabric" });
  await expect(welcome).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      })),
    )
    .toEqual({ documentWidth: 320, viewportWidth: 320 });

  await welcome.getByRole("button", { name: "Get started" }).click();
  const workspaces = page.getByRole("tablist", { name: "Workspaces" });
  await workspaces.getByRole("tab", { name: "History" }).click();
  await expect(page.locator("#workspace-panel-history")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      })),
    )
    .toEqual({ documentWidth: 320, viewportWidth: 320 });
});

test("canonical responsive widths remain free of horizontal overflow", async ({ page }) => {
  await installApiStub(page, { welcomeSeen: true });

  for (const width of [360, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width < 768 ? 720 : 900 });
    await page.goto("/");
    await expect(page.getByRole("tablist", { name: "Workspaces" })).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
        })),
      )
      .toEqual({ documentWidth: width, viewportWidth: width });
  }
});

test("images workspace queues a job and keeps result/history in sync", async ({ page }) => {
  const imageModel = {
    id: "sdxl-e2e",
    name: "SDXL E2E",
    family: "sdxl",
    job_type: "image",
    size_bytes: 1_000_000,
    loaded: false,
    available: true,
    compatibility_warnings: [],
  };
  const image = {
    id: "image-e2e",
    job_id: "job-done",
    family: "sdxl",
    params: { prompt: "E2E generated result", steps: 20, guidance: 4 },
    created_at: "2026-07-23T10:00:00Z",
    url: "/api/images/image-e2e/file",
    thumb_url: "/api/images/image-e2e/thumb",
    width: 768,
    height: 768,
    seed: 42,
    tags: [],
  };
  const queuedJob = {
    id: "job-queued",
    type: "image",
    status: "queued",
    priority: 1,
    model_id: imageModel.id,
    params: { prompt: "queued from e2e" },
    progress: 0,
    created_at: "2026-07-23T10:01:00Z",
  };
  const observed = await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/models": { body: [imageModel] },
      "/api/images": { body: [image] },
      "/api/jobs": { body: [queuedJob] },
      "POST /api/jobs": { body: [queuedJob] },
      "/api/jobs/plan": {
        body: {
          queued: 1,
          swaps: 0,
          current_model: null,
          steps: [{ model_id: "sdxl-e2e", model: "SDXL E2E", type: "image", count: 1 }],
        },
      },
    },
  });
  await page.goto("/");

  await expect(page.getByText("E2E generated result", { exact: true })).toBeVisible();
  await expect(page.getByText("1 queued", { exact: true })).toBeVisible();
  await page.locator("#image-prompt").fill("new e2e image");
  await page.getByRole("button", { name: "Queue generation" }).click();
  await expect
    .poll(() => observed.some(({ method, path }) => method === "POST" && path === "/api/jobs"))
    .toBe(true);

  await page.getByRole("tablist", { name: "Workspaces" }).getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("button", { name: "E2E generated result" })).toBeVisible();
});

test("settings load failure is visible and retryable", async ({ page }) => {
  const observed = await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/settings": { status: 503, body: { detail: "settings unavailable" } },
      "/api/settings/overrides": { status: 503, body: { detail: "settings unavailable" } },
    },
  });
  await page.goto("/");
  await page.getByRole("tablist", { name: "Workspaces" }).getByRole("tab", { name: "Settings" }).click();

  await expect(page.getByText(/settings unavailable/i).first()).toBeVisible();
  const before = observed.filter(({ path }) => path === "/api/settings").length;
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect
    .poll(() => observed.filter(({ path }) => path === "/api/settings").length)
    .toBeGreaterThan(before);
});

test("an in-use model cannot be deleted from the manager", async ({ page }) => {
  const observed = await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/models/installed": {
        body: {
          items: [
            {
              kind: "image",
              kind_label: "Image",
              name: "Resident SDXL",
              path: "image/resident.safetensors",
              size_bytes: 1024,
              is_dir: false,
              in_use: true,
            },
          ],
          kinds: { image: "Image" },
          total_used_bytes: 1024,
          disk: { free_mb: 4096, models_root: "models" },
        },
      },
    },
  });
  await page.goto("/");
  await page.getByRole("tablist", { name: "Workspaces" }).getByRole("tab", { name: "Models" }).click();

  await expect(page.getByText("Resident SDXL")).toBeVisible();
  const remove = page.getByRole("button", { name: "Delete" });
  await expect(remove).toBeDisabled();
  await expect(remove).toHaveAttribute("title", /Free GPU first/);
  expect(observed.some(({ method, path }) => method === "DELETE" && path === "/api/models/installed")).toBe(
    false,
  );
});

test("voice live controls stay gated until native assets and a model are ready", async ({ page }) => {
  const voiceStatus = {
    engine: "native-rvc",
    stub: true,
    ready: false,
    assets: [
      {
        name: "content_vec",
        path: null,
        found: false,
        source: null,
        optional: false,
      },
    ],
    asset_download: null,
    models: [],
    audio_devices: { inputs: [], outputs: [] },
    device: "cpu",
    settings: {
      pitch: 0,
      speaker_id: 0,
      index_ratio: 0.55,
      protect: 0.5,
      noise_scale: 0.66,
      f0_smoothing: 0,
      f0_detector: "fcpe",
      input_highpass_hz: 80,
      input_gate_db: -90,
      input_formant: 0,
      input_denoise: "off",
      input_denoise_mix: 0.75,
      silence_threshold_db: -72,
      silence_hold_ms: 250,
      server_input_device_id: null,
      server_output_device_id: null,
      server_monitor_device_id: null,
      server_input_gain: 1,
      server_output_gain: 1,
      server_monitor_gain: 1,
      server_audio_sample_rate: 48000,
      server_read_chunk_size: 133,
      cross_fade_overlap_size: 0.05,
      extra_convert_size: 2,
      pass_through: false,
    },
    loaded_model: null,
    live: false,
    session_config: null,
    session_error: null,
    recording: { active: false, duration_s: 0, samples: 0, sample_rate: null },
    metrics: {
      input_vu: 0,
      output_vu: 0,
      output_peak: 0,
      output_peak_dbfs: null,
      limiter_reduction_db: 0,
      timings_ms: {},
      total_ms: null,
      total_p95_ms: null,
      chunk_ms: null,
      latency_headroom_ms: null,
      latency_warning: null,
      provider_health: {},
      overruns: 0,
      underruns: 0,
      squelched: true,
    },
  };
  await installApiStub(page, {
    welcomeSeen: true,
    routes: {
      "/api/voice/engine/status": { body: voiceStatus },
      "/api/voice/engine/presets": { body: [] },
    },
  });
  await page.goto("/");
  await page.getByRole("tablist", { name: "Workspaces" }).getByRole("tab", { name: "Voice" }).click();

  await expect(page.getByRole("button", { name: "Start Live" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Download voice assets/ })).toBeVisible();
  await expect(page.getByText("Shared voice assets needed")).toBeVisible();
});

test("WebSocket reconnect reconciles an authoritative REST snapshot", async ({ page }) => {
  const observed = await installApiStub(page, { welcomeSeen: true, fakeWebSocket: true });
  await page.goto("/");
  await expect(page.locator("output[title^='Synced']")).toBeVisible();
  const before = observed.filter(({ path }) => path === "/api/jobs").length;

  await page.evaluate(() => {
    (window as typeof window & { __closeHfabricSocket?: () => void }).__closeHfabricSocket?.();
  });
  await expect(page.locator("output[title='Reconnecting']")).toBeVisible();
  await expect
    .poll(() => observed.filter(({ path }) => path === "/api/jobs").length, { timeout: 5_000 })
    .toBeGreaterThan(before);
  await expect(page.locator("output[title^='Synced']")).toBeVisible();
});
