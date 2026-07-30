import { Select } from "./Select";
import { Toggle } from "./Toggle";
import { Button, LabeledSlider, Panel, SignedControl, field, nativeF0Options } from "./VoicePanelControls";
import { denoiseOptions, inputHighpassOptions } from "./voiceHelpers";

type VoiceTuningPanelProps = {
  busy: string;
  canApply: boolean;
  f0Detector: string;
  f0Smoothing: number;
  indexRatio: number;
  indexRisk: boolean;
  inputDenoise: "off" | "dtln";
  inputDenoiseMix: number;
  inputHighpassHz: number;
  markTuning: () => void;
  onBypass: (next: boolean) => void;
  onFeminine: () => void;
  onLowLatency: () => void;
  onPtt: (next: boolean) => void;
  onQuality: () => void;
  onStable: () => void;
  passThrough: boolean;
  pitch: number;
  protect: number;
  protectRisk: boolean;
  ptt: boolean;
  selectedHasIndex: boolean;
  selectedName: string;
  selectedSupportsPitch: boolean;
  setDraftPitch: (value: number) => void;
  setDraftSpeakerId: (value: number) => void;
  setF0Detector: (value: string) => void;
  setF0Smoothing: (value: number) => void;
  setIndexRatio: (value: number) => void;
  setInputDenoise: (value: "off" | "dtln") => void;
  setInputDenoiseMix: (value: number) => void;
  setInputHighpassHz: (value: number) => void;
  setProtect: (value: number) => void;
  setSilenceHoldMs: (value: number) => void;
  setSilenceThresholdDb: (value: number) => void;
  silenceHoldMs: number;
  silenceThresholdDb: number;
  speakerId: number;
  statusLoaded: boolean;
};

