import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { toast } from "./Toast";
import { ZoomableImage } from "./ZoomableImage";
import type { ImageItem, Model } from "../types";

const FAMILY_LABELS: Record<string, string> = {
  flux: "FLUX",
  flux2: "FLUX.2",
  "qwen-image": "Qwen-Image",
  "z-image": "Z-Image",
  sdxl: "SDXL",
  upscaler: "Upscaler",
  unknown: "Unknown",
};

export function Chip({ children, onClear }: { children: ReactNode; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-white/70">
      {children}
      <button onClick={onClear} className="text-white/40 hover:text-white" title="remove filter">×</button>
    </span>
  );
}

export function DetailModal({
  image,
  models,
  onClose,
  onReproduce,
  onUpscale,
  onUpdate,
  onDelete,
}: {
  image: ImageItem;
  models: Model[];
  onClose: () => void;
  onReproduce: (image: ImageItem, opts: { keepSeed: boolean }) => void;
  onUpscale: (image: ImageItem, scale: 2 | 4) => void;
  onUpdate: (image: ImageItem) => void;
  onDelete: () => void;
}) {
  const params = image.params ?? {};
  const modelName = text(params.model);
  const knownModel = models.some((m) => m.job_type === "image" && m.name === modelName);
  const [tagsDraft, setTagsDraft] = useState((image.tags ?? []).join(", "));
  const [savingMeta, setSavingMeta] = useState(false);

  useEffect(() => {
    setTagsDraft((image.tags ?? []).join(", "));
  }, [image.id, image.tags]);

  const patchMeta = async (body: { favorite?: boolean; tags?: string[] }) => {
    setSavingMeta(true);
    try {
      const updated = await api.updateImage(image.id, body);
      onUpdate(updated);
      return updated;
    } catch {
      toast.error("Could not update image metadata");
      return null;
    } finally {
      setSavingMeta(false);
    }
  };

  const toggleFavorite = async () => {
    const updated = await patchMeta({ favorite: !image.favorite });
    if (updated) toast.success(updated.favorite ? "Added to favorites" : "Removed from favorites");
  };

  const saveTags = async () => {
    const updated = await patchMeta({ tags: parseTags(tagsDraft) });
    if (updated) toast.success("Tags saved");
  };

  const copyImage = async () => {
    try {
      const blob = await api.downloadUrlBlob(image.url);
      await navigator.clipboard.write([new ClipboardItem({ [blob.type || "image/png"]: blob })]);
      toast.success("Image copied");
    } catch {
      toast.error("Copy failed — browser blocked clipboard");
    }
  };

  const reveal = async () => {
    try {
      await api.revealImage(image.id);
      toast.success("Opened in file explorer");
    } catch {
      toast.error("Could not open explorer");
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex bg-black/85" onClick={onClose}>
      <div
        className="m-auto flex max-h-[92vh] w-[min(1100px,94vw)] gap-4 overflow-hidden rounded-lg border border-white/10 bg-surface p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
          <ZoomableImage src={image.url} className="h-[84vh] w-full rounded" />
        </div>
        <aside className="flex w-72 shrink-0 flex-col overflow-y-auto">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-semibold text-white/80">Details</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={toggleFavorite}
                disabled={savingMeta}
                className={`rounded border px-2 py-0.5 text-[11px] transition disabled:opacity-40 ${
                  image.favorite
                    ? "border-amber-300/50 bg-amber-400/15 text-amber-100"
                    : "border-white/15 text-white/45 hover:bg-white/10 hover:text-white/80"
                }`}
              >
                {image.favorite ? "Favorited" : "Favorite"}
              </button>
              <button onClick={onClose} className="text-white/40 hover:text-white">close</button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => onReproduce(image, { keepSeed: true })} className={primaryBtn} title={knownModel ? "" : "model not loaded — params applied, model unchanged"}>
              Edit in composer
            </button>
            <button onClick={() => onReproduce(image, { keepSeed: false })} className={actionBtn}>
              Variation
            </button>
            <button onClick={() => onUpscale(image, 2)} className={actionBtn}>
              Upscale 2x
            </button>
            <button onClick={() => onUpscale(image, 4)} className={actionBtn}>
              Upscale 4x
            </button>
          </div>

          <dl className="mt-3 space-y-2">
            <Meta label="Model" value={modelName} />
            <Meta label="Family" value={familyLabel(image.family)} />
            <Meta label="Seed" value={text(image.seed)} />
            <Meta label="Size" value={image.width && image.height ? `${image.width}x${image.height}` : ""} />
            <Meta label="Steps" value={text(params.steps)} />
            <Meta label="Guidance" value={text(params.guidance)} />
            <Meta label="LoRA" value={loraSummary(params.loras)} />
            <Meta label="Created" value={new Date(image.created_at).toLocaleString()} />
          </dl>

          <div className="mt-3">
            <div className="text-xs uppercase tracking-wide text-white/35">Tags</div>
            <div className="mt-1 flex min-h-6 flex-wrap gap-1">
              {(image.tags ?? []).length ? (
                image.tags.map((tag) => (
                  <span key={tag} className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-[11px] text-white/65">
                    {tag}
                  </span>
                ))
              ) : (
                <span className="text-xs text-white/30">-</span>
              )}
            </div>
            <div className="mt-2 flex gap-1.5">
              <input
                value={tagsDraft}
                onChange={(e) => setTagsDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void saveTags();
                }}
                placeholder="tag, another tag"
                className="min-w-0 flex-1 rounded border border-white/10 bg-black/30 px-2 py-1 text-xs outline-none focus:border-accent"
              />
              <button onClick={saveTags} disabled={savingMeta} className={`${actionBtn} disabled:opacity-40`}>
                Save
              </button>
            </div>
          </div>

          <div className="mt-3">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wide text-white/35">Prompt</div>
              <button
                onClick={() => navigator.clipboard?.writeText(text(params.prompt)).catch(() => {})}
                className="text-[11px] text-white/40 hover:text-white/80"
              >
                copy
              </button>
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-white/70">{text(params.prompt) || "-"}</p>
          </div>
          {text(params.negative) ? (
            <div className="mt-3">
              <div className="text-xs uppercase tracking-wide text-white/35">Negative</div>
              <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-white/55">{text(params.negative)}</p>
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-1.5">
            <button onClick={copyImage} className={actionBtn}>Copy</button>
            <button onClick={reveal} className={actionBtn}>Show in folder</button>
            <a href={image.url} download={`${image.id}.png`} className={actionBtn}>PNG</a>
            <a href={api.assetUrl(`/api/images/${image.id}/metadata`)} download className={actionBtn}>JSON</a>
            <button onClick={onDelete} className="rounded border border-red-400/25 px-2.5 py-1 text-xs text-red-300 hover:bg-red-400/10">
              Delete
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

const actionBtn = "rounded border border-white/15 px-2.5 py-1 text-xs hover:bg-white/10";
const primaryBtn = "rounded bg-accent px-2.5 py-1 text-xs font-medium text-white transition hover:bg-accent-hover";

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-white/35">{label}</dt>
      <dd className="mt-0.5 truncate text-white/70" title={value}>{value || "-"}</dd>
    </div>
  );
}

function text(value: unknown): string {
  if (value == null) return "";
  return String(value);
}

export function familyLabel(value: unknown): string {
  const key = text(value);
  return FAMILY_LABELS[key] ?? key;
}

function parseTags(value: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of value.split(/[,\n]/)) {
    const tag = raw.trim().replace(/\s+/g, " ").slice(0, 40);
    const key = tag.toLocaleLowerCase();
    if (!tag || seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
    if (out.length >= 32) break;
  }
  return out;
}

function loraSummary(value: unknown): string {
  if (!Array.isArray(value) || !value.length) return "";
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const name = "name" in item ? text(item.name) : "id" in item ? text(item.id) : "";
      const weight = "weight" in item ? text(item.weight) : "";
      return weight ? `${name || "LoRA"} @ ${weight}` : name;
    })
    .filter(Boolean)
    .join(", ");
}
