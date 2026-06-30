import { Badge } from "./Badge";
import { Select, type SelectOption } from "./Select";
import { Toggle } from "./Toggle";
import {
  assetSearchHint,
  Button,
  CompactSignedControl,
  DiagnosticsCompact,
  LabeledSlider,
  MiniButton,
  Panel,
  PresetCard,
  SignedControl,
  VoiceOption,
  clamp,
  field,
  nativeF0Options,
  timingsLine,
} from "./VoicePanelControls";
import {
  DeviceSelect,
  LatencyMeter,
  MonitorSelect,
  OfflineDevice,
  RoutingApplyHint,
  type RoutingApplyState,
} from "./VoicePanelParts";
import { Meter, type MeterSample } from "./VoiceMeters";
import { denoiseOptions, deviceName, formatMs, inputHighpassOptions, latencyPresets, meter, sampleRates } from "./voiceHelpers";
import type {
  VoiceAudioDevice,
  VoiceEngineConvertResult,
  VoiceEnginePreset,
  VoiceEngineRecordingResult,
  VoiceEngineStatus,
  VoiceModel,
} from "../types";

type VoiceLiveConsolePanelProps = {
  busy: string;
  canGoLive: boolean;
  inputDeviceId: number;
  inputDevices: VoiceAudioDevice[];
  live: boolean;
  modelId: string;
  monitorDeviceId: number;
  monitorGain: number;
  monitorOn: boolean;
  onLive: (next: boolean) => void;
  onMonitor: (next: boolean) => void;
  onRecording: (next: boolean) => void;
  onRestartLive: () => void;
  outputDeviceId: number;
  outputDevices: VoiceAudioDevice[];
  outputPeak: number;
  outputPeakTone: "amber" | "sky";
  ready: boolean;
  recording: boolean;
  recordingResult: VoiceEngineRecordingResult | null;
  selected: VoiceModel | undefined;
  setMonitorGain: (value: number) => void;
  status: VoiceEngineStatus | null;
  statusLoaded: boolean;
};

