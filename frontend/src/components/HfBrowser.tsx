import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Select } from "./Select";
import { toast } from "./Toast";
import { fmtBytes } from "./format";
import type { CustomDownloadItem, HfRepoFile, HfSearchResult } from "../types";

const subtleButton =
  "ui-button rounded-md px-2.5 py-1 text-xs disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-ui-inverse transition hover:bg-accent-hover disabled:opacity-35";
const field =
  "ui-field w-full rounded-md px-2.5 py-1.5 text-[13px]";

// Weight-ish files worth pre-suggesting; everything is still shown and selectable.
const WEIGHT_RE = /\.(safetensors|gguf|pt|pth|bin|ckpt|onnx)$/i;

const SORT_OPTIONS = [
  { value: "downloads", label: "Downloads" },
  { value: "likes", label: "Likes" },
  { value: "updated", label: "Updated" },
  { value: "trending", label: "Trending" },
];

type FocusOption = { value: string; label: string; seed: string; kind: string; filter?: string };

const FOCUS_OPTIONS: FocusOption[] = [
  { value: "all", label: "All", seed: "", kind: "llm" },
  { value: "gguf", label: "GGUF", seed: "gguf", filter: "gguf", kind: "llm" },
  { value: "image", label: "Image", seed: "text-to-image safetensors", kind: "image" },
  { value: "lora", label: "LoRA", seed: "lora safetensors", filter: "lora", kind: "lora" },
  { value: "voice", label: "Voice", seed: "rvc voice conversion", kind: "voice" },
];

function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", year: "numeric" }).format(time);
}

function cleanTag(tag: string): string {
  if (tag.startsWith("license:")) return tag.slice("license:".length);
  if (tag.startsWith("base_model:")) return tag.slice("base_model:".length);
  return tag;
}

function resultTags(result: HfSearchResult): string[] {
  const tags = [
    ...(result.weight_formats ?? []),
    result.pipeline_tag ?? "",
    result.library_name ?? "",
    result.license ? `license:${result.license}` : "",
    ...result.tags,
  ]
    .filter(Boolean)
    .map(cleanTag);
  return [...new Set(tags)].slice(0, 6);
}

function isKnownKind(kind: string | null | undefined, options: { value: string }[]): kind is string {
  return !!kind && options.some((option) => option.value === kind);
}

