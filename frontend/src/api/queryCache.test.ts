import { describe, expect, it, vi } from "vitest";

import { QueryCache } from "./queryCache";

describe("QueryCache", () => {
  it("deduplicates concurrent reads and serves fresh data", async () => {
    const cache = new QueryCache();
    const loader = vi.fn(async () => ({ value: 1 }));
    const first = cache.fetch("jobs", loader, { staleTime: 10_000 });
    const second = cache.fetch("jobs", loader, { staleTime: 10_000 });
    expect(first).toBe(second);
    await expect(first).resolves.toEqual({ value: 1 });
    await expect(cache.fetch("jobs", loader, { staleTime: 10_000 })).resolves.toEqual({ value: 1 });
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight request when invalidated", () => {
    const cache = new QueryCache();
    let signal: AbortSignal | undefined;
    void cache.fetch("jobs", async (nextSignal) => {
      signal = nextSignal;
      return new Promise<never>(() => undefined);
    });
    cache.invalidate("jobs");
    expect(signal?.aborted).toBe(true);
  });
});
