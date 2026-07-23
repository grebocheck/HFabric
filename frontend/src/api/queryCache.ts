type CacheEntry<T> = {
  value?: T;
  updatedAt: number;
  promise?: Promise<T>;
  controller?: AbortController;
};

/**
 * Small request cache for app-level snapshots. It deduplicates concurrent
 * reads, serves fresh values briefly, and aborts obsolete requests when a key
 * is invalidated. It deliberately does not try to become a global state store.
 */
export class QueryCache {
  private readonly entries = new Map<string, CacheEntry<unknown>>();

  fetch<T>(
    key: string,
    loader: (signal: AbortSignal) => Promise<T>,
    { staleTime = 0, force = false }: { staleTime?: number; force?: boolean } = {},
  ): Promise<T> {
    const now = Date.now();
    const existing = this.entries.get(key) as CacheEntry<T> | undefined;
    if (!force && existing?.value !== undefined && now - existing.updatedAt < staleTime) {
      return Promise.resolve(existing.value);
    }
    if (existing?.promise) return existing.promise;

    const controller = new AbortController();
    const entry: CacheEntry<T> = existing ?? { updatedAt: 0 };
    const promise = loader(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          entry.value = value;
          entry.updatedAt = Date.now();
        }
        return value;
      })
      .finally(() => {
        if (entry.promise === promise) {
          entry.promise = undefined;
          entry.controller = undefined;
        }
      });
    entry.promise = promise;
    entry.controller = controller;
    this.entries.set(key, entry as CacheEntry<unknown>);
    return promise;
  }

  invalidate(key?: string) {
    if (key !== undefined) {
      const entry = this.entries.get(key);
      entry?.controller?.abort();
      this.entries.delete(key);
      return;
    }
    for (const entry of this.entries.values()) entry.controller?.abort();
    this.entries.clear();
  }
}

export const appQueryCache = new QueryCache();
