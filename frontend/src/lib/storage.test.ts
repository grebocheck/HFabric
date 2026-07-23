import { afterEach, describe, expect, it, vi } from "vitest";

import { readStoredEnum, storage } from "./storage";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("storage", () => {
  it("reads and writes values", () => {
    expect(storage.set("key", "value")).toBe(true);
    expect(storage.get("key")).toBe("value");
    expect(storage.remove("key")).toBe(true);
    expect(storage.get("key")).toBeNull();
  });

  it("falls back when a stored enum value is invalid", () => {
    localStorage.setItem("view", "invented");
    expect(readStoredEnum("view", ["images", "history"] as const, "images")).toBe("images");
  });

  it("does not crash when browser storage rejects access", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked");
    });

    expect(storage.get("key")).toBeNull();
    expect(storage.set("key", "value")).toBe(false);
    expect(storage.remove("key")).toBe(false);
  });
});
