import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Select } from "./Select";
import { toast } from "./Toast";
import { fmtBytes } from "./format";
import type { CivitaiAuthStatus, CivitaiSearchResult, CivitaiVersionFiles, CustomDownloadItem } from "../types";

const NSFW_KEY = "imagefabric.civitai.nsfw";

const subtleButton = "ui-button rounded-md px-2.5 py-1 text-xs disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-ui-inverse transition hover:bg-accent-hover disabled:opacity-35";
const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-[13px]";

const SORT_OPTIONS = [
  { value: "downloads", label: "Most downloaded" },
  { value: "rated", label: "Highest rated" },
  { value: "newest", label: "Newest" },
];

// CivitAI model types we map to a model folder; "" = any. Picking one both filters
// the search and pre-selects the matching save-to folder.
type FocusOption = { value: string; label: string; types: string; kind?: string };
const FOCUS_OPTIONS: FocusOption[] = [
  { value: "all", label: "All", types: "" },
  { value: "checkpoint", label: "Checkpoints", types: "Checkpoint", kind: "image" },
  { value: "lora", label: "LoRA", types: "LORA,LoCon,DoRA", kind: "lora" },
  { value: "ti", label: "Embeddings", types: "TextualInversion", kind: "embed" },
];

function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function isKnownKind(kind: string | null | undefined, options: { value: string }[]): kind is string {
  return !!kind && options.some((option) => option.value === kind);
}

