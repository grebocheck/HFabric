import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import type { VoiceEnginePreset, VoiceEngineSettingsUpdate, VoiceEngineStatus, VoiceModel } from "../types";

type VoicePresetControllerOptions = {
  execute: (label: string, operation: () => Promise<VoiceEngineStatus | null | void>) => Promise<void>;
  modelId: string;
  models: VoiceModel[];
  presetSettings: () => VoiceEngineSettingsUpdate;
  setModelId: (modelId: string) => void;
  setOfflineModelId: (modelId: string) => void;
  setTuningDirty: (dirty: boolean) => void;
};

export function useVoicePresets({
  execute,
  modelId,
  models,
  presetSettings,
  setModelId,
  setOfflineModelId,
  setTuningDirty,
}: VoicePresetControllerOptions) {
  const [voicePresets, setVoicePresets] = useState<VoiceEnginePreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
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
  }, []);

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

  const applyVoicePreset = (preset: VoiceEnginePreset) =>
    execute("preset-apply", async () => {
      setSelectedPresetId(preset.id);
      setPresetName(preset.name);
      if (preset.model_id && models.some((model) => model.id === preset.model_id)) {
        setModelId(preset.model_id);
        setOfflineModelId(preset.model_id);
      }
      const next = await api.voiceEngineSettings(preset.settings);
      setTuningDirty(false);
      return next;
    });

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
      setTuningDirty(false);
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
