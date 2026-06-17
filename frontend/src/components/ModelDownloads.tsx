import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Panel, SectionTitle, SkeletonRows } from "./WorkspaceChrome";
import { toast } from "./Toast";
import type { ModelDownloadState } from "../types";

const subtleButton =
  "rounded-md border border-white/15 px-2.5 py-1 text-xs text-white/65 transition hover:bg-white/10 hover:text-white disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white transition hover:bg-accent-hover disabled:opacity-35";

function fmtMb(mb: number): string {
  if (!mb) return "—";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

// Model download manager (P18.4): curated, hardware-aware starter models with
// size/license, recommended preselected, impossible ones behind Advanced, and a
// disk-budget guard. Files land in the models/ folders the registry scans.
export function ModelDownloads({ onModelsChanged }: { onModelsChanged?: () => void }) {
  const [data, setData] = useState<ModelDownloadState | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  const prevState = useRef("idle");
  const initialized = useRef(false);
  const onModelsChangedRef = useRef(onModelsChanged);
  onModelsChangedRef.current = onModelsChanged;

  const refresh = useCallback(async () => {
    try {
      setData(await api.downloadsState());
    } catch {
      /* keep last known state if the backend blips */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Preselect the recommended, not-yet-present models once, when the catalog loads.
  useEffect(() => {
    if (!data || initialized.current) return;
    initialized.current = true;
    setSelected(new Set(data.catalog.filter((i) => i.recommended && !i.present).map((i) => i.key)));
  }, [data]);

  const downloading = data?.status.state === "running";

  useEffect(() => {
    if (!downloading) return;
    const timer = setInterval(() => void refresh(), 1500);
    return () => clearInterval(timer);
  }, [downloading, refresh]);

  useEffect(() => {
    const status = data?.status;
    if (!status) return;
    if (prevState.current === "running" && status.state === "done") {
      toast.success(status.message || "Downloads complete");
      // The backend rescans on completion (P24.8); pull the fresh catalog + the
      // app-wide model list so a just-downloaded model is usable without a restart.
      void refresh();
      onModelsChangedRef.current?.();
    } else if (prevState.current === "running" && status.state === "error") {
      toast.error(status.message || "Some downloads failed", { duration: 10000 });
    }
    prevState.current = status.state;
  }, [data?.status, refresh]);

  const rescan = async () => {
    if (rescanning || downloading) return;
    setRescanning(true);
    try {
      const counts = await api.rescanModels();
      await refresh();
      onModelsChangedRef.current?.();
      toast.success(`Rescanned: ${counts.models} models, ${counts.loras} LoRAs`);
    } catch (err) {
      toast.error(errMsg(err, "Rescan failed"));
    } finally {
      setRescanning(false);
    }
  };

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const catalog = useMemo(() => data?.catalog ?? [], [data]);
  const visible = useMemo(
    () => catalog.filter((i) => showAdvanced || i.recommended || i.present),
    [catalog, showAdvanced],
  );
  const advancedHidden = catalog.filter((i) => !i.recommended && !i.present).length;
  const selectedItems = catalog.filter((i) => selected.has(i.key) && !i.present);
  const totalMb = selectedItems.reduce((sum, i) => sum + i.approx_size_mb, 0);

  const start = async () => {
    const keys = selectedItems.map((i) => i.key);
    if (!keys.length) return;
    setBusy(true);
    try {
      await api.downloadsStart(keys);
      toast.info("Downloading models… this can take a while.");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Could not start download"));
    } finally {
      setBusy(false);
    }
  };

  const status = data?.status;
  const pct =
    status && status.progress.total > 0
      ? Math.round((status.progress.done / status.progress.total) * 100)
      : null;
  const freeMb = data?.disk.free_mb ?? null;
  const disabled = busy || downloading || !data?.available || selectedItems.length === 0;

  return (
    <Panel>
      <SectionTitle
        title="Model downloads"
        subtitle="Curated starter models that fit this machine — recommended are preselected"
        actions={
          <button onClick={() => void start()} className={primaryButton} disabled={disabled}>
            {downloading
              ? "Downloading…"
              : `Download selected${selectedItems.length ? ` (${selectedItems.length} · ~${fmtMb(totalMb)})` : ""}`}
          </button>
        }
      />
      <div className="space-y-3 p-3 text-xs">
        {!data ? (
          <SkeletonRows rows={3} />
        ) : (
          <>
            {!data.available ? (
              <div className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-white/75">
                In-app downloads need <span className="font-mono">huggingface_hub</span>, which is not
                installed in this environment. Run the accelerator setup (<span className="font-mono">setup … real</span>)
                or <span className="font-mono">pip install huggingface_hub</span>.
              </div>
            ) : null}

            {downloading ? (
              <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-white/75">
                <div className="mb-1 flex items-center justify-between">
                  <span className="truncate">{status?.message ?? "Downloading…"}</span>
                  {pct != null ? <span className="font-mono text-white/55">{pct}%</span> : null}
                </div>
                {pct != null ? (
                  <div className="h-1.5 overflow-hidden rounded bg-white/10">
                    <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="flex items-center justify-between text-[11px] text-white/40">
              <span>
                {freeMb != null ? `${fmtMb(freeMb)} free on ${data.disk.models_root}/` : "disk space unknown"}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={() => void rescan()} className={subtleButton} disabled={downloading || rescanning} title="Re-read the model folders so files added by hand appear without a restart">
                  {rescanning ? "Rescanning…" : "Rescan models"}
                </button>
                <button onClick={() => void refresh()} className={subtleButton} disabled={downloading}>
                  Refresh
                </button>
              </div>
            </div>

            <ul className="space-y-1.5">
              {visible.map((item) => (
                <li
                  key={item.key}
                  className={`flex items-start gap-2.5 rounded-md border px-3 py-2 ${
                    item.present ? "border-emerald-500/25 bg-emerald-500/5" : "border-white/10 bg-black/20"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 accent-[var(--accent)]"
                    checked={item.present || selected.has(item.key)}
                    disabled={item.present || downloading}
                    onChange={() => toggle(item.key)}
                    aria-label={`Download ${item.label}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-white/85">{item.label}</span>
                      <span className="text-white/35">{fmtMb(item.approx_size_mb)}</span>
                      {item.present ? (
                        <span className="rounded bg-emerald-600/35 px-1.5 py-0.5 text-[10px] text-emerald-100">downloaded</span>
                      ) : item.recommended ? (
                        <span className="rounded bg-accent/30 px-1.5 py-0.5 text-[10px] text-white/80">recommended</span>
                      ) : (
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/45">advanced</span>
                      )}
                    </div>
                    <div className="mt-0.5 text-[11px] text-white/40">{item.reason}</div>
                    <div className="mt-0.5 text-[11px] text-white/30">
                      <span className="font-mono">{item.dest}/</span>
                      {" · "}
                      <a
                        href={item.repo_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-white/45 underline decoration-dotted hover:text-white/70"
                      >
                        {item.license} — verify on model card
                      </a>
                    </div>
                  </div>
                </li>
              ))}
            </ul>

            {advancedHidden > 0 ? (
              <button onClick={() => setShowAdvanced((v) => !v)} className={subtleButton}>
                {showAdvanced ? "Hide" : `Show ${advancedHidden} advanced`} model{advancedHidden === 1 ? "" : "s"}
              </button>
            ) : null}

            <p className="text-[11px] text-white/30">
              Sizes are approximate. Model files are user-supplied and keep their own provider licenses —
              review each model card before use. See MODEL_NOTICE.md.
            </p>
          </>
        )}
      </div>
    </Panel>
  );
}
