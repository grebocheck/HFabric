import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Gallery } from "./Gallery";
import type { ImageItem, ImageStats, Model } from "../types";

const mocks = vi.hoisted(() => ({
  api: {
    queryImages: vi.fn(),
    imageStats: vi.fn(),
    deleteImage: vi.fn(),
    exportImages: vi.fn(),
    updateImage: vi.fn(),
    revealImage: vi.fn(),
    downloadUrlBlob: vi.fn(),
    assetUrl: vi.fn((url: string) => url),
  },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));

afterEach(cleanup);

const MODELS: Model[] = [
  {
    id: "sdxl",
    name: "SDXL base",
    family: "sdxl",
    job_type: "image",
    size_bytes: 1,
    loaded: false,
  },
];

const STATS: ImageStats = {
  total: 2,
  today: 2,
  by_model: [{ model: "SDXL base", count: 2 }],
  by_family: [{ family: "sdxl", count: 2 }],
  by_lora: [],
  by_tag: [],
};

function image(over: Partial<ImageItem>): ImageItem {
  return {
    id: "img1",
    job_id: "job1",
    seed: 1,
    width: 256,
    height: 256,
    family: "sdxl",
    favorite: false,
    tags: [],
    params: { prompt: "first prompt", model: "SDXL base" },
    created_at: "2026-06-12T10:00:00Z",
    url: "/api/images/img1/file",
    thumb_url: null,
    ...over,
  };
}

beforeEach(() => {
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.queryImages.mockResolvedValue([
    image({ id: "img1", params: { prompt: "first prompt", model: "SDXL base" } }),
    image({ id: "img2", params: { prompt: "second prompt", model: "SDXL base" } }),
  ]);
  mocks.api.imageStats.mockResolvedValue(STATS);
  mocks.api.deleteImage.mockResolvedValue({ deleted: "img1" });
  mocks.api.exportImages.mockResolvedValue(new Blob(["zip"], { type: "application/zip" }));
  mocks.api.updateImage.mockImplementation(async (id: string, body: Partial<ImageItem>) => image({ id, ...body }));
  mocks.api.revealImage.mockResolvedValue({});
  mocks.api.downloadUrlBlob.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
  mocks.api.assetUrl.mockImplementation((url: string) => url);
});

describe("Gallery", () => {
  it("combines model and favorite filters, then bulk deletes the selected image", async () => {
    const user = userEvent.setup();
    const { container } = render(<Gallery models={MODELS} reloadSignal={0} onReproduce={() => {}} />);

    await waitFor(() => expect(mocks.api.queryImages).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 60, offset: 0 }),
    ));
    await screen.findByText(/2 total/);

    await user.click(screen.getByText("All models (2)"));
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(screen.getByRole("button", { name: "Favorites" }));

    await waitFor(() => expect(mocks.api.queryImages).toHaveBeenCalledWith(
      expect.objectContaining({ model: "SDXL base", favorite: true, limit: 60, offset: 0 }),
    ));
    expect(screen.getAllByText("Favorites").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SDXL base").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Select" }));
    const firstImage = container.querySelector('button[title="first prompt"]');
    expect(firstImage).toBeTruthy();
    await user.click(firstImage as HTMLButtonElement);
    expect(screen.getByText("1 selected")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Delete selected" }));
    await waitFor(() => expect(mocks.api.deleteImage).toHaveBeenCalledWith("img1"));
  });

  it("pages through images in the detail modal with arrow keys and closes on Escape", async () => {
    const user = userEvent.setup();
    const { container } = render(<Gallery models={MODELS} reloadSignal={0} onReproduce={() => {}} />);

    await waitFor(() => expect(mocks.api.queryImages).toHaveBeenCalled());
    await screen.findByText(/2 total/);

    // open the first image — its prompt shows as visible text only in the modal
    await user.click(container.querySelector('button[title="first prompt"]') as HTMLButtonElement);
    expect(await screen.findByText("first prompt")).toBeTruthy();

    await user.keyboard("{ArrowRight}");
    expect(await screen.findByText("second prompt")).toBeTruthy();

    await user.keyboard("{ArrowLeft}");
    expect(await screen.findByText("first prompt")).toBeTruthy();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByText("first prompt")).toBeNull());
  });
});
