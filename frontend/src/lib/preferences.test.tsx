import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPreferences, inRange, oneOf, usePreference } from "./preferences";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const defaults = { model: "", steps: 28, mode: "fast" as "fast" | "quality", advanced: false };
const createStore = () =>
  createPreferences("test.preferences", defaults, {
    rules: { steps: inRange(1, 150), mode: oneOf("fast", "quality") },
  });

describe("workspace preferences", () => {
  it("persists immediately and restores through a fresh store after reload", () => {
    const store = createStore();
    const first = renderHook(() => usePreference(store, "steps"));
    act(() => first.result.current[1](42));
    first.unmount();
    expect(createStore().get()).toEqual({ ...defaults, steps: 42 });
  });

  it("merges functional updates from multiple owners without dropping other fields", () => {
    const store = createStore();
    const a = renderHook(() => usePreference(store, "steps"));
    const b = renderHook(() => usePreference(store, "model"));
    act(() => {
      a.result.current[1]((value) => value + 1);
      b.result.current[1]("local-model");
      a.result.current[1]((value) => value + 1);
    });
    expect(store.get()).toMatchObject({ steps: 30, model: "local-model" });
    expect(a.result.current[0]).toBe(30);
  });

  it("validates each field and drops unknown keys from old or tampered data", () => {
    localStorage.setItem(
      "test.preferences",
      JSON.stringify({
        version: 1,
        values: {
          model: "kept",
          steps: -100,
          mode: "removed-mode",
          advanced: "yes",
          obsolete: true,
        },
      }),
    );
    expect(createStore().get()).toEqual({ ...defaults, model: "kept" });
    localStorage.setItem("test.preferences", "{broken");
    expect(createStore().get()).toEqual(defaults);
    localStorage.setItem("test.preferences", JSON.stringify({ version: 999, values: { steps: 42 } }));
    expect(createStore().get()).toEqual(defaults);
  });

  it("migrates legacy preferences once and preserves the new version", () => {
    const migrate = vi.fn(() => ({ steps: 50 }));
    const store = createPreferences("test.preferences", defaults, { migrate });
    expect(store.get().steps).toBe(50);
    store.set((values) => ({ ...values, model: "selected" }));
    expect(createStore().get()).toMatchObject({ steps: 50, model: "selected" });
    expect(migrate).toHaveBeenCalledOnce();
  });

  it("updates subscribers after another browser tab writes preferences", () => {
    const store = createStore();
    const hook = renderHook(() => usePreference(store, "steps"));
    act(() => {
      localStorage.setItem(
        "test.preferences",
        JSON.stringify({ version: 1, values: { ...defaults, steps: 60 } }),
      );
      window.dispatchEvent(new StorageEvent("storage", { key: "test.preferences" }));
    });
    expect(hook.result.current[0]).toBe(60);
  });

  it("keeps the current session usable when storage writes are blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const store = createStore();
    const hook = renderHook(() => usePreference(store, "steps"));
    act(() => hook.result.current[1](70));
    expect(hook.result.current[0]).toBe(70);
    expect(store.get().steps).toBe(70);
  });

  it("keeps edits in memory when localStorage is unavailable", () => {
    vi.stubGlobal("localStorage", undefined);
    const store = createStore();
    const hook = renderHook(() => usePreference(store, "steps"));
    act(() => hook.result.current[1](65));
    expect(hook.result.current[0]).toBe(65);
  });
});
