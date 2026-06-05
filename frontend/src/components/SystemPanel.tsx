import { useEffect, useState } from "react";
import { api } from "../api/client";
import { StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import type { ArbiterNote, GpuStatus, MemPoint, MemSnapshot, RuntimeSettings } from "../types";

export function SystemPanel({
  gpu,
  mem,
  history = [],
  note,
}: {
  gpu: GpuStatus;
  mem: MemSnapshot | null;
  history?: MemPoint[];
  note?: ArbiterNote | null;
}) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);

  useEffect(() => {
    api.runtimeSettings().then(setSettings).catch(() => {});
  }, []);

  const ram = mem?.ram;
  const vram = mem?.vram;

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto">
      <WorkspaceHeader
        title="System monitor"
        subtitle="Live RAM, VRAM, runtime, and model residency telemetry for the local workspace."
      >
        <StatusPill label={gpu.model ? "model resident" : "idle"} tone={gpu.model ? "info" : "neutral"} />
        <StatusPill label={vram ? `${vram.used_gb.toFixed(1)} GB VRAM used` : "no VRAM telemetry"} tone={vram ? "info" : "warn"} />
        <StatusPill label={ram ? `${ram.percent.toFixed(0)}% RAM` : "RAM waiting"} tone={ram && ram.percent > 85 ? "warn" : ram ? "good" : "neutral"} />
      </WorkspaceHeader>

      <ArbiterStatus note={note} />

      <MemoryTimeline history={history} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="VRAM" subtitle={vram ? `${vram.total_gb.toFixed(1)} GB total` : "no GPU telemetry"}>
          {vram ? (
            <>
              <Gauge used={vram.used_gb} total={vram.total_gb} color="bg-violet-500" />
              <Rows rows={{
                "Used": gb(vram.used_gb),
                "Free": gb(vram.free_gb),
                "Resident model": gpu.model ? `${gpu.family} · ${gpu.model}` : "— idle —",
                "CPU warm": gpu.warm?.length ? gpu.warm.map((w) => w.model).join(", ") : "—",
              }} />
            </>
          ) : (
            <div className="text-sm text-white/30">VRAM stats unavailable</div>
          )}
        </Card>

        <Card title="RAM" subtitle={ram ? `${ram.total_gb.toFixed(1)} GB total` : "loading…"}>
          {ram ? (
            <>
              <Gauge used={ram.used_gb} total={ram.total_gb} color={ram.percent > 85 ? "bg-red-500" : "bg-emerald-500"} />
              <Rows rows={{
                "Used": `${gb(ram.used_gb)} (${ram.percent.toFixed(0)}%)`,
                "Available": gb(ram.available_gb),
                "App (RSS)": gb(ram.process_rss_gb),
              }} />
            </>
          ) : (
            <div className="text-sm text-white/30">waiting for telemetry…</div>
          )}
        </Card>

        {settings ? (
          <Card title="Runtime" subtitle={settings.stub_mode ? "STUB mode" : "GPU mode"}>
            <Rows rows={{
              "Image models": String(settings.counts.image_models ?? 0),
              "LLM models": String(settings.counts.llm_models ?? 0),
              "LoRAs": String(settings.counts.loras ?? 0),
              "Attention": String(settings.acceleration.attention_backend ?? "-"),
              "torch.compile": String(settings.acceleration.torch_compile ?? false),
              "FLUX step cache": String(settings.acceleration.flux_step_cache ?? "-"),
              "Min free RAM (guard)": `${settings.memory.min_free_ram_gb ?? "-"} GB`,
            }} />
          </Card>
        ) : (
          <Card title="Runtime" subtitle="loading">
            <div className="text-sm text-white/30">waiting for runtime settings...</div>
          </Card>
        )}
      </div>

      <p className="text-xs text-white/30">Live telemetry streams over the WebSocket; updates roughly every few seconds.</p>
    </div>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-white/75">{title}</h3>
        {subtitle && <span className="text-xs text-white/35">{subtitle}</span>}
      </div>
      {children}
    </section>
  );
}

