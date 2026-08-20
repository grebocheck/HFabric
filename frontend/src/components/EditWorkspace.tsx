import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { EditApply, ImageItem, Job, Lora, Model, Preset } from "../types";
import { ImageParamForm, LoraCard, Notice } from "./ImageComposerParts";
import { MaskEditor } from "./MaskEditor";
import { ModelPicker } from "./ModelPicker";
import { PromptLibrary } from "./PromptLibrary";
import { Select } from "./Select";
import { Slider } from "./Slider";
import { toast } from "./Toast";
import { Toggle } from "./Toggle";
import { ZoomableImage } from "./ZoomableImage";
import {
  imageDimensionGrid,
  imageFamilyDefaults,
  isLoraCompatible,
  parseLoraSelections,
} from "./imageComposerHelpers";
import {
  buildEditJobParams,
  DEFAULT_EDIT_DRAFT,
  editDraftPatchFromParams,
  EDIT_MODE_LABELS,
  round64,
  supportsEditMode,
  type EditDraft,
  type EditMode,
} from "./editWorkspaceHelpers";
import { useImageDefaultSettings } from "./useImageDefaultSettings";

type Source = { token: string; url: string; width: number; height: number };
type ViewMode = "source" | "result" | "compare";

const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-sm";
const label = "text-[10px] font-medium uppercase tracking-wide text-ui-subtle";
const section = "border-b border-border p-3 last:border-b-0";
const ratios = [
  { label: "1:1", w: 1, h: 1 },
  { label: "3:4", w: 3, h: 4 },
  { label: "4:3", w: 4, h: 3 },
  { label: "16:9", w: 16, h: 9 },
  { label: "9:16", w: 9, h: 16 },
];

