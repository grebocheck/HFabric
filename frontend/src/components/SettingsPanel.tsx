import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { LlamaRuntime } from "./LlamaRuntime";
import { Panel, SectionTitle, SkeletonRows, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import { Toggle } from "./Toggle";
import { toast } from "./Toast";
import type {
  RuntimeSettings,
  SettingsGroup,
  SettingsOverrideValues,
  SettingsSchemaEntry,
  SettingsValue,
} from "../types";

const control =
  "w-full rounded-md border border-white/10 bg-black/25 px-2.5 py-1.5 text-sm text-white/80 outline-none transition placeholder:text-white/25 focus:border-accent";
const subtleButton =
  "rounded-md border border-white/15 px-3 py-1.5 text-sm text-white/65 transition hover:bg-white/10 hover:text-white disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent-hover disabled:opacity-35";

export function SettingsPanel() {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [overrides, setOverrides] = useState<{
    values: SettingsOverrideValues;
    groups: SettingsGroup[];
    schema: SettingsSchemaEntry[];
    path: string;
  } | null>(null);
  const [saved, setSaved] = useState<SettingsOverrideValues | null>(null);
  const [draft, setDraft] = useState<SettingsOverrideValues | null>(null);
  const [activeGroup, setActiveGroup] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [runtime, writable] = await Promise.all([api.runtimeSettings(), api.settingsOverrides()]);
      setSettings(runtime);
      setOverrides({
        values: writable.values,
        groups: writable.groups,
        schema: writable.schema,
        path: writable.path,
      });
      setSaved(writable.values);
      setDraft(writable.values);
      setActiveGroup((current) => current || writable.groups[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load settings");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const specs = useMemo(() => overrides?.schema ?? [], [overrides?.schema]);
  const groups = useMemo(() => overrides?.groups ?? [], [overrides?.groups]);
  const cleanQuery = query.trim().toLowerCase();
  const visibleSpecs = useMemo(
    () => specs.filter((spec) => matchesQuery(spec, cleanQuery)),
    [specs, cleanQuery],
  );
  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const spec of visibleSpecs) counts[spec.group] = (counts[spec.group] ?? 0) + 1;
    return counts;
  }, [visibleSpecs]);

  useEffect(() => {
    if (!groups.length) return;
    if (!activeGroup || (cleanQuery && !groupCounts[activeGroup])) {
      const next = groups.find((group) => !cleanQuery || groupCounts[group.id])?.id;
      if (next) setActiveGroup(next);
    }
  }, [activeGroup, cleanQuery, groupCounts, groups]);

  const changedKeys = useMemo(() => {
    if (!draft || !saved) return [];
    return specs
      .filter((spec) => !sameValue(draft[spec.key], saved[spec.key]))
      .map((spec) => spec.key);
  }, [draft, saved, specs]);
  const changedSet = useMemo(() => new Set(changedKeys), [changedKeys]);
  const restartChanged = useMemo(
    () => specs.filter((spec) => spec.restart_required && changedSet.has(spec.key)),
    [changedSet, specs],
  );
  const activeSpecs = visibleSpecs.filter((spec) => spec.group === activeGroup);
  const activeMeta = groups.find((group) => group.id === activeGroup);

  const updateDraft = useCallback((key: string, value: SettingsValue) => {
    setDraft((current) => ({ ...(current ?? {}), [key]: value } as SettingsOverrideValues));
  }, []);

  const save = async () => {
    if (!draft || !changedKeys.length) return;
    setSaving(true);
    setError("");
    try {
      const next = await api.saveSettingsOverrides(draft);
      setOverrides({
        values: next.values,
        groups: next.groups,
        schema: next.schema,
        path: next.path,
      });
      setSaved(next.values);
      setDraft(next.values);
      setSettings(await api.runtimeSettings());
      window.dispatchEvent(new CustomEvent("hfabric:settings-overrides"));
      toast.success("Settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    if (saved) setDraft(saved);
    setError("");
  };

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-hidden">
      <WorkspaceHeader
        title="Settings"
        subtitle="Persistent local defaults for generation, model runtime, memory policy, and tool placement."
        actions={
          <>
            <button onClick={() => void load()} className={subtleButton} disabled={saving}>
              Refresh
            </button>
            <button onClick={revert} className={subtleButton} disabled={!changedKeys.length || saving}>
              Revert
            </button>
            <button onClick={() => void save()} className={primaryButton} disabled={!changedKeys.length || saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </>
        }
      >
        <StatusPill label={settings?.stub_mode ? "STUB mode" : "GPU mode"} tone={settings?.stub_mode ? "warn" : "good"} />
        <StatusPill label={`${specs.length || 0} writable settings`} tone="info" />
        <StatusPill label={changedKeys.length ? `${changedKeys.length} unsaved` : "saved"} tone={changedKeys.length ? "warn" : "good"} />
        {restartChanged.length ? <StatusPill label={`${restartChanged.length} need restart`} tone="warn" /> : null}
      </WorkspaceHeader>

      {error ? (
        <div className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-sm text-error-fg">{error}</div>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)_300px] gap-4 max-[1180px]:grid-cols-[230px_minmax(0,1fr)] max-[860px]:block max-[860px]:overflow-y-auto">
        <Panel className="min-h-0 overflow-hidden max-[860px]:mb-4">
          <SectionTitle title="Groups" subtitle={changedKeys.length ? `${changedKeys.length} pending changes` : "No pending changes"} />
          <div className="border-b border-white/10 p-3">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className={control}
              placeholder="Search settings"
            />
          </div>
          <nav className="min-h-0 overflow-y-auto p-2">
            {groups.map((group) => {
              const count = groupCounts[group.id] ?? 0;
              if (cleanQuery && !count) return null;
              const dirty = specs.some((spec) => spec.group === group.id && changedSet.has(spec.key));
              return (
                <button
                  key={group.id}
                  onClick={() => setActiveGroup(group.id)}
                  className={`mb-1 flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition ${
                    activeGroup === group.id
                      ? "bg-accent/20 text-white"
                      : "text-white/55 hover:bg-white/10 hover:text-white/85"
                  }`}
                >
                  <span className="min-w-0 truncate">{group.label}</span>
                  <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] ${dirty ? "bg-warn/20 text-warn-fg" : "bg-white/10 text-white/45"}`}>
                    {count || specs.filter((spec) => spec.group === group.id).length}
                  </span>
                </button>
              );
            })}
          </nav>
        </Panel>

        <Panel className="min-h-0 overflow-hidden max-[860px]:mb-4">
          <SectionTitle
            title={activeMeta?.label ?? "Settings"}
            subtitle={activeMeta?.description}
            actions={restartChanged.some((spec) => spec.group === activeGroup) ? <StatusPill label="restart pending" tone="warn" /> : null}
          />
          <div className="min-h-0 overflow-y-auto p-4">
            {!draft && !error ? <SkeletonRows rows={8} /> : null}
            {draft && activeSpecs.length ? (
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                {activeSpecs.map((spec) => (
                  <SettingField
                    key={spec.key}
                    spec={spec}
                    value={draft[spec.key]}
                    dirty={changedSet.has(spec.key)}
                    onChange={(value) => updateDraft(spec.key, value)}
                  />
                ))}
              </div>
            ) : null}
            {draft && !activeSpecs.length ? (
              <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-white/10 text-sm text-white/35">
                No matching settings
              </div>
            ) : null}
          </div>
        </Panel>

        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto max-[1180px]:col-span-2 max-[860px]:col-span-1">
          <RuntimeSummary settings={settings} />
          <LlamaRuntime />
          <Panel>
            <SectionTitle title="System .env" subtitle="Kept outside the Settings tab" />
            <div className="space-y-2 p-3 text-xs">
              <EnvOnly label="Host" value="HFAB_HOST" />
              <EnvOnly label="Port" value="HFAB_PORT" />
              <EnvOnly label="API token" value="HFAB_API_TOKEN" />
              <EnvOnly label="Serve frontend" value="HFAB_SERVE_FRONTEND" />
              <EnvOnly label="Frontend dev port" value="HFAB_FRONTEND_PORT" />
            </div>
          </Panel>
          <Panel>
            <SectionTitle title="Persistence" subtitle="Local override file" />
            <div className="p-3 text-xs">
              <div className="truncate rounded-md border border-white/10 bg-black/25 px-2 py-1.5 font-mono text-white/55" title={overrides?.path ?? ""}>
                {overrides?.path ?? "loading..."}
              </div>
              {restartChanged.length ? (
                <div className="mt-3 rounded-md border border-warn/25 bg-warn/10 px-3 py-2 text-warn-fg">
                  Restart required for: {restartChanged.map((spec) => spec.label).join(", ")}
                </div>
              ) : null}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function SettingField({
  spec,
  value,
  dirty,
  onChange,
}: {
  spec: SettingsSchemaEntry;
  value: SettingsValue;
  dirty: boolean;
  onChange: (value: SettingsValue) => void;
}) {
  return (
    <label className={`block rounded-md border bg-black/20 p-3 ${dirty ? "border-warn/35" : "border-white/10"}`}>
      <div className="mb-2 flex min-h-6 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-white/80" title={spec.label}>{spec.label}</div>
          {spec.description ? <div className="mt-0.5 max-h-8 overflow-hidden text-xs leading-4 text-white/35">{spec.description}</div> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {dirty ? <MiniPill tone="warn">edited</MiniPill> : null}
          {spec.restart_required ? <MiniPill>restart</MiniPill> : null}
        </div>
      </div>
      <Control spec={spec} value={value} onChange={onChange} />
      {spec.min != null || spec.max != null || spec.multiple_of ? (
        <div className="mt-1.5 truncate text-[11px] text-white/30">
          {[spec.min != null ? `min ${formatValue(spec.min)}` : "", spec.max != null ? `max ${formatValue(spec.max)}` : "", spec.multiple_of ? `step ${spec.multiple_of}` : ""]
            .filter(Boolean)
            .join(" / ")}
        </div>
      ) : null}
    </label>
  );
}

function Control({
  spec,
  value,
  onChange,
}: {
  spec: SettingsSchemaEntry;
  value: SettingsValue;
  onChange: (value: SettingsValue) => void;
}) {
  if (spec.kind === "boolean") {
    return (
      <div className="flex h-9 items-center justify-between rounded-md border border-white/10 bg-black/25 px-2.5">
        <span className="text-sm text-white/50">{value ? "On" : "Off"}</span>
        <Toggle checked={Boolean(value)} onChange={onChange} ariaLabel={spec.label} />
      </div>
    );
  }

  if (spec.kind === "choice") {
    return (
      <select
        value={value == null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value)}
        className={control}
      >
        {(spec.choices ?? []).map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
    );
  }

  if (spec.kind === "integer" || spec.kind === "number") {
    const numericKind = spec.kind;
    return (
      <input
        type="number"
        value={value == null ? "" : String(value)}
        min={spec.min}
        max={spec.max}
        step={spec.step ?? (spec.kind === "integer" ? 1 : 0.1)}
        onChange={(event) => onChange(parseNumeric(event.target.value, numericKind))}
        className={control}
      />
    );
  }

  return (
    <input
      type="text"
      value={value == null ? "" : String(value)}
      onChange={(event) => onChange(event.target.value)}
      className={`${control} ${spec.kind === "path" ? "font-mono text-xs" : ""}`}
      placeholder={spec.nullable ? "unset" : undefined}
    />
  );
}

function RuntimeSummary({ settings }: { settings: RuntimeSettings | null }) {
  const capability = settings?.capability;
  const gpuName = capability?.primary_gpu?.name ?? "-";
  const vramMb = capability?.primary_gpu?.vram_mb;
  const gpuLabel = vramMb ? `${gpuName} (${Math.round(vramMb / 1024)} GB)` : gpuName;

  return (
    <Panel>
      <SectionTitle title="Runtime" subtitle={capability?.effective_stub_mode ? "STUB mode" : "Current process"} />
      <div className="space-y-3 p-3 text-xs">
        {settings ? (
          <>
            {capability ? (
              <SummaryRows rows={{
                "Profile": capability.active_profile,
                "Backend": capability.backend,
                "Tier": capability.hardware_tier,
                "GPU": gpuLabel,
              }} />
            ) : null}
            <SummaryRows rows={{
              "Image models": String(settings.counts.image_models ?? 0),
              "LLM models": String(settings.counts.llm_models ?? 0),
              "LoRAs": String(settings.counts.loras ?? 0),
              "Learned profiles": String(settings.counts.learned_profiles ?? 0),
            }} />
            <SummaryRows rows={{
              "Attention": String(settings.acceleration.attention_backend ?? "-"),
              "torch.compile": formatValue(settings.acceleration.torch_compile),
              "FLUX cache": String(settings.acceleration.flux_step_cache ?? "-"),
              "RAM guard": `${formatValue(settings.memory.min_free_ram_gb)} GB`,
            }} />
          </>
        ) : (
          <SkeletonRows rows={3} />
        )}
      </div>
    </Panel>
  );
}

function SummaryRows({ rows }: { rows: Record<string, string> }) {
  return (
    <dl className="space-y-1.5 rounded-md border border-white/10 bg-black/20 p-3">
      {Object.entries(rows).map(([key, value]) => (
        <div key={key} className="grid min-w-0 grid-cols-[110px_minmax(0,1fr)] gap-2">
          <dt className="text-white/35">{key}</dt>
          <dd className="truncate text-white/65" title={value}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function EnvOnly({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 grid-cols-[96px_minmax(0,1fr)] gap-2 rounded-md border border-white/10 bg-black/20 px-2 py-1.5">
      <span className="text-white/35">{label}</span>
      <span className="truncate font-mono text-white/65" title={value}>{value}</span>
    </div>
  );
}

function MiniPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${tone === "warn" ? "bg-warn/20 text-warn-fg" : "bg-white/10 text-white/45"}`}>
      {children}
    </span>
  );
}

function matchesQuery(spec: SettingsSchemaEntry, query: string): boolean {
  if (!query) return true;
  return (
    spec.key.toLowerCase().includes(query)
    || spec.label.toLowerCase().includes(query)
    || (spec.description ?? "").toLowerCase().includes(query)
  );
}

function parseNumeric(raw: string, kind: "integer" | "number"): SettingsValue {
  if (raw.trim() === "") return "";
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  return kind === "integer" ? Math.trunc(value) : value;
}

function sameValue(a: SettingsValue, b: SettingsValue): boolean {
  return a === b || (a == null && b === "") || (b == null && a === "");
}

function formatValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}
