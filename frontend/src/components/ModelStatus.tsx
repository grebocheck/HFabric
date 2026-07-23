import { Logo } from "./Logo";
import type { AppTheme, GpuStatus, MemSnapshot } from "../types";
import type { EventConnectionState } from "../api/useEvents";
import type { View } from "../workspaces";
export type { View } from "../workspaces";

const familyColor: Record<string, string> = {
  flux: "bg-accent",
  flux2: "bg-sky-600",
  "qwen-image": "bg-violet-600",
  "z-image": "bg-cyan-600",
  sdxl: "bg-pink-600",
  "ltx-video": "bg-cyan-600",
  "wan-video": "bg-violet-600",
  "hunyuan-video": "bg-indigo-600",
  cogvideo: "bg-sky-600",
  gguf: "bg-emerald-600",
};

const themeLabel: Record<AppTheme, string> = {
  dark: "Black",
  dim: "Dim",
  light: "Light",
};

export function ModelStatus({
  gpu,
  connected,
  connectionState,
  lastSyncAt,
  busy,
  mem,
  view,
  theme,
  tabs,
  onView,
  onPrefetch,
  onFree,
  onTheme,
  onPalette,
}: {
  gpu: GpuStatus;
  connected: boolean;
  connectionState: EventConnectionState;
  lastSyncAt: number | null;
  busy: boolean;
  mem: MemSnapshot | null;
  view: View;
  theme: AppTheme;
  tabs: { id: View; label: string }[];
  onView: (v: View) => void;
  onPrefetch?: (view: View) => void;
  onFree: () => void;
  onTheme: () => void;
  onPalette: () => void;
}) {
  const socketLabel =
    connectionState === "ready"
      ? `Synced${lastSyncAt ? ` ${new Date(lastSyncAt).toLocaleTimeString()}` : ""}`
      : connectionState === "syncing"
        ? "Connected, synchronizing state"
        : connectionState === "degraded"
          ? "Connected, state refresh failed"
          : connectionState === "offline"
            ? "Offline"
            : connectionState === "reconnecting"
              ? "Reconnecting"
              : "Connecting";
  const connectionColor =
    connectionState === "ready" ? "bg-emerald-400" : connected ? "bg-amber-400" : "bg-red-500";

  const moveTab = (index: number, key: string) => {
    let next = index;
    if (key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (key === "Home") next = 0;
    else if (key === "End") next = tabs.length - 1;
    else return false;
    const target = tabs[next];
    if (!target) return false;
    onView(target.id);
    requestAnimationFrame(() => document.getElementById(`workspace-tab-${target.id}`)?.focus());
    return true;
  };

  return (
    <header className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-2 border-b border-line bg-base/95 px-3 py-2 md:grid-cols-[auto_minmax(0,1fr)_auto] md:gap-4 md:px-5 md:py-3">
      <div className="contents">
        <div className="flex shrink-0 items-center gap-2">
          <Logo className="h-7 w-7" />
          <span className="text-lg font-semibold tracking-tight">HFabric</span>
          {busy ? (
            <svg
              className="h-3.5 w-3.5 animate-spin text-accent"
              viewBox="0 0 24 24"
              fill="none"
              aria-label="working"
            >
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
              <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
          ) : (
            <output className={`inline-block h-2 w-2 rounded-full ${connectionColor}`} title={socketLabel}>
              <span className="sr-only">{socketLabel}</span>
            </output>
          )}
        </div>

        <div
          role="tablist"
          aria-label="Workspaces"
          aria-orientation="horizontal"
          className="col-span-2 row-start-2 flex w-full min-w-0 max-w-full items-center gap-1 overflow-x-auto rounded-lg border border-line bg-control p-1 md:col-span-1 md:col-start-2 md:row-start-1"
        >
          {tabs.map((t, index) => (
            <button
              id={`workspace-tab-${t.id}`}
              key={t.id}
              role="tab"
              aria-selected={view === t.id}
              aria-controls={`workspace-panel-${t.id}`}
              tabIndex={view === t.id ? 0 : -1}
              onClick={() => onView(t.id)}
              onMouseEnter={() => onPrefetch?.(t.id)}
              onFocus={() => onPrefetch?.(t.id)}
              onKeyDown={(event) => {
                if (moveTab(index, event.key)) event.preventDefault();
              }}
              className={`rounded-md px-3 py-1 text-sm font-medium transition ${
                view === t.id
                  ? "bg-accent text-ui-inverse shadow-sm"
                  : "text-ui-muted hover:bg-control-hover hover:text-ui"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="col-start-2 row-start-1 flex shrink-0 items-center gap-2 text-sm md:col-start-3 md:gap-3">
        {mem?.vram ? (
          <div
            className="hidden items-center gap-1.5 sm:flex"
            title={`VRAM ${mem.vram.used_gb.toFixed(1)} / ${mem.vram.total_gb.toFixed(1)} GB`}
          >
            <span className="text-xs text-ui-subtle">VRAM</span>
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-control-active">
              <div
                className="h-full bg-accent transition-all"
                style={{
                  width: `${Math.min(100, (mem.vram.used_gb / Math.max(1, mem.vram.total_gb)) * 100)}%`,
                }}
              />
            </div>
          </div>
        ) : null}
        <span className="hidden text-ui-muted lg:inline">Active model:</span>
        {gpu.model ? (
          <span className="flex min-w-0 items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-medium text-ui-inverse ${
                familyColor[gpu.family ?? ""] ?? "bg-slate-600"
              }`}
            >
              {gpu.family}
            </span>
            <span className="max-w-52 truncate font-mono" title={gpu.model}>
              {gpu.model}
            </span>
            <span className="rounded border border-success-border bg-success-bg px-1.5 py-0.5 text-[10px] font-medium text-success-fg">
              {gpu.pin ? gpu.pin.label : "on GPU"}
            </span>
          </span>
        ) : gpu.lanes?.length ? (
          // A non-arbiter GPU consumer (voice / TTS / transcribe) is running; no
          // resident heavy model, but the GPU is busy — say so instead of "idle".
          <span className="flex min-w-0 items-center gap-2" title="GPU busy (non-model workload)">
            <span className="max-w-52 truncate rounded border border-info-border bg-info-bg px-1.5 py-0.5 text-xs font-medium text-info-fg">
              {gpu.lanes.map((l) => l.label).join(", ")}
            </span>
            <span className="rounded border border-info-border bg-info-bg px-1.5 py-0.5 text-[10px] font-medium text-info-fg">
              on GPU
            </span>
          </span>
        ) : (
          <span className="hidden text-ui-subtle sm:inline">idle</span>
        )}
        {gpu.warm?.length ? (
          <span className="flex items-center gap-1 text-xs text-ui-subtle">
            <span>CPU warm:</span>
            <span
              className="max-w-44 truncate font-mono text-ui-muted"
              title={gpu.warm.map((m) => m.model).join(", ")}
            >
              {gpu.warm.map((m) => m.model).join(", ")}
            </span>
          </span>
        ) : null}
        <button
          onClick={onFree}
          disabled={!gpu.model && !gpu.warm?.length}
          className="ui-button hidden rounded px-2.5 py-1 text-xs sm:inline-flex"
        >
          Free GPU
        </button>
        <button onClick={onTheme} title="Cycle theme" className="ui-button rounded px-2.5 py-1 text-xs">
          {themeLabel[theme]}
        </button>
        <button
          onClick={onPalette}
          title="Command palette (Ctrl+K)"
          className="ui-button rounded px-2 py-1 font-mono text-[11px]"
        >
          Ctrl K
        </button>
      </div>
    </header>
  );
}
