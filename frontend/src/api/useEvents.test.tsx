import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reconnectDelay, useEvents } from "./useEvents";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.onopen?.();
  }

  close() {
    this.onclose?.();
  }

  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useEvents", () => {
  it("uses capped exponential backoff with jitter", () => {
    expect(reconnectDelay(0, () => 0.5, 500, 30_000)).toBe(500);
    expect(reconnectDelay(3, () => 0.5, 500, 30_000)).toBe(4_000);
    expect(reconnectDelay(20, () => 0.5, 500, 30_000)).toBe(30_000);
    expect(reconnectDelay(1, () => 0, 500, 30_000)).toBe(800);
  });

  it("reconciles a snapshot before reporting ready", async () => {
    let resolveSync: (() => void) | undefined;
    const sync = vi.fn(() => new Promise<void>((resolve) => {
      resolveSync = resolve;
    }));
    const onEvent = vi.fn();
    const { result } = renderHook(() => useEvents(onEvent, { onConnect: sync }));
    const socket = FakeWebSocket.instances[0];

    act(() => socket.open());
    expect(result.current.state).toBe("syncing");
    expect(sync).toHaveBeenCalledTimes(1);

    act(() => resolveSync?.());
    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(result.current.connected).toBe(true);
    expect(result.current.lastSyncAt).not.toBeNull();

    act(() => socket.message({ type: "job.done", ts: 1 }));
    expect(onEvent).toHaveBeenCalledWith({ type: "job.done", ts: 1 });
  });

  it("reconnects after the jittered delay and reconciles again", async () => {
    vi.useFakeTimers();
    const sync = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useEvents(() => undefined, {
      onReconnect: sync,
      random: () => 0.5,
      baseDelayMs: 500,
    }));
    const first = FakeWebSocket.instances[0];
    act(() => first.open());
    await act(async () => Promise.resolve());
    expect(sync).not.toHaveBeenCalled();
    act(() => first.close());
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => vi.advanceTimersByTime(500));
    expect(FakeWebSocket.instances).toHaveLength(2);
    act(() => FakeWebSocket.instances[1].open());
    await act(async () => Promise.resolve());
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("pauses reconnect timers while the tab is hidden", () => {
    vi.useFakeTimers();
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    renderHook(() => useEvents(() => undefined, {
      random: () => 0.5,
      baseDelayMs: 500,
    }));
    const first = FakeWebSocket.instances[0];
    visibility = "hidden";
    act(() => first.close());
    act(() => vi.advanceTimersByTime(5_000));
    expect(FakeWebSocket.instances).toHaveLength(1);

    visibility = "visible";
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
