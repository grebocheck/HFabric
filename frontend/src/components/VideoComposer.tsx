import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { Model, VideoItem } from "../types";
import { ModelPicker } from "./ModelPicker";
import { toast } from "./Toast";

type VideoMode = "t2v" | "i2v";

const PRESETS = [
  { label: "480p landscape", width: 832, height: 480 },
  { label: "480p portrait", width: 480, height: 832 },
  { label: "720p landscape", width: 1280, height: 704 },
  { label: "720p portrait", width: 704, height: 1280 },
];

export function VideoComposer({
  models,
  modelsLoading,
  onQueued,
  onGetModels,
}: {
  models: Model[];
  modelsLoading: boolean;
  onQueued: () => void;
  onGetModels: () => void;
}) {
  const videoModels = useMemo(() => models.filter((model) => model.job_type === "video"), [models]);
  const available = useMemo(() => videoModels.filter((model) => model.available !== false), [videoModels]);
  const [modelId, setModelId] = useState("");
  const [mode, setMode] = useState<VideoMode>("t2v");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [width, setWidth] = useState(832);
  const [height, setHeight] = useState(480);
  const [frames, setFrames] = useState(49);
  const [fps, setFps] = useState(16);
  const [steps, setSteps] = useState(25);
  const [guidance, setGuidance] = useState(4);
  const [seed, setSeed] = useState(-1);
  const [source, setSource] = useState<{ token: string; url: string; name: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (available.length && !available.some((model) => model.id === modelId)) {
      const preferred = available.find((model) => model.family === "ltx-video") ?? available[0];
      setModelId(preferred.id);
    }
  }, [available, modelId]);

  const selected = videoModels.find((model) => model.id === modelId);
  const duration = frames / Math.max(1, fps);

  const chooseModel = (id: string) => {
    setModelId(id);
    const model = videoModels.find((item) => item.id === id);
    if (model?.family === "ltx-video") {
      setWidth(704); setHeight(512); setFrames(49); setFps(16); setSteps(25); setGuidance(3);
    } else if (model?.family === "wan-video") {
      setWidth(832); setHeight(480); setFrames(49); setFps(16); setSteps(30); setGuidance(5);
    }
  };

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const result = await api.uploadInitImage(file);
      setSource({ token: result.init_image, url: result.url, name: file.name });
      setMode("i2v");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not upload source image");
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (!modelId || !prompt.trim() || (mode === "i2v" && !source)) return;
    setSubmitting(true);
    try {
      await api.createJobs([{
        type: "video",
        model_id: modelId,
        params: {
          prompt: prompt.trim(),
          negative: negative.trim(),
          mode,
          width,
          height,
          frames,
          fps,
          steps,
          guidance,
          seed,
          ...(mode === "i2v" && source ? { init_image: source.token } : {}),
        },
      }]);
      onQueued();
      toast.success("Video queued");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not queue video");
    } finally {
      setSubmitting(false);
    }
  };

  if (!modelsLoading && videoModels.length === 0) {
    return (
      <section className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface p-6 text-center">
        <div className="text-base font-semibold text-ui-strong">No video models found</div>
        <p className="mt-2 max-w-xs text-sm text-ui-muted">Place a local LTX or Wan Diffusers repository in models/video, then rescan.</p>
        <button onClick={onGetModels} className="ui-button mt-4 rounded-md px-3 py-2 text-sm">Open Models</button>
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold text-ui-strong">Video composer</h2>
        <p className="mt-1 text-xs text-ui-subtle">Local text-to-video and image-to-video</p>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-control p-1">
          {([ ["t2v", "Text to video"], ["i2v", "Image to video"] ] as const).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setMode(value)}
              className={`rounded-md px-2 py-1.5 text-xs font-medium ${mode === value ? "bg-accent text-ui-inverse" : "text-ui-muted hover:bg-control-hover"}`}
            >
              {label}
            </button>
          ))}
        </div>

        <Field label="Model">
          <ModelPicker models={videoModels} value={modelId} onChange={chooseModel} placeholder="select a video model" />
        </Field>

        {selected?.family === "wan-video" ? (
          <div className="rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
            Wan 2.2 is the quality tier. A clip can take several minutes on a single GPU.
          </div>
        ) : null}

        {mode === "i2v" ? (
          <Field label="Source frame">
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.currentTarget.value = "";
              }}
            />
            {source ? (
              <div className="relative overflow-hidden rounded-md border border-line bg-control">
                <img src={source.url} alt="Video source" className="h-32 w-full object-cover" />
                <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-ui-muted">
                  <span className="truncate">{source.name}</span>
                  <button onClick={() => setSource(null)} className="text-error-fg">Remove</button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="ui-button w-full rounded-md border-dashed px-3 py-5 text-sm disabled:opacity-50"
              >
                {uploading ? "Uploading…" : "Choose the first frame"}
              </button>
            )}
          </Field>
        ) : null}

        <Field label="Prompt">
          <textarea
            aria-label="Video prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={5}
            className="ui-field w-full resize-y rounded-md px-3 py-2 text-sm"
            placeholder="Describe motion, camera, subject and lighting…"
          />
        </Field>
        <Field label="Negative prompt">
          <textarea value={negative} onChange={(event) => setNegative(event.target.value)} rows={2} className="ui-field w-full resize-y rounded-md px-3 py-2 text-sm" />
        </Field>

        <Field label="Resolution">
          <select
            aria-label="Video resolution"
            value={`${width}x${height}`}
            onChange={(event) => {
              const preset = PRESETS.find((item) => `${item.width}x${item.height}` === event.target.value);
              if (preset) { setWidth(preset.width); setHeight(preset.height); }
            }}
            className="ui-field w-full rounded-md px-3 py-2 text-sm"
          >
            {PRESETS.map((preset) => <option key={preset.label} value={`${preset.width}x${preset.height}`}>{preset.label} · {preset.width}×{preset.height}</option>)}
            {!PRESETS.some((preset) => preset.width === width && preset.height === height) ? <option value={`${width}x${height}`}>{width}×{height}</option> : null}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <NumberField label="Frames" value={frames} min={9} max={161} step={4} onChange={setFrames} />
          <NumberField label="FPS" value={fps} min={4} max={30} onChange={setFps} />
          <NumberField label="Steps" value={steps} min={1} max={80} onChange={setSteps} />
          <NumberField label="Guidance" value={guidance} min={0} max={20} step={0.5} onChange={setGuidance} />
        </div>
        <div className="flex items-center justify-between rounded-md border border-line bg-control px-3 py-2 text-xs text-ui-muted">
          <span>{frames} frames · {fps} fps</span>
          <span>~{duration.toFixed(1)} s</span>
        </div>
        <NumberField label="Seed (-1 = random)" value={seed} min={-1} max={2147483647} onChange={setSeed} />
      </div>
      <div className="border-t border-line p-3">
        <button
          onClick={() => void submit()}
          disabled={submitting || !modelId || !prompt.trim() || (mode === "i2v" && !source)}
          className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-ui-inverse hover:bg-accent-hover disabled:opacity-40"
        >
          {submitting ? "Queueing…" : "Generate video"}
        </button>
      </div>
    </section>
  );
}