export function EditWorkspace({
  models,
  modelsLoading = false,
  loras,
  lorasLoading = false,
  presets,
  presetsLoading = false,
  jobs,
  images,
  apply,
  onQueued,
  onGetModels,
}: {
  models: Model[];
  modelsLoading?: boolean;
  loras: Lora[];
  lorasLoading?: boolean;
  presets: Preset[];
  presetsLoading?: boolean;
  jobs: Job[];
  images: ImageItem[];
  apply?: EditApply | null;
  onQueued: () => void;
  onGetModels: () => void;
}) {
  const [draft, setDraft] = useState<EditDraft>(DEFAULT_EDIT_DRAFT);
  const [modelId, setModelId] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [maskDraft, setMaskDraft] = useState<File | null>(null);
  const [presetId, setPresetId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [queuedJobId, setQueuedJobId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("source");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const appliedNonce = useRef<number | null>(null);
  const skipModelDefaults = useRef(false);
  const imageDefaults = useImageDefaultSettings();
  const patchDraft = useCallback((patch: Partial<EditDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
  }, []);
  const setDraftField = useCallback(<K extends keyof EditDraft,>(key: K, value: EditDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  }, []);
  const {
    mode,
    prompt,
    negative,
    steps,
    guidance,
    width,
    height,
    seed,
    batch,
    strength,
    resizeMode,
    maskBlur,
    maskGrow,
    maskInvert,
    paddingCrop,
    outpaint,
    controlType,
    controlScale,
    controlMask,
    selectedLoras,
  } = draft;

  const eligibleModels = useMemo(
    () => models.filter((model) => supportsEditMode(model, mode)).sort((a, b) => a.name.localeCompare(b.name)),
    [mode, models],
  );
  const selectedModel = eligibleModels.find((model) => model.id === modelId);
  const family = selectedModel?.family;
  const compatibleLoras = loras.filter((lora) => isLoraCompatible(lora, selectedModel));
  const imagePresets = presets.filter((preset) => preset.type === "image");
  const queuedJob = jobs.find((job) => job.id === queuedJobId);
  const resultId = Array.isArray(queuedJob?.result?.image_ids) ? String(queuedJob.result.image_ids[0] ?? "") : "";
  const result = images.find((image) => image.id === resultId) ?? null;
  const activeRatio = ratios.find((ratio) => Math.abs(width / height - ratio.w / ratio.h) < 0.02)?.label ?? "custom";

  useEffect(() => {
    if (!selectedModel) setModelId(eligibleModels[0]?.id ?? "");
  }, [eligibleModels, selectedModel]);

  useEffect(() => {
    if (!selectedModel) return;
    if (skipModelDefaults.current) {
      skipModelDefaults.current = false;
      return;
    }
    const defaults = imageFamilyDefaults(family, selectedModel, imageDefaults);
    const next: Partial<EditDraft> = {};
    if (defaults) {
      next.steps = defaults.steps;
      next.guidance = defaults.guidance;
      if (!source) {
        next.width = defaults.width;
        next.height = defaults.height;
      }
    }
    if (family === "qwen-image") next.strength = 0.6;
    if (family === "z-image") next.strength = 0.45;
    if (family === "anima") next.strength = 0.55;
    patchDraft(next);
  }, [family, imageDefaults, patchDraft, selectedModel, source]);

  useEffect(() => {
    if (!presetsLoading && presetId && !imagePresets.some((preset) => preset.id === presetId)) {
      setPresetId("");
    }
  }, [imagePresets, presetId, presetsLoading]);

  useEffect(() => {
    if (mode !== "outpaint" || !source) return;
    patchDraft({
      width: round64(source.width + outpaint.left + outpaint.right),
      height: round64(source.height + outpaint.top + outpaint.bottom),
    });
  }, [mode, outpaint, patchDraft, source]);

  const uploadSource = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const uploaded = await api.uploadInitImage(file);
      setSource({
        token: uploaded.init_image,
        url: uploaded.url,
        width: uploaded.width,
        height: uploaded.height,
      });
      patchDraft({ width: round64(uploaded.width), height: round64(uploaded.height) });
      setMaskDraft(null);
      setQueuedJobId(null);
      setViewMode("source");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Source upload failed");
    } finally {
      setUploading(false);
    }
  }, [patchDraft]);

  useEffect(() => {
    if (!apply || apply.nonce === appliedNonce.current) return;
    appliedNonce.current = apply.nonce;
    const params = apply.params;
    const target = apply.model_id ? models.find((model) => model.id === apply.model_id) : undefined;
    const restored = editDraftPatchFromParams(
      params,
      { width: apply.width ?? 1024, height: apply.height ?? 1024 },
      target?.family,
    );
    skipModelDefaults.current = true;
    patchDraft(restored);
    if (target && restored.mode && supportsEditMode(target, restored.mode)) setModelId(target.id);
    if (apply.source_url) {
      void api.downloadUrlBlob(apply.source_url)
        .then((blob) => uploadSource(new File([blob], `${apply.image_id ?? "history"}.png`, { type: blob.type || "image/png" })))
        .catch(() => toast.error("Could not load the history image into Edit"));
    }
  }, [apply, models, patchDraft, uploadSource]);

  useEffect(() => {
    if (result) setViewMode("result");
  }, [result]);

  const onMaskChange = useCallback((file: File | null) => setMaskDraft(file), []);

  const queue = async () => {
    if (!source || !selectedModel || !prompt.trim()) return;
    if ((mode === "inpaint" || (mode === "controlnet" && controlMask)) && !maskDraft) {
      toast.error("Paint a mask before queuing an inpaint");
      return;
    }
    setQueueing(true);
    try {
      let maskToken: string | undefined;
      if ((mode === "inpaint" || (mode === "controlnet" && controlMask)) && maskDraft) {
        maskToken = (await api.uploadMaskImage(maskDraft)).mask_image;
      }
      const params = buildEditJobParams(draft, {
        sourceToken: source.token,
        maskToken,
        family,
      });
      const created = await api.createJobs([{ type: "image", model_id: selectedModel.id, params }]);
      setQueuedJobId(created[0]?.id ?? null);
      onQueued();
      toast.success(`Queued ${EDIT_MODE_LABELS[mode].toLowerCase()} edit`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not queue edit");
    } finally {
      setQueueing(false);
    }
  };

  const applyPreset = () => {
    if (modelsLoading || lorasLoading || presetsLoading) return;
    const preset = imagePresets.find((item) => item.id === presetId);
    if (!preset) return;
    const targetId = typeof preset.params.model_id === "string" ? preset.params.model_id : "";
    const target = targetId ? models.find((model) => model.id === targetId) : undefined;
    if (targetId && (!target || !supportsEditMode(target, mode))) {
      toast.error("The model saved in this preset is unavailable for the current edit mode");
      return;
    }
    const parsedLoras = parseLoraSelections(preset.params.loras, loras, target ?? selectedModel);
    const restored = editDraftPatchFromParams({
      ...preset.params,
      edit_mode: mode,
      prompt: typeof preset.params.prompt === "string" ? preset.params.prompt : prompt,
    }, { width, height }, target?.family ?? family);
    patchDraft({
      ...restored,
      selectedLoras: parsedLoras,
    });
    if (target) {
      skipModelDefaults.current = true;
      setModelId(target.id);
    }
    if (Array.isArray(preset.params.loras) && parsedLoras.length < preset.params.loras.length) {
      toast.error("Some LoRAs in this preset are missing or incompatible and were skipped");
    }
  };

  const applyRatio = (rw: number, rh: number) => {
    setPresetId("");
    const base = Math.max(width, height, 512);
    const grid = imageDimensionGrid(family);
    const snap = (value: number) => Math.max(256, Math.round(value / grid) * grid);
    if (rw >= rh) {
      patchDraft({ width: snap(base), height: snap((base * rh) / rw) });
    } else {
      patchDraft({ height: snap(base), width: snap((base * rw) / rh) });
    }
  };

  const toggleLora = (lora: Lora, enabled: boolean) => {
    setPresetId("");
    setDraft((current) => ({
      ...current,
      selectedLoras: enabled
        ? [...current.selectedLoras.filter((item) => item.id !== lora.id), { id: lora.id, weight: 1 }]
        : current.selectedLoras.filter((item) => item.id !== lora.id),
    }));
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_minmax(0,1fr)] gap-4 max-[980px]:block max-[980px]:overflow-y-auto">
      <aside className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-panel shadow-panel max-[980px]:mb-4">
        <div className="border-b border-border p-3">
          <h2 className="text-sm font-semibold text-ui-strong">Edit image</h2>
          <p className="mt-0.5 text-xs text-ui-subtle">One resident model · full-resolution source and mask</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <section className={section}>
            <div className={label}>Mode</div>
            <div className="mt-1.5 grid grid-cols-2 gap-1.5">
              {(Object.keys(EDIT_MODE_LABELS) as EditMode[]).map((item) => (
                <button
                  key={item}
                  onClick={() => { setDraftField("mode", item); setPresetId(""); }}
                  className={`h-8 rounded-md border text-xs transition ${mode === item ? "border-accent bg-accent/15 text-accent-fg" : "border-border-strong text-ui-muted hover:bg-control-hover"}`}
                >
                  {EDIT_MODE_LABELS[item]}
                </button>
              ))}
            </div>
          </section>

          <section className={section}>
            <div className={label}>Model</div>
            <div className="mt-1.5">
              {eligibleModels.length ? (
                <ModelPicker models={eligibleModels} value={modelId} onChange={(value) => { setModelId(value); setPresetId(""); }} />
              ) : (
                <div className="rounded-md border border-warn-border bg-warn-bg p-2 text-xs text-warn-fg">
                  {modelsLoading ? "Loading models..." : "No installed model supports this mode."}
                  {!modelsLoading ? <button onClick={onGetModels} className="ml-2 underline">Get models</button> : null}
                </div>
              )}
            </div>
            {family === "flux2" && mode === "img2img" ? (
              <Notice tone="sky">FLUX.2 uses the source as a reference; denoise strength does not apply.</Notice>
            ) : null}
            {mode === "instruction" ? (
              <Notice tone="sky">Instruction models use separate weights and swap through the arbiter.</Notice>
            ) : null}
          </section>

          <section className={section}>
            <div className="flex items-center justify-between">
              <div className={label}>Source</div>
              {source ? <button onClick={() => setSource(null)} className="text-xs text-ui-subtle hover:text-ui">clear</button> : null}
            </div>
            <label className={`mt-1.5 flex min-h-16 cursor-pointer items-center justify-center rounded-md border border-dashed border-border-strong px-3 text-center text-xs text-ui-subtle hover:bg-control-hover ${uploading ? "pointer-events-none opacity-50" : ""}`}>
              {source ? `${source.width}×${source.height} loaded` : uploading ? "uploading..." : "Drop or choose an image"}
              <input type="file" accept="image/*" className="hidden" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadSource(file);
                event.target.value = "";
              }} />
            </label>
          </section>

          <section className={section}>
            <div className="flex items-center justify-between">
              <div className={label}>Instruction / prompt</div>
              <button onClick={() => setLibraryOpen(true)} className="ui-button ui-button-compact rounded-md">Library</button>
            </div>
            <textarea value={prompt} onChange={(event) => { setDraftField("prompt", event.target.value); setPresetId(""); }} rows={5} className={`${field} mt-1.5 resize-y`} placeholder="Describe what should change..." />
            <input value={negative} onChange={(event) => { setDraftField("negative", event.target.value); setPresetId(""); }} className={`${field} mt-2`} placeholder="Negative prompt (optional)" />
            <PromptLibrary open={libraryOpen} onClose={() => setLibraryOpen(false)} currentPrompt={prompt} currentNegative={negative} onApply={(body, neg) => {
              patchDraft({
                prompt: prompt.trim() ? `${prompt.trim()}, ${body}` : body,
                ...(neg ? { negative: negative.trim() ? `${negative.trim()}, ${neg}` : neg } : {}),
              });
              setPresetId("");
            }} />
          </section>

          {mode !== "instruction" && family !== "flux2" ? (
            <section className={section}>
              <div className="flex items-center justify-between text-xs text-ui-subtle"><span>Strength</span><span className="font-mono">{strength.toFixed(2)}</span></div>
              <Slider value={strength} min={0.05} max={1} step={0.05} onChange={(value) => setDraftField("strength", value)} />
              <div className="mt-2"><Select ariaLabel="Resize mode" value={resizeMode} onChange={(value) => setDraftField("resizeMode", value)} options={[{ value: "crop", label: "Crop to fit" }, { value: "pad", label: "Pad to fit" }, { value: "stretch", label: "Stretch" }]} /></div>
            </section>
          ) : null}

          {(mode === "inpaint" || mode === "outpaint" || (mode === "controlnet" && controlMask)) ? (
            <section className={section}>
              <div className={label}>Mask quality</div>
              <div className="mt-1.5 grid grid-cols-2 gap-2">
                <Num label="Grow / shrink" value={maskGrow} set={(value) => setDraftField("maskGrow", value)} />
                <Num label="Blur" value={maskBlur} set={(value) => setDraftField("maskBlur", value)} />
                <Num label="Crop padding" value={paddingCrop} set={(value) => setDraftField("paddingCrop", value)} />
                <div className="flex items-end gap-2 pb-1 text-xs text-ui-muted"><Toggle checked={maskInvert} onChange={(value) => setDraftField("maskInvert", value)} ariaLabel="Invert mask" />Invert</div>
              </div>
            </section>
          ) : null}

          {mode === "outpaint" ? (
            <section className={section}>
              <div className={label}>Extend canvas</div>
              <div className="mt-1.5 grid grid-cols-2 gap-2">
                {(["left", "right", "top", "bottom"] as const).map((side) => <Num key={side} label={side} value={outpaint[side]} set={(value) => setDraft((current) => ({ ...current, outpaint: { ...current.outpaint, [side]: Math.max(0, value) } }))} step={64} />)}
              </div>
            </section>
          ) : null}

          {mode === "controlnet" ? (
            <section className={section}>
              <div className={label}>ControlNet</div>
              <div className="mt-1.5"><Select ariaLabel="ControlNet type" value={controlType} onChange={(value) => setDraftField("controlType", value)} options={["canny", "depth", "pose", "scribble", "union-canny", "union-depth", "union-pose", "union-scribble"].map((value) => ({ value, label: value }))} /></div>
              <div className="mt-2 flex items-center gap-2 text-xs text-ui-muted"><Toggle checked={controlMask} onChange={(enabled) => { setDraftField("controlMask", enabled); if (!enabled) setMaskDraft(null); }} ariaLabel="Use an inpaint mask with ControlNet" />Use inpaint mask</div>
              <div className="mt-2 flex items-center justify-between text-xs text-ui-subtle"><span>Scale</span><span>{controlScale.toFixed(2)}</span></div>
              <Slider value={controlScale} min={0} max={2} step={0.05} onChange={(value) => setDraftField("controlScale", value)} />
            </section>
          ) : null}

          <ImageParamForm activeRatio={activeRatio} batch={batch} dimensionGrid={imageDimensionGrid(selectedModel?.family)} guidance={guidance} height={height} labelClass={label} onApplyRatio={applyRatio} ratios={ratios} sectionClass={section} seed={seed} setBatch={(value) => { setDraftField("batch", value); setPresetId(""); }} setGuidance={(value) => { setDraftField("guidance", value); setPresetId(""); }} setHeight={(value) => { setDraftField("height", value); setPresetId(""); }} setSeed={(value) => { setDraftField("seed", value); setPresetId(""); }} setSteps={(value) => { setDraftField("steps", value); setPresetId(""); }} setWidth={(value) => { setDraftField("width", value); setPresetId(""); }} steps={steps} width={width} />

          {compatibleLoras.length ? (
            <section className={section}>
              <div className={label}>LoRA</div>
              <div className="mt-1.5 space-y-2">{compatibleLoras.map((lora) => {
                const selected = selectedLoras.find((item) => item.id === lora.id);
                return <LoraCard key={lora.id} lora={lora} selected={selected} onToggle={(enabled) => toggleLora(lora, enabled)} onWeight={(weight) => { setDraft((current) => ({ ...current, selectedLoras: current.selectedLoras.map((item) => item.id === lora.id ? { ...item, weight } : item) })); setPresetId(""); }} />;
              })}</div>
            </section>
          ) : null}

          <section className={section}>
            <div className={label}>Preset</div>
            <div className="mt-1.5 flex gap-2"><div className="min-w-0 flex-1"><Select ariaLabel="Edit preset" value={presetId} onChange={setPresetId} options={[{ value: "", label: "unsaved" }, ...imagePresets.map((preset) => ({ value: preset.id, label: preset.name }))]} /></div><button onClick={applyPreset} disabled={!presetId || modelsLoading || lorasLoading || presetsLoading} className="ui-button rounded-md px-3 text-xs">Apply</button></div>
          </section>
        </div>
        <div className="border-t border-border bg-raised p-3">
          <button onClick={() => void queue()} disabled={!source || !selectedModel || !prompt.trim() || queueing} className="ui-button-primary h-10 w-full rounded-md text-sm font-semibold disabled:opacity-40">
            {queueing ? "Queuing..." : `Queue ${EDIT_MODE_LABELS[mode]}`}
          </button>
        </div>
      </aside>

      <main className="flex min-h-[620px] min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-panel shadow-panel">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div><h2 className="text-sm font-semibold text-ui-strong">Source ⇆ result</h2><p className="text-xs text-ui-subtle">Paint and inspect at the source resolution</p></div>
          <div className="flex gap-1 rounded-md border border-border bg-control p-1">
            {(["source", "result", "compare"] as ViewMode[]).map((item) => <button key={item} disabled={item !== "source" && !result} onClick={() => setViewMode(item)} className={`rounded px-2.5 py-1 text-xs capitalize disabled:opacity-30 ${viewMode === item ? "bg-accent text-ui-inverse" : "text-ui-muted hover:bg-control-hover"}`}>{item}</button>)}
          </div>
        </div>
        <div className="ui-stage min-h-0 flex-1 p-4">
          {!source ? <DropHero uploading={uploading} onFile={(file) => void uploadSource(file)} /> : (mode === "inpaint" || (mode === "controlnet" && controlMask)) && viewMode === "source" ? (
            <MaskEditor src={source.url} onMaskChange={onMaskChange} large onFeatherChange={(value) => setDraftField("maskBlur", value)} />
          ) : viewMode === "compare" && result ? (
            <ComparePane before={source.url} after={result.url} />
          ) : (
            <ZoomableImage src={viewMode === "result" && result ? result.url : source.url} className="h-full min-h-[560px] w-full rounded-md" />
          )}
        </div>
        <div className="flex items-center justify-between border-t border-border bg-raised px-4 py-2 text-xs text-ui-subtle">
          <span>{queuedJob ? `${queuedJob.status}${queuedJob.progress_note ? ` · ${queuedJob.progress_note}` : ""}` : "Ready"}</span>
          <span>{width}×{height} · {steps} steps</span>
        </div>
      </main>
    </div>
  );
}

