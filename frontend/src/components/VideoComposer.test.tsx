import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Model, VideoItem } from "../types";
import { VideoComposer, VideoResult } from "./VideoComposer";

const mocks = vi.hoisted(() => ({
  api: {
    createJobs: vi.fn(),
    deleteVideo: vi.fn(),
    uploadInitImage: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));

afterEach(cleanup);

const model = {
  id: "ltx",
  name: "LTX Video",
  family: "ltx-video",
  job_type: "video",
  size_bytes: 1,
  loaded: false,
  warm: false,
  available: true,
} as Model;

beforeEach(() => {
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.createJobs.mockResolvedValue([]);
});

describe("VideoComposer", () => {
  it("queues a text-to-video job with the selected clip settings", async () => {
    const user = userEvent.setup();
    const onQueued = vi.fn();
    render(<VideoComposer models={[model]} modelsLoading={false} onQueued={onQueued} onGetModels={vi.fn()} />);

    await user.type(screen.getByLabelText("Video prompt"), "a paper boat sailing");
    await user.click(screen.getByRole("button", { name: "Generate video" }));

    await waitFor(() => expect(mocks.api.createJobs).toHaveBeenCalledOnce());
    expect(mocks.api.createJobs.mock.calls[0][0][0]).toMatchObject({
      type: "video",
      model_id: "ltx",
      params: { prompt: "a paper boat sailing", mode: "t2v" },
    });
    expect(onQueued).toHaveBeenCalled();
  });

  it("renders the mp4 player with poster and controls", () => {
    const video = {
      id: "v1",
      job_id: "j1",
      url: "/video.mp4",
      poster_url: "/poster.webp",
      thumb_url: "/thumb.webp",
      width: 832,
      height: 480,
      frames: 49,
      fps: 16,
      duration_s: 3.0625,
      family: "ltx-video",
      params: { prompt: "paper boat" },
      created_at: "2026-06-22T00:00:00Z",
    } as VideoItem;
    render(<VideoResult videos={[video]} generating={false} onOpenHistory={vi.fn()} />);
    const player = screen.getByLabelText("Generated video") as HTMLVideoElement;
    expect(player.getAttribute("src")).toBe("/video.mp4");
    expect(player.getAttribute("poster")).toBe("/poster.webp");
    expect(player.controls).toBe(true);
  });
});
