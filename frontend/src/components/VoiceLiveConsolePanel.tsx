import { Badge } from "./Badge";
import { Toggle } from "./Toggle";
import { assetSearchHint, Button, LabeledSlider, Panel } from "./VoicePanelControls";
import { LatencyMeter } from "./VoicePanelParts";
import { Meter } from "./VoiceMeters";
import { deviceName, formatMs, meter } from "./voiceHelpers";
import type { VoiceAudioDevice, VoiceEngineRecordingResult, VoiceEngineStatus, VoiceModel } from "../types";

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
      aside={
        <Badge color={live ? "bg-success-bg text-success-fg" : "ui-chip"}>
          {live ? "on air" : "stopped"}
        </Badge>
      }
    >
      {status?.session_error ? (
        <div className="mb-3 rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
          {status.session_error}
        </div>
      ) : null}

      <div
        className={`rounded-md border p-4 ${live ? "border-success-border bg-success-bg" : "border-border bg-sunken"}`}
      >
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="truncate text-base font-semibold text-ui-strong">
              {live ? "Live voice is running" : "Live voice is off"}
            </div>
            <div className="mt-1 truncate text-sm text-ui-subtle">
              {deviceName(inputDevices, inputDeviceId, "input")}
              {" -> "}
              {selected?.name ?? "voice"}
              {" -> "}
              {deviceName(outputDevices, outputDeviceId, "output")}
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
            {busy
              ? "busy..."
              : !ready
                ? assetSearchHint
                : !modelId
                  ? "select a voice model"
                  : "cannot start right now"}
          </div>
        ) : null}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Meter label="Input" value={meter(status?.metrics.input_vu ?? 0)} />
        <Meter
          label={monitorOn ? "Output / Monitor" : "Output"}
          value={meter(status?.metrics.output_vu ?? 0)}
          tone="sky"
        />
        <Meter label="Output peak" value={meter(outputPeak)} tone={outputPeakTone} />
        <LatencyMeter
          value={
            status?.metrics.measured_latency_p95_ms ??
            status?.metrics.measured_latency_ms ??
            status?.metrics.estimated_latency_ms ??
            status?.metrics.chunk_ms
          }
        />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.75fr)]">
        <div
          className={`rounded-md border px-3 py-2 ${recording ? "border-error-border bg-error-bg" : "border-border bg-sunken"}`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ui">Recorder</span>
                <Badge color={recording ? "bg-error-bg text-error-fg" : "ui-chip"}>
                  {recording ? `${(status?.recording.duration_s ?? 0).toFixed(1)} s` : "ready"}
                </Badge>
              </div>
              <div className="mt-0.5 truncate text-xs text-ui-subtle">
                {recordingResult
                  ? `${recordingResult.sample_rate} Hz / ${recordingResult.duration_s.toFixed(2)} s`
                  : "live output"}
              </div>
            </div>
            <Button
              onClick={() => onRecording(!recording)}
              disabled={!live || Boolean(busy)}
              tone={recording ? "danger" : "ghost"}
            >
              {busy === "record-on"
                ? "Starting..."
                : busy === "record-off"
                  ? "Saving..."
                  : recording
                    ? "Save"
                    : "Record"}
            </Button>
          </div>
          {recordingResult ? (
            <div className="mt-3 grid gap-2">
              <div>
                <div className="mb-1 text-[11px] font-medium text-ui-subtle">Output</div>
                <audio controls src={recordingResult.url} className="w-full" />
              </div>
              {recordingResult.raw_url ? (
                <div>
                  <div className="mb-1 text-[11px] font-medium text-ui-subtle">Raw</div>
                  <audio controls src={recordingResult.raw_url} className="w-full" />
                </div>
              ) : null}
              <div className="mt-1 flex flex-wrap justify-end gap-2">
                <a href={recordingResult.url} download className="ui-button rounded px-2 py-1 text-xs">
                  WAV
                </a>
                <a href={recordingResult.mp3_url} download className="ui-button rounded px-2 py-1 text-xs">
                  MP3
                </a>
                {recordingResult.raw_url ? (
                  <a href={recordingResult.raw_url} download className="ui-button rounded px-2 py-1 text-xs">
                    Raw
                  </a>
                ) : null}
                {recordingResult.metadata_url ? (
                  <a
                    href={recordingResult.metadata_url}
                    download
                    className="ui-button rounded px-2 py-1 text-xs"
                  >
                    JSON
                  </a>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <div
          className={`rounded-md border px-3 py-2 ${monitorOn ? "border-info-border bg-info-bg" : "border-border bg-sunken"}`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ui">Monitor</span>
                <Badge color={monitorOn ? "bg-info-bg text-info-fg" : "ui-chip"}>
                  {monitorOn ? "on" : "off"}
                </Badge>
              </div>
              <div
                className="mt-0.5 truncate text-xs text-ui-subtle"
                title={deviceName(outputDevices, monitorDeviceId, "Off")}
              >
                {deviceName(outputDevices, monitorDeviceId, "Off")}
              </div>
            </div>
            <Toggle
              checked={monitorOn}
              onChange={onMonitor}
              disabled={!statusLoaded || outputDevices.length === 0}
              ariaLabel="Toggle monitor"
            />
          </div>
          <div className="mt-2">
            <LabeledSlider
              label="Monitor gain"
              value={monitorGain}
              min={0}
              max={2}
              step={0.01}
              onChange={setMonitorGain}
            />
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
        <Badge>input q {formatMs(status?.metrics.input_queue_ms)}</Badge>
        <Badge>output q {formatMs(status?.metrics.output_queue_ms)}</Badge>
        {status?.metrics.clock_drift_ppm != null ? (
          <Badge
            color={
              Math.abs(status.metrics.clock_drift_ppm) > 100
                ? "bg-warn-bg text-warn-fg"
                : "ui-chip"
            }
          >
            drift {status.metrics.clock_drift_ppm.toFixed(1)} ppm
          </Badge>
        ) : null}
        <Badge
          color={
            status?.metrics.squelched
              ? "bg-amber-600/40 text-amber-100"
              : "bg-emerald-700/45 text-emerald-100"
          }
        >
          {status?.metrics.squelched ? "silence" : "voice"}
        </Badge>
      </div>
    </Panel>
  );
}
