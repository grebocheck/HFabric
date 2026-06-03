import type { ImageItem } from "../types";

export function Gallery({ images }: { images: ImageItem[] }) {
  return (
    <div className="flex h-full flex-col">
      <h2 className="px-1 pb-2 text-sm font-semibold text-white/70">Gallery</h2>
      <div className="flex-1 overflow-y-auto pr-1">
        {images.length === 0 && <div className="px-1 text-sm text-white/30">no images yet</div>}
        <div className="grid grid-cols-2 gap-2">
          {images.map((img) => (
            <a
              key={img.id}
              href={img.url}
              target="_blank"
              rel="noreferrer"
              className="group relative overflow-hidden rounded-md border border-white/10"
              title={String(img.params?.prompt ?? "")}
            >
              <img
                src={img.thumb_url ?? img.url}
                alt=""
                loading="lazy"
                className="aspect-square w-full object-cover transition group-hover:scale-105"
              />
              <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] text-white/80">
                seed {img.seed ?? "?"}
              </span>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
