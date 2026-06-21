import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ModelDownloads } from "./ModelDownloads";
import { Panel, SkeletonRows } from "./WorkspaceChrome";
import { toast } from "./Toast";
import { fmtBytes } from "./format";
import type { InstalledModel, InstalledModelsState } from "../types";

type Pane = "download" | "all" | string;

// Stable taxonomy order for the sidebar (kinds not present are skipped).
const KIND_ORDER = ["image", "llm", "lora", "vision", "embed", "tts", "transcribe", "voice"];

// Unified Model Manager (P25): a sidebar of kinds (count + total size) on the left,
// the download surface or a filtered installed list on the right.
export function ModelManager({ onModelsChanged }: { onModelsChanged?: () => void }) {
  const [data, setData] = useState<InstalledModelsState | null>(null);
  const [pane, setPane] = useState<Pane>("all");
  const [deleting, setDeleting] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      setData(await api.installedModels());
    } catch {
      /* keep last known list if the backend blips */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onDownloadsChanged = useCallback(() => {
    void refresh();
    onModelsChanged?.();
  }, [refresh, onModelsChanged]);

  const items = useMemo(() => data?.items ?? [], [data]);

  // Per-kind aggregates for the sidebar, in a stable taxonomy order.
  const kindStats = useMemo(() => {
    const map = new Map<string, { count: number; bytes: number }>();
    for (const item of items) {
      const s = map.get(item.kind) ?? { count: 0, bytes: 0 };
      s.count += 1;
      s.bytes += item.size_bytes;
      map.set(item.kind, s);
    }
    return KIND_ORDER
      .filter((k) => map.has(k))
      .map((k) => ({ kind: k, label: data?.kinds[k] ?? k, ...map.get(k)! }));
  }, [items, data]);

  const visibleItems = useMemo(
    () => (pane === "all" ? items : items.filter((i) => i.kind === pane)),
    [items, pane],
  );

  const del = async (item: InstalledModel) => {
    if (item.in_use) return;
    if (!window.confirm(`Delete "${item.name}" (${fmtBytes(item.size_bytes)})? This removes the files from disk.`)) return;
    const key = `${item.kind}/${item.path}`;
    setDeleting(key);
    try {
      const res = await api.deleteInstalledModel(item.kind, item.path);
      toast.success(`Deleted ${item.name} — freed ${fmtBytes(res.freed_bytes)}`);
      await refresh();
      onModelsChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete model");
    } finally {
      setDeleting("");
    }
  };

  const freeMb = data?.disk.free_mb ?? null;
  const navItem = (active: boolean) =>
    `flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition ${
      active ? "bg-control-active text-ui-strong" : "text-ui-muted hover:bg-control-hover hover:text-ui"
    }`;

  return (
    <div className="flex h-full w-full gap-4 overflow-hidden">
      <aside className="flex w-60 shrink-0 flex-col gap-2 overflow-y-auto rounded-lg border border-border bg-panel p-2.5 shadow-panel">
        <button onClick={() => setPane("download")} className={`${navItem(pane === "download")} font-medium`}>
          <span className="flex items-center gap-2"><span className="text-accent">＋</span> Get models</span>
        </button>

        <div className="mt-1 px-2.5 text-[10px] font-semibold uppercase tracking-wide text-ui-subtle">Installed</div>
        <button onClick={() => setPane("all")} className={navItem(pane === "all")}>
          <span>All</span>
          <span className="shrink-0 text-[11px] text-ui-subtle">{items.length} · {fmtBytes(data?.total_used_bytes ?? 0)}</span>
        </button>
        {kindStats.map((k) => (
          <button key={k.kind} onClick={() => setPane(k.kind)} className={navItem(pane === k.kind)}>
            <span className="min-w-0 truncate">{k.label}</span>
            <span className="shrink-0 text-[11px] text-ui-subtle">{k.count} · {fmtBytes(k.bytes)}</span>
          </button>
        ))}
        {data && kindStats.length === 0 ? (
          <div className="px-2.5 py-1 text-[11px] text-ui-subtle">Nothing installed yet.</div>
        ) : null}

        <div className="mt-auto border-t border-border px-2.5 pt-2 text-[11px] text-ui-subtle">
          <div className="flex items-center justify-between">
            <span>On disk</span>
            <span className="text-ui-muted">{fmtBytes(data?.total_used_bytes ?? 0)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Free</span>
            <span className={freeMb != null && freeMb < 5120 ? "text-warn-fg" : "text-ui-muted"}>
              {freeMb != null ? (freeMb >= 1024 ? `${(freeMb / 1024).toFixed(1)} GB` : `${freeMb} MB`) : "—"}
            </span>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto">
        {pane === "download" ? (
          <ModelDownloads onModelsChanged={onDownloadsChanged} />
        ) : (
          <Panel className="flex h-full flex-col">
            <div className="flex min-h-11 items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-ui-strong">
                  {pane === "all" ? "All installed models" : data?.kinds[pane] ?? pane}
                </div>
                <div className="mt-0.5 text-xs text-ui-subtle">
                  {visibleItems.length} item{visibleItems.length === 1 ? "" : "s"} ·{" "}
                  {fmtBytes(visibleItems.reduce((s, i) => s + i.size_bytes, 0))}
                </div>
              </div>
              <button onClick={() => void refresh()} className="ui-button ui-button-compact rounded-md">
                Refresh
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {!data ? (
                <SkeletonRows rows={5} />
              ) : visibleItems.length === 0 ? (
                <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 text-center">
                  <p className="text-sm text-ui-subtle">No models here yet.</p>
                  <button
                    onClick={() => setPane("download")}
                    className="rounded-md border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-medium text-accent-fg hover:bg-accent/25"
                  >
                    Get models
                  </button>
                </div>
              ) : (
                <ul className="space-y-1.5">
                  {visibleItems.map((item) => {
                    const key = `${item.kind}/${item.path}`;
                    return (
                      <li key={key} className="ui-card flex items-center gap-2.5 rounded-md px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-[13px] text-ui-strong" title={item.name}>{item.name}</span>
                            {pane === "all" ? (
                              <span className="ui-chip rounded px-1.5 py-0.5 text-[10px]">{data.kinds[item.kind] ?? item.kind}</span>
                            ) : null}
                            {item.is_dir ? <span className="ui-chip rounded px-1.5 py-0.5 text-[10px]">folder</span> : null}
                            {item.in_use ? <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">on GPU</span> : null}
                          </div>
                          <div className="mt-0.5 font-mono text-[11px] text-ui-subtle">{fmtBytes(item.size_bytes)}</div>
                        </div>
                        <button
                          onClick={() => void del(item)}
                          disabled={item.in_use || deleting === key}
                          title={item.in_use ? "Loaded on the GPU — Free GPU first" : "Delete from disk"}
                          className="shrink-0 rounded-md border border-red-400/25 px-2.5 py-1 text-xs text-red-300 hover:bg-red-400/10 disabled:opacity-30"
                        >
                          {deleting === key ? "Deleting…" : "Delete"}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
