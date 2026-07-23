import { Badge } from "./Badge";
import { Select, type SelectOption } from "./Select";
import { Button, CompactSignedControl, Panel, VoiceOption, field, timingsLine } from "./VoicePanelControls";
import type { VoiceEngineConvertResult, VoiceModel } from "../types";

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
      aside={
        <Badge color={ready ? "bg-emerald-700/55 text-emerald-100" : "bg-amber-600/40 text-amber-100"}>
          {ready ? "ready" : "not ready"}
        </Badge>
      }
    >
      {offlineError ? (
        <div className="mb-3 rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
          {offlineError}
        </div>
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
        <div>
          <div className="mb-1.5 text-xs font-medium text-ui-muted">Voice</div>
          <Select
            ariaLabel="Offline conversion voice"
            value={offlineModelId}
            onChange={setOfflineModelId}
            placeholder="no voices"
            options={voiceOptions}
            renderOption={(option) => <VoiceOption option={option} models={models} />}
          />
        </div>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_1fr_auto]">
        <CompactSignedControl
          label="Pitch"
          value={offlinePitch}
          min={-24}
          max={24}
          step={1}
          onChange={(value) => setOfflinePitch(Math.round(value))}
          unit=" st"
        />
        <CompactSignedControl
          label="Formant"
          value={offlineFormant}
          min={-2}
          max={2}
          step={0.05}
          precision={2}
          onChange={setOfflineFormant}
        />
        <div className="flex items-end">
          <Button
            onClick={() => void onOfflineConvert()}
            disabled={!ready || !offlineFile || !offlineModelId || offlineBusy}
            tone="success"
            className="w-full xl:w-auto"
          >
            {offlineBusy ? "Converting..." : "Convert"}
          </Button>
        </div>
      </div>

      {offlineResult ? (
        <div className="ui-card mt-4 rounded-md p-3">
          <audio controls src={offlineResult.url} className="w-full" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="flex gap-2">
              <a href={offlineResult.url} download className="ui-button rounded-md px-3 py-1.5">
                WAV
              </a>
              <a href={offlineResult.mp3_url} download className="ui-button rounded-md px-3 py-1.5">
                MP3
              </a>
            </span>
            <span className="text-xs text-ui-subtle">
              {offlineResult.sample_rate} Hz / {offlineResult.duration_s.toFixed(2)} s / pitch{" "}
              {offlineResult.params.pitch}
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
