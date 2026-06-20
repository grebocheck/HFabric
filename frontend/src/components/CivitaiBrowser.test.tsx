import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CivitaiBrowser } from "./CivitaiBrowser";
import type { CivitaiSearchResponse, CivitaiSearchResult } from "../types";

const mocks = vi.hoisted(() => ({
  api: {
    civitaiAuthStatus: vi.fn(),
    civitaiSearch: vi.fn(),
    civitaiVersionFiles: vi.fn(),
    civitaiAuthSave: vi.fn(),
    civitaiAuthSaveCookie: vi.fn(),
    civitaiAuthClear: vi.fn(),
    downloadsCustom: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));
vi.mock("./Toast", () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));

afterEach(cleanup);

function result(over: Partial<CivitaiSearchResult>): CivitaiSearchResult {
  return {
    id: 1,
    name: "Model One",
    type: "LORA",
    nsfw: false,
    creator: "alice",
    downloads: 1000,
    likes: 50,
    base_model: "SDXL 1.0",
    tags: [],
    preview: null,
    suggested_kind: "lora",
    version_count: 1,
    versions: [{ id: 10, name: "v1", base_model: "SDXL 1.0" }],
    url: "https://civitai.com/models/1",
    ...over,
  };
}

function response(results: CivitaiSearchResult[], nextPage: number | null): CivitaiSearchResponse {
  return { query: "", sort: "downloads", nsfw: false, limit: 24, page: 1, total_pages: null, next_page: nextPage, results };
}

function renderBrowser() {
  return render(
    <CivitaiBrowser kind="lora" setKind={() => {}} kindOptions={[{ value: "lora", label: "LoRA" }]} onStarted={() => {}} />,
  );
}

beforeEach(() => {
  localStorage.clear();
  Object.values(mocks.api).forEach((fn) => fn.mockReset());
  mocks.api.civitaiAuthStatus.mockResolvedValue({ has_key: false, has_cookie: false });
  mocks.api.civitaiSearch.mockResolvedValue(response([], null)); // default for auto-load on mount
});

describe("CivitaiBrowser", () => {
  it("auto-loads top models on open (no query needed)", async () => {
    mocks.api.civitaiSearch.mockResolvedValue(response([result({ name: "Cool LoRA" })], null));
    renderBrowser();

    // No click: the tab fills itself so a lazy user sees options immediately.
    expect(await screen.findByText("Cool LoRA")).toBeTruthy();
    expect(mocks.api.civitaiSearch).toHaveBeenCalledWith("", expect.objectContaining({ page: 1, nsfw: false }));
  });

  it("RED toggle flips host and persists to localStorage", async () => {
    mocks.api.civitaiSearch.mockResolvedValue(response([], null));
    const user = userEvent.setup();
    renderBrowser();

    const toggle = screen.getByRole("switch");
    expect(toggle.getAttribute("aria-checked")).toBe("false");

    await user.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(localStorage.getItem("imagefabric.civitai.nsfw")).toBe("true");
  });

  it("loads another page and appends results", async () => {
    mocks.api.civitaiSearch
      .mockResolvedValueOnce(response([result({ id: 1, name: "First" })], 2)) // auto-load (page 1)
      .mockResolvedValueOnce(response([result({ id: 2, name: "Second" })], null)); // Load more (page 2)
    const user = userEvent.setup();
    renderBrowser();

    await screen.findByText("First");

    await user.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.getByText("Second")).toBeTruthy());
    expect(screen.getByText("First")).toBeTruthy(); // appended, not replaced
    expect(mocks.api.civitaiSearch).toHaveBeenLastCalledWith("", expect.objectContaining({ page: 2 }));
  });

  it("saves a CivitAI API key from the account panel", async () => {
    mocks.api.civitaiAuthSave.mockResolvedValue({ has_key: true, has_cookie: false, verified: true });
    const user = userEvent.setup();
    renderBrowser();

    await user.click(screen.getByRole("button", { name: /^Account$/ }));
    await user.type(screen.getByPlaceholderText("Paste CivitAI API key"), "secret-key");
    await user.click(screen.getAllByRole("button", { name: /Save & verify/ })[0]);

    await waitFor(() => expect(mocks.api.civitaiAuthSave).toHaveBeenCalledWith("secret-key"));
  });

  it("saves a CivitAI session cookie for reuse in upload", async () => {
    mocks.api.civitaiAuthSaveCookie.mockResolvedValue({ has_key: false, has_cookie: true, verified: true });
    const user = userEvent.setup();
    renderBrowser();

    await user.click(screen.getByRole("button", { name: /^Account$/ }));
    await user.type(screen.getByPlaceholderText("Paste __Secure-civitai-token cookie"), "cookie-val");
    await user.click(screen.getAllByRole("button", { name: /Save & verify/ })[1]);

    await waitFor(() => expect(mocks.api.civitaiAuthSaveCookie).toHaveBeenCalledWith("cookie-val"));
  });
});