function Gauge({ used, total, color }: { used: number; total: number; color: string }) {
  const pct = total > 0 ? Math.min(100, Math.max(0, (used / total) * 100)) : 0;
  return (
    <div className="mb-3 h-2.5 overflow-hidden rounded bg-white/10">
      <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function Rows({ rows }: { rows: Record<string, string> }) {
  return (
    <dl className="space-y-1.5 text-sm">
      {Object.entries(rows).map(([k, v]) => (
        <div key={k} className="flex items-center justify-between gap-2">
          <dt className="text-white/40">{k}</dt>
          <dd className="min-w-0 truncate text-white/80" title={v}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const gb = (v: number) => `${v.toFixed(1)} GB`;

const NOTE_TONES: Record<string, string> = {
  ram_budget: "border-red-400/30 bg-red-500/10 text-red-200",
  voice_lane: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  swap: "border-violet-400/30 bg-violet-500/10 text-violet-200",
  idle: "border-white/10 bg-white/5 text-white/55",
};

function ArbiterStatus({ note }: { note?: ArbiterNote | null }) {
  const tone = note ? NOTE_TONES[note.reason] ?? NOTE_TONES.idle : NOTE_TONES.idle;
  const when = note ? new Date(note.ts * 1000).toLocaleTimeString() : null;
  return (
    <section className={`rounded-lg border px-4 py-3 ${tone}`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide opacity-80">Arbiter</h3>
        {when && <span className="text-[11px] opacity-60">{note?.reason} · {when}</span>}
      </div>
      <p className="mt-1 text-sm">{note ? note.message : "No recent arbiter activity — the GPU is idle or steadily serving one model."}</p>
    </section>
  );
}

function MemoryTimeline({ history }: { history: MemPoint[] }) {
  const W = 100;
  const H = 32;
  const points = history.filter((p) => p.ram || p.vram);

  const path = (frac: (p: MemPoint) => number | null) => {
    const coords: string[] = [];
    points.forEach((p, i) => {
      const v = frac(p);
      if (v == null) return;
      const x = points.length > 1 ? (i / (points.length - 1)) * W : 0;
      const y = H - Math.min(1, Math.max(0, v)) * H;
      coords.push(`${x.toFixed(2)},${y.toFixed(2)}`);
    });
    return coords.join(" ");
  };

  const vramPath = path((p) => (p.vram && p.vram.total_gb > 0 ? p.vram.used_gb / p.vram.total_gb : null));
  const ramPath = path((p) => (p.ram ? p.ram.percent / 100 : null));

  // vertical markers where the resident model changed (a swap)
  const swaps = points
    .map((p, i) => ({ i, swap: i > 0 && p.resident !== points[i - 1].resident }))
    .filter((m) => m.swap)
    .map((m) => (points.length > 1 ? (m.i / (points.length - 1)) * W : 0));

  const last = points[points.length - 1];

  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-white/75">Memory pressure</h3>
        <span className="text-xs text-white/35">
          {points.length ? `${points.length} samples · ${swaps.length} swap${swaps.length === 1 ? "" : "s"}` : "collecting telemetry…"}
        </span>
      </div>
      {points.length < 2 ? (
        <div className="flex h-20 items-center justify-center text-sm text-white/30">collecting telemetry…</div>
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-24 w-full">
            {swaps.map((x, i) => (
              <line key={i} x1={x} y1={0} x2={x} y2={H} stroke="rgb(248 250 252 / 0.18)" strokeWidth={0.4} strokeDasharray="1.5 1.5" />
            ))}
            {ramPath && <polyline points={ramPath} fill="none" stroke="rgb(16 185 129 / 0.85)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
            {vramPath && <polyline points={vramPath} fill="none" stroke="rgb(139 92 246 / 0.95)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
          </svg>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-white/45">
            <Legend color="bg-violet-500" label={`VRAM used${last?.vram ? ` · ${last.vram.used_gb.toFixed(1)}/${last.vram.total_gb.toFixed(0)} GB` : ""}`} />
            <Legend color="bg-emerald-500" label={`RAM %${last?.ram ? ` · ${last.ram.percent.toFixed(0)}%` : ""}`} />
            <Legend color="bg-white/30" label="model swap" dashed />
          </div>
        </>
      )}
    </section>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2 ${dashed ? "w-3 border-t border-dashed border-white/40" : `w-3 rounded ${color}`}`} />
      {label}
    </span>
  );
}
