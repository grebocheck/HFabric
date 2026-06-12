import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RuntimeSettings, SettingsOverrides } from "../types";

export function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [overrides, setOverrides] = useState<SettingsOverrides | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError("");
    Promise.all([api.runtimeSettings(), api.settingsOverrides()])
      .then(([runtime, writable]) => {
        setSettings(runtime);
        setOverrides(writable);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load settings"));
  }, [open]);

  const saveOverrides = async () => {
    if (!overrides) return;
    setSaving(true);
    setError("");
    try {
      const next = await api.saveSettingsOverrides(overrides.values);
      setOverrides(next);
      setSettings(await api.runtimeSettings());
      window.dispatchEvent(new CustomEvent("hfabric:settings-overrides"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-20 bg-black/40" onClick={onClose}>
      <aside
        className="absolute right-4 top-16 flex max-h-[calc(100vh-5rem)] w-[420px] max-w-[calc(100vw-2rem)] flex-col rounded-lg border border-white/10 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <h2 className="text-sm font-semibold text-white/75">Settings</h2>
          <button onClick={onClose} className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10">
            Close
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto p-4 text-sm">
          {error ? <div className="rounded-md border border-red-400/25 bg-red-400/10 p-2 text-xs text-red-200">{error}</div> : null}
          {!settings && !error ? <div className="text-white/35">loading...</div> : null}
          {settings ? (
            <div className="flex flex-col gap-4">
              <Section title="Runtime" rows={{
                "Stub mode": settings.stub_mode,
                "Models": settings.counts.models,
                "Image models": settings.counts.image_models,
                "LLM models": settings.counts.llm_models,
                "LoRAs": settings.counts.loras,
              }} />
              {overrides ? (
                <WritableSettings
                  overrides={overrides}
                  setOverrides={setOverrides}
                  onSave={saveOverrides}
                  saving={saving}
                />
              ) : null}
              <Section title="Acceleration" rows={settings.acceleration} />
              <Section title="Memory" rows={settings.memory} />
              <p className="text-xs leading-5 text-white/35">
                Memory-safety knobs such as min_free_ram_gb and keep-warm RAM headroom stay env-only.
              </p>
              <Section title="Paths" rows={settings.paths} mono />
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function WritableSettings({
  overrides,
  setOverrides,
  onSave,
  saving,
}: {
  overrides: SettingsOverrides;
  setOverrides: (value: SettingsOverrides) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const values = overrides.values;
  const update = (key: keyof SettingsOverrides["values"], value: number | boolean) => {
    setOverrides({ ...overrides, values: { ...values, [key]: value } });
  };

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs uppercase tracking-wide text-white/40">Writable defaults</h3>
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded border border-accent/40 px-2.5 py-1 text-xs text-accent-fg hover:bg-accent/15 disabled:opacity-40"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      <div className="space-y-2 rounded-md border border-white/10 p-2.5">
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Steps" value={values.default_steps} step={1} onChange={(v) => update("default_steps", v)} />
          <NumberField label="Guidance" value={values.default_guidance} step={0.1} onChange={(v) => update("default_guidance", v)} />
          <NumberField label="Width" value={values.default_width} step={64} onChange={(v) => update("default_width", v)} />
          <NumberField label="Height" value={values.default_height} step={64} onChange={(v) => update("default_height", v)} />
          <NumberField label="Warm max" value={values.keep_warm_max_models} step={1} onChange={(v) => update("keep_warm_max_models", v)} />
          <label className="flex items-center justify-between rounded border border-white/10 bg-black/20 px-2 py-1.5 text-xs">
            <span className="text-white/45">Keep warm</span>
            <input
              type="checkbox"
              checked={values.keep_warm_models}
              onChange={(event) => update("keep_warm_models", event.target.checked)}
              className="h-4 w-4 accent-accent"
            />
          </label>
        </div>
        <p className="text-[11px] leading-4 text-white/30">
          Saved to data/settings-overrides.json and applied to new jobs or future swaps.
        </p>
      </div>
    </section>
  );
}

function NumberField({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] text-white/40">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-white/75 outline-none focus:border-accent"
      />
    </label>
  );
}

function Section({ title, rows, mono = false }: { title: string; rows: Record<string, unknown>; mono?: boolean }) {
  return (
    <section>
      <h3 className="mb-2 text-xs uppercase tracking-wide text-white/40">{title}</h3>
      <dl className="divide-y divide-white/5 rounded-md border border-white/10">
        {Object.entries(rows).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[140px_1fr] gap-2 px-2.5 py-2">
            <dt className="text-white/40">{key}</dt>
            <dd className={`min-w-0 truncate text-white/75 ${mono ? "font-mono text-xs" : ""}`} title={format(value)}>
              {format(value)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function format(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
