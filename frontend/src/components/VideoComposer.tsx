import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { Model } from "../types";
import { ModelPicker } from "./ModelPicker";
import { toast } from "./Toast";

export { VideoHistory } from "./video/VideoHistory";
export { VideoResult } from "./video/VideoResult";

import {
  CLIP_PRESETS,
  DEFAULT_PRESET,
  FAMILY_DEFAULT_PRESET,
  RESOLUTION_PRESETS,
  applyClipSettings,
  type VideoMode,
} from "./video/videoPresets";

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
  const [presetId, setPresetId] = useState(DEFAULT_PRESET.id);
  const [width, setWidth] = useState(DEFAULT_PRESET.width);
  const [height, setHeight] = useState(DEFAULT_PRESET.height);
  const [frames, setFrames] = useState(DEFAULT_PRESET.frames);
  const [fps, setFps] = useState(DEFAULT_PRESET.fps);
  const [steps, setSteps] = useState(DEFAULT_PRESET.steps);
  const [guidance, setGuidance] = useState(DEFAULT_PRESET.guidance);
  const [seed, setSeed] = useState(-1);
  const [source, setSource] = useState<{ token: string; url: string; name: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const setters = useMemo(() => ({ setWidth, setHeight, setFrames, setFps, setSteps, setGuidance }), []);

  const applyPreset = useCallback(
    (id: string) => {
      const preset = CLIP_PRESETS.find((item) => item.id === id);
      if (!preset) return;
      setPresetId(id);
      applyClipSettings(preset, setters);
    },
    [setters],
  );

  const applyFamilyDefaults = useCallback(
    (family?: string) => {
      const presetIdForFamily = family ? FAMILY_DEFAULT_PRESET[family] : undefined;
      if (presetIdForFamily) applyPreset(presetIdForFamily);
    },
    [applyPreset],
  );

  useEffect(() => {
    if (available.length && !available.some((model) => model.id === modelId)) {
      const preferred = available.find((model) => model.family === "ltx-video") ?? available[0];
      setModelId(preferred.id);
      applyFamilyDefaults(preferred.family);
    }
  }, [available, modelId, applyFamilyDefaults]);

  const selected = videoModels.find((model) => model.id === modelId);
  const framepackSelected = selected?.family === "hunyuan-video";
  const textOnlySelected = selected?.family === "cogvideo";
  const clipPresets = useMemo(() => {
    const family = selected?.family;
    return CLIP_PRESETS.filter((preset) => !family || preset.families.includes(family));
  }, [selected?.family]);
  const duration = frames / Math.max(1, fps);

  useEffect(() => {
    if (framepackSelected && mode !== "i2v") setMode("i2v");
    if (textOnlySelected && mode !== "t2v") setMode("t2v");
  }, [framepackSelected, mode, textOnlySelected]);

  const chooseModel = (id: string) => {
    setModelId(id);
    applyFamilyDefaults(videoModels.find((item) => item.id === id)?.family);
  };

  const markCustom =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setPresetId("custom");
      setter(value);
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
      await api.createJobs([
        {
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
        },
      ]);
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
        <p className="mt-2 max-w-xs text-sm text-ui-muted">
          Place a local LTX or Wan Diffusers repository in models/video, then rescan.
        </p>
        <button onClick={onGetModels} className="ui-button mt-4 rounded-md px-3 py-2 text-sm">
          Open Models
        </button>
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
          {(
            [
              ["t2v", "Text to video"],
              ["i2v", "Image to video"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => {
                if (framepackSelected && value === "t2v") return;
                if (textOnlySelected && value === "i2v") return;
                setMode(value);
              }}
              disabled={(framepackSelected && value === "t2v") || (textOnlySelected && value === "i2v")}
              className={`rounded-md px-2 py-1.5 text-xs font-medium ${mode === value ? "bg-accent text-ui-inverse" : "text-ui-muted hover:bg-control-hover"}`}
            >
              {label}
            </button>
          ))}
        </div>

        <Field label="Model">
          <ModelPicker
            models={videoModels}
            value={modelId}
            onChange={chooseModel}
            placeholder="select a video model"
          />
        </Field>

        {selected?.family === "wan-video" ? (
          <div className="rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
            Wan 2.2 is the quality tier. A clip can take several minutes on a single GPU.
          </div>
        ) : null}
        {framepackSelected ? (
          <div className="rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
            FramePack is image-to-video only. Use a first frame and start with the draft preset before longer
            clips.
          </div>
        ) : null}
        {textOnlySelected ? (
          <div className="rounded-md border border-info-border bg-info-bg px-3 py-2 text-xs leading-5 text-info-fg">
            CogVideoX fallback is text-to-video only. Use it for the light ROCm/MPS path and CUDA smoke
            checks.
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
                  <button onClick={() => setSource(null)} className="text-error-fg">
                    Remove
                  </button>
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
          <textarea
            value={negative}
            onChange={(event) => setNegative(event.target.value)}
            rows={2}
            className="ui-field w-full resize-y rounded-md px-3 py-2 text-sm"
          />
        </Field>

        <Field label="Clip preset">
          <select
            aria-label="Video clip preset"
            value={presetId}
            onChange={(event) => applyPreset(event.target.value)}
            className="ui-field w-full rounded-md px-3 py-2 text-sm"
          >
            {clipPresets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label} · {preset.width}×{preset.height} · {preset.frames}f · {preset.steps} steps
              </option>
            ))}
            {presetId === "custom" ? <option value="custom">Custom</option> : null}
          </select>
        </Field>

        <Field label="Resolution">
          <select
            aria-label="Video resolution"
            value={`${width}x${height}`}
            onChange={(event) => {
              const preset = RESOLUTION_PRESETS.find(
                (item) => `${item.width}x${item.height}` === event.target.value,
              );
              if (preset) {
                setPresetId("custom");
                setWidth(preset.width);
                setHeight(preset.height);
              }
            }}
            className="ui-field w-full rounded-md px-3 py-2 text-sm"
          >
            {RESOLUTION_PRESETS.map((preset) => (
              <option key={preset.label} value={`${preset.width}x${preset.height}`}>
                {preset.label} · {preset.width}×{preset.height}
              </option>
            ))}
            {!RESOLUTION_PRESETS.some((preset) => preset.width === width && preset.height === height) ? (
              <option value={`${width}x${height}`}>
                {width}×{height}
              </option>
            ) : null}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <NumberField
            label="Frames"
            value={frames}
            min={9}
            max={161}
            step={4}
            onChange={markCustom(setFrames)}
          />
          <NumberField label="FPS" value={fps} min={4} max={30} onChange={markCustom(setFps)} />
          <NumberField label="Steps" value={steps} min={1} max={80} onChange={markCustom(setSteps)} />
          <NumberField
            label="Guidance"
            value={guidance}
            min={0}
            max={20}
            step={0.5}
            onChange={markCustom(setGuidance)}
          />
        </div>
        <div className="flex items-center justify-between rounded-md border border-line bg-control px-3 py-2 text-xs text-ui-muted">
          <span>
            {frames} frames · {fps} fps
          </span>
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-ui-muted">{label}</span>
      {children}
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        aria-label={label}
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="ui-field w-full rounded-md px-3 py-2 text-sm"
      />
    </Field>
  );
}
