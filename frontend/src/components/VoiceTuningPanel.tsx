import { Select } from "./Select";
import { Toggle } from "./Toggle";
import { Button, LabeledSlider, Panel, SignedControl, field, nativeF0Options } from "./VoicePanelControls";
import { denoiseOptions, inputHighpassOptions } from "./voiceHelpers";

type VoiceTuningPanelProps = {
  busy: string;
  canApply: boolean;
  f0Detector: string;
  f0Smoothing: number;
  formantShift: number;
  indexRatio: number;
  indexRisk: boolean;
  inputDenoise: "off" | "dtln";
  inputDenoiseMix: number;
  inputGateDb: number;
  inputHighpassHz: number;
  noiseRisk: boolean;
  noiseScale: number;
  markTuning: () => void;
  onBypass: (next: boolean) => void;
  onClear: () => void;
  onFeminine: () => void;
  onPtt: (next: boolean) => void;
  onRecommended: () => void;
  onSmooth: () => void;
  passThrough: boolean;
  pitch: number;
  plus12Tuning: boolean;
  protect: number;
  protectRisk: boolean;
  ptt: boolean;
  selectedName: string;
  selectedSupportsPitch: boolean;
  setDraftFormant: (value: number) => void;
  setDraftPitch: (value: number) => void;
  setDraftSpeakerId: (value: number) => void;
  setF0Detector: (value: string) => void;
  setF0Smoothing: (value: number) => void;
  setIndexRatio: (value: number) => void;
  setInputDenoise: (value: "off" | "dtln") => void;
  setInputDenoiseMix: (value: number) => void;
  setInputGateDb: (value: number) => void;
  setInputHighpassHz: (value: number) => void;
  setNoiseScale: (value: number) => void;
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
  formantShift,
  indexRatio,
  indexRisk,
  inputDenoise,
  inputDenoiseMix,
  inputGateDb,
  inputHighpassHz,
  noiseRisk,
  noiseScale,
  markTuning,
  onBypass,
  onClear,
  onFeminine,
  onPtt,
  onRecommended,
  onSmooth,
  passThrough,
  pitch,
  plus12Tuning,
  protect,
  protectRisk,
  ptt,
  selectedName,
  selectedSupportsPitch,
  setDraftFormant,
  setDraftPitch,
  setDraftSpeakerId,
  setF0Detector,
  setF0Smoothing,
  setIndexRatio,
  setInputDenoise,
  setInputDenoiseMix,
  setInputGateDb,
  setInputHighpassHz,
  setNoiseScale,
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
          <Button onClick={onRecommended} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "recommended" ? "Applying..." : "Baseline"}
          </Button>
          <Button onClick={onClear} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "clear-preset" ? "Applying..." : "Clear"}
          </Button>
          <Button onClick={onSmooth} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "smooth-preset" ? "Applying..." : "Smooth"}
          </Button>
          <Button onClick={onFeminine} disabled={!canApply} tone="ghost" className="px-2 py-1 text-xs">
            {busy === "female-preset" ? "Applying..." : "Female +12 RMVPE"}
          </Button>
        </div>
      }
    >
      <div className="grid gap-3 lg:grid-cols-[minmax(260px,0.75fr)_minmax(0,1fr)]">
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
        <SignedControl
          label="Formant"
          value={formantShift}
          min={-2}
          max={2}
          step={0.05}
          precision={2}
          onChange={setDraftFormant}
          quick={[-0.5, 0, 0.5]}
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

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <LabeledSlider
          label="Index ratio"
          value={indexRatio}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => {
            setIndexRatio(value);
            markTuning();
          }}
          valueLabel={indexRatio.toFixed(2)}
          tone={indexRisk ? "warn" : "neutral"}
          note={plus12Tuning ? "safe zone +12: 0.25-0.35" : "speech safe zone: 0.20-0.45"}
        />
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
          label="Noise scale"
          value={noiseScale}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => {
            setNoiseScale(value);
            markTuning();
          }}
          valueLabel={noiseScale.toFixed(2)}
          tone={noiseRisk ? "warn" : "neutral"}
          note={plus12Tuning ? "safe zone +12: 0.45-0.55" : "speech safe zone: 0.45-0.60"}
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

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <LabeledSlider
          label="Noise gate"
          value={inputGateDb}
          min={-90}
          max={-20}
          step={1}
          onChange={(value) => {
            setInputGateDb(value);
            markTuning();
          }}
          valueLabel={inputGateDb <= -90 ? "off" : `${inputGateDb.toFixed(0)} dB`}
        />
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
