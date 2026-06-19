// Shared range slider with a value readout (P5.D3 control kit).
export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.01,
  disabled = false,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-control-active accent-accent disabled:cursor-not-allowed"
      />
      <span className="w-9 shrink-0 text-right font-mono text-xs tabular-nums text-ui-muted">{value.toFixed(2)}</span>
    </div>
  );
}
