import { useMemo, useState } from "react";

import { api } from "../../api/client";
import type { VideoItem } from "../../types";
import { toast } from "../Toast";

type VideoMode = "t2v" | "i2v";

export function VideoHistory({ videos, onDeleted }: { videos: VideoItem[]; onDeleted: () => void }) {
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState("all");
  const [mode, setMode] = useState<VideoMode | "all">("all");
  const families = useMemo(
    () => Array.from(new Set(videos.map((video) => String(video.family || "unknown")))).sort(),
    [videos],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return videos.filter((video) => {
      if (family !== "all" && String(video.family || "unknown") !== family) return false;
      if (mode !== "all" && String(video.params.mode || "t2v") !== mode) return false;
      if (!needle) return true;
      const haystack = [
        video.family,
        video.params.prompt,
        video.params.model,
        `${video.width}x${video.height}`,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [family, mode, query, videos]);
  const filtersActive = Boolean(query.trim() || family !== "all" || mode !== "all");

  if (!videos.length) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-line text-sm text-ui-subtle">
        No generated videos yet
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_160px_150px_auto] gap-2 max-[760px]:grid-cols-1">
        <input
          aria-label="Search videos"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="ui-field rounded-md px-3 py-2 text-sm"
          placeholder="Search prompt, model or size"
        />
        <select
          aria-label="Video family filter"
          value={family}
          onChange={(event) => setFamily(event.target.value)}
          className="ui-field rounded-md px-3 py-2 text-sm"
        >
          <option value="all">All families</option>
          {families.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <select
          aria-label="Video mode filter"
          value={mode}
          onChange={(event) => setMode(event.target.value as VideoMode | "all")}
          className="ui-field rounded-md px-3 py-2 text-sm"
        >
          <option value="all">All modes</option>
          <option value="t2v">Text to video</option>
          <option value="i2v">Image to video</option>
        </select>
        <button
          onClick={() => {
            setQuery("");
            setFamily("all");
            setMode("all");
          }}
          disabled={!filtersActive}
          className="ui-button rounded-md px-3 py-2 text-sm disabled:opacity-40"
        >
          Clear
        </button>
      </div>
      <div className="shrink-0 text-xs text-ui-subtle">
        {filtered.length} / {videos.length} clips
      </div>
      {filtered.length ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((video) => (
            <article
              key={video.id}
              className="overflow-hidden rounded-lg border border-line bg-surface shadow-panel"
            >
              <video
                src={video.url}
                poster={video.poster_url ?? undefined}
                controls
                loop
                preload="metadata"
                className="aspect-video w-full bg-black object-contain"
              />
              <div className="space-y-2 p-3">
                <div className="line-clamp-2 text-sm text-ui-strong">
                  {String(video.params.prompt ?? "Untitled video")}
                </div>
                <div className="flex items-center justify-between text-xs text-ui-subtle">
                  <span>{video.family}</span>
                  <span>
                    {video.width}×{video.height} · {Number(video.duration_s ?? 0).toFixed(1)}s
                  </span>
                </div>
                <div className="flex justify-end">
                  <button
                    onClick={() =>
                      api
                        .deleteVideo(video.id)
                        .then(onDeleted)
                        .catch((error) => toast.error(String(error)))
                    }
                    className="text-xs text-error-fg hover:text-error"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-line text-sm text-ui-subtle">
          No videos match the current filters
        </div>
      )}
    </div>
  );
}
