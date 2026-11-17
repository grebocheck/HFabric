import { useCallback, useSyncExternalStore, type SetStateAction } from "react";
import { storage } from "./storage";

type Validator<T> = (value: unknown) => value is T;
type Rules<T> = { [K in keyof T]?: Validator<T[K]> };

export const oneOf =
  <T extends string>(...values: T[]): Validator<T> =>
  (value): value is T =>
    typeof value === "string" && values.includes(value as T);
export const inRange =
  (min: number, max: number): Validator<number> =>
  (value): value is number =>
    typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
export const optionalNumber: Validator<number | ""> = (value): value is number | "" =>
  value === "" || (typeof value === "number" && Number.isFinite(value));
export const stringList: Validator<string[]> = (value): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

function restore<T>(fallback: T, value: unknown): T {
  if (typeof fallback === "number")
    return (typeof value === "number" && Number.isFinite(value) ? value : fallback) as T;
  if (Array.isArray(fallback)) return (Array.isArray(value) ? value : fallback) as T;
  if (fallback && typeof fallback === "object") {
    const record =
      value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
    return Object.fromEntries(
      Object.entries(fallback).map(([key, item]) => [key, restore(item, record[key])]),
    ) as T;
  }
  return (typeof value === typeof fallback ? value : fallback) as T;
}

/** One versioned document per workspace. Writes happen in the setter, so reload
 * and unmount never depend on an effect/debounce. Server resources stay on the
 * server; this store owns only explicitly declared browser preferences/drafts.
 */
export function createPreferences<T extends object>(
  key: string,
  defaults: T,
  options: { rules?: Rules<T>; migrate?: () => Partial<T>; parse?: (value: unknown) => T } = {},
) {
  let raw: string | null | undefined;
  let snapshot = defaults;
  const listeners = new Set<() => void>();
  const decode = (candidate: unknown): T => {
    if (options.parse) return options.parse(candidate);
    const next = restore(defaults, candidate);
    for (const field of Object.keys(options.rules ?? {}) as Array<keyof T>) {
      const value = candidate && typeof candidate === "object" ? (candidate as T)[field] : undefined;
      const validate = options.rules?.[field];
      if (validate) next[field] = validate(value) ? value : defaults[field];
    }
    return next;
  };
  const get = (): T => {
    const stored = storage.get(key);
    if (stored !== raw) {
      raw = stored;
      try {
        const parsed = stored ? JSON.parse(stored) : null;
        snapshot = decode(parsed?.version === 1 ? parsed.values : parsed ? {} : (options.migrate?.() ?? {}));
      } catch {
        snapshot = decode({});
      }
    }
    return snapshot;
  };
  const notify = () => listeners.forEach((listener) => listener());
  const onStorage = (event: StorageEvent) => {
    if (event.key === key || event.key === null) notify();
  };
  const set = (action: SetStateAction<T>) => {
    const current = get();
    const next = decode(typeof action === "function" ? action(current) : action);
    if (JSON.stringify(next) === JSON.stringify(current)) return;
    snapshot = next;
    const encoded = JSON.stringify({ version: 1, values: next });
    // Preserve this session's edits even when browser persistence is unavailable.
    raw = storage.set(key, encoded) ? encoded : storage.get(key);
    notify();
  };
  const subscribe = (listener: () => void) => {
    if (!listeners.size) globalThis.addEventListener?.("storage", onStorage);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
      if (!listeners.size) globalThis.removeEventListener?.("storage", onStorage);
    };
  };
  return { get, set, subscribe };
}

type Preferences<T extends object> = ReturnType<typeof createPreferences<T>>;

export function usePreferences<T extends object>(store: Preferences<T>) {
  const value = useSyncExternalStore(store.subscribe, store.get, store.get);
  return [value, store.set] as const;
}

export function usePreference<T extends object, K extends keyof T>(store: Preferences<T>, key: K) {
  const [values] = usePreferences(store);
  const set = useCallback(
    (action: SetStateAction<T[K]>) => {
      store.set((current) => ({
        ...current,
        [key]: typeof action === "function" ? (action as (value: T[K]) => T[K])(current[key]) : action,
      }));
    },
    [store, key],
  );
  return [values[key], set] as const;
}
