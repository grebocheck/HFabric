import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HfBrowser } from "./HfBrowser";

const mocks = vi.hoisted(() => ({
  api: { hfSearch: vi.fn(), hfRepoFiles: vi.fn(), downloadsCustom: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));
vi.mock("./Toast", () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));

afterEach(cleanup);

const kindOptions = [
  { value: "llm", label: "LLM" },
  { value: "image", label: "Image" },
  { value: "voice", label: "Voice" },
];

beforeEach(() => {
  mocks.api.hfSearch.mockReset();
  mocks.api.hfRepoFiles.mockReset();
  mocks.api.downloadsCustom.mockReset();
  mocks.api.hfSearch.mockResolvedValue({
    query: "qwen",
    sort: "downloads",
    limit: 24,
    filters: [],
    results: [
      {
        id: "owner/Qwen-GGUF",
        author: "owner",
        sha: "abc123",
        downloads: 1234,
        likes: 42,
        last_modified: "2026-01-02T00:00:00+00:00",
        created_at: "2025-12-01T00:00:00+00:00",
        pipeline_tag: "text-generation",
        library_name: "transformers",
        tags: ["gguf", "license:apache-2.0"],
        license: "apache-2.0",
        gated: false,
        private: false,
        weight_count: 1,
        file_count: 2,
        weight_formats: ["gguf"],
        suggested_kind: "llm",
        url: "https://huggingface.co/owner/Qwen-GGUF",
      },
    ],
  });
  mocks.api.hfRepoFiles.mockResolvedValue({
    repo: "owner/Qwen-GGUF",
    files: [
      { path: "model-q4.gguf", size_bytes: 1024 },
      { path: "README.md", size_bytes: 512 },
    ],
  });
  mocks.api.downloadsCustom.mockResolvedValue({
    state: "running",
    message: "",
    current: null,
    progress: { done: 0, total: 1 },
    failed: [],
    updated_at: 0,
  });
});

describe("HfBrowser", () => {
  it("searches Hugging Face, opens a repo, and downloads selected weights", async () => {
    const user = userEvent.setup();
    const setKind = vi.fn();
    const onStarted = vi.fn();
    render(<HfBrowser kind="llm" setKind={setKind} kindOptions={kindOptions} onStarted={onStarted} />);

    await user.type(screen.getByPlaceholderText("Search Hugging Face weights"), "qwen");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(mocks.api.hfSearch).toHaveBeenCalledWith("qwen", {
        limit: 24,
        sort: "downloads",
        filter: undefined,
      }),
    );
    expect(await screen.findByText("owner/Qwen-GGUF")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Files" }));

    await waitFor(() => expect(mocks.api.hfRepoFiles).toHaveBeenCalledWith("owner/Qwen-GGUF"));
    expect(await screen.findByText("model-q4.gguf")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /Download 1 selected/ }));

    await waitFor(() =>
      expect(mocks.api.downloadsCustom).toHaveBeenCalledWith([
        {
          source: "hf",
          kind: "llm",
          repo: "owner/Qwen-GGUF",
          filename: "model-q4.gguf",
          subdir: undefined,
        },
      ]),
    );
    expect(onStarted).toHaveBeenCalled();
  });

  it("keeps multi-file picks inside the repo folder", async () => {
    const user = userEvent.setup();
    render(<HfBrowser kind="llm" setKind={vi.fn()} kindOptions={kindOptions} onStarted={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("owner/model repo id"), "owner/Qwen-GGUF");
    await user.click(screen.getByRole("button", { name: "Browse repo" }));
    expect(await screen.findByText("model-q4.gguf")).toBeTruthy();

    await user.click(screen.getByText("README.md"));
    await user.click(screen.getByRole("button", { name: /Download 2 selected/ }));

    await waitFor(() =>
      expect(mocks.api.downloadsCustom).toHaveBeenCalledWith([
        {
          source: "hf",
          kind: "llm",
          repo: "owner/Qwen-GGUF",
          filename: "model-q4.gguf",
          subdir: "Qwen-GGUF",
        },
        {
          source: "hf",
          kind: "llm",
          repo: "owner/Qwen-GGUF",
          filename: "README.md",
          subdir: "Qwen-GGUF",
        },
      ]),
    );
  });
});
