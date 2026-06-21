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
  imageFamilyDefaults,
  isLoraCompatible,
  isModelAvailable,
  numberParam,
  type LoraSelection,
} from "./imageComposerHelpers";

type EditMode = "img2img" | "inpaint" | "outpaint" | "instruction" | "controlnet";
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

const modeLabels: Record<EditMode, string> = {
  img2img: "Img2img",
  inpaint: "Inpaint",
  outpaint: "Outpaint",
  instruction: "Instruction",
  controlnet: "ControlNet",
};

export function editModeFromParams(params: Record<string, unknown>): EditMode {
  const candidate = typeof params.edit_mode === "string" ? params.edit_mode : "img2img";
  return candidate in modeLabels ? candidate as EditMode : "img2img";
}

export function supportsEditMode(model: Model, mode: EditMode): boolean {
  if (!isModelAvailable(model) || model.job_type !== "image") return false;
  if (mode === "instruction") return model.family === "qwen-image-edit" || model.family === "flux-kontext";
  if (mode === "controlnet") return model.family === "sdxl";
  if (mode === "inpaint" || mode === "outpaint") {
    return ["sdxl", "flux", "flux2", "qwen-image", "z-image"].includes(model.family);
  }
  return ["sdxl", "flux", "flux2", "qwen-image", "z-image", "anima"].includes(model.family);
}

