import { meter, waveformSlots } from "./voiceHelpers";

export type MeterSample = {
  input: number;
  output: number;
};

export function Meter({
  label,
  value,
  tone = "emerald",
}: {
  label: string;
  value: number;
  tone?: "emerald" | "sky" | "amber";
}) {
  const bar = tone === "sky" ? "bg-sky-400/80" : tone === "amber" ? "bg-amber-300/85" : "bg-emerald-400/80";
  return (
    <div className="ui-card rounded-md px-3 py-2">
      <div className="flex items-center justify-between text-xs">
        <span className="uppercase tracking-wide text-ui-subtle">{label}</span>
        <span className="font-mono text-ui-muted">{value}%</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-control-active">
        <div className={`h-full rounded-full transition-[width] ${bar}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export function WaveformMonitor({ samples }: { samples: MeterSample[] }) {
  const bars = Array.from({ length: waveformSlots }, (_, index) => {
    const offset = samples.length - waveformSlots + index;
    return offset >= 0 ? samples[offset] : { input: 0, output: 0 };
  });
  const latest = samples[samples.length - 1] ?? { input: 0, output: 0 };

  return (
    <div className="ui-card rounded-md px-3 py-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="uppercase tracking-wide text-ui-subtle">Waveform</span>
        <span className="font-mono text-ui-muted">
          in {meter(latest.input)}% / out {meter(latest.output)}%
        </span>
      </div>
      <div className="mt-3 flex h-24 items-center gap-px overflow-hidden rounded bg-stage px-2 py-2">
        {bars.map((sample, index) => {
          const inputHeight = sample.input > 0 ? Math.max(2, sample.input * 46) : 0;
          const outputHeight = sample.output > 0 ? Math.max(2, sample.output * 46) : 0;
          return (
            <div key={index} className="relative h-full min-w-0 flex-1">
              <div className="absolute left-0 right-0 top-1/2 h-px bg-white/15" />
              <div
                className="absolute bottom-1/2 left-0 right-0 rounded-t-sm bg-emerald-400/80"
                style={{ height: `${inputHeight}%` }}
              />
              <div
                className="absolute left-0 right-0 top-1/2 rounded-b-sm bg-sky-400/75"
                style={{ height: `${outputHeight}%` }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