export function VoiceLiveConsolePanel({
  busy,
  canGoLive,
  inputDeviceId,
  inputDevices,
  live,
  modelId,
  monitorDeviceId,
  monitorGain,
  monitorOn,
  onLive,
  onMonitor,
  onRecording,
  onRestartLive,
  outputDeviceId,
  outputDevices,
  outputPeak,
  outputPeakTone,
  ready,
  recording,
  recordingResult,
  selected,
  setMonitorGain,
  status,
  statusLoaded,
}: VoiceLiveConsolePanelProps) {
  return (
    <Panel
      title="Live Console"
      aside={(
        <Badge color={live ? "bg-success-bg text-success-fg" : "ui-chip"}>
          {live ? "on air" : "stopped"}
        </Badge>
      )}
    >
      {status?.session_error ? (
        <div className="mb-3 rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
          {status.session_error}
        </div>
      ) : null}

      <div className={`rounded-md border p-4 ${live ? "border-success-border bg-success-bg" : "border-border bg-sunken"}`}>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="truncate text-base font-semibold text-ui-strong">
              {live ? "Live voice is running" : "Live voice is off"}
            </div>
            <div className="mt-1 truncate text-sm text-ui-subtle">
              {deviceName(inputDevices, inputDeviceId, "input")}{" -> "}{selected?.name ?? "voice"}{" -> "}{deviceName(outputDevices, outputDeviceId, "output")}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {live ? (
              <>
                <Button onClick={() => onLive(false)} disabled={Boolean(busy) || recording} tone="danger">
                  {busy === "live-off" ? "Stopping..." : "Stop"}
                </Button>
                <Button onClick={onRestartLive} disabled={Boolean(busy) || recording} tone="warn">
                  {busy === "live-restart" ? "Restarting..." : "Restart"}
                </Button>
              </>
            ) : (
              <Button onClick={() => onLive(true)} disabled={!canGoLive} tone="success">
                {busy === "live-on" ? "Starting..." : "Start Live"}
              </Button>
            )}
          </div>
        </div>
        {!live && !canGoLive ? (
          <div className="mt-2 text-xs text-amber-200/75">
            {busy ? "busy..." : !ready ? assetSearchHint : !modelId ? "select a voice model" : "cannot start right now"}
          </div>
        ) : null}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Meter label="Input" value={meter(status?.metrics.input_vu ?? 0)} />
        <Meter label={monitorOn ? "Output / Monitor" : "Output"} value={meter(status?.metrics.output_vu ?? 0)} tone="sky" />
        <Meter label="Output peak" value={meter(outputPeak)} tone={outputPeakTone} />
        <LatencyMeter value={status?.metrics.total_ms ?? status?.metrics.chunk_ms} />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.75fr)]">
        <div className={`rounded-md border px-3 py-2 ${recording ? "border-error-border bg-error-bg" : "border-border bg-sunken"}`}>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ui">Recorder</span>
                <Badge color={recording ? "bg-error-bg text-error-fg" : "ui-chip"}>
                  {recording ? `${(status?.recording.duration_s ?? 0).toFixed(1)} s` : "ready"}
                </Badge>
              </div>
              <div className="mt-0.5 truncate text-xs text-ui-subtle">
                {recordingResult ? `${recordingResult.sample_rate} Hz / ${recordingResult.duration_s.toFixed(2)} s` : "live output"}
              </div>
            </div>
            <Button onClick={() => onRecording(!recording)} disabled={!live || Boolean(busy)} tone={recording ? "danger" : "ghost"}>
              {busy === "record-on" ? "Starting..." : busy === "record-off" ? "Saving..." : recording ? "Save" : "Record"}
            </Button>
          </div>
          {recordingResult ? (
            <div className="mt-3">
              <audio controls src={recordingResult.url} className="w-full" />
              <div className="mt-2 flex justify-end gap-2">
                <a href={recordingResult.url} download className="ui-button rounded px-2 py-1 text-xs">WAV</a>
                <a href={recordingResult.mp3_url} download className="ui-button rounded px-2 py-1 text-xs">MP3</a>
              </div>
            </div>
          ) : null}
        </div>

        <div className={`rounded-md border px-3 py-2 ${monitorOn ? "border-info-border bg-info-bg" : "border-border bg-sunken"}`}>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ui">Monitor</span>
                <Badge color={monitorOn ? "bg-info-bg text-info-fg" : "ui-chip"}>
                  {monitorOn ? "on" : "off"}
                </Badge>
              </div>
              <div className="mt-0.5 truncate text-xs text-ui-subtle" title={deviceName(outputDevices, monitorDeviceId, "Off")}>
                {deviceName(outputDevices, monitorDeviceId, "Off")}
              </div>
            </div>
            <Toggle checked={monitorOn} onChange={onMonitor} disabled={!statusLoaded || outputDevices.length === 0} ariaLabel="Toggle monitor" />
          </div>
          <div className="mt-2">
            <LabeledSlider label="Monitor gain" value={monitorGain} min={0} max={2} step={0.01} onChange={setMonitorGain} />
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge>overruns {status?.metrics.overruns ?? 0}</Badge>
        <Badge>underruns {status?.metrics.underruns ?? 0}</Badge>
        <Badge>chunk {formatMs(status?.metrics.chunk_ms)}</Badge>
        <Badge color={status?.metrics.latency_warning ? "bg-warn-bg text-warn-fg" : "ui-chip"}>
          p95 {formatMs(status?.metrics.total_p95_ms)}
        </Badge>
        <Badge color={status?.metrics.squelched ? "bg-amber-600/40 text-amber-100" : "bg-emerald-700/45 text-emerald-100"}>
          {status?.metrics.squelched ? "silence" : "voice"}
        </Badge>
      </div>
    </Panel>
  );
}

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
      aside={(
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
      )}
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
        <label className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">F0 detector</div>
          <Select
            value={f0Detector}
            onChange={(value) => {
              setF0Detector(value);
              markTuning();
            }}
            options={nativeF0Options}
          />
        </label>
        <label className="min-w-0">
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
        </label>
        <label className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Denoise</div>
          <Select
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
              onChange={(value) => { setInputDenoiseMix(value); markTuning(); }}
              valueLabel={inputDenoise === "dtln" ? inputDenoiseMix.toFixed(2) : "off"}
              disabled={inputDenoise !== "dtln"}
            />
          </div>
        </label>
        <label className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-ui-muted">High-pass</div>
          <Select
            value={String(inputHighpassHz)}
            onChange={(value) => {
              setInputHighpassHz(Number(value));
              markTuning();
            }}
            options={inputHighpassOptions}
          />
        </label>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <LabeledSlider
          label="Index ratio"
          value={indexRatio}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => { setIndexRatio(value); markTuning(); }}
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
          onChange={(value) => { setProtect(value); markTuning(); }}
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
          onChange={(value) => { setNoiseScale(value); markTuning(); }}
          valueLabel={noiseScale.toFixed(2)}
          tone={noiseRisk ? "warn" : "neutral"}
          note={plus12Tuning ? "safe zone +12: 0.45-0.55" : "speech safe zone: 0.45-0.60"}
        />
        <LabeledSlider label="F0 smooth" value={f0Smoothing} min={0} max={1} step={0.01} onChange={(value) => { setF0Smoothing(value); markTuning(); }} valueLabel={f0Smoothing.toFixed(2)} />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <LabeledSlider
          label="Noise gate"
          value={inputGateDb}
          min={-90}
          max={-20}
          step={1}
          onChange={(value) => { setInputGateDb(value); markTuning(); }}
          valueLabel={inputGateDb <= -90 ? "off" : `${inputGateDb.toFixed(0)} dB`}
        />
        <LabeledSlider
          label="Idle squelch"
          value={silenceThresholdDb}
          min={-90}
          max={-20}
          step={1}
          onChange={(value) => { setSilenceThresholdDb(value); markTuning(); }}
          valueLabel={silenceThresholdDb <= -90 ? "off" : `${silenceThresholdDb.toFixed(0)} dB`}
        />
        <LabeledSlider
          label="Hold"
          value={silenceHoldMs}
          min={0}
          max={2000}
          step={50}
          onChange={(value) => { setSilenceHoldMs(value); markTuning(); }}
          valueLabel={`${Math.round(silenceHoldMs)} ms`}
        />
        <div className="ui-card flex items-end justify-between gap-3 rounded-md px-3 py-2">
          <label className="flex items-center gap-2 text-sm text-ui-muted">
            <Toggle checked={passThrough} onChange={onBypass} disabled={!statusLoaded || Boolean(busy)} />
            Bypass
          </label>
          <label className="flex items-center gap-2 text-sm text-ui-muted">
            <Toggle checked={ptt} onChange={onPtt} disabled={!statusLoaded} />
            PTT
          </label>
        </div>
      </div>
    </Panel>
  );
}