function DropHero({ uploading, onFile }: { uploading: boolean; onFile: (file: File) => void }) {
  return <label
    onDragOver={(event) => event.preventDefault()}
    onDrop={(event) => {
      event.preventDefault();
      const file = event.dataTransfer.files?.[0];
      if (file) onFile(file);
    }}
    className="flex h-full min-h-[560px] cursor-pointer items-center justify-center rounded-lg border border-dashed border-white/25 bg-stage text-sm text-ui-inverse hover:brightness-110"
  >
    {uploading ? "Uploading source..." : "Drop or choose a source image"}
    <input type="file" accept="image/*" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) onFile(file); }} />
  </label>;
}

function ComparePane({ before, after }: { before: string; after: string }) {
  const [position, setPosition] = useState(50);
  return <div className="relative h-full min-h-[560px] overflow-hidden rounded-md bg-stage">
    <img src={before} alt="source" className="absolute inset-0 h-full w-full object-contain" />
    <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}><img src={after} alt="result" className="h-full w-full object-contain" /></div>
    <div className="pointer-events-none absolute inset-y-0 w-px bg-white shadow" style={{ left: `${position}%` }} />
    <input aria-label="Compare source and result" type="range" min={0} max={100} value={position} onChange={(event) => setPosition(Number(event.target.value))} className="absolute inset-x-6 bottom-5" />
  </div>;
}

function Num({ label: text, value, set, step = 1 }: { label: string; value: number; set: (value: number) => void; step?: number }) {
  return <label><span className={label}>{text}</span><input type="number" value={value} step={step} onChange={(event) => set(Number(event.target.value))} className={`${field} mt-1`} /></label>;
}
