import { Badge } from "./Badge";
import { MaskEditor } from "./MaskEditor";
import { Slider } from "./Slider";
import { Toggle } from "./Toggle";
import type { Lora } from "../types";
import { familyColor, formatSize, type LoraSelection } from "./imageComposerHelpers";

export type RatioOption = { label: string; w: number; h: number };

export function SourceImageBlock({
  initImage,
  labelClass,
  onClear,
  onPickInitImage,
  sectionClass,
  setMaskDraft,
  setStrength,
  strength,
  uploadBusy,
  uploadError,
}: {
  initImage: { token: string; url: string } | null;
  labelClass: string;
  onClear: () => void;
  onPickInitImage: (file: File | null | undefined) => void;
  sectionClass: string;
  setMaskDraft: (file: File | null) => void;
  setStrength: (value: number) => void;
  strength: number;
  uploadBusy: boolean;
  uploadError: string;
}) {
  return (
    <section className={sectionClass}>
      <div className="flex items-center justify-between">
        <div className={labelClass}>Source image (img2img)</div>
        {initImage ? (
          <button onClick={onClear} className="text-[11px] text-white/45 transition hover:text-white/80">
            clear
          </button>
        ) : null}
      </div>
      {initImage ? (
        <div className="mt-1.5 space-y-2">
          <img
            src={initImage.url}
            alt="source"
            className="max-h-40 w-full rounded-md border border-white/10 bg-black/30 object-contain"
          />
          <div className="flex items-center justify-between text-[11px] text-white/40">
            <span>Strength</span>
            <span className="font-mono text-white/60">{strength.toFixed(2)}</span>
          </div>
          <Slider value={strength} min={0.05} max={1} step={0.05} onChange={setStrength} />
          <p className="text-[11px] text-white/35">Lower keeps the source; higher follows the prompt.</p>
          <MaskEditor src={initImage.url} onMaskChange={setMaskDraft} />
        </div>
      ) : (
        <label
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            onPickInitImage(event.dataTransfer.files?.[0]);
          }}
          className={`mt-1.5 flex cursor-pointer items-center justify-center rounded-md border border-dashed border-white/15 px-3 py-4 text-center text-xs text-white/45 transition hover:border-white/30 hover:text-white/70 ${
            uploadBusy ? "pointer-events-none opacity-50" : ""
          }`}
        >
          {uploadBusy ? "uploading..." : "drop or click to add a source image"}
          <input
            type="file"
            accept="image/*"
            className="hidden"
            disabled={uploadBusy}
            onChange={(event) => {
              onPickInitImage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </label>
      )}
      {uploadError ? <Notice tone="amber">{uploadError}</Notice> : null}
    </section>
  );
}

export function ImageParamForm({
  activeRatio,
  guidance,
  height,
  labelClass,
  onApplyRatio,
  ratios,
  sectionClass,
  seed,
  setBatch,
  setGuidance,
  setHeight,
  setSeed,
  setSteps,
  setWidth,
  steps,
  batch,
  width,
}: {
  activeRatio: string;
  guidance: number;
  height: number;
  labelClass: string;
  onApplyRatio: (w: number, h: number) => void;
  ratios: RatioOption[];
  sectionClass: string;
  seed: number;
  setBatch: (value: number) => void;
  setGuidance: (value: number) => void;
  setHeight: (value: number) => void;
  setSeed: (value: number) => void;
  setSteps: (value: number) => void;
  setWidth: (value: number) => void;
  steps: number;
  batch: number;
  width: number;
}) {
  return (
    <>
      <section className={sectionClass}>
        <div className="flex items-center justify-between">
          <div className={labelClass}>Canvas</div>
          <span className="text-[11px] text-white/35">{activeRatio}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {ratios.map((ratio) => {
            const active = activeRatio === ratio.label;
            return (
              <button
                key={ratio.label}
                onClick={() => onApplyRatio(ratio.w, ratio.h)}
                className={`h-7 rounded-md border px-2.5 text-xs transition ${
                  active ? "border-accent/70 bg-accent/20 text-white" : "border-white/15 text-white/60 hover:bg-white/10"
                }`}
              >
                {ratio.label}
              </button>
            );
          })}
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Num label="Width" v={width} set={setWidth} step={64} labelClass={labelClass} />
          <Num label="Height" v={height} set={setHeight} step={64} labelClass={labelClass} />
        </div>
      </section>

      <section className={sectionClass}>
        <div className={labelClass}>Sampling</div>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <Num label="Steps" v={steps} set={setSteps} labelClass={labelClass} />
          <Num label="Guidance" v={guidance} set={setGuidance} step={0.1} labelClass={labelClass} />
          <Num label="Seed" v={seed} set={setSeed} labelClass={labelClass} />
          <Num label="Batch" v={batch} set={setBatch} labelClass={labelClass} />
        </div>
      </section>
    </>
  );
}

export function Notice({ tone, children }: { tone: "amber" | "emerald" | "sky"; children: string }) {
  const classes = {
    amber: "border-amber-500/30 bg-amber-500/10 text-amber-100",
    emerald: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
    sky: "border-sky-500/30 bg-sky-500/10 text-sky-100",
  };
  return <div className={`mt-2 rounded-md border px-2.5 py-2 text-xs leading-5 ${classes[tone]}`}>{children}</div>;
}

export function LoraCard({
  lora,
  selected,
  onToggle,
  onWeight,
}: {
  lora: Lora;
  selected?: LoraSelection;
  onToggle: (enabled: boolean) => void;
  onWeight: (weight: number) => void;
}) {
  const enabled = Boolean(selected);
  const weight = selected?.weight ?? 1;

  return (
    <div className={`rounded-md border px-2.5 py-2 transition ${
      enabled ? "border-accent/45 bg-accent/10" : "border-white/10 bg-black/20"
    }`}>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-white/75" title={lora.name}>{lora.name}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge color={familyColor(lora.family ?? "unknown")}>{lora.family ?? "any"}</Badge>
            <Badge>{formatSize(lora.size_bytes)}</Badge>
          </div>
        </div>
        <Toggle checked={enabled} onChange={onToggle} ariaLabel={`Toggle ${lora.name}`} />
      </div>
      <div className={`mt-2 ${enabled ? "" : "pointer-events-none opacity-35"}`}>
        <div className="mb-1 flex items-center justify-between text-[11px] text-white/40">
          <span>Weight</span>
          <span className="font-mono text-white/60">{weight.toFixed(2)}</span>
        </div>
        <Slider value={weight} min={-2} max={2} step={0.05} onChange={onWeight} />
      </div>
    </div>
  );
}

function Num({
  label: l,
  labelClass,
  v,
  set,
  step = 1,
}: {
  label: string;
  labelClass: string;
  v: number;
  set: (n: number) => void;
  step?: number;
}) {
  return (
    <label className="block">
      <div className={labelClass}>{l}</div>
      <input
        type="number"
        value={v}
        step={step}
        onChange={(e) => set(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}
