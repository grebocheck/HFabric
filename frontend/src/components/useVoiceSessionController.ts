import { usePreference } from "../lib/preferences";
import { preferences } from "../settings/workspacePreferences";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { MeterSample } from "./VoiceMeters";
import { useVoiceOfflineConversion } from "./useVoiceOfflineConversion";
import { useVoicePresets } from "./useVoicePresets";
import { useVoiceSettings } from "./useVoiceSettings";
import { clamp, focusIsTextEntry } from "./VoicePanelControls";
import {
  feminineVoicePreset,
  latencyPresets,
  lowLatencyVoicePreset,
  nativeRoutingSettingsPatch,
  nativeTuningSettingsPatch,
  nativeVoicePresetSettingsPatch,
  num,
  qualityVoicePreset,
  resolveMonitorDeviceId,
  selectedNativeModelId,
  stableVoicePreset,
  voiceStateToNativePatch,
  waveformSlots,
  type VoiceTuningState,
} from "./voiceHelpers";
import type { VoiceAudioDevice, VoiceEngineRecordingResult } from "../types";

type Profile =
  | typeof stableVoicePreset
  | typeof lowLatencyVoicePreset
  | typeof qualityVoicePreset
  | typeof feminineVoicePreset;

const virtualCablePattern =
  /\b(vb-cable|vb-audio|voicemeeter|virtual cable|cable input|cable output|blackhole|loopback|soundflower)\b/i;
function looksLikeVirtualCable(device: VoiceAudioDevice | undefined): boolean {
  return Boolean(device && virtualCablePattern.test(`${device.name} ${device.host_api}`));
}

