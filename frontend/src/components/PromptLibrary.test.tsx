import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PromptLibrary } from "./PromptLibrary";
import type { PromptSnippet } from "../types";

const mocks = vi.hoisted(() => ({
  api: { listPrompts: vi.fn(), createPrompt: vi.fn(), deletePrompt: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));
vi.mock("./Toast", () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));

afterEach(cleanup);

function snippet(over: Partial<PromptSnippet>): PromptSnippet {
  return {
    id: "p1",
    name: "Neon city",
    body: "neon city at night, rain",
    negative: "blurry",
    tags: ["cyberpunk"],
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.listPrompts.mockResolvedValue([
    snippet({ id: "p1", name: "Neon city", body: "neon city at night", tags: ["cyberpunk"] }),
    snippet({ id: "p2", name: "Portrait", body: "studio portrait", negative: null, tags: ["people"] }),
  ]);
  mocks.api.createPrompt.mockResolvedValue(snippet({ id: "p3" }));
  mocks.api.deletePrompt.mockResolvedValue({ deleted: "p1" });
});

describe("PromptLibrary", () => {
  it("inserts a snippet's body + negative and closes", async () => {
    const onApply = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <PromptLibrary
        open
        onClose={onClose}
        currentPrompt=""
        currentNegative=""
        onApply={onApply}
      />,
    );

    await screen.findByText("Neon city");
    const insertButtons = screen.getAllByRole("button", { name: "Insert" });
    await user.click(insertButtons[0]);

    expect(onApply).toHaveBeenCalledWith("neon city at night", "blurry");
    expect(onClose).toHaveBeenCalled();
  });

  it("filters by the search box", async () => {
    const user = userEvent.setup();
    render(
      <PromptLibrary open onClose={vi.fn()} currentPrompt="" currentNegative="" onApply={vi.fn()} />,
    );

    await screen.findByText("Neon city");
    await user.type(screen.getByPlaceholderText(/Search/i), "portrait");

    expect(screen.queryByText("Neon city")).toBeNull();
    expect(screen.getByText("Portrait")).toBeTruthy();
  });

  it("saves the current composer prompt", async () => {
    const user = userEvent.setup();
    render(
      <PromptLibrary
        open
        onClose={vi.fn()}
        currentPrompt="a brave knight"
        currentNegative="lowres"
        onApply={vi.fn()}
      />,
    );

    await screen.findByText("Neon city");
    await user.click(screen.getByRole("button", { name: "Save current" }));

    await waitFor(() =>
      expect(mocks.api.createPrompt).toHaveBeenCalledWith({ body: "a brave knight", negative: "lowres" }),
    );
  });
});
