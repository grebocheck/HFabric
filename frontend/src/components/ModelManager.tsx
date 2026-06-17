import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { ModelDownloads } from "./ModelDownloads";
import { Panel, SectionTitle, SkeletonRows, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import { toast } from "./Toast";
import type { InstalledModel, InstalledModelsState } from "../types";

// Unified Model Manager (P25): one place to get models for every type from any
// source (curated catalog + HuggingFace/URL via ModelDownloads) and to see/delete
// what's installed to reclaim disk.
export function ModelManager({ onModelsChanged }: { onModelsChanged?: () => void }) {
  const [data, setData] = useState<InstalledModelsState | null>(null);
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

  const onModelsChanged_ = useCallback(() => {
    void refresh();
    onModelsChanged?.();
  }, [refresh, onModelsChanged]);

  const grouped = useMemo(() => {
    const by = new Map<string, InstalledModel[]>();
    for (const item of data?.items ?? []) {
      const list = by.get(item.kind) ?? [];
      list.push(item);
      by.set(item.kind, list);
    }
    return [...by.entries()];
  }, [data]);

  const del = async (item: InstalledModel) => {
    const key = `${item.kind}/${item.path}`;
    if (item.in_use) return;
    if (!window.confirm(`Delete "${item.name}" (${fmtBytes(item.size_bytes)})? This removes the files from disk.`)) {
      return;
    }
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

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto">
      <WorkspaceHeader
        title="Models"
        subtitle="Download models for every workspace from the curated catalog or any source, and manage what's installed to reclaim disk."
      >
        <StatusPill label={`${data?.items.length ?? 0} installed`} tone="info" />
        <StatusPill label={`${fmtBytes(data?.total_used_bytes ?? 0)} on disk`} tone="neutral" />
        <StatusPill
          label={freeMb != null ? `${fmtMb(freeMb)} free` : "disk unknown"}
          tone={freeMb != null && freeMb < 5120 ? "warn" : "good"}
        />
      </WorkspaceHeader>

      <ModelDownloads onModelsChanged={onModelsChanged_} />

      <Panel>
        <SectionTitle
          title="Installed models"
          subtitle="Everything on disk across all model types — delete to free space"
          actions={
            <button onClick={() => void refresh()} className="rounded-md border border-white/15 px-2.5 py-1 text-xs text-white/65 hover:bg-white/10 hover:text-white">
              Refresh
            </button>
          }
        />
        <div className="space-y-4 p-3">
          {!data ? (
            <SkeletonRows rows={4} />
          ) : grouped.length === 0 ? (
            <div className="rounded-md border border-dashed border-white/10 px-3 py-6 text-center text-sm text-white/35">
              No models installed yet. Use the catalog or "Add from a source" above to get started.
            </div>
          ) : (
            grouped.map(([kind, items]) => (
              <div key={kind}>
                <div className="mb-1.5 flex items-baseline justify-between">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-white/45">
                    {data.kinds[kind] ?? kind}
                  </h4>
                  <span className="text-[11px] text-white/30">
                    {items.length} · {fmtBytes(items.reduce((s, i) => s + i.size_bytes, 0))}
                  </span>
                </div>
                <ul className="space-y-1.5">
                  {items.map((item) => {
                    const key = `${item.kind}/${item.path}`;
                    return (
                      <li
                        key={key}
                        className="flex items-center gap-2.5 rounded-md border border-white/10 bg-black/20 px-3 py-2"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-[13px] text-white/85" title={item.name}>{item.name}</span>
                            {item.is_dir ? (
                              <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/45">folder</span>
                            ) : null}
                            {item.in_use ? (
                              <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">on GPU</span>
                            ) : null}
                          </div>
                          <div className="mt-0.5 font-mono text-[11px] text-white/30">{fmtBytes(item.size_bytes)}</div>
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
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}

function fmtMb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function fmtBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}