type VoiceRoutingPanelProps = {
  busy: string;
  chunkRestartPending: boolean;
  crossFadeOverlap: number;
  deviceMissing: { input: boolean; output: boolean; monitor: boolean };
  extraConvert: number;
  inputDeviceId: number;
  inputDevices: VoiceAudioDevice[];
  inputGain: number;
  inputRestartPending: boolean;
  monitorDeviceId: number;
  monitorRestartPending: boolean;
  onPreset: (preset: (typeof latencyPresets)[number]) => void;
  outputDeviceId: number;
  outputDevices: VoiceAudioDevice[];
  outputGain: number;
  outputIsVirtualCable: boolean;
  outputRestartPending: boolean;
  readChunkSize: number;
  routingApplyState: RoutingApplyState;
  sampleRate: number;
  sampleRateRestartPending: boolean;
  setCrossFadeOverlap: (value: number) => void;
  setExtraConvert: (value: number) => void;
  setInputDeviceId: (value: number) => void;
  setInputGain: (value: number) => void;
  setMonitorDeviceId: (value: number) => void;
  setOutputDeviceId: (value: number) => void;
  setOutputGain: (value: number) => void;
  setReadChunkSize: (value: number) => void;
  setSampleRate: (value: number) => void;
  statusLoaded: boolean;
  statusStub: boolean;
  virtualCableDetected: boolean;
};

