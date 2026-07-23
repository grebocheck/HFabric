import { useEffect, useMemo, useRef, useState } from "react";

import type { VideoItem } from "../../types";
import { ResilientImage } from "../ResilientImage";

type VideoResultProps = {
  videos: VideoItem[];
  generating: boolean;
  onOpenHistory: () => void;
};

export function VideoResult({ videos, generating, onOpenHistory }: VideoResultProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const lastLatest = useRef<string | null>(null);
  const video = useMemo(
    () => videos.find((item) => item.id === selectedId) ?? videos[0] ?? null,
    [videos, selectedId],
  );

  useEffect(() => {
    const latest = videos[0]?.id ?? null;
    if (latest && latest !== lastLatest.current) {
      lastLatest.current = latest;
      setSelectedId(latest);
    } else if (selectedId && !videos.some((item) => item.id === selectedId)) {
      setSelectedId(videos[0]?.id ?? null);
    }
  }, [videos, selectedId]);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-ui-strong">Result</h2>
          <p className="mt-1 text-xs text-ui-subtle">MP4 · local generation · no audio</p>
        </div>
        <button onClick={onOpenHistory} className="text-xs text-accent-fg hover:text-accent">
          History
        </button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center bg-sunken p-4">
        {video ? (
          <div className="w-full max-w-5xl">
            <video
              key={video.id}
              aria-label="Generated video"
              src={video.url}
              poster={video.poster_url ?? undefined}
              controls
              loop
              playsInline
              className="max-h-[calc(100vh-18rem)] w-full rounded-lg bg-black shadow-popover"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ui-muted">
              <span className="line-clamp-1">{String(video.params.prompt ?? "Generated video")}</span>
              <span>
                {video.width}×{video.height} · {video.frames}f · {Number(video.duration_s ?? 0).toFixed(1)}s
              </span>
            </div>
          </div>
        ) : generating ? (
          <div className="text-center text-sm text-ui-muted">
            <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />
            Generating frames…
          </div>
        ) : (
          <div className="max-w-sm text-center text-sm leading-6 text-ui-subtle">
            Your newest clip will appear here. Start with a short 480p preset while tuning the prompt.
          </div>
        )}
      </div>
      {videos.length > 1 ? (
        <div className="border-t border-line bg-raised p-3">
          <div className="flex max-h-40 flex-wrap content-start gap-2 overflow-y-auto pb-1">
            {videos.slice(0, 50).map((item) => (
              <button
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                title={String(item.params?.prompt ?? "")}
                className={`group relative h-[68px] w-[120px] shrink-0 overflow-hidden rounded-md border transition ${
                  video?.id === item.id ? "border-accent/90" : "border-line hover:border-border-strong"
                }`}
              >
                {item.poster_url ? (
                  <ResilientImage
                    sources={[item.thumb_url, item.poster_url]}
                    alt=""
                    loading="lazy"
                    placeholder="clip"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-black text-[10px] text-ui-subtle">
                    clip
                  </div>
                )}
                <span className="pointer-events-none absolute inset-0 grid place-items-center">
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-black/55 text-[10px] text-white backdrop-blur">
                    ▶
                  </span>
                </span>
                <span className="pointer-events-none absolute bottom-0 right-0 rounded-tl bg-black/65 px-1 text-[10px] text-white/80">
                  {Number(item.duration_s ?? 0).toFixed(1)}s
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
