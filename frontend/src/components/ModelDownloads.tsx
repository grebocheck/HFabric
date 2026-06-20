import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { CivitaiBrowser } from "./CivitaiBrowser";
import { HfBrowser } from "./HfBrowser";
import { Select } from "./Select";
import { Panel, SectionTitle, SkeletonRows } from "./WorkspaceChrome";
import { toast } from "./Toast";
import type { CustomDownloadItem, ModelDownloadItem, ModelDownloadState } from "../types";

const subtleButton =
  "ui-button rounded-md px-2.5 py-1 text-xs disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-ui-inverse transition hover:bg-accent-hover disabled:opacity-35";
const field =
  "ui-field w-full rounded-md px-2.5 py-1.5 text-[13px]";

// The model kinds the custom downloader can target (mirrors the backend folders).
const KIND_OPTIONS = [
  { value: "llm", label: "LLM (chat)" },
  { value: "image", label: "Image" },
  { value: "lora", label: "LoRA" },
  { value: "vision", label: "Vision (multimodal)" },
  { value: "embed", label: "Embeddings (RAG)" },
  { value: "tts", label: "Text-to-speech" },
  { value: "transcribe", label: "Transcription" },
  { value: "voice", label: "Voice changer" },
];

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

  // --- custom (any-source) download: Hugging Face catalog (HfBrowser) or direct URL ---
  const [installedOpen, setInstalledOpen] = useState(false);
  const [source, setSource] = useState<"hf" | "civitai" | "url">("hf");
  const [kind, setKind] = useState("llm");
  const [filename, setFilename] = useState("");
  const [url, setUrl] = useState("");

  const addCustom = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      toast.error("Enter a direct download URL");
      return;
    }
    const item: CustomDownloadItem = { source: "url", kind, url: trimmed, filename: filename.trim() || undefined };
    setBusy(true);
    try {
      await api.downloadsCustom([item]);
      toast.info("Downloading… this can take a while.");
      setFilename("");
      setUrl("");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Could not start download"));
    } finally {
      setBusy(false);
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
  // Three clearly-separated buckets so the page isn't one long checkbox wall:
  // what to grab now, optional extras, and what's already on disk.
  const recommended = useMemo(() => catalog.filter((i) => i.recommended && !i.present), [catalog]);
  const advanced = useMemo(() => catalog.filter((i) => !i.recommended && !i.present), [catalog]);
  const installed = useMemo(() => catalog.filter((i) => i.present), [catalog]);
  const installedMb = installed.reduce((sum, i) => sum + i.approx_size_mb, 0);
  const selectedItems = catalog.filter((i) => selected.has(i.key) && !i.present);
  const totalMb = selectedItems.reduce((sum, i) => sum + i.approx_size_mb, 0);

  const renderRow = (item: ModelDownloadItem) => (
    <li
      key={item.key}
      className={`flex items-start gap-2.5 rounded-md border px-3 py-2 ${
        item.present ? "border-success-border bg-success-bg" : "border-line bg-control"
      }`}
    >
      {item.present ? (
        <span className="mt-0.5 text-success-fg" aria-hidden>✓</span>
      ) : (
        <input
          type="checkbox"
          className="mt-0.5 accent-[var(--accent)]"
          checked={selected.has(item.key)}
          disabled={downloading}
          onChange={() => toggle(item.key)}
          aria-label={`Download ${item.label}`}
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-ui-strong">{item.label}</span>
          <span className="text-ui-subtle">{fmtMb(item.approx_size_mb)}</span>
        </div>
        <div className="mt-0.5 text-[11px] text-ui-subtle">{item.reason}</div>
        <div className="mt-0.5 text-[11px] text-ui-subtle">
          <span className="font-mono">{item.dest}/</span>
          {" · "}
          <a
            href={item.repo_url}
            target="_blank"
            rel="noreferrer"
            className="text-ui-subtle underline decoration-dotted hover:text-ui"
          >
            {item.license} — verify on model card
          </a>
        </div>
      </div>
    </li>
  );

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
        title="Model catalog"
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
              <div className="rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-warn-fg">
                In-app downloads need <span className="font-mono">huggingface_hub</span>, which is not
                installed in this environment. Run the accelerator setup (<span className="font-mono">setup … real</span>)
                or <span className="font-mono">pip install huggingface_hub</span>.
              </div>
            ) : null}

            {downloading ? (
              <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-accent-fg">
                <div className="mb-1 flex items-center justify-between">
                  <span className="truncate">{status?.message ?? "Downloading…"}</span>
                  {pct != null ? <span className="font-mono text-ui-muted">{pct}%</span> : null}
                </div>
                {pct != null ? (
                  <div className="h-1.5 overflow-hidden rounded bg-control-active">
                    <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="flex items-center justify-between text-[11px] text-ui-subtle">
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

            {/* 1) Recommended — the one-click path for the impatient. */}
            <section className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-[12px] font-medium text-ui">Recommended for this machine</span>
                {recommended.length ? (
                  <span className="text-[11px] text-ui-subtle">preselected · {fmtMb(totalMb)}</span>
                ) : null}
              </div>
              {recommended.length ? (
                <ul className="space-y-1.5">{recommended.map(renderRow)}</ul>
              ) : (
                <div className="rounded-md border border-success-border bg-success-bg px-3 py-2 text-success-fg">
                  You already have every recommended model. Browse below for more.
                </div>
              )}
              {advanced.length ? (
                <>
                  <button onClick={() => setShowAdvanced((v) => !v)} className={subtleButton}>
                    {showAdvanced
                      ? "Hide optional curated models"
                      : `Show ${advanced.length} optional curated model${advanced.length === 1 ? "" : "s"}`}
                  </button>
                  {showAdvanced ? <ul className="space-y-1.5">{advanced.map(renderRow)}</ul> : null}
                </>
              ) : null}
            </section>

            {/* 2) Browse & install — promoted, always open, prefilled on open. */}
            <section className="space-y-2 rounded-md border border-line bg-control p-3">
              <div className="text-[12px] font-medium text-ui">Browse &amp; install from a source</div>
              <div className="flex rounded-md border border-line bg-raised p-0.5 text-xs">
                {(["hf", "civitai", "url"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSource(s)}
                    className={`rounded px-2.5 py-1 transition ${source === s ? "bg-accent/15 text-accent-fg" : "text-ui-muted hover:bg-control-hover hover:text-ui"}`}
                  >
                    {s === "hf" ? "Hugging Face" : s === "civitai" ? "CivitAI" : "Direct URL"}
                  </button>
                ))}
              </div>
              {source === "hf" ? (
                <HfBrowser
                  kind={kind}
                  setKind={setKind}
                  kindOptions={KIND_OPTIONS}
                  disabled={downloading}
                  autoLoad={data.available}
                  onStarted={() => void refresh()}
                />
              ) : source === "civitai" ? (
                <CivitaiBrowser
                  kind={kind}
                  setKind={setKind}
                  kindOptions={KIND_OPTIONS}
                  disabled={downloading}
                  onStarted={() => void refresh()}
                />
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <span className="text-[11px] text-ui-subtle">Save to</span>
                    <div className="w-44"><Select value={kind} onChange={setKind} options={KIND_OPTIONS} /></div>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <input className={field} placeholder="https://… direct file URL" value={url} onChange={(e) => setUrl(e.target.value)} />
                    <input className={field} placeholder="save as (optional)" value={filename} onChange={(e) => setFilename(e.target.value)} />
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-ui-subtle">
                      Lands in <span className="font-mono">models/{kind}/</span>. Review the license first.
                    </span>
                    <button onClick={() => void addCustom()} className={primaryButton} disabled={busy || downloading}>
                      {downloading ? "Downloading…" : "Download"}
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* 3) Installed — collapsed so it isn't a wall. */}
            {installed.length ? (
              <div className="rounded-md border border-line bg-control">
                <button
                  onClick={() => setInstalledOpen((v) => !v)}
                  className="flex w-full items-center justify-between px-3 py-2 text-left text-[12px] text-ui-muted hover:text-ui"
                >
                  <span>Installed starter models · {installed.length} · {fmtMb(installedMb)}</span>
                  <span className="text-ui-subtle">{installedOpen ? "–" : "+"}</span>
                </button>
                {installedOpen ? (
                  <ul className="space-y-1.5 border-t border-line p-3">{installed.map(renderRow)}</ul>
                ) : null}
              </div>
            ) : null}

            <p className="text-[11px] text-ui-subtle">
              Sizes are approximate. Model files are user-supplied and keep their own provider licenses —
              review each model card before use. See MODEL_NOTICE.md.
            </p>
          </>
        )}
      </div>
    </Panel>
  );
}
