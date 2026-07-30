import { Select } from "./Select";
import { LabeledSlider, MiniButton, Panel, clamp, field } from "./VoicePanelControls";
import {
  DeviceSelect,
  MonitorSelect,
  OfflineDevice,
  RoutingApplyHint,
  type RoutingApplyState,
} from "./VoicePanelParts";
import { deviceNumericId, latencyPresets, sampleRates } from "./voiceHelpers";
import type { VoiceAudioDevice } from "../types";

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
  const selectedInput = inputDevices.find((device) => deviceNumericId(device) === inputDeviceId);
  const selectedOutput = outputDevices.find((device) => deviceNumericId(device) === outputDeviceId);
  const legacyHostApi = [selectedInput, selectedOutput].some((device) =>
    String(device?.host_api ?? "").toLowerCase().includes("mme"),
  );
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
          <OfflineDevice
            label="Input"
            message={statusLoaded ? "No input devices reported" : "Loading devices"}
          />
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
          <OfflineDevice
            label="Output"
            message={statusLoaded ? "No output devices reported" : "Loading devices"}
          />
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
          <OfflineDevice
            label="Monitor"
            message={statusLoaded ? "No output device for monitor" : "Loading devices"}
          />
        )}
      </div>

      {legacyHostApi ? (
        <div className="mt-3 rounded-md border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-xs text-amber-100/80">
          MME adds large driver buffers. Select the matching 48 kHz WASAPI microphone and virtual-cable
          endpoints for lower latency and fewer underruns.
        </div>
      ) : null}

      {statusLoaded && !statusStub ? (
        <div
          className={`mt-3 rounded-md border px-3 py-2 text-xs leading-5 ${
            outputIsVirtualCable
              ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-100/80"
              : virtualCableDetected
                ? "border-amber-400/25 bg-amber-400/10 text-amber-100/80"
                : "border-border bg-sunken text-ui-subtle"
          }`}
        >
          {outputIsVirtualCable ? (
            <>
              Virtual cable output selected; choose its matching input as the microphone in Discord, OBS, or
              calls.
            </>
          ) : virtualCableDetected ? (
            <>
              Virtual cable detected. Select its playback/input side as Output before starting live routing.
            </>
          ) : (
            <>
              No virtual audio cable detected for app routing. Install VB-CABLE or Voicemeeter from the
              official VB-Audio site, then refresh devices.{" "}
              <a
                className="text-accent-fg underline-offset-2 hover:underline"
                href="https://vb-audio.com/Cable/"
                target="_blank"
                rel="noreferrer"
              >
                Open VB-Audio
              </a>
            </>
          )}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-ui-muted">Sample rate</span>
            {sampleRateRestartPending ? <span className="text-[11px] text-amber-200/70">restart</span> : null}
          </div>
          <Select
            ariaLabel="Voice sample rate"
            value={String(sampleRate)}
            onChange={(v) => setSampleRate(Number(v))}
            options={sampleRates.map((rate) => ({ value: String(rate), label: `${rate} Hz` }))}
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-ui-muted">Chunk</span>
            {chunkRestartPending ? <span className="text-[11px] text-amber-200/70">restart</span> : null}
          </div>
          <input
            type="number"
            min={30}
            max={1020}
            step={15}
            value={readChunkSize}
            onChange={(event) => {
              const raw = clamp(Number(event.target.value), 30, 1020);
              setReadChunkSize(Math.round(raw / 15) * 15);
            }}
            className={field}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-4">
        <LabeledSlider
          label="Analysis context"
          value={extraConvert}
          min={0}
          max={10}
          step={0.1}
          onChange={setExtraConvert}
          valueLabel={`${extraConvert.toFixed(1)} s`}
        />
        <LabeledSlider
          label="Crossfade"
          value={crossFadeOverlap}
          min={0}
          max={0.2}
          step={0.01}
          onChange={setCrossFadeOverlap}
          valueLabel={`${Math.round(crossFadeOverlap * 1000)} ms`}
        />
        <LabeledSlider
          label="Input gain"
          value={inputGain}
          min={0}
          max={2}
          step={0.01}
          onChange={setInputGain}
          valueLabel={inputGain.toFixed(2)}
        />
        <LabeledSlider
          label="Output gain"
          value={outputGain}
          min={0}
          max={2}
          step={0.01}
          onChange={setOutputGain}
          valueLabel={outputGain.toFixed(2)}
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {latencyPresets.map((preset) => (
          <MiniButton
            key={preset.id}
            onClick={() => onPreset(preset)}
            disabled={!statusLoaded || Boolean(busy)}
            active={
              readChunkSize === preset.chunk &&
              crossFadeOverlap === preset.crossFade &&
              extraConvert === preset.extra
            }
          >
            {preset.label}
          </MiniButton>
        ))}
      </div>
    </Panel>
  );
}
