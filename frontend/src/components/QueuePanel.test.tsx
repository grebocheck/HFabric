import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueuePanel } from "./QueuePanel";
import type { Job } from "../types";

const mocks = vi.hoisted(() => ({
  api: {
    cancelJob: vi.fn(),
    clearFinished: vi.fn(),
    queuePlan: vi.fn(),
    setPriority: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: mocks.api }));

afterEach(cleanup);

function job(over: Partial<Job>): Job {
  return {
    id: "job",
    type: "image",
    status: "queued",
    priority: 0,
    model_id: "sdxl",
    params: { prompt: "prompt" },
    progress: 0,
    result: null,
    error: null,
    created_at: "2026-06-12T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...over,
  };
}

beforeEach(() => {
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.cancelJob.mockResolvedValue({});
  mocks.api.clearFinished.mockResolvedValue({ removed: 0 });
  mocks.api.queuePlan.mockResolvedValue({ queued: 0, swaps: 0, current_model_id: null, current_model: null, steps: [] });
  mocks.api.setPriority.mockResolvedValue({});
});

describe("QueuePanel", () => {
  it("renders job cards per status and cancels the running job", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(
      <QueuePanel
        onChanged={onChanged}
        jobs={[
          job({ id: "run", status: "running", progress: 0.42, model_id: "sdxl-run" }),
          job({ id: "queue", status: "queued", model_id: "sdxl-queue" }),
          job({ id: "err", status: "error", error: "failed", model_id: "sdxl-error" }),
          job({ id: "done", status: "done", model_id: "sdxl-done" }),
          job({ id: "cancelled", status: "cancelled", model_id: "sdxl-cancelled" }),
        ]}
      />,
    );

    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("queued")).toBeTruthy();
    expect(screen.getByText("error")).toBeTruthy();
    expect(screen.getByText("done")).toBeTruthy();
    expect(screen.getByText("cancelled")).toBeTruthy();
    expect(screen.getAllByText("42%").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(mocks.api.cancelJob).toHaveBeenCalledWith("run"));
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows the inline plan and attaches matching arbiter notes to queued cards", async () => {
    mocks.api.queuePlan.mockResolvedValue({
      queued: 2,
      swaps: 1,
      current_model_id: "old",
      current_model: "Old model",
      steps: [
        { model_id: "sdxl-queue", model: "SDXL queue", type: "image", count: 2 },
      ],
    });

    render(
      <QueuePanel
        onChanged={vi.fn()}
        jobs={[job({ id: "queue", status: "queued", model_id: "sdxl-queue" })]}
        note={{
          reason: "ram_budget",
          message: "Refused SDXL queue: needs memory",
          model_id: "sdxl-queue",
          model: "SDXL queue",
          family: "sdxl",
          predicted_gb: 12.4,
          available_gb: 4.2,
          ts: 1,
        }}
      />,
    );

    expect(await screen.findByText("Plan: 2 queued / 1 swap")).toBeTruthy();
    expect(screen.getByText("waiting: RAM budget refused (needs ~12.4 GB)")).toBeTruthy();
  });
});
