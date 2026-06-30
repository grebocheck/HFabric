import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Model, VideoItem } from "../types";
import { VideoComposer, VideoHistory, VideoResult } from "./VideoComposer";

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

const framepackModel = {
  ...model,
  id: "framepack",
  name: "FramePack Hunyuan",
  family: "hunyuan-video",
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

  it("applies clip presets to queued video params", async () => {
    const user = userEvent.setup();
    render(<VideoComposer models={[model]} modelsLoading={false} onQueued={vi.fn()} onGetModels={vi.fn()} />);

    await user.selectOptions(screen.getByLabelText("Video clip preset"), "ltx-draft");
    await user.type(screen.getByLabelText("Video prompt"), "a fast draft clip");
    await user.click(screen.getByRole("button", { name: "Generate video" }));

    await waitFor(() => expect(mocks.api.createJobs).toHaveBeenCalledOnce());
    expect(mocks.api.createJobs.mock.calls[0][0][0].params).toMatchObject({
      prompt: "a fast draft clip",
      width: 704,
      height: 512,
      frames: 25,
      fps: 24,
      steps: 8,
      guidance: 3,
    });
  });

  it("forces FramePack models to image-to-video presets", async () => {
    render(<VideoComposer models={[framepackModel]} modelsLoading={false} onQueued={vi.fn()} onGetModels={vi.fn()} />);

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Text to video" }) as HTMLButtonElement).disabled).toBe(true);
    });
    expect((screen.getByLabelText("Video clip preset") as HTMLSelectElement).value).toBe("hunyuan-long");
    expect((screen.getByLabelText("Frames") as HTMLInputElement).value).toBe("91");
    expect(screen.getByRole("button", { name: "Choose the first frame" })).toBeTruthy();
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

  it("plays an older clip when its mini-history thumbnail is clicked", async () => {
    const user = userEvent.setup();
    const clip = (id: string, prompt: string) => ({
      id,
      job_id: id,
      url: `/${id}.mp4`,
      poster_url: `/${id}.webp`,
      thumb_url: null,
      width: 832,
      height: 480,
      frames: 49,
      fps: 24,
      duration_s: 2,
      family: "ltx-video",
      params: { prompt },
      created_at: "2026-06-22T00:00:00Z",
    }) as VideoItem;
    // Newest first, mirroring the list order the API returns.
    render(<VideoResult videos={[clip("v2", "train"), clip("v1", "boat")]} generating={false} onOpenHistory={vi.fn()} />);

    expect((screen.getByLabelText("Generated video") as HTMLVideoElement).getAttribute("src")).toBe("/v2.mp4");
    await user.click(screen.getByTitle("boat"));
    expect((screen.getByLabelText("Generated video") as HTMLVideoElement).getAttribute("src")).toBe("/v1.mp4");
  });

  it("filters video history by search, family and mode", async () => {
    const user = userEvent.setup();
    const clip = (id: string, prompt: string, family: string, mode: "t2v" | "i2v") => ({
      id,
      job_id: id,
      url: `/${id}.mp4`,
      poster_url: `/${id}.webp`,
      thumb_url: null,
      width: 832,
      height: 480,
      frames: 49,
      fps: 24,
      duration_s: 2,
      family,
      params: { prompt, mode },
      created_at: "2026-06-22T00:00:00Z",
    }) as VideoItem;

    render(
      <VideoHistory
        videos={[
          clip("v1", "paper boat drifting", "ltx-video", "t2v"),
          clip("v2", "city street timelapse", "wan-video", "i2v"),
        ]}
        onDeleted={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Search videos"), "paper");
    expect(screen.getByText("paper boat drifting")).toBeTruthy();
    expect(screen.queryByText("city street timelapse")).toBeNull();

    await user.clear(screen.getByLabelText("Search videos"));
    await user.selectOptions(screen.getByLabelText("Video family filter"), "wan-video");
    expect(screen.queryByText("paper boat drifting")).toBeNull();
    expect(screen.getByText("city street timelapse")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Video mode filter"), "t2v");
    expect(screen.getByText("No videos match the current filters")).toBeTruthy();
  });
});
