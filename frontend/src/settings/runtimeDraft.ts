import { createPreferences } from "../lib/preferences";
import type { SettingsOverrideValues, SettingsSchemaEntry, SettingsValue } from "../types";

function isValue(value: unknown): value is SettingsValue {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  );
}

export const runtimeDraft = createPreferences(
  "hfabric.preferences.runtime-draft",
  {
    edits: {} as Record<string, SettingsValue>,
  },
  {
    rules: {
      edits: (value): value is Record<string, SettingsValue> =>
        value !== null &&
        typeof value === "object" &&
        !Array.isArray(value) &&
        Object.values(value).every(isValue),
    },
  },
);

/** Only reapply fields still accepted by the current server schema. */
export function restoreRuntimeDraft(
  values: SettingsOverrideValues,
  schema: SettingsSchemaEntry[],
): SettingsOverrideValues {
  const restored = { ...values };
  const edits = runtimeDraft.get().edits;
  for (const spec of schema) {
    const value = edits[spec.key];
    if (value === undefined) continue;
    if (value === null) {
      if (spec.nullable) restored[spec.key] = value;
      continue;
    }
    if (spec.kind === "boolean" && typeof value !== "boolean") continue;
    if (spec.kind === "integer" || spec.kind === "number") {
      if (typeof value !== "number" || (spec.kind === "integer" && !Number.isInteger(value))) continue;
      if ((spec.min != null && value < spec.min) || (spec.max != null && value > spec.max)) continue;
    } else if (spec.kind !== "boolean" && typeof value !== "string") continue;
    if (spec.kind === "choice" && !spec.choices?.some((choice) => choice.value === value)) continue;
    restored[spec.key] = value;
  }
  return restored;
}

export function acknowledgeRuntimeDraft(submitted: SettingsOverrideValues) {
  runtimeDraft.set(({ edits }) => ({
    edits: Object.fromEntries(
      Object.entries(edits).filter(([key, value]) => !(key in submitted) || value !== submitted[key]),
    ),
  }));
}
