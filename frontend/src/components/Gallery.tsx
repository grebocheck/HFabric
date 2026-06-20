import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Select, type SelectOption } from "./Select";
import { toast } from "./Toast";
import { Chip, DetailModal, familyLabel } from "./GalleryParts";
import type { ImageItem, ImageStats, Model } from "../types";

const PAGE = 60;

const DATE_RANGES = [
  { value: "all", label: "All time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

const SIZE_FILTERS = [
  { value: "", label: "All sizes" },
  { value: "square", label: "Square" },
  { value: "landscape", label: "Landscape" },
  { value: "portrait", label: "Portrait" },
  { value: "large", label: "1024+ px" },
  { value: "small", label: "Under 1024" },
];

function rangeStart(id: string): string | undefined {
  const now = Date.now();
  if (id === "today") {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }
  if (id === "7d") return new Date(now - 7 * 86_400_000).toISOString();
  if (id === "30d") return new Date(now - 30 * 86_400_000).toISOString();
  return undefined;
}

function localDateKey(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function dateGroupLabel(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  if (localDateKey(date) === localDateKey(now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (localDateKey(date) === localDateKey(yesterday)) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  }).format(date);
}

export function Gallery({
  models,
  reloadSignal,
  onReproduce,
  onUpscale,
}: {
  models: Model[];
  reloadSignal: number;
  onReproduce: (image: ImageItem, opts: { keepSeed: boolean }) => void;
  onUpscale: (image: ImageItem, scale: 2 | 4) => void;
}) {
  // `applied` is what actually drives fetching; `query` is the live input box.
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState({ q: "", model: "", family: "", size: "", lora: "", favorite: false, tag: "", range: "all" });
  const [items, setItems] = useState<ImageItem[]>([]);
  const [stats, setStats] = useState<ImageStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadSentinelRef = useRef<HTMLDivElement>(null);
  const requestVersionRef = useRef(0);
  const loadingRef = useRef(false);

  const refreshStats = useCallback(() => {
    api.imageStats().then(setStats).catch(() => {});
  }, []);

  const fetchPage = useCallback(
    (offset: number) =>
      api.queryImages({
        q: applied.q || undefined,
        model: applied.model || undefined,
        family: applied.family || undefined,
        size: applied.size || undefined,
        lora: applied.lora || undefined,
        favorite: applied.favorite ? true : undefined,
        tag: applied.tag || undefined,
        date_from: rangeStart(applied.range),
        limit: PAGE,
        offset,
      }),
    [applied],
  );

  const reload = useCallback(async () => {
    const requestVersion = ++requestVersionRef.current;
    loadingRef.current = true;
    setLoading(true);
    setLoadError(false);
    try {
      const rows = await fetchPage(0);
      if (requestVersion !== requestVersionRef.current) return;
      setItems(rows);
      setHasMore(rows.length === PAGE);
    } catch {
      if (requestVersion !== requestVersionRef.current) return;
      setItems([]);
      setHasMore(false);
      setLoadError(true);
    } finally {
      if (requestVersion === requestVersionRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [fetchPage]);

  useEffect(() => {
    void reload();
  }, [reload, reloadSignal]);

  useEffect(() => {
    refreshStats();
  }, [refreshStats, reloadSignal]);

  const loadMore = useCallback(async (): Promise<ImageItem[]> => {
    if (loadingRef.current || !hasMore) return [];
    const requestVersion = requestVersionRef.current;
    loadingRef.current = true;
    setLoading(true);
    setLoadError(false);
    try {
      const rows = await fetchPage(items.length);
      if (requestVersion !== requestVersionRef.current) return [];
      setItems((prev) => {
        const known = new Set(prev.map((item) => item.id));
        return [...prev, ...rows.filter((item) => !known.has(item.id))];
      });
      setHasMore(rows.length === PAGE);
      return rows;
    } catch {
      if (requestVersion === requestVersionRef.current) setLoadError(true);
      return [];
    } finally {
      if (requestVersion === requestVersionRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [fetchPage, hasMore, items.length]);

  useEffect(() => {
    const root = scrollRef.current;
    const target = loadSentinelRef.current;
    if (!root || !target || !hasMore || loadError || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { root, rootMargin: "0px 0px 480px 0px", threshold: 0.01 },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadError, loadMore]);

  const dateGroups = useMemo(() => {
    const groups = new Map<string, { label: string; items: ImageItem[] }>();
    for (const item of items) {
      const key = localDateKey(item.created_at);
      const group = groups.get(key);
      if (group) group.items.push(item);
      else groups.set(key, { label: dateGroupLabel(item.created_at), items: [item] });
    }
    return [...groups.entries()].map(([key, group]) => ({ key, ...group }));
  }, [items]);

  const open = useMemo(() => items.find((i) => i.id === openId) ?? null, [items, openId]);
  const openIndex = useMemo(() => (openId ? items.findIndex((i) => i.id === openId) : -1), [items, openId]);
  const goPrev = useCallback(() => {
    if (openIndex > 0) setOpenId(items[openIndex - 1].id);
  }, [openIndex, items]);
  const goNext = useCallback(() => {
    if (openIndex >= 0 && openIndex < items.length - 1) {
      setOpenId(items[openIndex + 1].id);
    } else if (openIndex >= 0 && hasMore) {
      void loadMore().then((rows) => {
        if (rows[0]) setOpenId(rows[0].id);
      });
    }
  }, [hasMore, loadMore, openIndex, items]);

  // Arrow keys page through the open image; Escape closes. Guarded so typing in
  // the tag / search inputs keeps normal caret movement.
  useEffect(() => {
    if (!openId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpenId(null); return; }
      const el = document.activeElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); goPrev(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); goNext(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId, goPrev, goNext]);

  const removeOne = useCallback(
    async (id: string) => {
      try {
        await api.deleteImage(id);
        setItems((prev) => prev.filter((i) => i.id !== id));
        setSelected((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        if (openId === id) setOpenId(null);
        refreshStats();
      } catch {
        toast.error("Could not delete image");
      }
    },
    [openId, refreshStats],
  );

  const removeSelected = async () => {
    const ids = [...selected];
    if (!ids.length) return;
    await Promise.allSettled(ids.map((id) => api.deleteImage(id)));
    setItems((prev) => prev.filter((i) => !selected.has(i.id)));
    setSelected(new Set());
    setSelectMode(false);
    refreshStats();
    toast.success(`Deleted ${ids.length} image${ids.length > 1 ? "s" : ""}`);
  };

  const exportSelected = async () => {
    const ids = [...selected];
    if (!ids.length || exporting) return;
    setExporting(true);
    try {
      const blob = await api.exportImages(ids);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `hfabric-images-${ids.length}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${ids.length} image${ids.length > 1 ? "s" : ""}`);
    } catch {
      toast.error("Could not export selected images");
    } finally {
      setExporting(false);
    }
  };

  const toggleSelected = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submitSearch = () => setApplied((a) => ({ ...a, q: query }));

  const modelOptions: SelectOption[] = [
    { value: "", label: stats ? `All models (${stats.total})` : "All models" },
    ...(stats?.by_model ?? []).map((m) => ({ value: m.model, label: m.model, hint: String(m.count) })),
  ];
  const familyOptions: SelectOption[] = [
    { value: "", label: "All families" },
    ...(stats?.by_family ?? []).map((row) => ({ value: row.family, label: familyLabel(row.family), hint: String(row.count) })),
  ];
  const selectedFamilyName = familyOptions.find((option) => option.value === applied.family)?.label ?? familyLabel(applied.family);
  const loraOptions: SelectOption[] = [
    { value: "", label: "All LoRAs" },
    ...(stats?.by_lora ?? []).map((lora) => ({ value: lora.id, label: lora.name, hint: String(lora.count) })),
  ];
  const selectedLoraName = loraOptions.find((option) => option.value === applied.lora)?.label ?? applied.lora;
  const tagOptions: SelectOption[] = [
    { value: "", label: "All tags" },
    ...(stats?.by_tag ?? []).map((tag) => ({ value: tag.tag, label: tag.tag, hint: String(tag.count) })),
  ];
  const selectedTagName = tagOptions.find((option) => option.value === applied.tag)?.label ?? applied.tag;

  const handleImageUpdate = useCallback(
    (updated: ImageItem) => {
      setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      refreshStats();
      void reload();
    },
    [refreshStats, reload],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* --- header: counters + search + filters --- */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-ui-strong">History</h2>
          {stats && (
            <span className="text-xs text-ui-subtle">
              {stats.total} total · {stats.today} today
            </span>
          )}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitSearch();
              }}
              placeholder="search prompt / seed"
              className="ui-field w-44 rounded-l-md px-2 py-1 text-xs"
            />
            <button
              onClick={submitSearch}
              className="ui-button rounded-r-md border-l-0 px-2 py-1 text-xs"
            >
              Go
            </button>
          </div>
          <div className="w-40">
            <Select value={applied.model} options={modelOptions} onChange={(v) => setApplied((a) => ({ ...a, model: v }))} />
          </div>
          <div className="w-32">
            <Select value={applied.family} options={familyOptions} onChange={(v) => setApplied((a) => ({ ...a, family: v }))} />
          </div>
          <div className="w-32">
            <Select value={applied.size} options={SIZE_FILTERS} onChange={(v) => setApplied((a) => ({ ...a, size: v }))} />
          </div>
          <div className="w-40">
            <Select value={applied.lora} options={loraOptions} onChange={(v) => setApplied((a) => ({ ...a, lora: v }))} />
          </div>
          <button
            onClick={() => setApplied((a) => ({ ...a, favorite: !a.favorite }))}
            className={`rounded-md border px-2.5 py-1 text-xs transition ${
              applied.favorite ? "border-warn-border bg-warn-bg text-warn-fg" : "ui-button"
            }`}
          >
            Favorites
          </button>
          <div className="w-36">
            <Select value={applied.tag} options={tagOptions} onChange={(v) => setApplied((a) => ({ ...a, tag: v }))} />
          </div>
          <div className="w-36">
            <Select value={applied.range} options={DATE_RANGES} onChange={(v) => setApplied((a) => ({ ...a, range: v }))} />
          </div>
          <button
            onClick={() => {
              setSelectMode((v) => !v);
              setSelected(new Set());
            }}
            className={`rounded-md border px-2.5 py-1 text-xs transition ${
              selectMode ? "border-accent/70 bg-accent/15 text-accent-fg" : "ui-button"
            }`}
          >
            {selectMode ? "Done" : "Select"}
          </button>
        </div>
      </div>

      {(applied.q || applied.model || applied.family || applied.size || applied.lora || applied.favorite || applied.tag || applied.range !== "all") && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {applied.q && <Chip onClear={() => { setQuery(""); setApplied((a) => ({ ...a, q: "" })); }}>“{applied.q}”</Chip>}
          {applied.model && <Chip onClear={() => setApplied((a) => ({ ...a, model: "" }))}>{applied.model}</Chip>}
          {applied.family && <Chip onClear={() => setApplied((a) => ({ ...a, family: "" }))}>Family: {selectedFamilyName}</Chip>}
          {applied.size && (
            <Chip onClear={() => setApplied((a) => ({ ...a, size: "" }))}>
              {SIZE_FILTERS.find((r) => r.value === applied.size)?.label}
            </Chip>
          )}
          {applied.lora && <Chip onClear={() => setApplied((a) => ({ ...a, lora: "" }))}>LoRA: {selectedLoraName}</Chip>}
          {applied.favorite && <Chip onClear={() => setApplied((a) => ({ ...a, favorite: false }))}>Favorites</Chip>}
          {applied.tag && <Chip onClear={() => setApplied((a) => ({ ...a, tag: "" }))}>Tag: {selectedTagName}</Chip>}
          {applied.range !== "all" && (
            <Chip onClear={() => setApplied((a) => ({ ...a, range: "all" }))}>
              {DATE_RANGES.find((r) => r.value === applied.range)?.label}
            </Chip>
          )}
        </div>
      )}

      {/* --- bulk action bar --- */}
      {selectMode && (
        <div className="flex items-center gap-2 rounded-md border border-line bg-raised px-3 py-1.5 text-xs shadow-panel">
          <span className="text-ui-muted">{selected.size} selected</span>
          <button
            onClick={removeSelected}
            disabled={!selected.size}
            className="rounded border border-error-border px-2 py-0.5 text-error-fg hover:bg-error-bg disabled:opacity-30"
          >
            Delete selected
          </button>
          <button
            onClick={exportSelected}
            disabled={!selected.size || exporting}
            className="ui-button rounded px-2 py-0.5 disabled:opacity-30"
          >
            {exporting ? "Exporting..." : "Export ZIP"}
          </button>
          <button onClick={() => setSelected(new Set())} disabled={!selected.size} className="ui-button rounded px-2 py-0.5 disabled:opacity-30">
            Clear
          </button>
        </div>
      )}

      {/* --- grid --- */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-ui-subtle">
            {loading ? "loading…" : loadError ? "could not load history" : "no images match"}
            {loadError && !loading && (
              <button onClick={() => void reload()} className="ui-button rounded-md px-3 py-1 text-xs">
                Retry
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-5">
              {dateGroups.map((group) => (
                <section key={group.key} data-history-date={group.key}>
                  <div className="sticky top-0 z-10 mb-2 flex items-center gap-2 border-b border-line bg-surface/95 py-1.5 backdrop-blur">
                    <h3 className="text-xs font-semibold text-ui-strong">{group.label}</h3>
                    <span className="text-[11px] text-ui-subtle">{group.items.length}</span>
                  </div>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
                    {group.items.map((img) => {
                      const isSel = selected.has(img.id);
                      return (
                        <button
                          key={img.id}
                          onClick={() => (selectMode ? toggleSelected(img.id) : setOpenId(img.id))}
                          title={String(img.params?.prompt ?? "")}
                          className={`group relative aspect-square animate-fade-in overflow-hidden rounded-md border transition ${
                            isSel ? "border-accent ring-2 ring-accent/40" : "border-line hover:border-border-strong"
                          }`}
                        >
                          <img src={img.thumb_url ?? img.url} alt="" loading="lazy" className="h-full w-full object-cover" />
                          {img.favorite && (
                            <span className="absolute right-1.5 top-1.5 rounded border border-amber-200/30 bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-amber-100">
                              Fav
                            </span>
                          )}
                          {selectMode && (
                            <span className={`absolute left-1.5 top-1.5 grid h-5 w-5 place-items-center rounded border text-[11px] ${
                              isSel ? "border-accent/80 bg-accent text-ui-inverse" : "border-white/60 bg-black/40 text-transparent"
                            }`}>
                              ✓
                            </span>
                          )}
                          {!selectMode && (
                            <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/80 to-transparent px-1.5 pb-1 pt-4 text-left text-[10px] text-white/70 opacity-0 transition group-hover:opacity-100">
                              {String(img.params?.model ?? "")}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
            {(hasMore || loading || loadError) && (
              <div ref={loadSentinelRef} className="mt-3 flex min-h-10 items-center justify-center text-xs text-ui-subtle" role="status">
                {loading ? "loading more…" : loadError ? (
                  <button onClick={() => void loadMore()} className="ui-button rounded-md px-3 py-1 text-xs">
                    Retry loading
                  </button>
                ) : "more images load automatically"}
              </div>
            )}
          </>
        )}
      </div>

      {open && (
        <DetailModal
          image={open}
          models={models}
          onClose={() => setOpenId(null)}
          onReproduce={onReproduce}
          onUpscale={onUpscale}
          onUpdate={handleImageUpdate}
          onDelete={() => void removeOne(open.id)}
          onPrev={goPrev}
          onNext={goNext}
          hasPrev={openIndex > 0}
          hasNext={openIndex >= 0 && (openIndex < items.length - 1 || hasMore)}
        />
      )}
    </div>
  );
}
