import { useState } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";
import type { BusEvent, ChatConversation, ChatMessage, LlmConfig, Model } from "../types";

const mocks = vi.hoisted(() => ({
  eventHandler: undefined as ((event: BusEvent) => void) | undefined,
  api: {
    listConversations: vi.fn(),
    listPresets: vi.fn(),
    getLlmConfig: vi.fn(),
    createConversation: vi.fn(),
    sendChatMessage: vi.fn(),
    stopLlm: vi.fn(),
    cancelJob: vi.fn(),
    truncateFrom: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: mocks.api, apiAssetUrl: (url: string) => url }));
vi.mock("../api/useEvents", () => ({
  useEvents: (onEvent: (event: BusEvent) => void) => {
    mocks.eventHandler = onEvent;
    return { connected: true };
  },
}));

afterEach(cleanup);

const MODELS: Model[] = [
  {
    id: "llm",
    name: "Stub LLM",
    family: "gguf",
    job_type: "llm",
    size_bytes: 1,
    loaded: false,
  },
  {
    id: "sdxl",
    name: "Stub SDXL",
    family: "sdxl",
    job_type: "image",
    size_bytes: 1,
    loaded: false,
  },
];

function conversation(over: Partial<ChatConversation> = {}): ChatConversation {
  return {
    id: "c1",
    title: "New chat",
    model_id: "llm",
    system: null,
    params: {},
    created_at: "2026-06-12T10:00:00Z",
    updated_at: "2026-06-12T10:00:00Z",
    ...over,
  };
}

function message(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: "m",
    role: "assistant",
    content: "",
    created_at: "2026-06-12T10:00:00Z",
    ...over,
  };
}

function llmConfig(): LlmConfig {
  return {
    ctx: 8192,
    ngl: 999,
    backend: "default",
    backends: [{ id: "default", label: "Default", available: true, path: "llama", context_types: ["f16"] }],
    context_type: "f16",
    context_types: [{ id: "f16", label: "F16", experimental: false }],
    stub: true,
    loaded: false,
    model_id: null,
    defaults: { temperature: 0.8, max_tokens: 512 },
  };
}

function renderPanel() {
  function Harness() {
    const [draft, setDraft] = useState("");
    return <ChatPanel models={MODELS} draft={draft} setDraft={setDraft} />;
  }
  return render(<Harness />);
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  localStorage.clear();
  mocks.eventHandler = undefined;
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.listConversations.mockResolvedValue([]);
  mocks.api.listPresets.mockResolvedValue([]);
  mocks.api.getLlmConfig.mockResolvedValue(llmConfig());
  mocks.api.createConversation.mockResolvedValue(conversation());
  mocks.api.sendChatMessage.mockResolvedValue({
    job_id: "job-1",
    conversation: conversation({ title: "Hello" }),
    user_message: message({ id: "u1", role: "user", content: "Hello" }),
    assistant_message: message({ id: "a1", role: "assistant", content: "", job_id: "job-1" }),
  });
  mocks.api.stopLlm.mockResolvedValue({ stopped: false });
  mocks.api.cancelJob.mockResolvedValue({});
  mocks.api.truncateFrom.mockResolvedValue({ removed: 0 });
});

describe("ChatPanel", () => {
  it("sends a message, renders streamed thinking, then splits reasoning from the answer", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(await screen.findByPlaceholderText(/Message/), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(mocks.api.sendChatMessage).toHaveBeenCalledWith(
      "c1",
      expect.objectContaining({ content: "Hello", model_id: "llm" }),
    ));

    await act(async () => {
      mocks.eventHandler?.({ type: "llm.token", job_id: "job-1", token: "<think>plan", ts: 1 });
    });
    expect(screen.getByText(/Thinking/)).toBeTruthy();
    expect(screen.getByText("plan")).toBeTruthy();

    await act(async () => {
      mocks.eventHandler?.({
        type: "job.done",
        job_id: "job-1",
        text: "<think>plan</think>Final answer",
        ts: 2,
      });
    });

    expect(screen.getByText("Reasoning")).toBeTruthy();
    expect(screen.getByText("Final answer")).toBeTruthy();
  });

  it("renders a failed streamed reply as an error message", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(await screen.findByPlaceholderText(/Message/), "fail please");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.api.sendChatMessage).toHaveBeenCalled());

    await act(async () => {
      mocks.eventHandler?.({ type: "job.error", job_id: "job-1", error: "backend exploded", ts: 3 });
    });

    expect(screen.getByText(/backend exploded/)).toBeTruthy();
  });
});
