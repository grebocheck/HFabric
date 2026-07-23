/**
 * A single, defensive boundary around browser storage.
 *
 * Browsers can expose `localStorage` while still throwing on access (private
 * mode, disabled cookies, a full quota, or an opaque origin). UI state must
 * remain usable in all of those cases.
 */
export const storage = {
  get(key: string): string | null {
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  },

  set(key: string, value: string): boolean {
    try {
      globalThis.localStorage?.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },

  remove(key: string): boolean {
    try {
      globalThis.localStorage?.removeItem(key);
      return true;
    } catch {
      return false;
    }
  },
};

export function readStoredEnum<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const value = storage.get(key);
  return value !== null && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}