export function EditWorkspace({
  models,
  modelsLoading = false,
  loras,
  presets,
  jobs,
  images,
  apply,
  onQueued,
  onGetModels,
}: {
  models: Model[];
  modelsLoading?: boolean;
  loras: Lora[];
  presets: Preset[];
  jobs: Job[];
  images: ImageItem[];
  apply?: EditApply | null;
  onQueued: () => void;
  onGetModels: () => void;
}) {
  const [mode, setMode] = useState<EditMode>("img2img");
  const [modelId, setModelId] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(3.5);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState(-1);
  const [batch, setBatch] = useState(1);
  const [strength, setStrength] = useState(0.6);
  const [resizeMode, setResizeMode] = useState("crop");
  const [maskDraft, setMaskDraft] = useState<File | null>(null);
  const [maskBlur, setMaskBlur] = useState(6);
  const [maskGrow, setMaskGrow] = useState(0);
  const [maskInvert, setMaskInvert] = useState(false);
  const [paddingCrop, setPaddingCrop] = useState(32);
  const [outpaint, setOutpaint] = useState({ left: 128, right: 128, top: 128, bottom: 128 });
  const [controlType, setControlType] = useState("canny");
  const [controlScale, setControlScale] = useState(0.75);
  const [controlMask, setControlMask] = useState(false);
  const [selectedLoras, setSelectedLoras] = useState<LoraSelection[]>([]);
  const [presetId, setPresetId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [queuedJobId, setQueuedJobId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("source");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const appliedNonce = useRef<number | null>(null);
  const skipModelDefaults = useRef(false);

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
    const defaults = imageFamilyDefaults(family, selectedModel);
    if (defaults) {
      setSteps(defaults.steps);
      setGuidance(defaults.guidance);
      if (!source) {
        setWidth(defaults.width);
        setHeight(defaults.height);
      }
    }
    if (family === "qwen-image") setStrength(0.6);
    if (family === "z-image") setStrength(0.45);
    if (family === "anima") setStrength(0.55);
  }, [family, selectedModel, source]);

  useEffect(() => {
    if (mode !== "outpaint" || !source) return;
    setWidth(round64(source.width + outpaint.left + outpaint.right));
    setHeight(round64(source.height + outpaint.top + outpaint.bottom));
  }, [mode, outpaint, source]);

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
      setWidth(round64(uploaded.width));
      setHeight(round64(uploaded.height));
      setMaskDraft(null);
      setQueuedJobId(null);
      setViewMode("source");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Source upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  useEffect(() => {
    if (!apply || apply.nonce === appliedNonce.current) return;
    appliedNonce.current = apply.nonce;
    const params = apply.params;
    const requestedMode = editModeFromParams(params);
    skipModelDefaults.current = true;
    setMode(requestedMode);
    setPrompt(typeof params.prompt === "string" ? params.prompt : "");
    setNegative(typeof params.negative === "string" ? params.negative : "");
    setSteps(numberParam(params.steps, 28));
    setGuidance(numberParam(params.guidance, 3.5));
    setWidth(numberParam(params.width, apply.width ?? 1024));
    setHeight(numberParam(params.height, apply.height ?? 1024));
    setSeed(numberParam(params.seed, -1));
    setBatch(numberParam(params.batch_size, 1));
    setStrength(numberParam(params.requested_strength ?? params.strength, 0.6));
    setResizeMode(typeof params.resize_mode === "string" ? params.resize_mode : "crop");
    setMaskBlur(numberParam(params.mask_blur, 6));
    setMaskGrow(numberParam(params.mask_grow, 0));
    setMaskInvert(Boolean(params.mask_invert));
    setPaddingCrop(numberParam(params.padding_mask_crop, 32));
    const margins = typeof params.outpaint === "object" && params.outpaint ? params.outpaint as Record<string, unknown> : params;
    setOutpaint({
      left: numberParam(margins.left ?? params.outpaint_left, 128),
      right: numberParam(margins.right ?? params.outpaint_right, 128),
      top: numberParam(margins.top ?? params.outpaint_top, 128),
      bottom: numberParam(margins.bottom ?? params.outpaint_bottom, 128),
    });
    setControlType(typeof params.control_type === "string" ? params.control_type : "canny");
    setControlScale(numberParam(params.control_scale, 0.75));
    setControlMask(requestedMode === "controlnet" && Boolean(params.mask_image ?? params.inpaint));
    const target = apply.model_id ? models.find((model) => model.id === apply.model_id) : undefined;
    if (target && supportsEditMode(target, requestedMode)) setModelId(target.id);
    if (apply.source_url) {
      void api.downloadUrlBlob(apply.source_url)
        .then((blob) => uploadSource(new File([blob], `${apply.image_id ?? "history"}.png`, { type: blob.type || "image/png" })))
        .catch(() => toast.error("Could not load the history image into Edit"));
    }
  }, [apply, models, uploadSource]);

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
      const params: Record<string, unknown> = {
        prompt: prompt.trim(),
        negative: negative.trim() || undefined,
        steps,
        guidance,
        width,
        height,
        seed,
        batch_size: batch,
        edit_mode: mode,
        init_image: source.token,
        mask_image: maskToken,
        strength: mode === "instruction" || (family === "flux2" && mode === "img2img") ? undefined : strength,
        resize_mode: resizeMode,
        mask_blur: maskBlur,
        mask_grow: maskGrow,
        mask_invert: maskInvert,
        padding_mask_crop: paddingCrop,
        outpaint_left: outpaint.left,
        outpaint_right: outpaint.right,
        outpaint_top: outpaint.top,
        outpaint_bottom: outpaint.bottom,
        control_image: mode === "controlnet" ? source.token : undefined,
        control_type: mode === "controlnet" ? controlType : undefined,
        control_scale: mode === "controlnet" ? controlScale : undefined,
        loras: selectedLoras.length ? selectedLoras : undefined,
      };
      const created = await api.createJobs([{ type: "image", model_id: selectedModel.id, params }]);
      setQueuedJobId(created[0]?.id ?? null);
      onQueued();
      toast.success(`Queued ${modeLabels[mode].toLowerCase()} edit`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not queue edit");
    } finally {
      setQueueing(false);
    }
  };

  const applyPreset = () => {
    const preset = imagePresets.find((item) => item.id === presetId);
    if (!preset) return;
    setPrompt(typeof preset.params.prompt === "string" ? preset.params.prompt : prompt);
    setNegative(typeof preset.params.negative === "string" ? preset.params.negative : negative);
    setSteps(numberParam(preset.params.steps, steps));
    setGuidance(numberParam(preset.params.guidance, guidance));
  };

  const applyRatio = (rw: number, rh: number) => {
    const base = Math.max(width, height, 512);
    if (rw >= rh) {
      setWidth(round64(base));
      setHeight(round64((base * rh) / rw));
    } else {
      setHeight(round64(base));
      setWidth(round64((base * rw) / rh));
    }
  };

  const toggleLora = (lora: Lora, enabled: boolean) => {
    setSelectedLoras((current) => enabled
      ? [...current.filter((item) => item.id !== lora.id), { id: lora.id, weight: 1 }]
      : current.filter((item) => item.id !== lora.id));
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
              {(Object.keys(modeLabels) as EditMode[]).map((item) => (
                <button
                  key={item}
                  onClick={() => setMode(item)}
                  className={`h-8 rounded-md border text-xs transition ${mode === item ? "border-accent bg-accent/15 text-accent-fg" : "border-border-strong text-ui-muted hover:bg-control-hover"}`}
                >
                  {modeLabels[item]}
                </button>
              ))}
            </div>
          </section>

          <section className={section}>
            <div className={label}>Model</div>
            <div className="mt-1.5">
              {eligibleModels.length ? (
                <ModelPicker models={eligibleModels} value={modelId} onChange={setModelId} />
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
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} className={`${field} mt-1.5 resize-y`} placeholder="Describe what should change..." />
            <input value={negative} onChange={(event) => setNegative(event.target.value)} className={`${field} mt-2`} placeholder="Negative prompt (optional)" />
            <PromptLibrary open={libraryOpen} onClose={() => setLibraryOpen(false)} currentPrompt={prompt} currentNegative={negative} onApply={(body, neg) => {
              setPrompt(prompt.trim() ? `${prompt.trim()}, ${body}` : body);
              if (neg) setNegative(negative.trim() ? `${negative.trim()}, ${neg}` : neg);
            }} />
          </section>

          {mode !== "instruction" && family !== "flux2" ? (
            <section className={section}>
              <div className="flex items-center justify-between text-xs text-ui-subtle"><span>Strength</span><span className="font-mono">{strength.toFixed(2)}</span></div>
              <Slider value={strength} min={0.05} max={1} step={0.05} onChange={setStrength} />
              <div className="mt-2"><Select value={resizeMode} onChange={setResizeMode} options={[{ value: "crop", label: "Crop to fit" }, { value: "pad", label: "Pad to fit" }, { value: "stretch", label: "Stretch" }]} /></div>
            </section>
          ) : null}

          {(mode === "inpaint" || mode === "outpaint" || (mode === "controlnet" && controlMask)) ? (
            <section className={section}>
              <div className={label}>Mask quality</div>
              <div className="mt-1.5 grid grid-cols-2 gap-2">
                <Num label="Grow / shrink" value={maskGrow} set={setMaskGrow} />
                <Num label="Blur" value={maskBlur} set={setMaskBlur} />
                <Num label="Crop padding" value={paddingCrop} set={setPaddingCrop} />
                <label className="flex items-end gap-2 pb-1 text-xs text-ui-muted"><Toggle checked={maskInvert} onChange={setMaskInvert} ariaLabel="Invert mask" />Invert</label>
              </div>
            </section>
          ) : null}

          {mode === "outpaint" ? (
            <section className={section}>
              <div className={label}>Extend canvas</div>
              <div className="mt-1.5 grid grid-cols-2 gap-2">
                {(["left", "right", "top", "bottom"] as const).map((side) => <Num key={side} label={side} value={outpaint[side]} set={(value) => setOutpaint((current) => ({ ...current, [side]: Math.max(0, value) }))} step={64} />)}
              </div>
            </section>
          ) : null}

          {mode === "controlnet" ? (
            <section className={section}>
              <div className={label}>ControlNet</div>
              <div className="mt-1.5"><Select value={controlType} onChange={setControlType} options={["canny", "depth", "pose", "scribble", "union-canny", "union-depth", "union-pose", "union-scribble"].map((value) => ({ value, label: value }))} /></div>
              <label className="mt-2 flex items-center gap-2 text-xs text-ui-muted"><Toggle checked={controlMask} onChange={(enabled) => { setControlMask(enabled); if (!enabled) setMaskDraft(null); }} ariaLabel="Use an inpaint mask with ControlNet" />Use inpaint mask</label>
              <div className="mt-2 flex items-center justify-between text-xs text-ui-subtle"><span>Scale</span><span>{controlScale.toFixed(2)}</span></div>
              <Slider value={controlScale} min={0} max={2} step={0.05} onChange={setControlScale} />
            </section>
          ) : null}

          <ImageParamForm activeRatio={activeRatio} batch={batch} guidance={guidance} height={height} labelClass={label} onApplyRatio={applyRatio} ratios={ratios} sectionClass={section} seed={seed} setBatch={setBatch} setGuidance={setGuidance} setHeight={setHeight} setSeed={setSeed} setSteps={setSteps} setWidth={setWidth} steps={steps} width={width} />

          {compatibleLoras.length ? (
            <section className={section}>
              <div className={label}>LoRA</div>
              <div className="mt-1.5 space-y-2">{compatibleLoras.map((lora) => {
                const selected = selectedLoras.find((item) => item.id === lora.id);
                return <LoraCard key={lora.id} lora={lora} selected={selected} onToggle={(enabled) => toggleLora(lora, enabled)} onWeight={(weight) => setSelectedLoras((current) => current.map((item) => item.id === lora.id ? { ...item, weight } : item))} />;
              })}</div>
            </section>
          ) : null}

          <section className={section}>
            <div className={label}>Preset</div>
            <div className="mt-1.5 flex gap-2"><div className="min-w-0 flex-1"><Select value={presetId} onChange={setPresetId} options={[{ value: "", label: "unsaved" }, ...imagePresets.map((preset) => ({ value: preset.id, label: preset.name }))]} /></div><button onClick={applyPreset} disabled={!presetId} className="ui-button rounded-md px-3 text-xs">Apply</button></div>
          </section>
        </div>
        <div className="border-t border-border bg-raised p-3">
          <button onClick={() => void queue()} disabled={!source || !selectedModel || !prompt.trim() || queueing} className="ui-button-primary h-10 w-full rounded-md text-sm font-semibold disabled:opacity-40">
            {queueing ? "Queuing..." : `Queue ${modeLabels[mode]}`}
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
            <MaskEditor src={source.url} onMaskChange={onMaskChange} large onFeatherChange={setMaskBlur} />
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

export function round64(value: number): number {
  return Math.max(64, Math.round(value / 64) * 64);
}