// Browse CivitAI as an in-app catalog: search models with preview images, pick a
// version + file, and download into the chosen model folder via the shared custom
// downloader. NSFW is off by default; enabling it switches to the civitai.red host.
export function CivitaiBrowser({
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
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("downloads");
  const [focus, setFocus] = useState("all");
  const [nsfw, setNsfw] = useState(() => {
    try {
      return localStorage.getItem(NSFW_KEY) === "true";
    } catch {
      return false;
    }
  });
  const [results, setResults] = useState<CivitaiSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // CivitAI account: API key (downloads) and/or session cookie (downloads now,
  // reused for image upload later — it acts on behalf of the logged-in account).
  const [auth, setAuth] = useState<CivitaiAuthStatus | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [cookieInput, setCookieInput] = useState("");
  const [savingAuth, setSavingAuth] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  useEffect(() => {
    api.civitaiAuthStatus().then(setAuth).catch(() => setAuth({ has_key: false, has_cookie: false }));
  }, []);

  const toggleNsfw = (on: boolean) => {
    setNsfw(on);
    try {
      localStorage.setItem(NSFW_KEY, on ? "true" : "false");
    } catch {
      /* preference is best-effort */
    }
  };

  const saveCredential = async (
    label: string,
    save: () => Promise<CivitaiAuthStatus>,
    onDone: () => void,
  ) => {
    setSavingAuth(true);
    try {
      const result = await save();
      onDone();
      setAuth(await api.civitaiAuthStatus());
      if (result.verified) toast.success(`CivitAI ${label} saved and verified`);
      else toast.error(result.reason || `${label} saved, but CivitAI did not accept it`, { duration: 8000 });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Could not save the ${label}`);
    } finally {
      setSavingAuth(false);
    }
  };

  const saveKey = () => {
    const clean = keyInput.trim();
    if (clean) void saveCredential("API key", () => api.civitaiAuthSave(clean), () => setKeyInput(""));
  };
  const saveCookie = () => {
    const clean = cookieInput.trim();
    if (clean) void saveCredential("session login", () => api.civitaiAuthSaveCookie(clean), () => setCookieInput(""));
  };

  const clearCredential = async (target: "key" | "cookie") => {
    setSavingAuth(true);
    try {
      setAuth(await api.civitaiAuthClear(target));
      toast.info(`CivitAI ${target === "key" ? "API key" : "session login"} removed`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the credential");
    } finally {
      setSavingAuth(false);
    }
  };

  const [openModel, setOpenModel] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [files, setFiles] = useState<CivitaiVersionFiles | null>(null);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [selectedFile, setSelectedFile] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const focusOption = FOCUS_OPTIONS.find((o) => o.value === focus) ?? FOCUS_OPTIONS[0];

  const chooseFocus = (value: string) => {
    const next = FOCUS_OPTIONS.find((o) => o.value === value) ?? FOCUS_OPTIONS[0];
    setFocus(next.value);
    if (isKnownKind(next.kind, kindOptions)) setKind(next.kind);
  };

  const search = async () => {
    setSearching(true);
    setOpenModel(null);
    setFiles(null);
    try {
      const res = await api.civitaiSearch(query, { types: focusOption.types, sort, nsfw, limit: 24, page: 1 });
      setResults(res.results);
      setNextPage(res.next_page ?? null);
    } catch (err) {
      setResults(null);
      setNextPage(null);
      toast.error(err instanceof Error ? err.message : "Could not search CivitAI");
    } finally {
      setSearching(false);
    }
  };

  // Show top models on open so the tab is never an empty box (lazy-user UX).
  const didAuto = useRef(false);
  useEffect(() => {
    if (!didAuto.current && results === null) {
      didAuto.current = true;
      void search();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMore = async () => {
    if (nextPage == null) return;
    setLoadingMore(true);
    try {
      const res = await api.civitaiSearch(query, { types: focusOption.types, sort, nsfw, limit: 24, page: nextPage });
      setResults((prev) => [...(prev ?? []), ...res.results]);
      setNextPage(res.next_page ?? null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load more");
    } finally {
      setLoadingMore(false);
    }
  };

  const openVersion = async (vid: number) => {
    setVersionId(vid);
    setLoadingFiles(true);
    setFiles(null);
    setSelectedFile(null);
    try {
      const res = await api.civitaiVersionFiles(vid, nsfw);
      setFiles(res);
      if (isKnownKind(res.suggested_kind, kindOptions)) setKind(res.suggested_kind);
      const primary = res.files.find((f) => f.primary) ?? res.files[0];
      setSelectedFile(primary ? primary.id : null);
    } catch (err) {
      setFiles(null);
      toast.error(err instanceof Error ? err.message : "Could not read that model version");
    } finally {
      setLoadingFiles(false);
    }
  };

  const openCard = (model: CivitaiSearchResult) => {
    if (openModel === model.id) {
      setOpenModel(null);
      setFiles(null);
      return;
    }
    setOpenModel(model.id);
    if (isKnownKind(model.suggested_kind, kindOptions)) setKind(model.suggested_kind);
    const first = model.versions[0];
    if (first) void openVersion(first.id);
  };

  const download = async () => {
    if (!files || selectedFile == null) return;
    const file = files.files.find((f) => f.id === selectedFile);
    if (!file || !file.download_url) {
      toast.error("That file has no download URL");
      return;
    }
    const item: CustomDownloadItem = {
      source: "civitai",
      kind,
      url: file.download_url,
      filename: file.name,
      sha256: file.sha256 ?? undefined,
      label: `${files.model_name ?? files.name} — ${file.name}`,
    };
    setBusy(true);
    try {
      await api.downloadsCustom([item]);
      toast.info("Downloading… this can take a while.");
      onStarted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not start download");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Toolbar — every search control lives at the top. */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          className={`${field} min-w-[14rem] flex-1`}
          placeholder="Search CivitAI models"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void search(); }}
        />
        <div className="w-40"><Select value={sort} onChange={setSort} options={SORT_OPTIONS} /></div>
        <button onClick={() => void search()} className={primaryButton} disabled={searching}>
          {searching ? "Searching…" : "Search"}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
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
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => toggleNsfw(!nsfw)}
            role="switch"
            aria-checked={nsfw}
            title={`Browse civitai.${nsfw ? "red" : "com"} — Red also shows adult content`}
            className="flex items-center gap-1.5 text-xs text-ui-muted hover:text-ui"
          >
            <span className={`relative inline-block h-4 w-7 rounded-full transition ${nsfw ? "bg-red-500/70" : "bg-control-active"}`}>
              <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${nsfw ? "left-3.5" : "left-0.5"}`} />
            </span>
            <span className={nsfw ? "font-medium text-red-300" : ""}>RED</span>
          </button>
          <button onClick={() => setAccountOpen((v) => !v)} className="flex items-center gap-1.5 text-[11px] text-ui-subtle hover:text-ui">
            {auth && (auth.has_key || auth.has_cookie) ? (
              <span className="rounded border border-success-border bg-success-bg px-1.5 py-0.5 text-[10px] text-success-fg">
                {auth.has_cookie ? (auth.has_key ? "key+login" : "logged in") : "key"}
              </span>
            ) : null}
            {accountOpen ? "Hide account" : "Account"}
          </button>
        </div>
      </div>

      {/* CivitAI now gates most downloads behind an account — say so up front. */}
      {auth && !auth.has_key && !auth.has_cookie && !accountOpen ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-[11px] text-warn-fg">
          <span>CivitAI requires an API key or session login to download models. Browsing works without one.</span>
          <button onClick={() => setAccountOpen(true)} className={subtleButton}>Sign in</button>
        </div>
      ) : null}

      {accountOpen ? (
        <div className="space-y-3 rounded-md border border-line bg-control p-2.5 text-xs">
          {/* API key — simplest, ToS-clean path for downloads. */}
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-ui">API key <span className="font-normal text-ui-subtle">— for downloads</span></div>
            {auth?.has_key ? (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-ui">A key is saved.</span>
                <button onClick={() => void clearCredential("key")} className={subtleButton} disabled={savingAuth}>Remove</button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="password"
                  className={`${field} flex-1`}
                  placeholder="Paste CivitAI API key"
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveKey(); }}
                />
                <button onClick={saveKey} className={primaryButton} disabled={savingAuth || !keyInput.trim()}>
                  {savingAuth ? "Saving…" : "Save & verify"}
                </button>
              </div>
            )}
            <p className="text-[11px] text-ui-subtle">CivitAI → Account settings → API Keys.</p>
          </div>

          {/* Session login — native account auth, reused for image upload later. */}
          <div className="space-y-1.5 border-t border-line pt-2.5">
            <div className="text-[11px] font-medium text-ui">Session login <span className="font-normal text-ui-subtle">— downloads + future image upload</span></div>
            {auth?.has_cookie ? (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-ui">Logged in (session saved).</span>
                <button onClick={() => void clearCredential("cookie")} className={subtleButton} disabled={savingAuth}>Log out</button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="password"
                  className={`${field} flex-1`}
                  placeholder="Paste __Secure-civitai-token cookie"
                  value={cookieInput}
                  onChange={(e) => setCookieInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveCookie(); }}
                />
                <button onClick={saveCookie} className={primaryButton} disabled={savingAuth || !cookieInput.trim()}>
                  {savingAuth ? "Saving…" : "Save & verify"}
                </button>
              </div>
            )}
            <p className="text-[11px] text-ui-subtle">
              Log in to <a href="https://civitai.com/login" target="_blank" rel="noreferrer" className="underline decoration-dotted hover:text-ui">civitai.com</a>,
              then copy the <span className="font-mono">__Secure-civitai-token</span> cookie (DevTools → Application → Cookies → civitai.com).
              Stored locally in <span className="font-mono">data/secrets.json</span>; expires, so re-paste when downloads start failing.
            </p>
          </div>
        </div>
      ) : null}

      {/* Results — one flat list that fills the available height. */}
      {results && results.length === 0 ? (
        <div className="rounded-md border border-dashed border-line px-3 py-6 text-center text-xs text-ui-subtle">
          Nothing found. Try another search or focus.
        </div>
      ) : results ? (
        <ul className="max-h-[64vh] divide-y divide-line overflow-y-auto rounded-md border border-line">
          {results.map((model) => (
            <li key={model.id} className={openModel === model.id ? "bg-accent/5" : ""}>
              <div className="flex items-start gap-2.5 px-3 py-2">
                {model.preview?.url ? (
                  <img src={model.preview.url} alt="" loading="lazy" className="h-14 w-14 shrink-0 rounded object-cover" />
                ) : (
                  <div className="h-14 w-14 shrink-0 rounded bg-raised" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="min-w-0 truncate text-[13px] text-ui-strong" title={model.name}>{model.name}</span>
                    {model.type ? <span className="rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] text-ui-subtle">{model.type}</span> : null}
                    {model.base_model ? <span className="rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] text-ui-subtle">{model.base_model}</span> : null}
                    {model.nsfw ? <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-200">adult</span> : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ui-subtle">
                    {model.creator ? <span>by {model.creator}</span> : null}
                    <span>{fmtCount(model.downloads)} downloads</span>
                    <span>{fmtCount(model.likes)} likes</span>
                    <span>{model.version_count} version{model.version_count === 1 ? "" : "s"}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <a href={model.url} target="_blank" rel="noreferrer" className="ui-button rounded-md px-2.5 py-1 text-xs">Card</a>
                  <button onClick={() => openCard(model)} className={subtleButton} disabled={disabled}>
                    {openModel === model.id ? "Hide" : "Get"}
                  </button>
                </div>
              </div>

              {openModel === model.id ? (
                <div className="space-y-2 border-t border-line bg-raised/40 px-3 py-2 pl-[4.4rem]">
                  {model.versions.length > 1 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {model.versions.map((v) => (
                        <button
                          key={v.id}
                          onClick={() => void openVersion(v.id)}
                          className={`rounded px-2 py-0.5 text-[11px] transition ${
                            versionId === v.id ? "bg-accent/15 text-accent-fg" : "bg-raised text-ui-muted hover:bg-control-hover hover:text-ui"
                          }`}
                        >
                          {v.name}{v.base_model ? ` · ${v.base_model}` : ""}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {loadingFiles ? (
                    <div className="text-[11px] text-ui-subtle">Loading files…</div>
                  ) : files && files.version_id === versionId ? (
                    <>
                      {files.trained_words.length ? (
                        <div className="text-[11px] text-ui-subtle">
                          Trigger words: <span className="font-mono text-ui">{files.trained_words.join(", ")}</span>
                        </div>
                      ) : null}
                      <ul className="space-y-0.5">
                        {files.files.map((f) => (
                          <li key={f.id}>
                            <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-control-hover">
                              <input
                                type="radio"
                                name={`civitai-file-${model.id}`}
                                className="accent-[var(--accent)]"
                                checked={selectedFile === f.id}
                                onChange={() => setSelectedFile(f.id)}
                              />
                              <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ui" title={f.name}>{f.name}</span>
                              {f.format ? <span className="shrink-0 text-[10px] text-ui-subtle">{f.format}</span> : null}
                              {f.primary ? <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent-fg">primary</span> : null}
                              <span className="shrink-0 text-[11px] text-ui-subtle">{f.size_kb ? fmtBytes(f.size_kb * 1024) : "—"}</span>
                            </label>
                          </li>
                        ))}
                      </ul>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-ui-subtle">Save to</span>
                          <div className="w-40"><Select value={kind} onChange={setKind} options={kindOptions} /></div>
                        </div>
                        <button onClick={() => void download()} className={primaryButton} disabled={busy || disabled || selectedFile == null}>
                          {disabled ? "Downloading…" : "Download"}
                        </button>
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {results && results.length > 0 && nextPage != null ? (
        <button onClick={() => void loadMore()} className={`${subtleButton} w-full`} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}

      <p className="text-[11px] text-ui-subtle">
        Models keep their CivitAI licenses — review the model card before use. The RED toggle browses
        civitai.red, which also shows adult content (off by default).
      </p>
    </div>
  );
}
