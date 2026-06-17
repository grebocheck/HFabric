import { useMemo, useState } from "react";
import { api } from "../api/client";
import { Select } from "./Select";
import { toast } from "./Toast";
import { fmtBytes } from "./format";
import type { CustomDownloadItem, HfRepoFile } from "../types";

const subtleButton =
  "rounded-md border border-white/15 px-2.5 py-1 text-xs text-white/65 transition hover:bg-white/10 hover:text-white disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white transition hover:bg-accent-hover disabled:opacity-35";
const field =
  "w-full rounded-md border border-white/10 bg-black/30 px-2.5 py-1.5 text-[13px] outline-none transition placeholder:text-white/25 focus:border-accent";

// Weight-ish files worth pre-suggesting; everything is still shown and selectable.
const WEIGHT_RE = /\.(safetensors|gguf|pt|pth|bin|ckpt|onnx)$/i;

// Browse a HuggingFace repo (P25): fetch the file list with sizes, pick specific
// file(s) or the whole repo, and download into the chosen kind folder.
export function HfBrowser({
  kind,
  setKind,
  kindOptions,
  disabled,
  onStarted,
}: {
  kind: string;
  setKind: (v: string) => void;
  kindOptions: { value: string; label: string }[];
  disabled?: boolean;
  onStarted: () => void;
}) {
  const [repo, setRepo] = useState("");
  const [files, setFiles] = useState<HfRepoFile[] | null>(null);
  const [loadedRepo, setLoadedRepo] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [browsing, setBrowsing] = useState(false);
  const [busy, setBusy] = useState(false);

  const repoName = loadedRepo.split("/").pop() ?? loadedRepo;
  const totalBytes = useMemo(() => (files ?? []).reduce((s, f) => s + f.size_bytes, 0), [files]);
  const selectedBytes = useMemo(
    () => (files ?? []).filter((f) => selected.has(f.path)).reduce((s, f) => s + f.size_bytes, 0),
    [files, selected],
  );

  const browse = async () => {
    const id = repo.trim();
    if (!id) return;
    setBrowsing(true);
    try {
      const res = await api.hfRepoFiles(id);
      setFiles(res.files);
      setLoadedRepo(res.repo);
      // Pre-select the weight files (the common single-file case) so one click downloads.
      setSelected(new Set(res.files.filter((f) => WEIGHT_RE.test(f.path)).map((f) => f.path)));
    } catch (err) {
      setFiles(null);
      toast.error(err instanceof Error ? err.message : "Could not read that repo");
    } finally {
      setBrowsing(false);
    }
  };

  const toggle = (path: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const start = async (items: CustomDownloadItem[]) => {
    setBusy(true);
    try {
      await api.downloadsCustom(items);
      toast.info("Downloading… this can take a while.");
      onStarted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not start download");
    } finally {
      setBusy(false);
    }
  };

  const downloadSelected = () => {
    if (!files) return;
    // Top-level files land flat in the kind folder; files inside a repo subpath keep
    // their structure under a folder named after the repo (so partial diffusers repos
    // still assemble).
    const items: CustomDownloadItem[] = files
      .filter((f) => selected.has(f.path))
      .map((f) => ({
        source: "hf",
        kind,
        repo: loadedRepo,
        filename: f.path,
        subdir: f.path.includes("/") ? repoName : undefined,
      }));
    if (items.length) void start(items);
  };

  const downloadWholeRepo = () =>
    void start([{ source: "hf-repo", kind, repo: loadedRepo }]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          className={field}
          placeholder="HuggingFace repo, e.g. ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void browse(); }}
        />
        <button onClick={() => void browse()} className={subtleButton} disabled={browsing || !repo.trim()}>
          {browsing ? "Loading…" : "Browse"}
        </button>
      </div>

      {files ? (
        files.length === 0 ? (
          <div className="rounded-md border border-dashed border-white/10 px-3 py-3 text-center text-xs text-white/35">
            No files found in <span className="font-mono">{loadedRepo}</span>.
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between text-[11px] text-white/40">
              <span className="truncate">
                <span className="font-mono text-white/55">{loadedRepo}</span> · {files.length} files · {fmtBytes(totalBytes)}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={() => setSelected(new Set(files.map((f) => f.path)))} className="hover:text-white/70">all</button>
                <button onClick={() => setSelected(new Set())} className="hover:text-white/70">none</button>
              </div>
            </div>
            <ul className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-white/10 bg-black/15 p-1.5">
              {files.map((f) => (
                <li key={f.path}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-white/5">
                    <input
                      type="checkbox"
                      className="accent-[var(--accent)]"
                      checked={selected.has(f.path)}
                      onChange={() => toggle(f.path)}
                    />
                    <span className={`min-w-0 flex-1 truncate font-mono text-[12px] ${WEIGHT_RE.test(f.path) ? "text-white/80" : "text-white/45"}`} title={f.path}>
                      {f.path}
                    </span>
                    <span className="shrink-0 text-[11px] text-white/35">{f.size_bytes ? fmtBytes(f.size_bytes) : "—"}</span>
                  </label>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-white/40">Save to</span>
                <div className="w-44"><Select value={kind} onChange={setKind} options={kindOptions} /></div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={downloadWholeRepo} className={subtleButton} disabled={busy || disabled}>
                  Whole repo
                </button>
                <button onClick={downloadSelected} className={primaryButton} disabled={busy || disabled || selected.size === 0}>
                  {disabled ? "Downloading…" : `Download ${selected.size || ""} selected${selectedBytes ? ` (${fmtBytes(selectedBytes)})` : ""}`}
                </button>
              </div>
            </div>
            <p className="text-[11px] text-white/30">
              Single weight files land in <span className="font-mono">models/{kind}/</span>; multi-file repos go in a
              <span className="font-mono"> {repoName}/</span> subfolder. Review the model's license first.
            </p>
          </>
        )
      ) : null}
    </div>
  );
}
