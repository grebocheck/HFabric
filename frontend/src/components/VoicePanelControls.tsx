import type { ReactNode } from "react";
import { Badge } from "./Badge";
import { Slider } from "./Slider";
import { WaveformMonitor, type MeterSample } from "./VoiceMeters";
import { f0Options, formatMs } from "./voiceHelpers";
import type {
  VoiceEngineAsset,
  VoiceEnginePreset,
  VoiceEngineSettingsUpdate,
  VoiceEngineStatus,
  VoiceModel,
} from "../types";

export const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-sm";
export const assetSearchHint = "ContentVec + rmvpe.pt -> models/voice/pretrain";
const denoiseAssetHint = "dtln_model_1.onnx + dtln_model_2.onnx -> models/voice/pretrain/denoise";
export const modelDirHint = "models/voice";

const nativeF0Detectors = new Set(["rmvpe", "fcpe", "crepe_tiny", "crepe_full"]);
export const nativeF0Options = f0Options.map((option) => (
  nativeF0Detectors.has(option.value)
    ? option
    : { ...option, disabled: true, hint: "unavailable" }
));


export function focusIsTextEntry(): boolean {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement)) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable;
}

export function routingKey(body: VoiceEngineSettingsUpdate): string {
  return JSON.stringify(body);
}

export function parseApiError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const match = raw.match(/^(\d{3})\s+([\s\S]*)$/);
  const status = match?.[1] ?? "";
  let detail = match?.[2] ?? raw;
  try {
    const parsed = JSON.parse(detail) as { detail?: unknown };
    if (parsed.detail) detail = String(parsed.detail);
  } catch {
    // Keep the plain response text.
  }
  if (status === "415") return `Unsupported audio file: ${detail}`;
  if (status === "503") return `Voice engine is not ready: ${detail}`;
  if (status === "413") return `Audio file is too large: ${detail}`;
  return detail || raw;
}

export function assetTitle(asset: VoiceEngineAsset): string {
  if (!asset.found && asset.name === "denoise_dtln") return denoiseAssetHint;
  return asset.found ? (asset.path ?? asset.name) : assetSearchHint;
}

export function timingsLine(timings: Record<string, number>): string {
  const parts = Object.entries(timings)
    .filter(([, value]) => Number.isFinite(value))
    .map(([key, value]) => `${key} ${formatMs(value)}`);
  return parts.join(" / ") || "timings unavailable";
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}

function signed(value: number, digits = 0): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}

export function Panel({
  title,
  eyebrow,
  aside,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface p-4 shadow-panel ${className}`}>
      <div className="mb-3 flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow ? <div className="text-[11px] font-medium text-ui-subtle">{eyebrow}</div> : null}
          <h3 className="truncate text-sm font-semibold text-ui-strong">{title}</h3>
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function StatusTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "good" | "warn" | "info";
}) {
  const color = {
    neutral: "border-line bg-control",
    good: "border-success-border bg-success-bg",
    warn: "border-warn-border bg-warn-bg",
    info: "border-info-border bg-info-bg",
  }[tone];
  return (
    <div className={`min-w-0 rounded-md border px-3 py-2 ${color}`}>
      <div className="truncate text-[11px] text-ui-subtle">{label}</div>
      <div className="mt-0.5 truncate text-sm font-medium text-ui">{value}</div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  tone = "ghost",
  className = "",
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "ghost" | "primary" | "danger" | "warn" | "success";
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  const tones = {
    ghost: "border-line bg-control text-ui-muted hover:bg-control-hover hover:text-ui",
    primary: "border-accent/40 bg-accent text-ui-inverse hover:bg-accent-hover",
    danger: "border-error-border bg-error text-ui-inverse hover:bg-error",
    warn: "border-warn-border bg-warn-bg text-warn-fg hover:bg-warn-bg",
    success: "border-success-border bg-success text-ui-inverse hover:bg-success",
  }[tone];
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-35 ${tones} ${className}`}
    >
      {children}
    </button>
  );
}

export function MiniButton({
  children,
  onClick,
  active = false,
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-2 py-1 text-xs transition disabled:opacity-30 ${
        active
          ? "border-accent/45 bg-accent/15 text-accent-fg"
          : "border-line bg-control text-ui-muted hover:bg-control-hover hover:text-ui"
      }`}
    >
      {children}
    </button>
  );
}

export function SignedControl({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  unit = "",
  precision = 0,
  quick = [],
  disabled = false,
  note,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  unit?: string;
  precision?: number;
  quick?: number[];
  disabled?: boolean;
  note?: ReactNode;
}) {
  const commit = (next: number) => onChange(clamp(Number(next.toFixed(precision || 3)), min, max));
  return (
    <div className={`rounded-md border border-line bg-control p-3 ${disabled ? "opacity-55" : ""}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 text-xs font-medium text-ui-muted">{label}</div>
        <div className="shrink-0 font-mono text-lg font-semibold tabular-nums text-ui-strong">
          {signed(value, precision)}{unit}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-[34px_1fr_34px] items-center gap-2">
        <button
          type="button"
          onClick={() => commit(value - step)}
          disabled={disabled || value <= min}
          className="grid h-8 w-8 place-items-center rounded-md border border-line bg-raised text-lg leading-none text-ui-muted transition hover:bg-control-hover disabled:opacity-25"
        >
          -
        </button>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(event) => commit(Number(event.target.value))}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-control-active accent-accent disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={() => commit(value + step)}
          disabled={disabled || value >= max}
          className="grid h-8 w-8 place-items-center rounded-md border border-line bg-raised text-lg leading-none text-ui-muted transition hover:bg-control-hover disabled:opacity-25"
        >
          +
        </button>
      </div>
      {quick.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {quick.map((item) => (
            <MiniButton key={item} active={Math.abs(item - value) < step / 2} disabled={disabled} onClick={() => commit(item)}>
              {signed(item, precision)}{unit}
            </MiniButton>
          ))}
        </div>
      ) : null}
      {note ? <div className="mt-2 text-xs text-ui-subtle">{note}</div> : null}
    </div>
  );
}

