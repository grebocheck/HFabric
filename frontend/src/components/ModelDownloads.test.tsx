import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelDownloads } from "./ModelDownloads";
import type { ModelDownloadItem, ModelDownloadState } from "../types";

const mocks = vi.hoisted(() => ({
  api: { downloadsState: vi.fn(), downloadsStart: vi.fn() },
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

    // recommended present model stays out of the advanced bucket; advanced one is hidden
    expect(await screen.findByText("SDXL")).toBeTruthy();
    expect(screen.getByText("Chat")).toBeTruthy();
    expect(screen.queryByText("FLUX fp4")).toBeNull();

    const button = screen.getByRole("button", { name: /Download selected/ });
    await user.click(button);

    await waitFor(() => expect(mocks.api.downloadsStart).toHaveBeenCalledWith(["sdxl"]));
  });

  it("reveals advanced models behind the toggle", async () => {
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

    await user.click(screen.getByRole("button", { name: /Show 1 advanced model/ }));
    expect(screen.getByText("FLUX fp4")).toBeTruthy();
  });
});
