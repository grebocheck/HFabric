import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelDownloads } from "./ModelDownloads";
import type { ModelDownloadItem, ModelDownloadState } from "../types";

const mocks = vi.hoisted(() => ({
  api: { downloadsState: vi.fn(), downloadsStart: vi.fn(), hfSearch: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));
vi.mock("./Toast", () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));

afterEach(cleanup);

function item(over: Partial<ModelDownloadItem>): ModelDownloadItem {
  return {
    key: "vendor/repo/file",
    repo: "vendor/repo",
    filename: "file",
    dest: "models/llm",
    label: "Model",
    reason: "starter",
    feature: null,
    approx_size_mb: 100,
    license: "Apache-2.0",
    repo_url: "https://huggingface.co/vendor/repo",
    present: false,
    recommended: true,
    ...over,
  };
}

function state(catalog: ModelDownloadItem[]): ModelDownloadState {
  return {
    catalog,
    disk: { free_mb: 100_000, models_root: "models" },
    status: { state: "idle", message: "", current: null, progress: { done: 0, total: 0 }, failed: [], updated_at: 0 },
    available: true,
  };
}

beforeEach(() => {
  mocks.api.downloadsState.mockReset();
  mocks.api.downloadsStart.mockReset();
  mocks.api.hfSearch.mockReset();
  mocks.api.hfSearch.mockResolvedValue({ query: "", sort: "downloads", limit: 24, filters: [], results: [] });
  mocks.api.downloadsStart.mockResolvedValue({
    state: "running", message: "", current: null, progress: { done: 0, total: 1 }, failed: [], updated_at: 0,
  });
});

describe("ModelDownloads", () => {
  it("preselects recommended-not-present and downloads exactly those", async () => {
    mocks.api.downloadsState.mockResolvedValue(
      state([
        item({ key: "sdxl", label: "SDXL", recommended: true, present: false, approx_size_mb: 6900 }),
        item({ key: "gguf", label: "Chat", recommended: true, present: true }),
        item({ key: "flux", label: "FLUX fp4", recommended: false, present: false }),
      ]),
    );
    const user = userEvent.setup();
    render(<ModelDownloads />);

    // Recommended-not-present shows in the Recommended section; installed and
    // optional/advanced models are tucked away by default.
    expect(await screen.findByText("SDXL")).toBeTruthy();
    expect(screen.queryByText("Chat")).toBeNull(); // installed → collapsed section
    expect(screen.queryByText("FLUX fp4")).toBeNull(); // optional → behind toggle

    const button = screen.getByRole("button", { name: /Download selected/ });
    await user.click(button);

    await waitFor(() => expect(mocks.api.downloadsStart).toHaveBeenCalledWith(["sdxl"]));
  });

  it("reveals optional curated models behind the toggle", async () => {
    mocks.api.downloadsState.mockResolvedValue(
      state([
        item({ key: "sdxl", label: "SDXL", recommended: true, present: false }),
        item({ key: "flux", label: "FLUX fp4", recommended: false, present: false }),
      ]),
    );
    const user = userEvent.setup();
    render(<ModelDownloads />);

    await screen.findByText("SDXL");
    expect(screen.queryByText("FLUX fp4")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Show 1 optional curated model/ }));
    expect(screen.getByText("FLUX fp4")).toBeTruthy();
  });

  it("collapses installed models into an expandable section", async () => {
    mocks.api.downloadsState.mockResolvedValue(
      state([
        item({ key: "sdxl", label: "SDXL", recommended: true, present: false }),
        item({ key: "gguf", label: "Chat", recommended: true, present: true }),
      ]),
    );
    const user = userEvent.setup();
    render(<ModelDownloads />);

    await screen.findByText("SDXL");
    expect(screen.queryByText("Chat")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Installed starter models/ }));
    expect(screen.getByText("Chat")).toBeTruthy();
  });
});