export function VoiceRoutingPanel({
  busy,
  chunkRestartPending,
  crossFadeOverlap,
  deviceMissing,
  extraConvert,
  inputDeviceId,
  inputDevices,
  inputGain,
  inputRestartPending,
  monitorDeviceId,
  monitorRestartPending,
  onPreset,
  outputDeviceId,
  outputDevices,
  outputGain,
  outputIsVirtualCable,
  outputRestartPending,
  readChunkSize,
  routingApplyState,
  sampleRate,
  sampleRateRestartPending,
  setCrossFadeOverlap,
  setExtraConvert,
  setInputDeviceId,
  setInputGain,
  setMonitorDeviceId,
  setOutputDeviceId,
  setOutputGain,
  setReadChunkSize,
  setSampleRate,
  statusLoaded,
  statusStub,
  virtualCableDetected,
}: VoiceRoutingPanelProps) {
  return (
    <Panel
      title="Routing And Timing"
      aside={<RoutingApplyHint canReach={statusLoaded} state={routingApplyState} />}
    >
      <div className="grid gap-3">
        {inputDevices.length ? (
          <DeviceSelect
            label="Input"
            value={inputDeviceId}
            devices={inputDevices}
            fallback="No input selected"
            missing={deviceMissing.input}
            restartPending={inputRestartPending}
            onChange={setInputDeviceId}
          />
        ) : (
          <OfflineDevice label="Input" message={statusLoaded ? "No input devices reported" : "Loading devices"} />
        )}
        {outputDevices.length ? (
          <DeviceSelect
            label="Output"
            value={outputDeviceId}
            devices={outputDevices}
            fallback="No output selected"
            missing={deviceMissing.output}
            restartPending={outputRestartPending}
            onChange={setOutputDeviceId}
          />
        ) : (
          <OfflineDevice label="Output" message={statusLoaded ? "No output devices reported" : "Loading devices"} />
        )}
        {outputDevices.length ? (
          <MonitorSelect
            value={monitorDeviceId}
            devices={outputDevices}
            missing={deviceMissing.monitor}
            restartPending={monitorRestartPending}
            onChange={setMonitorDeviceId}
          />
        ) : (
          <OfflineDevice label="Monitor" message={statusLoaded ? "No output device for monitor" : "Loading devices"} />
        )}
      </div>

      {statusLoaded && !statusStub ? (
        <div className={`mt-3 rounded-md border px-3 py-2 text-xs leading-5 ${
          outputIsVirtualCable
            ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-100/80"
            : virtualCableDetected
              ? "border-amber-400/25 bg-amber-400/10 text-amber-100/80"
              : "border-border bg-sunken text-ui-subtle"
        }`}
        >
          {outputIsVirtualCable ? (
            <>Virtual cable output selected; choose its matching input as the microphone in Discord, OBS, or calls.</>
          ) : virtualCableDetected ? (
            <>Virtual cable detected. Select its playback/input side as Output before starting live routing.</>
          ) : (
            <>
              No virtual audio cable detected for app routing. Install VB-CABLE or Voicemeeter from the official VB-Audio site, then refresh devices.{" "}
              <a className="text-accent-fg underline-offset-2 hover:underline" href="https://vb-audio.com/Cable/" target="_blank" rel="noreferrer">
                Open VB-Audio
              </a>
            </>
          )}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-ui-muted">Sample rate</span>
            {sampleRateRestartPending ? <span className="text-[11px] text-amber-200/70">restart</span> : null}
          </div>
          <Select
            value={String(sampleRate)}
            onChange={(v) => setSampleRate(Number(v))}
            options={sampleRates.map((rate) => ({ value: String(rate), label: `${rate} Hz` }))}
          />
        </label>

        <label>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-ui-muted">Chunk</span>
            {chunkRestartPending ? <span className="text-[11px] text-amber-200/70">restart</span> : null}
          </div>
          <input
            type="number"
            min={1}
            max={1024}
            value={readChunkSize}
            onChange={(event) => setReadChunkSize(clamp(Number(event.target.value), 1, 1024))}
            className={field}
          />
        </label>
      </div>

      <div className="mt-4 grid gap-4">
        <LabeledSlider label="Extra buffer" value={extraConvert} min={0} max={10} step={0.1} onChange={setExtraConvert} valueLabel={`${extraConvert.toFixed(1)} s`} />
        <LabeledSlider label="Crossfade" value={crossFadeOverlap} min={0} max={0.2} step={0.01} onChange={setCrossFadeOverlap} valueLabel={`${Math.round(crossFadeOverlap * 1000)} ms`} />
        <LabeledSlider label="Input gain" value={inputGain} min={0} max={2} step={0.01} onChange={setInputGain} valueLabel={inputGain.toFixed(2)} />
        <LabeledSlider label="Output gain" value={outputGain} min={0} max={2} step={0.01} onChange={setOutputGain} valueLabel={outputGain.toFixed(2)} />
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {latencyPresets.map((preset) => (
          <MiniButton
            key={preset.id}
            onClick={() => onPreset(preset)}
            disabled={!statusLoaded || Boolean(busy)}
            active={readChunkSize === preset.chunk && crossFadeOverlap === preset.crossFade && extraConvert === preset.extra}
          >
            {preset.label}
          </MiniButton>
        ))}
      </div>
    </Panel>
  );
}

type VoicePresetsPanelProps = {
  applyVoicePreset: (preset: VoiceEnginePreset) => void;
  busy: string;
  canApply: boolean;
  models: VoiceModel[];
  onDeleteVoicePreset: () => void;
  onSaveVoicePreset: () => void;
  onUpdateVoicePreset: () => void;
  presetName: string;
  selectVoicePreset: (presetId: string) => void;
  selectedPreset: VoiceEnginePreset | null;
  selectedPresetId: string;
  setPresetName: (value: string) => void;
  voicePresets: VoiceEnginePreset[];
};

export function VoicePresetsPanel({
  applyVoicePreset,
  busy,
  canApply,
  models,
  onDeleteVoicePreset,
  onSaveVoicePreset,
  onUpdateVoicePreset,
  presetName,
  selectVoicePreset,
  selectedPreset,
  selectedPresetId,
  setPresetName,
  voicePresets,
}: VoicePresetsPanelProps) {
  return (
    <Panel title="Presets" aside={<Badge>{voicePresets.length}</Badge>}>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
        <input
          value={presetName}
          onChange={(event) => setPresetName(event.target.value)}
          placeholder={selectedPreset ? selectedPreset.name : "New preset name"}
          className={field}
        />
        <Button onClick={onSaveVoicePreset} disabled={!canApply || !presetName.trim()} className="whitespace-nowrap">
          {busy === "preset-save" ? "Saving..." : "Save As"}
        </Button>
        <Button onClick={onUpdateVoicePreset} disabled={!canApply || !selectedPreset} tone="primary" className="whitespace-nowrap">
          {busy === "preset-update" ? "Updating..." : "Update"}
        </Button>
      </div>

      <div className="mt-3 flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
        {voicePresets.length ? voicePresets.map((preset) => (
          <PresetCard
            key={preset.id}
            preset={preset}
            models={models}
            active={preset.id === selectedPresetId}
            canApply={canApply}
            busy={busy}
            onSelect={() => selectVoicePreset(preset.id)}
            onApply={() => void applyVoicePreset(preset)}
            onUpdate={onUpdateVoicePreset}
            onDelete={onDeleteVoicePreset}
          />
        )) : (
          <div className="ui-card rounded-md px-3 py-3 text-sm text-ui-subtle">
            No saved voice presets yet.
          </div>
        )}
      </div>
    </Panel>
  );
}

type VoiceOfflineConvertPanelProps = {
  models: VoiceModel[];
  offlineBusy: boolean;
  offlineError: string;
  offlineFile: File | null;
  offlineFormant: number;
  offlineModelId: string;
  offlinePitch: number;
  offlineResult: VoiceEngineConvertResult | null;
  onOfflineConvert: () => void;
  ready: boolean;
  setOfflineFile: (file: File | null) => void;
  setOfflineFormant: (value: number) => void;
  setOfflineModelId: (value: string) => void;
  setOfflinePitch: (value: number) => void;
  voiceOptions: SelectOption[];
};

export function VoiceOfflineConvertPanel({
  models,
  offlineBusy,
  offlineError,
  offlineFile,
  offlineFormant,
  offlineModelId,
  offlinePitch,
  offlineResult,
  onOfflineConvert,
  ready,
  setOfflineFile,
  setOfflineFormant,
  setOfflineModelId,
  setOfflinePitch,
  voiceOptions,
}: VoiceOfflineConvertPanelProps) {
  return (
    <Panel
      title="Offline Convert"
      aside={(
        <Badge color={ready ? "bg-emerald-700/55 text-emerald-100" : "bg-amber-600/40 text-amber-100"}>
          {ready ? "ready" : "not ready"}
        </Badge>
      )}
    >
      {offlineError ? (
        <div className="mb-3 rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">{offlineError}</div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[minmax(220px,1fr)_minmax(220px,0.9fr)]">
        <label>
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Audio file</div>
          <input
            type="file"
            accept=".wav,.flac,.ogg,.mp3,audio/wav,audio/flac,audio/ogg,audio/mpeg"
            onChange={(event) => setOfflineFile(event.target.files?.[0] ?? null)}
            className={`${field} file:mr-3 file:rounded file:border-0 file:bg-control-active file:px-2 file:py-1 file:text-xs file:text-ui-muted`}
          />
        </label>
        <label>
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Voice</div>
          <Select
            value={offlineModelId}
            onChange={setOfflineModelId}
            placeholder="no voices"
            options={voiceOptions}
            renderOption={(option) => <VoiceOption option={option} models={models} />}
          />
        </label>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_1fr_auto]">
        <CompactSignedControl label="Pitch" value={offlinePitch} min={-24} max={24} step={1} onChange={(value) => setOfflinePitch(Math.round(value))} unit=" st" />
        <CompactSignedControl label="Formant" value={offlineFormant} min={-2} max={2} step={0.05} precision={2} onChange={setOfflineFormant} />
        <div className="flex items-end">
          <Button onClick={() => void onOfflineConvert()} disabled={!ready || !offlineFile || !offlineModelId || offlineBusy} tone="success" className="w-full xl:w-auto">
            {offlineBusy ? "Converting..." : "Convert"}
          </Button>
        </div>
      </div>

      {offlineResult ? (
        <div className="ui-card mt-4 rounded-md p-3">
          <audio controls src={offlineResult.url} className="w-full" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="flex gap-2">
              <a href={offlineResult.url} download className="ui-button rounded-md px-3 py-1.5">WAV</a>
              <a href={offlineResult.mp3_url} download className="ui-button rounded-md px-3 py-1.5">MP3</a>
            </span>
            <span className="text-xs text-ui-subtle">
              {offlineResult.sample_rate} Hz / {offlineResult.duration_s.toFixed(2)} s / pitch {offlineResult.params.pitch}
              {" / "}formant {offlineResult.params.input_formant.toFixed(2)}
              {" / "}denoise {offlineResult.params.input_denoise}
            </span>
          </div>
          <div className="mt-2 text-xs text-ui-subtle">{timingsLine(offlineResult.timings_ms)}</div>
        </div>
      ) : null}
    </Panel>
  );
}

export function VoiceDiagnosticsPanel({
  meterHistory,
  status,
}: {
  meterHistory: MeterSample[];
  status: VoiceEngineStatus | null;
}) {
  return (
    <Panel title="Diagnostics" aside={<Badge>{formatMs(status?.metrics.total_ms ?? status?.metrics.chunk_ms)}</Badge>}>
      <DiagnosticsCompact status={status} samples={meterHistory} />
    </Panel>
  );
}
