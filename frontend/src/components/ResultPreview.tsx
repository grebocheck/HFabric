import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ImageItem } from "../types";
import { ZoomableImage } from "./ZoomableImage";

const actionBtn = "rounded-md border border-white/15 px-2.5 py-1.5 text-xs text-white/70 transition hover:bg-white/10 hover:text-white";

export function ResultPreview({
  images,
  onOpenHistory,
  onReproduce,
  onUpscale,
  generating = false,
  hasImageModels = true,
  modelsLoading = false,
  onGetModels,
}: {
  images: ImageItem[];
  onOpenHistory: () => void;
  onReproduce?: (image: ImageItem, opts: { keepSeed: boolean }) => void;
  onUpscale?: (image: ImageItem, scale: 2 | 4) => void;
  generating?: boolean;
  hasImageModels?: boolean;
  modelsLoading?: boolean;
  onGetModels?: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState(false);
  const [note, setNote] = useState("");
  const noteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastLatest = useRef<string | null>(null);

  const selected = useMemo(
    () => images.find((img) => img.id === selectedId) ?? images[0] ?? null,
    [images, selectedId],
  );
  const index = useMemo(() => (selected ? images.findIndex((img) => img.id === selected.id) : -1), [images, selected]);
  const goPrev = useCallback(() => {
    if (index > 0) setSelectedId(images[index - 1].id);
  }, [index, images]);
  const goNext = useCallback(() => {
    if (index >= 0 && index < images.length - 1) setSelectedId(images[index + 1].id);
  }, [index, images]);

  useEffect(() => {
    const latest = images[0]?.id ?? null;
    if (latest && latest !== lastLatest.current) {
      lastLatest.current = latest;
      setSelectedId(latest);
    }
    if (selectedId && !images.some((img) => img.id === selectedId)) {
      setSelectedId(images[0]?.id ?? null);
    }
  }, [images, selectedId]);

  // Left/Right page through the batch (also drives the lightbox); Escape closes
  // the lightbox. Guarded so arrow keys in the composer's inputs/sliders keep
  // their normal behavior.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setLightbox(false); return; }
      if (images.length < 2) return;
      const el = document.activeElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); goPrev(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); goNext(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [images.length, goPrev, goNext]);

  const flash = useCallback((msg: string) => {
    setNote(msg);
    if (noteTimer.current) clearTimeout(noteTimer.current);
    noteTimer.current = setTimeout(() => setNote(""), 2200);
  }, []);

  const copyImage = async () => {
    if (!selected) return;
    try {
      const blob = await api.downloadUrlBlob(selected.url);
      await navigator.clipboard.write([new ClipboardItem({ [blob.type || "image/png"]: blob })]);
      flash("copied");
    } catch {
      flash("copy blocked");
    }
  };

  const reveal = async () => {
    if (!selected) return;
    try {
      await api.revealImage(selected.id);
      flash("opened folder");
    } catch {
      flash("could not open");
    }
  };

  const params = selected?.params ?? {};
  const facts = selected
    ? [
        selected.width && selected.height ? `${selected.width}x${selected.height}` : "",
        text(params.steps) ? `${text(params.steps)} steps` : "",
        text(params.guidance) ? `cfg ${text(params.guidance)}` : "",
        selected.seed == null || selected.seed === -1 ? "random seed" : `seed ${selected.seed}`,
      ].filter(Boolean)
    : [];

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-white/10 bg-surface max-[860px]:mb-4 max-[860px]:h-[720px]">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-3 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white/85">Result</h2>
          <p className="mt-0.5 truncate text-xs text-white/40">
            {selected ? text(params.prompt) || "Generated image" : "No image yet"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {note ? <span className="text-xs text-emerald-300/85">{note}</span> : null}
          <button onClick={onOpenHistory} className={actionBtn}>History</button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black/35">
        {generating ? <div className="skeleton absolute inset-x-0 top-0 z-10 h-0.5" /> : null}
        {selected ? (
          <button
            onClick={() => setLightbox(true)}
            className="group flex h-full w-full items-center justify-center p-4"
            title="Open detail view"
          >
            <img src={selected.url} alt="" className="max-h-full max-w-full object-contain shadow-2xl shadow-black/50" />
            <span className="absolute right-3 top-3 rounded-md border border-white/10 bg-black/60 px-2 py-1 text-[11px] text-white/65 opacity-0 transition group-hover:opacity-100">
              Detail
            </span>
          </button>
        ) : generating ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-8">
            <div className="skeleton h-40 w-40 rounded-lg" />
            <span className="text-xs text-white/40">generating…</span>
          </div>
        ) : !hasImageModels && !modelsLoading ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-8 text-center">
            <p className="text-sm text-white/50">No image models installed yet.</p>
            <p className="max-w-xs text-xs leading-5 text-white/35">
              Open the Models tab to fetch a starter model for your hardware, then come back here to generate.
            </p>
            {onGetModels ? (
              <button
                onClick={onGetModels}
                className="mt-1 rounded-md border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-medium text-accent-fg hover:bg-accent/25"
              >
                Open Model downloads
              </button>
            ) : null}
          </div>
        ) : (
          <div className="flex h-full w-full items-center justify-center p-8 text-sm text-white/30">
            Queue a generation to see the result here.
          </div>
        )}
      </div>

      <div className="border-t border-white/10 bg-black/20 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <button onClick={copyImage} disabled={!selected} className={`${actionBtn} disabled:opacity-30`}>Copy</button>
            <button onClick={() => setLightbox(true)} disabled={!selected} className={`${actionBtn} disabled:opacity-30`}>Detail</button>
            <button
              onClick={() => selected && onReproduce?.(selected, { keepSeed: true })}
              disabled={!selected || !onReproduce}
              className={`${actionBtn} disabled:opacity-30`}
            >
              Reproduce
            </button>
            <button
              onClick={() => selected && onReproduce?.(selected, { keepSeed: false })}
              disabled={!selected || !onReproduce}
              className={`${actionBtn} disabled:opacity-30`}
            >
              Vary
            </button>
            <button
              onClick={() => selected && onUpscale?.(selected, 2)}
              disabled={!selected || !onUpscale}
              className={`${actionBtn} disabled:opacity-30`}
            >
              Upscale 2x
            </button>
            <button
              onClick={() => selected && onUpscale?.(selected, 4)}
              disabled={!selected || !onUpscale}
              className={`${actionBtn} disabled:opacity-30`}
            >
              4x
            </button>
            <button onClick={reveal} disabled={!selected} className={`${actionBtn} disabled:opacity-30`}>Folder</button>
            {selected ? (
              <>
                <a href={selected.url} download={`${selected.id}.png`} className={actionBtn}>PNG</a>
                <a href={api.assetUrl(`/api/images/${selected.id}/metadata`)} download className={actionBtn}>JSON</a>
              </>
            ) : null}
          </div>
          <div className="min-w-0 truncate text-xs text-white/40">
            {facts.length ? facts.join(" / ") : "Waiting for output"}
          </div>
        </div>

        {images.length > 1 ? (
          <div className="mt-3 flex max-h-44 flex-wrap content-start gap-2 overflow-y-auto pb-1">
            {images.slice(0, 50).map((img) => (
              <button
                key={img.id}
                onClick={() => setSelectedId(img.id)}
                title={text(img.params?.prompt)}
                className={`relative h-[68px] w-[68px] shrink-0 overflow-hidden rounded-md border transition ${
                  selected?.id === img.id ? "border-accent/90" : "border-white/10 hover:border-white/35"
                }`}
              >
                <img src={img.thumb_url ?? img.url} alt="" loading="lazy" className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {lightbox && selected && (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center bg-black/90"
          onClick={() => setLightbox(false)}
        >
          <ZoomableImage key={selected.id} src={selected.url} className="h-[94vh] w-[96vw]" />
          {index > 0 && (
            <button
              onClick={(e) => { e.stopPropagation(); goPrev(); }}
              aria-label="Previous image"
              className="absolute left-4 top-1/2 z-10 grid h-12 w-12 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-black/55 text-3xl leading-none text-white/80 backdrop-blur transition hover:bg-black/80"
            >
              ‹
            </button>
          )}
          {index >= 0 && index < images.length - 1 && (
            <button
              onClick={(e) => { e.stopPropagation(); goNext(); }}
              aria-label="Next image"
              className="absolute right-4 top-1/2 z-10 grid h-12 w-12 -translate-y-1/2 place-items-center rounded-full border border-white/15 bg-black/55 text-3xl leading-none text-white/80 backdrop-blur transition hover:bg-black/80"
            >
              ›
            </button>
          )}
          {images.length > 1 && (
            <span className="absolute bottom-5 left-1/2 -translate-x-1/2 rounded-md border border-white/15 bg-black/60 px-2.5 py-1 text-xs text-white/70 backdrop-blur">
              {index + 1} / {images.length}
            </span>
          )}
          <button
            onClick={() => setLightbox(false)}
            className="absolute right-5 top-5 rounded-md border border-white/20 bg-black/60 px-3 py-1.5 text-sm hover:bg-white/10"
          >
            Close
          </button>
        </div>
      )}
    </section>
  );
}

function text(value: unknown): string {
  if (value == null) return "";
  return String(value);
}