export function VideoResult({
  videos,
  generating,
  onOpenHistory,
}: {
  videos: VideoItem[];
  generating: boolean;
  onOpenHistory: () => void;
}) {
  const video = videos[0];
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-ui-strong">Result</h2>
          <p className="mt-1 text-xs text-ui-subtle">MP4 · local generation · no audio</p>
        </div>
        <button onClick={onOpenHistory} className="text-xs text-accent-fg hover:text-accent">History</button>
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
              className="max-h-[calc(100vh-15rem)] w-full rounded-lg bg-black shadow-popover"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ui-muted">
              <span className="line-clamp-1">{String(video.params.prompt ?? "Generated video")}</span>
              <span>{video.width}×{video.height} · {video.frames}f · {Number(video.duration_s ?? 0).toFixed(1)}s</span>
            </div>
          </div>
        ) : generating ? (
          <div className="text-center text-sm text-ui-muted"><div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />Generating frames…</div>
        ) : (
          <div className="max-w-sm text-center text-sm leading-6 text-ui-subtle">Your newest clip will appear here. Start with a short 480p preset while tuning the prompt.</div>
        )}
      </div>
    </section>
  );
}

export function VideoHistory({ videos, onDeleted }: { videos: VideoItem[]; onDeleted: () => void }) {
  if (!videos.length) {
    return <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-line text-sm text-ui-subtle">No generated videos yet</div>;
  }
  return (
    <div className="grid h-full grid-cols-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
      {videos.map((video) => (
        <article key={video.id} className="overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
          <video src={video.url} poster={video.poster_url ?? undefined} controls loop preload="metadata" className="aspect-video w-full bg-black object-contain" />
          <div className="space-y-2 p-3">
            <div className="line-clamp-2 text-sm text-ui-strong">{String(video.params.prompt ?? "Untitled video")}</div>
            <div className="flex items-center justify-between text-xs text-ui-subtle">
              <span>{video.family}</span>
              <span>{video.width}×{video.height} · {Number(video.duration_s ?? 0).toFixed(1)}s</span>
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => api.deleteVideo(video.id).then(onDeleted).catch((error) => toast.error(String(error)))}
                className="text-xs text-error-fg hover:text-error"
              >
                Delete
              </button>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-xs font-medium text-ui-muted">{label}</span>{children}</label>;
}

function NumberField({ label, value, min, max, step = 1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (value: number) => void }) {
  return (
    <Field label={label}>
      <input type="number" aria-label={label} value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} className="ui-field w-full rounded-md px-3 py-2 text-sm" />
    </Field>
  );
}
