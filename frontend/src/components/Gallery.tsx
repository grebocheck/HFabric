import { useCallback, useEffect, useMemo, useState } from "react";
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
  const [openId, setOpenId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

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
    setLoading(true);
    try {
      const rows = await fetchPage(0);
      setItems(rows);
      setHasMore(rows.length === PAGE);
    } catch {
      setItems([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [fetchPage]);

  useEffect(() => {
    void reload();
  }, [reload, reloadSignal]);

  useEffect(() => {
    refreshStats();
  }, [refreshStats, reloadSignal]);

  const loadMore = async () => {
    setLoading(true);
    try {
      const rows = await fetchPage(items.length);
      setItems((prev) => [...prev, ...rows]);
      setHasMore(rows.length === PAGE);
    } finally {
      setLoading(false);
    }
  };

  const open = useMemo(() => items.find((i) => i.id === openId) ?? null, [items, openId]);

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
          <h2 className="text-sm font-semibold text-white/80">History</h2>
          {stats && (
            <span className="text-xs text-white/40">
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
              className="w-44 rounded-l-md border border-white/10 bg-black/30 px-2 py-1 text-xs outline-none focus:border-accent"
            />
            <button
              onClick={submitSearch}
              className="rounded-r-md border border-l-0 border-white/10 px-2 py-1 text-xs text-white/70 hover:bg-white/10"
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
              applied.favorite ? "border-amber-300/60 bg-amber-400/15 text-amber-100" : "border-white/15 text-white/60 hover:bg-white/10"
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
              selectMode ? "border-accent/70 bg-accent/20 text-white" : "border-white/15 text-white/60 hover:bg-white/10"
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
        <div className="flex items-center gap-2 rounded-md border border-white/10 bg-black/30 px-3 py-1.5 text-xs">
          <span className="text-white/60">{selected.size} selected</span>
          <button
            onClick={removeSelected}
            disabled={!selected.size}
            className="rounded border border-red-400/30 px-2 py-0.5 text-red-300 hover:bg-red-400/10 disabled:opacity-30"
          >
            Delete selected
          </button>
          <button
            onClick={exportSelected}
            disabled={!selected.size || exporting}
            className="rounded border border-white/15 px-2 py-0.5 text-white/65 hover:bg-white/10 disabled:opacity-30"
          >
            {exporting ? "Exporting..." : "Export ZIP"}
          </button>
          <button onClick={() => setSelected(new Set())} disabled={!selected.size} className="rounded border border-white/15 px-2 py-0.5 text-white/60 hover:bg-white/10 disabled:opacity-30">
            Clear
          </button>
        </div>
      )}

      {/* --- grid --- */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-white/30">
            {loading ? "loading…" : "no images match"}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
              {items.map((img) => {
                const isSel = selected.has(img.id);
                return (
                  <button
                    key={img.id}
                    onClick={() => (selectMode ? toggleSelected(img.id) : setOpenId(img.id))}
                    title={String(img.params?.prompt ?? "")}
                    className={`group relative aspect-square animate-fade-in overflow-hidden rounded-md border transition ${
                      isSel ? "border-accent ring-2 ring-accent/40" : "border-white/10 hover:border-white/30"
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
                        isSel ? "border-accent/80 bg-accent text-white" : "border-white/40 bg-black/40 text-transparent"
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
            {hasMore && (
              <div className="mt-3 flex justify-center">
                <button
                  onClick={loadMore}
                  disabled={loading}
                  className="rounded-md border border-white/15 px-4 py-1.5 text-xs text-white/70 hover:bg-white/10 disabled:opacity-40"
                >
                  {loading ? "loading…" : "Load more"}
                </button>
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
        />
      )}
    </div>
  );
}
