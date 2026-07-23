import { Badge } from "./Badge";
import { Button, Panel, PresetCard, field } from "./VoicePanelControls";
import type { VoiceEnginePreset, VoiceModel } from "../types";

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
        <Button
          onClick={onSaveVoicePreset}
          disabled={!canApply || !presetName.trim()}
          className="whitespace-nowrap"
        >
          {busy === "preset-save" ? "Saving..." : "Save As"}
        </Button>
        <Button
          onClick={onUpdateVoicePreset}
          disabled={!canApply || !selectedPreset}
          tone="primary"
          className="whitespace-nowrap"
        >
          {busy === "preset-update" ? "Updating..." : "Update"}
        </Button>
      </div>

      <div className="mt-3 flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
        {voicePresets.length ? (
          voicePresets.map((preset) => (
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
          ))
        ) : (
          <div className="ui-card rounded-md px-3 py-3 text-sm text-ui-subtle">
            No saved voice presets yet.
          </div>
        )}
      </div>
    </Panel>
  );
}