export function useVoiceSessionController() {
  const {
    status,
    draft,
    error,
    setError,
    busy,
    refresh,
    updateDraft,
    tuningDirty,
    routingApplyState,
    run,
    applySettings,
  } = useVoiceSettings();
  const [modelId, setModelId] = usePreference(preferences.voiceUi, "modelId");
  const [ptt, setPtt] = useState(false);
  const [voicesOpen, setVoicesOpen] = usePreference(preferences.voiceUi, "voicesOpen");
  const [meterHistory, setMeterHistory] = useState<MeterSample[]>([]);
  const [recordingResult, setRecordingResult] = useState<VoiceEngineRecordingResult | null>(null);
  const {
    pitch,
    protect,
    passThrough,
    inputDeviceId,
    outputDeviceId,
    monitorDeviceId,
    monitorGain,
    sampleRate,
    readChunkSize,
  } = draft;
  const models = useMemo(() => status?.models ?? [], [status]);
  const selected = useMemo(() => models.find((model) => model.id === modelId), [models, modelId]);
  const loadedModel = models.find((model) => model.id === status?.loaded_model);
  const effectiveDraft = { ...draft, indexRatio: selected?.has_index ? draft.indexRatio : 0 };
  const {
    offlineBusy,
    offlineError,
    offlineFile,
    offlineModelId,
    offlinePitch,
    offlineResult,
    onOfflineConvert,
    setOfflineFile,
    setOfflineModelId,
    setOfflinePitch,
  } = useVoiceOfflineConversion(effectiveDraft);
  const {
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
  } = useVoicePresets({
    execute: run,
    modelId,
    models,
    presetSettings: () => nativeVoicePresetSettingsPatch(effectiveDraft),
    setModelId,
    setOfflineModelId,
    updateDraft,
  });

  const inputDevices = status?.audio_devices.inputs ?? [];
  const outputDevices = status?.audio_devices.outputs ?? [];
  const outputIsVirtualCable = looksLikeVirtualCable(
    outputDevices.find((device) => device.index === outputDeviceId),
  );
  const virtualCableDetected = [...inputDevices, ...outputDevices].some(looksLikeVirtualCable);
  const statusLoaded = Boolean(status);
  const ready = Boolean(status?.ready);
  const live = Boolean(status?.live);
  const monitorOn = monitorDeviceId >= 0;
  const recording = Boolean(status?.recording.active);
  const canApply = statusLoaded && !busy;
  const canGoLive = ready && Boolean(modelId) && !busy;
  const sessionConfig = status?.session_config;
  const deviceMissing = status?.settings.device_missing ?? { input: false, output: false, monitor: false };
  const inputRestartPending = Boolean(
    live &&
    sessionConfig &&
    sessionConfig.server_input_device_id !== (inputDeviceId >= 0 ? inputDeviceId : null),
  );
  const outputRestartPending = Boolean(
    live &&
    sessionConfig &&
    sessionConfig.server_output_device_id !== (outputDeviceId >= 0 ? outputDeviceId : null),
  );
  const monitorRestartPending = Boolean(
    live && sessionConfig && (sessionConfig.server_monitor_device_id ?? -1) !== monitorDeviceId,
  );
  const sampleRateRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_audio_sample_rate !== sampleRate,
  );
  const chunkRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_read_chunk_size !== readChunkSize,
  );
  const protectRisk = protect >= 0.5;
  const indexRisk = pitch >= 12 && effectiveDraft.indexRatio > 0.45;
  const outputPeak = status?.metrics.output_peak ?? 0;
  const outputPeakTone: "amber" | "sky" =
    outputPeak >= 0.85 || (status?.metrics.limiter_reduction_db ?? 0) > 0 ? "amber" : "sky";

  useEffect(() => {
    void refresh();
    void refreshPresets();
  }, [refresh, refreshPresets]);
  const assetDownloading = status?.asset_download?.state === "running";
  useEffect(() => {
    const interval = live ? 750 : assetDownloading ? 1200 : 0;
    if (!interval) return;
    const id = window.setInterval(() => {
      void refresh();
    }, interval);
    return () => window.clearInterval(id);
  }, [assetDownloading, live, refresh]);

  useEffect(() => {
    if (!status) return;
    const next = selectedNativeModelId(status.models, modelId, status.loaded_model);
    setModelId(next);
    setOfflineModelId(
      (previous) => selectedNativeModelId(status.models, previous || next, status.loaded_model) || previous,
    );
  }, [modelId, setModelId, setOfflineModelId, status]);
  useEffect(() => {
    if (!status) return;
    const sample = {
      input: Math.max(0, Math.min(1, num(status.metrics.input_vu, 0))),
      output: Math.max(0, Math.min(1, num(status.metrics.output_vu, 0))),
    };
    setMeterHistory((previous) => [...previous.slice(-(waveformSlots - 1)), sample]);
  }, [status]);

  const fullSettingsPatch = () => ({
    ...nativeTuningSettingsPatch(effectiveDraft),
    ...nativeRoutingSettingsPatch(draft),
  });
  const onApply = () => applySettings("apply", fullSettingsPatch());
  const fetchAssets = () => run("assets", () => api.voiceEngineFetchAssets());
  const fetchDtlnAssets = () =>
    run("dtln-assets", () => api.voiceEngineFetchAssets({ names: ["denoise_dtln"], include_optional: true }));
  const selectModel = (value: string) => {
    setModelId(value);
    setOfflineModelId(value);
  };
  const changeTuning = (patch: Partial<VoiceTuningState>) => {
    if (patch.pitch !== undefined) patch = { ...patch, pitch: clamp(Math.round(patch.pitch), -24, 24) };
    if (patch.speakerId !== undefined)
      patch = { ...patch, speakerId: clamp(Math.round(patch.speakerId), 0, 255) };
    updateDraft(patch);
  };

  const onLive = (next: boolean) =>
    run(next ? "live-on" : "live-off", async (save) => {
      if (!next) return api.voiceEngineSessionStop();
      if (!modelId) throw new Error("Select a voice model before starting live mode");
      await save(fullSettingsPatch());
      return api.voiceEngineSessionStart(modelId);
    });
  const onRestartLive = () =>
    run("live-restart", async (save) => {
      const next = modelId || status?.loaded_model;
      if (!next) throw new Error("Select a voice model before restarting live mode");
      await api.voiceEngineSessionStop();
      await save(fullSettingsPatch());
      return api.voiceEngineSessionStart(next);
    });
  const onMonitor = (next: boolean) => {
    if (!next) {
      updateDraft({ monitorDeviceId: -1 });
      return;
    }
    const resolved = resolveMonitorDeviceId(monitorDeviceId, outputDeviceId, outputDevices);
    if (resolved < 0) {
      setError("No output device is available for monitoring");
      return;
    }
    updateDraft({ monitorDeviceId: resolved });
  };
  const onBypass = (next: boolean) => {
    updateDraft({ passThrough: next });
    if (statusLoaded) void applySettings("bypass", { pass_through: next });
  };
  const onPtt = (next: boolean) => {
    setPtt(next);
    if (!statusLoaded) return;
    if (next) updateDraft({ passThrough: true });
    void applySettings("ptt", { pass_through: next || passThrough });
  };
  const onPreset = (preset: (typeof latencyPresets)[number]) =>
    updateDraft({
      readChunkSize: preset.chunk,
      crossFadeOverlap: preset.crossFade,
      extraConvert: preset.extra,
    });
  const applyQualityProfile = (label: string, profile: Profile, pitchOverride?: number) => {
    const patch = {
      ...profile,
      pitch: pitchOverride ?? pitch,
      indexRatio: selected?.has_index ? profile.indexRatio : 0,
    };
    updateDraft(patch);
    void applySettings(label, { ...voiceStateToNativePatch(patch), input_formant: 0, input_gate_db: -90 });
  };
  const onStable = () => applyQualityProfile("stable-preset", stableVoicePreset);
  const onLowLatency = () => applyQualityProfile("low-latency-preset", lowLatencyVoicePreset);
  const onQuality = () => applyQualityProfile("quality-preset", qualityVoicePreset);
  const onFeminine = () =>
    applyQualityProfile("female-preset", feminineVoicePreset, feminineVoicePreset.pitch);
  const onRecording = (next: boolean) =>
    run(next ? "record-on" : "record-off", async () => {
      if (next) {
        setRecordingResult(null);
        return api.voiceEngineRecordingStart();
      }
      const updated = await api.voiceEngineRecordingStop();
      setRecordingResult(updated.recording_result ?? null);
      return updated;
    });

  useEffect(() => {
    if (!ptt || !statusLoaded) return;
    const onDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || focusIsTextEntry() || event.repeat) return;
      event.preventDefault();
      void applySettings("ptt", { pass_through: false });
    };
    const onUp = (event: KeyboardEvent) => {
      if (event.code !== "Space" || focusIsTextEntry()) return;
      event.preventDefault();
      void applySettings("ptt", { pass_through: true });
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [applySettings, ptt, statusLoaded]);

  const assetsFound = (status?.assets ?? []).filter((asset) => asset.found).length;
  const totalAssets = status?.assets.length ?? 0;
  const denoiseDtlnMissing = Boolean(
    (status?.assets ?? []).find((asset) => asset.name === "denoise_dtln" && !asset.found),
  );
  const voiceOptions = models.map((m) => ({
    value: m.id,
    label: m.name,
    hint: `${m.source ?? "local"} ${m.slot}`,
  }));
  const selectedSupportsPitch = selected?.f0 !== false;

  return {
    header: {
      busy,
      canApply,
      error,
      live,
      onApply,
      refresh,
      selected,
      tuningDirty,
    },
    engine: {
      assetsFound,
      busy,
      denoiseDtlnMissing,
      loadedModel,
      modelId,
      models,
      onFetchAssets: () => {
        void fetchAssets();
      },
      onFetchDtlnAssets: () => {
        void fetchDtlnAssets();
      },
      onModelChange: selectModel,
      onModelListToggle: () => setVoicesOpen((open) => !open),
      onModelSelect: selectModel,
      ready,
      selected,
      status,
      totalAssets,
      voicesOpen,
      voiceOptions,
    },
    live: {
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
      setMonitorGain: (value: number) => updateDraft({ monitorGain: value }),
      status,
      statusLoaded,
    },
    tuning: {
      busy,
      canApply,
      draft: effectiveDraft,
      onChange: changeTuning,
      indexRisk,
      protectRisk,
      ptt,
      onBypass,
      onPtt,
      onStable,
      onLowLatency,
      onQuality,
      onFeminine,
      selectedHasIndex: Boolean(selected?.has_index),
      selectedName: selected?.name ?? "no voice selected",
      selectedSupportsPitch,
      statusLoaded,
    },
    routing: {
      busy,
      draft,
      onChange: updateDraft,
      chunkRestartPending,
      deviceMissing,
      inputDevices,
      inputRestartPending,
      monitorRestartPending,
      onPreset,
      outputDevices,
      outputIsVirtualCable,
      outputRestartPending,
      routingApplyState,
      sampleRateRestartPending,
      statusLoaded,
      statusStub: Boolean(status?.stub),
      virtualCableDetected,
    },
    presets: {
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
    },
    offline: {
      models,
      offlineBusy,
      offlineError,
      offlineFile,
      offlineModelId,
      offlinePitch,
      offlineResult,
      onOfflineConvert,
      ready,
      setOfflineFile,
      setOfflineModelId,
      setOfflinePitch,
      voiceOptions,
    },
    diagnostics: { meterHistory, status },
  };
}