// Browse Hugging Face as a small in-app catalog: search repos, inspect files,
// pick specific weights or download a complete repo into the chosen model folder.
export function HfBrowser({
  kind,
  setKind,
  kindOptions,
  disabled,
  autoLoad,
  onStarted,
}: {
  kind: string;
  setKind: (v: string) => void;
  kindOptions: { value: string; label: string }[];
  disabled?: boolean;
  autoLoad?: boolean;
  onStarted: () => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("downloads");
  const [focus, setFocus] = useState("all");
  const [results, setResults] = useState<HfSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [repo, setRepo] = useState("");
  const [files, setFiles] = useState<HfRepoFile[] | null>(null);
  const [loadedRepo, setLoadedRepo] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fileQuery, setFileQuery] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const [loadingRepo, setLoadingRepo] = useState("");
  const [busy, setBusy] = useState(false);

  const focusOption = FOCUS_OPTIONS.find((option) => option.value === focus) ?? FOCUS_OPTIONS[0];
  const repoName = loadedRepo.split("/").pop() ?? loadedRepo;
  const visibleFiles = useMemo(() => {
    const q = fileQuery.trim().toLowerCase();
    if (!q) return files ?? [];
    return (files ?? []).filter((file) => file.path.toLowerCase().includes(q));
  }, [fileQuery, files]);
  const totalBytes = useMemo(() => (files ?? []).reduce((s, f) => s + f.size_bytes, 0), [files]);
  const selectedBytes = useMemo(
    () => (files ?? []).filter((f) => selected.has(f.path)).reduce((s, f) => s + f.size_bytes, 0),
    [files, selected],
  );
  const selectedVisibleCount = visibleFiles.filter((file) => selected.has(file.path)).length;

  const chooseFocus = (value: string) => {
    const next = FOCUS_OPTIONS.find((option) => option.value === value) ?? FOCUS_OPTIONS[0];
    setFocus(next.value);
    if (isKnownKind(next.kind, kindOptions)) setKind(next.kind);
    if (!query.trim() && next.seed) setQuery(next.seed);
  };

  const search = async () => {
    const trimmed = query.trim() || focusOption.seed;
    if (!query.trim() && trimmed) setQuery(trimmed);
    setSearching(true);
    try {
      const res = await api.hfSearch(trimmed, {
        limit: 24,
        sort,
        filter: focusOption.filter,
      });
      setResults(res.results);
    } catch (err) {
      setResults(null);
      toast.error(err instanceof Error ? err.message : "Could not search Hugging Face");
    } finally {
      setSearching(false);
    }
  };

  // Show popular weights on open so the tab is never an empty box (lazy-user UX).
  const didAuto = useRef(false);
  useEffect(() => {
    if (autoLoad && !didAuto.current && results === null) {
      didAuto.current = true;
      void search();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad]);

  const browseRepo = async (id = repo, suggestedKind?: string | null) => {
    const clean = id.trim();
    if (!clean) return;
    if (isKnownKind(suggestedKind, kindOptions)) setKind(suggestedKind);
    setRepo(clean);
    setBrowsing(true);
    setLoadingRepo(clean);
    try {
      const res = await api.hfRepoFiles(clean);
      setFiles(res.files);
      setLoadedRepo(res.repo);
      setFileQuery("");
      // Pre-select the weight files (the common single-file case) so one click downloads.
      setSelected(new Set(res.files.filter((f) => WEIGHT_RE.test(f.path)).map((f) => f.path)));
    } catch (err) {
      setFiles(null);
      toast.error(err instanceof Error ? err.message : "Could not read that repo");
    } finally {
      setBrowsing(false);
      setLoadingRepo("");
    }
  };

  const toggle = (path: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const selectWeights = () => {
    setSelected(new Set((files ?? []).filter((f) => WEIGHT_RE.test(f.path)).map((f) => f.path)));
  };

  const start = async (items: CustomDownloadItem[]) => {
    setBusy(true);
    try {
      await api.downloadsCustom(items);
      toast.info("Downloading... this can take a while.");
      onStarted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not start download");
    } finally {
      setBusy(false);
    }
  };

  const downloadSelected = () => {
    if (!files) return;
    const picked = files.filter((f) => selected.has(f.path));
    const keepRepoFolder = picked.length > 1 || picked.some((f) => f.path.includes("/"));
    // Single-file weights stay flat for the common GGUF/SafeTensors case. Partial
    // multi-file repos stay together under a repo folder so model_index/config files
    // and nested weights do not get split across different model roots.
    const items: CustomDownloadItem[] = files
      .filter((f) => selected.has(f.path))
      .map((f) => ({
        source: "hf",
        kind,
        repo: loadedRepo,
        filename: f.path,
        subdir: keepRepoFolder ? repoName : undefined,
      }));
    if (items.length) void start(items);
  };

  const downloadWholeRepo = () => {
    if (!loadedRepo) return;
    void start([{ source: "hf-repo", kind, repo: loadedRepo }]);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded-md border border-line bg-control p-2.5">
        <div className="flex flex-wrap gap-1.5">
          {FOCUS_OPTIONS.map((option) => (
            <button
              key={option.value}
              onClick={() => chooseFocus(option.value)}
              className={`rounded px-2.5 py-1 text-xs transition ${
                focus === option.value ? "bg-accent/15 text-accent-fg" : "bg-raised text-ui-muted hover:bg-control-hover hover:text-ui"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_9rem_auto]">
          <input
            className={field}
            placeholder="Search Hugging Face weights"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void search(); }}
          />
          <Select value={sort} onChange={setSort} options={SORT_OPTIONS} />
          <button onClick={() => void search()} className={primaryButton} disabled={searching}>
            {searching ? "Searching..." : "Search"}
          </button>
        </div>

        {results ? (
          results.length === 0 ? (
            <div className="rounded-md border border-dashed border-line px-3 py-3 text-center text-xs text-ui-subtle">
              Nothing found.
            </div>
          ) : (
            <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {results.map((result) => (
                <li
                  key={result.id}
                  className={`rounded-md border px-2.5 py-2 ${
                    loadedRepo === result.id ? "border-accent/45 bg-accent/10" : "border-line bg-control"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="min-w-0 truncate font-mono text-[12px] text-ui-strong" title={result.id}>
                          {result.id}
                        </span>
                        {result.suggested_kind ? (
                          <span className="rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] text-ui-subtle">
                            {result.suggested_kind}
                          </span>
                        ) : null}
                        {result.gated ? (
                          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">gated</span>
                        ) : null}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ui-subtle">
                        <span>{fmtCount(result.downloads)} downloads</span>
                        <span>{fmtCount(result.likes)} likes</span>
                        {result.last_modified ? <span>{fmtDate(result.last_modified)}</span> : null}
                        <span>{result.weight_count} weights</span>
                        <span>{result.file_count} files</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {resultTags(result).map((tag) => (
                          <span key={tag} className="rounded bg-raised px-1.5 py-0.5 text-[10px] text-ui-subtle">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <a
                        href={result.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ui-button rounded-md px-2.5 py-1 text-xs"
                      >
                        Card
                      </a>
                      <button
                        onClick={() => void browseRepo(result.id, result.suggested_kind)}
                        className={subtleButton}
                        disabled={browsing || disabled}
                      >
                        {loadingRepo === result.id ? "Loading..." : "Files"}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <input
          className={field}
          placeholder="owner/model repo id"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void browseRepo(); }}
        />
        <button onClick={() => void browseRepo()} className={subtleButton} disabled={browsing || !repo.trim()}>
          {browsing ? "Loading..." : "Browse repo"}
        </button>
      </div>

      {files ? (
        files.length === 0 ? (
          <div className="rounded-md border border-dashed border-line px-3 py-3 text-center text-xs text-ui-subtle">
            No files found in <span className="font-mono">{loadedRepo}</span>.
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-ui-subtle">
              <span className="min-w-0 truncate">
                <span className="font-mono text-ui-muted">{loadedRepo}</span> / {files.length} files / {fmtBytes(totalBytes)}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={() => setSelected(new Set(files.map((f) => f.path)))} className="hover:text-ui">all</button>
                <button onClick={selectWeights} className="hover:text-ui">weights</button>
                <button onClick={() => setSelected(new Set())} className="hover:text-ui">none</button>
              </div>
            </div>
            <input
              className={field}
              placeholder="Filter files"
              value={fileQuery}
              onChange={(e) => setFileQuery(e.target.value)}
            />
            <ul className="max-h-64 space-y-1 overflow-y-auto rounded-md border border-line bg-control p-1.5">
              {visibleFiles.map((f) => (
                <li key={f.path}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-control-hover">
                    <input
                      type="checkbox"
                      className="accent-[var(--accent)]"
                      checked={selected.has(f.path)}
                      onChange={() => toggle(f.path)}
                    />
                    <span className={`min-w-0 flex-1 truncate font-mono text-[12px] ${WEIGHT_RE.test(f.path) ? "text-ui" : "text-ui-subtle"}`} title={f.path}>
                      {f.path}
                    </span>
                    <span className="shrink-0 text-[11px] text-ui-subtle">{f.size_bytes ? fmtBytes(f.size_bytes) : "-"}</span>
                  </label>
                </li>
              ))}
              {visibleFiles.length === 0 ? (
                <li className="px-2 py-4 text-center text-xs text-ui-subtle">No matching files.</li>
              ) : null}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-ui-subtle">Save to</span>
                <div className="w-44"><Select value={kind} onChange={setKind} options={kindOptions} /></div>
                <span className="text-[11px] text-ui-subtle">
                  {selectedVisibleCount}/{visibleFiles.length} shown selected
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={downloadWholeRepo} className={subtleButton} disabled={busy || disabled}>
                  Whole repo
                </button>
                <button onClick={downloadSelected} className={primaryButton} disabled={busy || disabled || selected.size === 0}>
                  {disabled ? "Downloading..." : `Download ${selected.size || ""} selected${selectedBytes ? ` (${fmtBytes(selectedBytes)})` : ""}`}
                </button>
              </div>
            </div>
            <p className="text-[11px] text-ui-subtle">
              Single-file weights land in <span className="font-mono">models/{kind}/</span>; multi-file picks use
              <span className="font-mono"> {repoName}/</span>.
            </p>
          </div>
        )
      ) : null}
    </div>
  );
}
