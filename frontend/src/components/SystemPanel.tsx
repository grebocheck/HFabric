import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { SetupDoctor } from "./SetupDoctor";
import { ModelDownloads } from "./ModelDownloads";
import { StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import { toast } from "./Toast";
import type {
  ArbiterNote,
  GpuStatus,
  ImageStats,
  MemPoint,
  MemSnapshot,
  ModelProfile,
  QueuePlan,
  RuntimeSettings,
  VoiceEngineStatus,
  VoiceProviderHealth,
} from "../types";

export function SystemPanel({
  gpu,
  mem,
  history = [],
  note,
  queueKey = "",
  imageSignal = 0,
  version,
  onModelsChanged,
}: {
  gpu: GpuStatus;
  mem: MemSnapshot | null;
  history?: MemPoint[];
  note?: ArbiterNote | null;
  queueKey?: string;
  imageSignal?: number;
  version?: string;
  onModelsChanged?: () => void;
}) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [plan, setPlan] = useState<QueuePlan | null>(null);
  const [imageStats, setImageStats] = useState<ImageStats | null>(null);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [voiceStatus, setVoiceStatus] = useState<VoiceEngineStatus | null>(null);

  useEffect(() => {
    api.runtimeSettings().then(setSettings).catch(() => {});
  }, []);

  const refreshProfiles = useCallback(() => {
    api.listModelProfiles().then(setProfiles).catch(() => {});
  }, []);

  useEffect(() => {
    refreshProfiles();
  }, [refreshProfiles]);

  // Refetch the swap-plan whenever the queue or the resident model changes.
  useEffect(() => {
    api.queuePlan().then(setPlan).catch(() => {});
  }, [queueKey, gpu.model_id]);

  useEffect(() => {
    api.imageStats().then(setImageStats).catch(() => {});
  }, [imageSignal]);

  useEffect(() => {
    api.voiceEngineStatus().then(setVoiceStatus).catch(() => {});
  }, []);

  const ram = mem?.ram;
  const vram = mem?.vram;
  const capability = settings?.capability;

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto">
      <WorkspaceHeader
        title="System monitor"
        subtitle="Live RAM, VRAM, runtime, and model residency telemetry for the local workspace."
      >
        {version ? <StatusPill label={`HFabric v${version}`} tone="neutral" /> : null}
        <StatusPill label={gpu.model ? "model resident" : "idle"} tone={gpu.model ? "info" : "neutral"} />
        <StatusPill label={vram ? `${vram.used_gb.toFixed(1)} GB VRAM used` : "no VRAM telemetry"} tone={vram ? "info" : "warn"} />
        <StatusPill label={ram ? `${ram.percent.toFixed(0)}% RAM` : "RAM waiting"} tone={ram && ram.percent > 85 ? "warn" : ram ? "good" : "neutral"} />
      </WorkspaceHeader>

      <SetupDoctor />

      <ModelDownloads onModelsChanged={onModelsChanged} />

      <ArbiterStatus note={note} />

      <SwapPlan plan={plan} />

      <LearnedProfiles profiles={profiles} onRefresh={refreshProfiles} />

      <MemoryTimeline history={history} />

      <Diagnostics />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <Card title="VRAM" subtitle={vram ? `${vram.total_gb.toFixed(1)} GB total` : "no GPU telemetry"}>
          {vram ? (
            <>
              <Gauge used={vram.used_gb} total={vram.total_gb} color="bg-accent" />
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

        <Card title="Generations" subtitle={imageStats ? `${imageStats.total} total` : "loading..."}>
          {imageStats ? (
            <>
              <Rows rows={{
                "Today": String(imageStats.today),
                "All time": String(imageStats.total),
                "Top model": imageStats.by_model[0]?.model ?? "-",
              }} />
              {imageStats.by_model.length ? <ModelCounts rows={imageStats.by_model.slice(0, 5)} /> : null}
            </>
          ) : (
            <div className="text-sm text-white/30">waiting for generation counters...</div>
          )}
        </Card>

        {settings ? (
          <Card title="Runtime" subtitle={capability?.effective_stub_mode ? "STUB mode" : `${capability?.backend ?? "GPU"} mode`}>
            <Rows rows={{
              "Profile": capability?.active_profile ?? (settings.stub_mode ? "cpu-safe" : "unknown"),
              "Tier": capability?.hardware_tier ?? "-",
              "Image models": String(settings.counts.image_models ?? 0),
              "LLM models": String(settings.counts.llm_models ?? 0),
              "LoRAs": String(settings.counts.loras ?? 0),
              "Attention": String(settings.acceleration.attention_backend ?? "-"),
              "torch.compile": String(settings.acceleration.torch_compile ?? false),
              "FLUX step cache": String(settings.acceleration.flux_step_cache ?? "-"),
              "Voice ContentVec": providerLabel(voiceStatus?.metrics.provider_health.content_vec),
              "Voice F0": providerLabel(voiceStatus?.metrics.provider_health.f0),
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

function ModelCounts({ rows }: { rows: ImageStats["by_model"] }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <div className="mt-3 space-y-2">
      {rows.map((row) => (
        <div key={row.model} className="min-w-0">
          <div className="mb-1 flex items-center justify-between gap-2 text-[11px]">
            <span className="min-w-0 truncate text-white/45" title={row.model}>{row.model}</span>
            <span className="shrink-0 font-mono text-white/55">{row.count}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-white/10">
            <div className="h-full rounded bg-accent/75" style={{ width: `${Math.max(6, (row.count / max) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const gb = (v: number) => `${v.toFixed(1)} GB`;

function providerLabel(provider?: VoiceProviderHealth | null): string {
  return String(provider?.actual ?? provider?.requested ?? "-");
}

const NOTE_TONES: Record<string, string> = {
  ram_budget: "border-red-400/30 bg-red-500/10 text-red-200",
  voice_lane: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  swap: "border-accent/30 bg-accent/10 text-accent-fg",
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

function Diagnostics() {
  const [busy, setBusy] = useState(false);

  const exportBundle = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const blob = await api.exportDiagnostics();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `hfabric-diagnostics-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Diagnostics exported");
    } catch {
      toast.error("Could not export diagnostics");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white/75">Diagnostics</h3>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-white/35">
            Bundle the logs, the hardware/capability report, and version stamps into a zip to attach to a
            bug report. Secrets (the API token) are scrubbed; the file is produced locally and never uploaded.
          </p>
        </div>
        <button
          onClick={exportBundle}
          disabled={busy}
          className="shrink-0 rounded-md border border-white/15 px-2.5 py-1 text-xs text-white/80 hover:bg-white/10 disabled:opacity-30"
        >
          {busy ? "Exporting…" : "Export diagnostics"}
        </button>
      </div>
    </section>
  );
}

function LearnedProfiles({ profiles, onRefresh }: { profiles: ModelProfile[]; onRefresh: () => void }) {
  const [busy, setBusy] = useState("");

  const resetOne = async (id: string) => {
    setBusy(id);
    try {
      await api.resetModelProfile(id);
      onRefresh();
    } finally {
      setBusy("");
    }
  };

  const resetAll = async () => {
    setBusy("__all__");
    try {
      await api.resetAllModelProfiles();
      onRefresh();
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white/75">Learned memory profiles</h3>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-white/35">
            Image models record measured RAM/VRAM after real loads. LLM VRAM is not measured here because
            llama-server reports no load_report; subprocess VRAM capture is out of scope.
          </p>
        </div>
        <button
          onClick={resetAll}
          disabled={!profiles.length || Boolean(busy)}
          className="shrink-0 rounded-md border border-red-400/25 px-2.5 py-1 text-xs text-red-300 hover:bg-red-400/10 disabled:opacity-30"
        >
          Reset all
        </button>
      </div>
      {profiles.length === 0 ? (
        <div className="rounded-md border border-dashed border-white/10 px-3 py-4 text-sm text-white/30">
          No learned profiles yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="text-white/35">
              <tr className="border-b border-white/10">
                <th className="py-2 pr-3 font-medium">Model</th>
                <th className="py-2 pr-3 font-medium">Family</th>
                <th className="py-2 pr-3 font-medium">Quant</th>
                <th className="py-2 pr-3 font-medium">RAM</th>
                <th className="py-2 pr-3 font-medium">VRAM</th>
                <th className="py-2 pr-3 font-medium">Samples</th>
                <th className="py-2 pr-3 font-medium">Updated</th>
                <th className="py-2 text-right font-medium">Reset</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-white/65">
              {profiles.map((profile) => (
                <tr key={profile.model_id}>
                  <td className="max-w-[240px] truncate py-2 pr-3" title={profile.model}>{profile.model}</td>
                  <td className="py-2 pr-3">{profile.family}</td>
                  <td className="py-2 pr-3">{profile.quant ?? "-"}</td>
                  <td className="py-2 pr-3">{profile.ram_gb == null ? "-" : gb(profile.ram_gb)}</td>
                  <td className="py-2 pr-3">{profile.vram_gb == null ? "-" : gb(profile.vram_gb)}</td>
                  <td className="py-2 pr-3">{profile.samples}</td>
                  <td className="py-2 pr-3">{new Date(profile.updated_at).toLocaleString()}</td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => resetOne(profile.model_id)}
                      disabled={Boolean(busy)}
                      className="rounded border border-white/15 px-2 py-0.5 text-[11px] text-white/55 hover:bg-white/10 hover:text-white/80 disabled:opacity-30"
                    >
                      {busy === profile.model_id ? "Resetting" : "Reset"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SwapPlan({ plan }: { plan: QueuePlan | null }) {
  const typeColor = (t: string) => (t === "image" ? "bg-accent/20 text-accent-fg border-accent/30" : "bg-emerald-500/20 text-emerald-200 border-emerald-400/30");
  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-white/75">Queue plan</h3>
        <span className="text-xs text-white/35">
          {plan && plan.queued > 0
            ? `${plan.queued} queued · ${plan.swaps} swap${plan.swaps === 1 ? "" : "s"}`
            : "queue empty"}
        </span>
      </div>
      {!plan || plan.queued === 0 ? (
        <div className="text-sm text-white/30">Nothing queued — no model swaps planned.</div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-white/45">
            now: {plan.current_model ?? "idle"}
          </span>
          {plan.steps.map((step, i) => (
            <span key={i} className="flex items-center gap-1.5">
              <span className="text-white/25">→</span>
              <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 ${typeColor(step.type)}`} title={step.model_id}>
                <span className="max-w-[150px] truncate">{step.model}</span>
                {step.count > 1 && <span className="opacity-70">×{step.count}</span>}
              </span>
            </span>
          ))}
        </div>
      )}
      {plan && plan.queued > 0 && (
        <p className="mt-2 text-[11px] text-white/35">
          The scheduler drains same-model jobs together to minimize swaps; this is the predicted order.
        </p>
      )}
    </section>
  );
}

function MemoryTimeline({ history }: { history: MemPoint[] }) {
  const W = 100;
  const H = 32;
  const [showRss, setShowRss] = useState(false);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
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
  const rssPath = path((p) => (
    showRss && p.ram && p.ram.total_gb > 0 ? p.ram.process_rss_gb / p.ram.total_gb : null
  ));

  // vertical markers where the resident model changed (a swap)
  const swaps = points
    .map((p, i) => ({ i, swap: i > 0 && p.resident !== points[i - 1].resident }))
    .filter((m) => m.swap)
    .map((m) => (points.length > 1 ? (m.i / (points.length - 1)) * W : 0));

  const last = points[points.length - 1];
  const hover = hoverIndex == null ? null : points[hoverIndex] ?? null;
  const hoverLeft = hoverIndex != null && points.length > 1 ? `${(hoverIndex / (points.length - 1)) * 100}%` : "0%";

  return (
    <section className="rounded-lg border border-white/10 bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-white/75">Memory pressure</h3>
        <div className="flex items-center gap-3">
          <label className="inline-flex items-center gap-1.5 text-xs text-white/45">
            <input
              type="checkbox"
              checked={showRss}
              onChange={(event) => setShowRss(event.target.checked)}
              className="h-3 w-3 accent-accent"
            />
            App RSS
          </label>
          <span className="text-xs text-white/35">
            {points.length ? `${points.length} samples / ${swaps.length} swap${swaps.length === 1 ? "" : "s"}` : "collecting telemetry..."}
          </span>
        </div>
      </div>
      {points.length < 2 ? (
        <div className="flex h-20 items-center justify-center text-sm text-white/30">collecting telemetry...</div>
      ) : (
        <>
          <div
            className="relative h-24"
            onMouseMove={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              const frac = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
              setHoverIndex(Math.min(points.length - 1, Math.max(0, Math.round(frac * (points.length - 1)))));
            }}
            onMouseLeave={() => setHoverIndex(null)}
          >
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
              {swaps.map((x, i) => (
                <line key={i} x1={x} y1={0} x2={x} y2={H} stroke="rgb(248 250 252 / 0.18)" strokeWidth={0.4} strokeDasharray="1.5 1.5" />
              ))}
              {ramPath && <polyline points={ramPath} fill="none" stroke="rgb(16 185 129 / 0.85)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
              {vramPath && <polyline points={vramPath} fill="none" stroke="rgb(139 92 246 / 0.95)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
              {rssPath && <polyline points={rssPath} fill="none" stroke="rgb(14 165 233 / 0.9)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
            </svg>
            {hover ? (
              <>
                <div className="pointer-events-none absolute bottom-0 top-0 w-px bg-white/25" style={{ left: hoverLeft }} />
                <div
                  className="pointer-events-none absolute top-1 z-10 min-w-44 rounded-md border border-white/10 bg-black/80 px-2 py-1.5 text-[11px] text-white/70 shadow-lg shadow-black/40"
                  style={{
                    left: hoverLeft,
                    transform: hoverIndex != null && hoverIndex > points.length * 0.65 ? "translateX(-100%)" : "translateX(0)",
                  }}
                >
                  <div className="font-mono text-white/45">{new Date(hover.ts * 1000).toLocaleTimeString()}</div>
                  <div>RAM: {hover.ram ? `${hover.ram.percent.toFixed(0)}% / ${gb(hover.ram.used_gb)} used` : "-"}</div>
                  <div>VRAM: {hover.vram ? `${gb(hover.vram.used_gb)} / ${gb(hover.vram.total_gb)}` : "-"}</div>
                  <div>RSS: {hover.ram ? gb(hover.ram.process_rss_gb) : "-"}</div>
                </div>
              </>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-white/45">
            <Legend color="bg-accent" label={`VRAM used${last?.vram ? ` / ${last.vram.used_gb.toFixed(1)}/${last.vram.total_gb.toFixed(0)} GB` : ""}`} />
            <Legend color="bg-emerald-500" label={`RAM %${last?.ram ? ` / ${last.ram.percent.toFixed(0)}%` : ""}`} />
            {showRss ? <Legend color="bg-info" label={`App RSS${last?.ram ? ` / ${gb(last.ram.process_rss_gb)}` : ""}`} /> : null}
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
