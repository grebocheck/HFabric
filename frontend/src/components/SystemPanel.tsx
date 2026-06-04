import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { GpuStatus, MemSnapshot, RuntimeSettings } from "../types";

export function SystemPanel({ gpu, mem }: { gpu: GpuStatus; mem: MemSnapshot | null }) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);

  useEffect(() => {
    api.runtimeSettings().then(setSettings).catch(() => {});
  }, []);

  const ram = mem?.ram;
  const vram = mem?.vram;

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col gap-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-white/75">System monitor</h2>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
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
      </div>

      {settings && (
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
      )}

      <p className="text-xs text-white/30">Live telemetry streams over the WebSocket; updates roughly every few seconds.</p>
    </div>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-white/10 p-4">
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
