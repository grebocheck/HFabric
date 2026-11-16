import { useState } from "react";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";
import { useChatPanelController } from "./useChatPanelController";
import type { BusEvent, ChatConversation, ChatMessage, LlmApiServerStatus, LlmConfig, Model } from "../types";

const mocks = vi.hoisted(() => ({
  eventHandler: undefined as ((event: BusEvent) => void) | undefined,
  sync: undefined as (() => Promise<void>) | undefined,
  api: {
    listConversations: vi.fn(),
    listPresets: vi.fn(),
    getLlmConfig: vi.fn(),
    setLlmConfig: vi.fn(),
    createPreset: vi.fn(),
    getLlmServer: vi.fn(),
    setLlmServer: vi.fn(),
    createConversation: vi.fn(),
    sendChatMessage: vi.fn(),
    stopLlm: vi.fn(),
    cancelJob: vi.fn(),
    truncateFrom: vi.fn(),
    getConversation: vi.fn(),
    getJob: vi.fn(),
  },
}));

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: mocks.api,
  apiAssetUrl: (url: string) => url,
}));
vi.mock("../api/useEvents", () => ({
  useBusEvents: (onEvent: (event: BusEvent) => void, sync: () => Promise<void>) => {
    mocks.eventHandler = onEvent;
    mocks.sync = sync;
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
    defaults: { temperature: 0.8, max_tokens: 4096 },
  };
}

function llmServer(): LlmApiServerStatus {
  return {
    enabled: false,
    available: false,
    protocol: "openai-compatible",
    base_url: "http://127.0.0.1:8261/v1",
    chat_completions_url: "http://127.0.0.1:8261/v1/chat/completions",
    models_url: "http://127.0.0.1:8261/v1/models",
    host: "127.0.0.1",
    port: 8261,
    model_id: null,
    model: null,
    loaded: false,
    pinned: false,
    stub: true,
    note: null,
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
  mocks.sync = undefined;
  for (const fn of Object.values(mocks.api)) fn.mockReset();
  mocks.api.listConversations.mockResolvedValue([]);
  mocks.api.listPresets.mockResolvedValue([]);
  mocks.api.getLlmConfig.mockResolvedValue(llmConfig());
  mocks.api.getLlmServer.mockResolvedValue(llmServer());
  mocks.api.setLlmServer.mockResolvedValue({ ...llmServer(), enabled: true });
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
  mocks.api.getConversation.mockResolvedValue({
    ...conversation(),
    messages: [message({ id: "u1", role: "user", content: "Hello" }), message({ id: "a1", job_id: "job-1" })],
  });
  mocks.api.getJob.mockResolvedValue({ id: "job-1", status: "running", result: {} });
});

describe("ChatPanel", () => {
  it("saves the sampling shown by an applied persona, including its seed", async () => {
    mocks.api.listPresets.mockResolvedValue([
      { id: "p1", name: "Seeded", type: "llm", params: { system: "Concise", seed: 0, top_p: 0.85 } },
    ]);
    mocks.api.createPreset.mockResolvedValue({ id: "copy" });
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "", setDraft: vi.fn() }),
    );
    await waitFor(() => expect(result.current.personasLoading).toBe(false));
    act(() => {
      result.current.applyPersona("p1");
      result.current.setPersonaName("Copy");
    });
    await act(async () => {
      await result.current.savePersona();
    });
    expect(mocks.api.createPreset).toHaveBeenCalledWith(
      "Copy",
      "llm",
      expect.objectContaining({ system: "Concise", seed: 0, top_p: 0.85 }),
    );
  });

  it("applies context through the shared config update path and uses the canonical response", async () => {
    let resolveConfig!: (value: unknown) => void;
    mocks.api.setLlmConfig.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveConfig = resolve;
        }),
    );
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "", setDraft: vi.fn() }),
    );
    await waitFor(() => expect(result.current.cfg).not.toBeNull());
    act(() => result.current.setCtxDraft(10000));
    let applying!: Promise<void>;
    await act(async () => {
      applying = result.current.applyCtx();
    });
    expect(result.current.configBusy).toBe(true);
    expect(mocks.api.setLlmConfig).toHaveBeenCalledWith({ ctx: 10000 });
    await act(async () => {
      resolveConfig({ ...llmConfig(), ctx: 8192, changed: true, reloaded: false, note: "normalized" });
      await applying;
    });
    expect(result.current.ctxDraft).toBe(8192);
    expect(result.current.cfgNote).toContain("normalized");
    expect(result.current.configBusy).toBe(false);
  });

  it("resets advanced sampling when selecting a conversation without overrides", async () => {
    mocks.api.getConversation.mockImplementation((id: string) =>
      Promise.resolve({
        ...conversation({ id, params: id === "seeded" ? { seed: 73, top_p: 0.9 } : {} }),
        messages: [],
      }),
    );
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "Hello", setDraft: vi.fn() }),
    );
    await act(async () => {
      await result.current.selectConversation("seeded");
    });
    expect(result.current.settings).toMatchObject({ seed: 73, topP: 0.9 });
    await act(async () => {
      await result.current.selectConversation("plain");
    });
    expect(result.current.settings).toMatchObject({ seed: "", topP: "" });
    await act(async () => {
      await result.current.send();
    });
    expect(mocks.api.sendChatMessage).toHaveBeenCalledWith(
      "plain",
      expect.objectContaining({ seed: undefined, top_p: undefined }),
    );
  });

  it("ignores a slow conversation response after a newer selection", async () => {
    let resolveA!: (value: unknown) => void;
    const detail = (id: string) => ({
      ...conversation({ id }),
      messages: [message({ id: `m-${id}`, content: id })],
    });
    mocks.api.getConversation.mockImplementation((id: string) =>
      id === "A"
        ? new Promise((resolve) => {
            resolveA = resolve;
          })
        : Promise.resolve(detail(id)),
    );
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "", setDraft: vi.fn() }),
    );
    let requestA!: Promise<void>;
    await act(async () => {
      requestA = result.current.selectConversation("A");
    });
    await act(async () => {
      await result.current.selectConversation("B");
    });
    await act(async () => {
      resolveA(detail("A"));
      await requestA;
    });
    expect(result.current.activeId).toBe("B");
    expect(result.current.messages[0].content).toBe("B");
  });

  it("does not append old job tokens to another conversation", async () => {
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "Hello", setDraft: vi.fn() }),
    );
    await act(async () => {
      await result.current.send();
    });
    mocks.api.getConversation.mockResolvedValue({
      ...conversation({ id: "c2" }),
      messages: [message({ id: "other", content: "Other reply" })],
    });
    await act(async () => {
      await result.current.selectConversation("c2");
    });
    act(() =>
      mocks.eventHandler?.({ type: "llm.token", job_id: "job-1", token: "Wrong conversation", ts: 1 }),
    );
    expect(result.current.messages[0].content).toBe("Other reply");
    expect(result.current.busy).toBe(false);
  });

  it("ignores a send response that arrives after selecting another conversation", async () => {
    let resolveSend!: (value: unknown) => void;
    mocks.api.sendChatMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSend = resolve;
        }),
    );
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "Hello", setDraft: vi.fn() }),
    );
    let send!: Promise<void>;
    await act(async () => {
      send = result.current.send();
    });
    mocks.api.getConversation.mockResolvedValue({
      ...conversation({ id: "c2" }),
      messages: [message({ id: "other", content: "Other reply" })],
    });
    await act(async () => {
      await result.current.selectConversation("c2");
    });
    await act(async () => {
      resolveSend({
        job_id: "job-1",
        conversation: conversation(),
        user_message: message({ id: "u1", role: "user", content: "Hello" }),
        assistant_message: message({ id: "a1", job_id: "job-1" }),
      });
      await send;
    });
    expect(result.current.activeId).toBe("c2");
    expect(result.current.messages[0].content).toBe("Other reply");
    expect(result.current.busy).toBe(false);
  });

  it("reconciles a completed job and its reply after reconnect", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(await screen.findByPlaceholderText(/Message/), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.api.sendChatMessage).toHaveBeenCalled());
    mocks.api.getJob.mockResolvedValue({ id: "job-1", status: "done", result: { text: "Recovered answer" } });
    mocks.api.getConversation.mockResolvedValue({
      ...conversation(),
      messages: [message({ id: "a1", content: "Recovered answer" })],
    });
    await act(async () => {
      await mocks.sync?.();
    });
    expect(screen.getByText("Recovered answer")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it("follows a tool child queued while the connection was lost", async () => {
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "Hello", setDraft: vi.fn() }),
    );
    await act(async () => {
      await result.current.send();
    });
    mocks.api.getJob.mockImplementation((id: string) =>
      Promise.resolve(
        id === "job-1"
          ? { id, status: "done", result: { child_job_id: "image-child" } }
          : { id, status: "running", result: {} },
      ),
    );
    mocks.api.getConversation.mockResolvedValue({
      ...conversation(),
      messages: [message({ id: "a1", content: "Generating image", job_id: "image-child" })],
    });
    await act(async () => {
      await mocks.sync?.();
    });
    expect(result.current.busy).toBe(true);
    act(() => mocks.eventHandler?.({ type: "job.done", job_id: "image-child", text: "Image ready", ts: 2 }));
    expect(result.current.messages[0].content).toBe("Image ready");
    expect(result.current.busy).toBe(false);
  });

  it("admits only one send while a new conversation is being created", async () => {
    let resolveCreate!: (value: ChatConversation) => void;
    mocks.api.createConversation.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const { result } = renderHook(() =>
      useChatPanelController({ models: MODELS, draft: "Hello", setDraft: vi.fn() }),
    );
    let first!: Promise<void>;
    let second!: Promise<void>;
    await act(async () => {
      first = result.current.send();
      second = result.current.send();
    });
    expect(mocks.api.createConversation).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCreate(conversation());
      await Promise.all([first, second]);
    });
    expect(mocks.api.sendChatMessage).toHaveBeenCalledTimes(1);
  });
  it("sends a message, renders streamed thinking, then splits reasoning from the answer", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(await screen.findByPlaceholderText(/Message/), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(mocks.api.sendChatMessage).toHaveBeenCalledWith(
        "c1",
        expect.objectContaining({ content: "Hello", model_id: "llm" }),
      ),
    );

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