export function CompactSignedControl({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  precision = 0,
  unit = "",
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  precision?: number;
  unit?: string;
}) {
  const commit = (next: number) => onChange(clamp(Number(next.toFixed(precision || 3)), min, max));
  return (
    <div className="min-w-0 rounded-md border border-line bg-control px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-ui-muted">{label}</span>
        <span className="shrink-0 font-mono text-sm font-semibold tabular-nums text-ui">
          {signed(value, precision)}{unit}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-[24px_1fr_24px] items-center gap-2">
        <button
          type="button"
          onClick={() => commit(value - step)}
          className="grid h-6 w-6 place-items-center rounded border border-line text-sm text-ui-muted hover:bg-control-hover"
        >
          -
        </button>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => commit(Number(event.target.value))}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-control-active accent-accent"
        />
        <button
          type="button"
          onClick={() => commit(value + step)}
          className="grid h-6 w-6 place-items-center rounded border border-line text-sm text-ui-muted hover:bg-control-hover"
        >
          +
        </button>
      </div>
    </div>
  );
}

export function LabeledSlider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  valueLabel,
  tone = "neutral",
  note,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  valueLabel?: string;
  tone?: "neutral" | "warn";
  note?: ReactNode;
  disabled?: boolean;
}) {
  const toneClass = tone === "warn" ? "text-warn-fg" : "text-ui-muted";
  const noteClass = tone === "warn" ? "text-warn-fg" : "text-ui-subtle";
  return (
    <div className={`min-w-0 ${disabled ? "opacity-45" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <div className={`truncate text-xs font-medium ${toneClass}`}>{label}</div>
        {valueLabel ? <div className="shrink-0 font-mono text-xs tabular-nums text-ui-subtle">{valueLabel}</div> : null}
      </div>
      <Slider value={value} min={min} max={max} step={step} onChange={onChange} disabled={disabled} />
      {note ? <div className={`mt-1 truncate text-[11px] ${noteClass}`} title={String(note)}>{note}</div> : null}
    </div>
  );
}

function presetMetric(preset: VoiceEnginePreset, key: keyof VoiceEngineSettingsUpdate, fallback = "..."): string {
  const value = preset.settings[key];
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number") {
    if (key === "input_formant" || key === "index_ratio" || key === "noise_scale" || key === "f0_smoothing") {
      return value.toFixed(2);
    }
    return String(value);
  }
  return String(value);
}

function presetModelLabel(preset: VoiceEnginePreset, models: VoiceModel[]): string {
  if (!preset.model_id) return "settings only";
  return models.find((model) => model.id === preset.model_id)?.name ?? preset.model_id;
}

export function PresetCard({
  preset,
  models,
  active,
  canApply,
  busy,
  onSelect,
  onApply,
  onUpdate,
  onDelete,
}: {
  preset: VoiceEnginePreset;
  models: VoiceModel[];
  active: boolean;
  canApply: boolean;
  busy: string;
  onSelect: () => void;
  onApply: () => void;
  onUpdate: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`rounded-md border p-3 transition ${
        active ? "border-accent/45 bg-accent/10" : "border-line bg-control hover:bg-control-hover"
      }`}
    >
      <button type="button" onClick={onSelect} className="block w-full min-w-0 text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ui-strong">{preset.name}</div>
            <div className="mt-1 truncate text-xs text-ui-subtle" title={presetModelLabel(preset, models)}>
              {presetModelLabel(preset, models)}
            </div>
          </div>
          {preset.model_id ? <Badge color="bg-sky-700/45 text-sky-100">model</Badge> : <Badge>settings</Badge>}
        </div>
        <div className="mt-3 grid grid-cols-4 gap-1.5">
          <PresetMini label="pitch" value={presetMetric(preset, "pitch", "0")} />
          <PresetMini label="form" value={presetMetric(preset, "input_formant", "0.00")} />
          <PresetMini label="idx" value={presetMetric(preset, "index_ratio", "0.00")} />
          <PresetMini label="chunk" value={presetMetric(preset, "server_read_chunk_size", "...")} />
        </div>
      </button>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button onClick={onApply} disabled={!canApply} tone={active ? "primary" : "ghost"} className="px-2 py-1 text-xs">
          {busy === "preset-apply" && active ? "Applying..." : "Apply"}
        </Button>
        <Button onClick={onUpdate} disabled={!canApply || !active} className="px-2 py-1 text-xs">
          {busy === "preset-update" && active ? "Updating..." : "Update"}
        </Button>
        <Button onClick={onDelete} disabled={!canApply || !active} tone="danger" className="px-2 py-1 text-xs">
          {busy === "preset-delete" && active ? "Deleting..." : "Delete"}
        </Button>
      </div>
    </div>
  );
}

function PresetMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded border border-line bg-raised px-2 py-1">
      <div className="truncate text-[10px] text-ui-subtle">{label}</div>
      <div className="truncate font-mono text-[11px] tabular-nums text-ui-muted">{value}</div>
    </div>
  );
}

export function DiagnosticsCompact({ status, samples }: { status: VoiceEngineStatus | null; samples: MeterSample[] }) {
  const metrics = status?.metrics;
  const providers = metrics?.provider_health;
  const timings = Object.entries(metrics?.timings_ms ?? {})
    .filter(([, value]) => Number.isFinite(value))
    .slice(0, 5);
  const peak = metrics?.output_peak ?? 0;
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-2">
        <StatusTile label="Total" value={formatMs(metrics?.total_ms ?? metrics?.chunk_ms)} />
        <StatusTile label="P95" value={formatMs(metrics?.total_p95_ms)} tone={metrics?.latency_warning ? "warn" : "neutral"} />
        <StatusTile label="Chunk" value={formatMs(metrics?.chunk_ms)} />
        <StatusTile label="Headroom" value={formatMs(metrics?.latency_headroom_ms)} tone={(metrics?.latency_headroom_ms ?? 1) <= 0 ? "warn" : "neutral"} />
        <StatusTile label="Peak" value={`${Math.round(peak * 100)}%`} tone={peak >= 0.85 ? "warn" : "neutral"} />
        <StatusTile label="Overruns" value={metrics?.overruns ?? 0} tone={metrics?.overruns ? "warn" : "neutral"} />
        <StatusTile label="Squelch" value={metrics?.squelched ? "silence" : "voice"} tone={metrics?.squelched ? "warn" : "good"} />
      </div>
      {metrics?.latency_warning ? (
        <div className="rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
          {metrics.latency_warning}
        </div>
      ) : null}
      <WaveformMonitor samples={samples} />
      <ProviderHealth providers={providers} />
      <div className="grid gap-1.5">
        {timings.length ? timings.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 rounded border border-line bg-control px-2 py-1 text-xs">
            <span className="truncate text-ui-subtle">{label}</span>
            <span className="shrink-0 font-mono text-ui-muted">{formatMs(value)}</span>
          </div>
        )) : (
          <div className="rounded border border-line bg-control px-2 py-1.5 text-xs text-ui-subtle">waiting for stages</div>
        )}
      </div>
    </div>
  );
}

function ProviderHealth({
  providers,
}: {
  providers?: VoiceEngineStatus["metrics"]["provider_health"];
}) {
  const rows = [
    ["ContentVec", providers?.content_vec],
    ["F0", providers?.f0],
  ] as const;
  return (
    <div className="grid gap-1.5">
      {rows.map(([label, item]) => (
        <div key={label} className="flex items-center justify-between gap-3 rounded border border-line bg-control px-2 py-1 text-xs">
          <span className="truncate text-ui-subtle">{label}</span>
          <span className="shrink-0 truncate font-mono text-ui-muted" title={String(item?.actual ?? item?.requested ?? "unknown")}>
            {item?.actual ?? item?.requested ?? "unknown"}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ModelBadges({ model }: { model: VoiceModel | null | undefined }) {
  if (!model) return <Badge>no voice</Badge>;
  return (
    <span className="flex flex-wrap gap-1.5">
      <Badge color="bg-accent/45 text-accent-fg">{model.type}{model.version ? ` ${model.version}` : ""}</Badge>
      <Badge color={model.f0 ? "bg-sky-700/50 text-sky-100" : "bg-white/10 text-white/55"}>
        {model.f0 ? "f0 pitch" : "no f0"}
      </Badge>
      <Badge color={model.has_index ? "bg-emerald-700/55 text-emerald-100" : "bg-white/10 text-white/55"}>
        {model.has_index ? "index" : "no index"}
      </Badge>
      {model.sampling_rate ? <Badge>{model.sampling_rate} Hz</Badge> : null}
    </span>
  );
}

export function VoiceOption({
  option,
  models,
}: {
  option: { value: string; label: string; hint?: string };
  models: VoiceModel[];
}) {
  const model = models.find((item) => item.id === option.value);
  return (
    <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
      <span className="min-w-0">
        <span className="block truncate">{option.label}</span>
        <span className="block truncate text-[11px] text-ui-subtle">{model?.slot ?? option.hint}</span>
      </span>
      {model ? <ModelBadges model={model} /> : null}
    </span>
  );
}
