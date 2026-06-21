import { Badge } from "./Badge";
import { Slider } from "./Slider";
import { Toggle } from "./Toggle";
import type { Lora } from "../types";
import { familyColor, formatSize, type LoraSelection } from "./imageComposerHelpers";

export type RatioOption = { label: string; w: number; h: number };

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
          <span className="text-[11px] text-ui-subtle">{activeRatio}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {ratios.map((ratio) => {
            const active = activeRatio === ratio.label;
            return (
              <button
                key={ratio.label}
                onClick={() => onApplyRatio(ratio.w, ratio.h)}
                className={`h-7 rounded-md border px-2.5 text-xs transition ${
                  active ? "border-accent/70 bg-accent/20 text-accent-fg" : "border-border-strong text-ui-muted hover:bg-control-hover"
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
      enabled ? "border-accent/45 bg-accent/10" : "border-border bg-sunken"
    }`}>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-ui" title={lora.name}>{lora.name}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge color={familyColor(lora.family ?? "unknown")}>{lora.family ?? "any"}</Badge>
            <Badge>{formatSize(lora.size_bytes)}</Badge>
          </div>
        </div>
        <Toggle checked={enabled} onChange={onToggle} ariaLabel={`Toggle ${lora.name}`} />
      </div>
      <div className={`mt-2 ${enabled ? "" : "pointer-events-none opacity-35"}`}>
        <div className="mb-1 flex items-center justify-between text-[11px] text-ui-subtle">
          <span>Weight</span>
          <span className="font-mono text-ui-muted">{weight.toFixed(2)}</span>
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
        className="ui-field mt-1 w-full rounded-md px-2 py-1.5 text-sm"
      />
    </label>
  );
}