export function VoiceTuningPanel({
  busy,
  canApply,
  f0Detector,
  f0Smoothing,
  indexRatio,
  indexRisk,
  inputDenoise,
  inputDenoiseMix,
  inputHighpassHz,
  markTuning,
  onBypass,
  onFeminine,
  onLowLatency,
  onPtt,
  onQuality,
  onStable,
  passThrough,
  pitch,
  protect,
  protectRisk,
  ptt,
  selectedHasIndex,
  selectedName,
  selectedSupportsPitch,
  setDraftPitch,
  setDraftSpeakerId,
  setF0Detector,
  setF0Smoothing,
  setIndexRatio,
  setInputDenoise,
  setInputDenoiseMix,
  setInputHighpassHz,
  setProtect,
  setSilenceHoldMs,
  setSilenceThresholdDb,
  silenceHoldMs,
  silenceThresholdDb,
  speakerId,
  statusLoaded,
}: VoiceTuningPanelProps) {
  return (
    <Panel
      title="Tuning"
      eyebrow={selectedName}
      aside={
        <div className="flex flex-wrap justify-end gap-1.5">
          <Button onClick={onStable} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "stable-preset" ? "Applying..." : "Stable"}
          </Button>
          <Button onClick={onLowLatency} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "low-latency-preset" ? "Applying..." : "Low latency"}
          </Button>
          <Button onClick={onQuality} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "quality-preset" ? "Applying..." : "Quality"}
          </Button>
          <Button onClick={onFeminine} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "female-preset" ? "Applying..." : "Female +10"}
          </Button>
        </div>
      }
    >
      <div className="grid gap-3">
        <SignedControl
          label="Pitch"
          value={pitch}
          min={-24}
          max={24}
          step={1}
          onChange={setDraftPitch}
          unit=" st"
          quick={[-12, -7, 0, 7, 12]}
          note={selectedSupportsPitch ? "f0 model" : "no-f0 model"}
        />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">F0 detector</div>
          <Select
            ariaLabel="F0 detector"
            value={f0Detector}
            onChange={(value) => {
              setF0Detector(value);
              markTuning();
            }}
            options={nativeF0Options}
          />
        </div>
        <div className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Speaker ID</div>
          <input
            type="number"
            min={0}
            max={255}
            step={1}
            value={speakerId}
            onChange={(event) => setDraftSpeakerId(Number(event.target.value))}
            className={field}
          />
        </div>
        <div className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Denoise</div>
          <Select
            ariaLabel="Input denoise"
            value={inputDenoise}
            onChange={(value) => {
              const nextDenoise = value === "dtln" ? "dtln" : "off";
              setInputDenoise(nextDenoise);
              if (nextDenoise === "dtln" && inputDenoiseMix <= 0) setInputDenoiseMix(0.75);
              markTuning();
            }}
            options={denoiseOptions}
          />
          <div className="mt-2">
            <LabeledSlider
              label="Denoise mix"
              value={inputDenoiseMix}
              min={0}
              max={1}
              step={0.01}
              onChange={(value) => {
                setInputDenoiseMix(value);
                markTuning();
              }}
              valueLabel={inputDenoise === "dtln" ? inputDenoiseMix.toFixed(2) : "off"}
              disabled={inputDenoise !== "dtln"}
            />
          </div>
        </div>
        <div className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">High-pass</div>
          <Select
            ariaLabel="Input high-pass"
            value={String(inputHighpassHz)}
            onChange={(value) => {
              setInputHighpassHz(Number(value));
              markTuning();
            }}
            options={inputHighpassOptions}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {selectedHasIndex ? (
          <LabeledSlider
            label="Index blend"
            value={indexRatio}
            min={0}
            max={0.6}
            step={0.01}
            onChange={(value) => {
              setIndexRatio(value);
              markTuning();
            }}
            valueLabel={indexRatio.toFixed(2)}
            tone={indexRisk ? "warn" : "neutral"}
            note="model has a retrieval index"
          />
        ) : (
          <div className="ui-card rounded-md px-3 py-2 text-sm text-ui-subtle">
            Retrieval index is unavailable for this voice; index blending is disabled.
          </div>
        )}
        <LabeledSlider
          label="Protect"
          value={protect}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => {
            setProtect(value);
            markTuning();
          }}
          valueLabel={protect.toFixed(2)}
          tone={protectRisk ? "warn" : "neutral"}
          note={protectRisk ? "risk zone: consonant protection off" : "safe zone: 0.25-0.35"}
        />
        <LabeledSlider
          label="F0 smooth"
          value={f0Smoothing}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => {
            setF0Smoothing(value);
            markTuning();
          }}
          valueLabel={f0Smoothing.toFixed(2)}
        />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <LabeledSlider
          label="Idle squelch"
          value={silenceThresholdDb}
          min={-90}
          max={-20}
          step={1}
          onChange={(value) => {
            setSilenceThresholdDb(value);
            markTuning();
          }}
          valueLabel={silenceThresholdDb <= -90 ? "off" : `${silenceThresholdDb.toFixed(0)} dB`}
        />
        <LabeledSlider
          label="Hold"
          value={silenceHoldMs}
          min={0}
          max={2000}
          step={50}
          onChange={(value) => {
            setSilenceHoldMs(value);
            markTuning();
          }}
          valueLabel={`${Math.round(silenceHoldMs)} ms`}
        />
        <div className="ui-card flex items-end justify-between gap-3 rounded-md px-3 py-2">
          <div className="flex items-center gap-2 text-sm text-ui-muted">
            <Toggle
              checked={passThrough}
              onChange={onBypass}
              disabled={!statusLoaded || Boolean(busy)}
              ariaLabel="Bypass voice conversion"
            />
            Bypass
          </div>
          <div className="flex items-center gap-2 text-sm text-ui-muted">
            <Toggle checked={ptt} onChange={onPtt} disabled={!statusLoaded} ariaLabel="Push to talk" />
            PTT
          </div>
        </div>
      </div>
    </Panel>
  );
}
