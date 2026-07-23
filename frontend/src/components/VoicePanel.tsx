import { Badge } from "./Badge";
import {
  VoiceDiagnosticsPanel,
  VoiceLiveConsolePanel,
  VoiceOfflineConvertPanel,
  VoicePresetsPanel,
  VoiceRoutingPanel,
  VoiceTuningPanel,
} from "./VoicePanelSections";
import { Button } from "./VoicePanelControls";
import { VoiceEnginePanel } from "./VoiceEnginePanel";
import { useVoiceSessionController } from "./useVoiceSessionController";

export function VoicePanel() {
  const view = useVoiceSessionController();
  const { header } = view;

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto p-1">
      <header className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-ui-strong">Voice Changer</h2>
            <Badge color={header.live ? "bg-success-bg text-success-fg" : "ui-chip"}>
              {header.live ? "live" : "idle"}
            </Badge>
            {header.tuningDirty ? <Badge color="bg-amber-600/40 text-amber-100">unsaved tuning</Badge> : null}
          </div>
          <p className="mt-1 truncate text-sm text-ui-subtle">
            {header.selected?.name ?? "No voice selected"} {header.selected ? "->" : ""}{" "}
            {header.live ? "microphone lane active" : "ready for setup"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void header.refresh()} disabled={Boolean(header.busy)}>
            Refresh
          </Button>
          <Button
            onClick={header.onApply}
            disabled={!header.canApply}
            tone={header.tuningDirty ? "primary" : "ghost"}
          >
            {header.busy === "apply" ? "Applying..." : header.tuningDirty ? "Apply Changes" : "Apply"}
          </Button>
        </div>
      </header>

      {header.error ? (
        <div className="rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
          {header.error}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.92fr)_minmax(0,1.45fr)]">
        <VoiceEnginePanel {...view.engine} />
        <VoiceLiveConsolePanel {...view.live} />
      </div>
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <VoiceTuningPanel {...view.tuning} />
        <VoiceRoutingPanel {...view.routing} />
      </div>
      <div className="grid gap-4 2xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <VoicePresetsPanel {...view.presets} />
        <VoiceOfflineConvertPanel {...view.offline} />
        <VoiceDiagnosticsPanel {...view.diagnostics} />
      </div>
    </div>
  );
}
