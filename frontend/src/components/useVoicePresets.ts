import { usePreference } from "../lib/preferences";
import { preferences } from "../settings/workspacePreferences";
import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import type { VoiceEnginePreset, VoiceEngineSettingsUpdate, VoiceModel } from "../types";
import type { VoiceOperation } from "./useVoiceSettings";
import { nativeSettingsToVoicePatch, type VoiceControlState } from "./voiceHelpers";

type VoicePresetControllerOptions = {
  execute: (label: string, operation: VoiceOperation) => Promise<boolean>;
  modelId: string;
  models: VoiceModel[];
  presetSettings: () => VoiceEngineSettingsUpdate;
  setModelId: (modelId: string) => void;
  setOfflineModelId: (modelId: string) => void;
  updateDraft: (patch: Partial<VoiceControlState>) => void;
};

export function useVoicePresets({
  execute,
  modelId,
  models,
  presetSettings,
  setModelId,
  setOfflineModelId,
  updateDraft,
}: VoicePresetControllerOptions) {
  const [voicePresets, setVoicePresets] = useState<VoiceEnginePreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = usePreference(preferences.voiceUi, "selectedPresetId");
  const [presetName, setPresetName] = useState("");
  const selectedPreset = useMemo(
    () => voicePresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [selectedPresetId, voicePresets],
  );

  const refreshPresets = useCallback(async () => {
    try {
      const next = await api.voiceEnginePresets();
      setVoicePresets(next);
      setSelectedPresetId((current) =>
        current && next.some((preset) => preset.id === current) ? current : (next[0]?.id ?? ""),
      );
    } catch {
      setVoicePresets([]);
    }
  }, [setSelectedPresetId]);

  const selectVoicePreset = (presetId: string) => {
    setSelectedPresetId(presetId);
    const preset = voicePresets.find((item) => item.id === presetId);
    if (preset) setPresetName(preset.name);
  };

  const onSaveVoicePreset = () =>
    execute("preset-save", async () => {
      const saved = await api.voiceEnginePresetCreate({
        name: presetName,
        model_id: modelId || null,
        settings: presetSettings(),
      });
      setVoicePresets(await api.voiceEnginePresets());
      setSelectedPresetId(saved.id);
      setPresetName(saved.name);
      return null;
    });

  const applyVoicePreset = (preset: VoiceEnginePreset) => {
    updateDraft(nativeSettingsToVoicePatch(preset.settings));
    return execute("preset-apply", async (save) => {
      setSelectedPresetId(preset.id);
      setPresetName(preset.name);
      if (preset.model_id && models.some((model) => model.id === preset.model_id)) {
        setModelId(preset.model_id);
        setOfflineModelId(preset.model_id);
      }
      return save(preset.settings);
    });
  };

  const onUpdateVoicePreset = () =>
    execute("preset-update", async () => {
      if (!selectedPreset) throw new Error("Choose a saved preset first");
      const updated = await api.voiceEnginePresetUpdate(selectedPreset.id, {
        name: presetName.trim() || selectedPreset.name,
        model_id: modelId || null,
        settings: presetSettings(),
      });
      setVoicePresets(await api.voiceEnginePresets());
      setSelectedPresetId(updated.id);
      setPresetName(updated.name);
      return null;
    });

  const onDeleteVoicePreset = () =>
    execute("preset-delete", async () => {
      if (!selectedPreset) throw new Error("Choose a saved preset first");
      await api.voiceEnginePresetDelete(selectedPreset.id);
      await refreshPresets();
      setPresetName("");
      return null;
    });

  return {
    applyVoicePreset,
    onDeleteVoicePreset,
    onSaveVoicePreset,
    onUpdateVoicePreset,
    presetName,
    refreshPresets,
    selectVoicePreset,
    selectedPreset,
    selectedPresetId,
    setPresetName,
    voicePresets,
  };
}
