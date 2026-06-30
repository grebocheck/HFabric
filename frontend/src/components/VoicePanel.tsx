import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Badge } from "./Badge";
import { Select } from "./Select";
import type { MeterSample } from "./VoiceMeters";
import {
  Row,
  VoiceSlotList,
  type RoutingApplyState,
} from "./VoicePanelParts";
import {
  Button,
  ModelBadges,
  Panel,
  StatusTile,
  VoiceOption,
  assetTitle,
  clamp,
  focusIsTextEntry,
  modelDirHint,
  parseApiError,
  routingKey,
} from "./VoicePanelControls";
import {
  VoiceDiagnosticsPanel,
  VoiceLiveConsolePanel,
  VoiceOfflineConvertPanel,
  VoicePresetsPanel,
  VoiceRoutingPanel,
  VoiceTuningPanel,
} from "./VoicePanelSections";
import {
  clearVoicePreset,
  feminineVoicePreset,
  formatBytes,
  latencyPresets,
  nativeRoutingSettingsPatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
  nativeVoicePresetSettingsPatch,
  num,
  recommendedVoicePreset,
  resolveMonitorDeviceId,
  selectedNativeModelId,
  smoothVoicePreset,
  waveformSlots,
} from "./voiceHelpers";
import type {
  VoiceAudioDevice,
  VoiceEngineConvertResult,
  VoiceEnginePreset,
  VoiceEngineRecordingResult,
  VoiceEngineSettingsUpdate,
  VoiceEngineStatus,
} from "../types";

type Profile =
  | typeof recommendedVoicePreset
  | typeof clearVoicePreset
  | typeof smoothVoicePreset
  | typeof feminineVoicePreset;

const virtualCablePattern = /\b(vb-cable|vb-audio|voicemeeter|virtual cable|cable input|cable output|blackhole|loopback|soundflower)\b/i;

function looksLikeVirtualCable(device: VoiceAudioDevice | undefined): boolean {
  if (!device) return false;
  return virtualCablePattern.test(`${device.name} ${device.host_api}`);
}

export function VoicePanel() {
  const [status, setStatus] = useState<VoiceEngineStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [modelId, setModelId] = useState("");
  const [pitch, setPitch] = useState(0);
  const [speakerId, setSpeakerId] = useState(0);
  const [formantShift, setFormantShift] = useState(0);
  const [inputGateDb, setInputGateDb] = useState(-90);
  const [inputHighpassHz, setInputHighpassHz] = useState(80);
  const [inputDenoise, setInputDenoise] = useState<"off" | "dtln">("off");
  const [inputDenoiseMix, setInputDenoiseMix] = useState(0.75);
  const [silenceThresholdDb, setSilenceThresholdDb] = useState(-72);
  const [silenceHoldMs, setSilenceHoldMs] = useState(250);
  const [indexRatio, setIndexRatio] = useState(0.55);
  const [protect, setProtect] = useState(0.5);
  const [noiseScale, setNoiseScale] = useState(0.66666);
  const [f0Smoothing, setF0Smoothing] = useState(0);
  const [f0Detector, setF0Detector] = useState("fcpe");
  const [passThrough, setPassThrough] = useState(false);
  const [ptt, setPtt] = useState(false);
  const [inputDeviceId, setInputDeviceId] = useState(-1);
  const [outputDeviceId, setOutputDeviceId] = useState(-1);
  const [monitorDeviceId, setMonitorDeviceId] = useState(-1);
  const [sampleRate, setSampleRate] = useState(48000);
  const [readChunkSize, setReadChunkSize] = useState(133);
  const [crossFadeOverlap, setCrossFadeOverlap] = useState(0.05);
  const [extraConvert, setExtraConvert] = useState(2);
  const [inputGain, setInputGain] = useState(1);
  const [outputGain, setOutputGain] = useState(1);
  const [monitorGain, setMonitorGain] = useState(1);
  const [meterHistory, setMeterHistory] = useState<MeterSample[]>([]);
  const [voicesOpen, setVoicesOpen] = useState(false);
  const [tuningDirty, setTuningDirty] = useState(false);
  const [routingApplyState, setRoutingApplyState] = useState<RoutingApplyState>("idle");
  const [offlineFile, setOfflineFile] = useState<File | null>(null);
  const [offlineModelId, setOfflineModelId] = useState("");
  const [offlinePitch, setOfflinePitch] = useState(0);
  const [offlineFormant, setOfflineFormant] = useState(0);
  const [offlineBusy, setOfflineBusy] = useState(false);
  const [offlineError, setOfflineError] = useState("");
  const [offlineResult, setOfflineResult] = useState<VoiceEngineConvertResult | null>(null);
  const [recordingResult, setRecordingResult] = useState<VoiceEngineRecordingResult | null>(null);
  const [voicePresets, setVoicePresets] = useState<VoiceEnginePreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const lastAppliedRoutingKeyRef = useRef("");
  const routingApplySeq = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const next = await api.voiceEngineStatus();
      setStatus(next);
      setError("");
      return next;
    } catch (err) {
      setError(parseApiError(err) || "failed to load native voice status");
      return null;
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    setBusy("assets");
    try {
      setStatus(await api.voiceEngineFetchAssets());
      setError("");
    } catch (err) {
      setError(parseApiError(err) || "could not start the voice-asset download");
    } finally {
      setBusy("");
    }
  }, []);

  const fetchDtlnAssets = useCallback(async () => {
    setBusy("dtln-assets");
    try {
      setStatus(await api.voiceEngineFetchAssets({ names: ["denoise_dtln"], include_optional: true }));
      setError("");
    } catch (err) {
      setError(parseApiError(err) || "could not start the DTLN asset download");
    } finally {
      setBusy("");
    }
  }, []);

  const refreshPresets = useCallback(async () => {
    try {
      const next = await api.voiceEnginePresets();
      setVoicePresets(next);
      setSelectedPresetId((current) => (current && next.some((preset) => preset.id === current) ? current : next[0]?.id ?? ""));
    } catch {
      setVoicePresets([]);
    }
  }, []);

  const models = useMemo(() => status?.models ?? [], [status]);
  const inputDevices = status?.audio_devices.inputs ?? [];
  const outputDevices = status?.audio_devices.outputs ?? [];
  const selectedOutputDevice = outputDevices.find((device) => device.index === outputDeviceId);
  const virtualCableDetected = [...inputDevices, ...outputDevices].some(looksLikeVirtualCable);
  const outputIsVirtualCable = looksLikeVirtualCable(selectedOutputDevice);
  const selected = useMemo(() => models.find((m) => m.id === modelId), [models, modelId]);
  const loadedModel = useMemo(
    () => models.find((m) => m.id === status?.loaded_model),
    [models, status?.loaded_model],
  );
  const statusLoaded = Boolean(status);
  const ready = Boolean(status?.ready);
  const live = Boolean(status?.live);
  const monitorOn = monitorDeviceId >= 0;
  const recording = Boolean(status?.recording.active);
  const canApply = statusLoaded && !busy;
  const canGoLive = ready && Boolean(modelId) && !busy;
  const selectedPreset = useMemo(
    () => voicePresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [selectedPresetId, voicePresets],
  );
  const sessionConfig = status?.session_config ?? null;
  const deviceMissing = status?.settings.device_missing ?? { input: false, output: false, monitor: false };
  const inputRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_input_device_id !== (inputDeviceId >= 0 ? inputDeviceId : null),
  );
  const outputRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_output_device_id !== (outputDeviceId >= 0 ? outputDeviceId : null),
  );
  const monitorRestartPending = Boolean(
    live
      && sessionConfig
      && (sessionConfig.server_monitor_device_id == null || sessionConfig.server_monitor_device_id < 0
        ? -1
        : sessionConfig.server_monitor_device_id) !== (monitorDeviceId >= 0 ? monitorDeviceId : -1),
  );
  const sampleRateRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_audio_sample_rate !== sampleRate,
  );
  const chunkRestartPending = Boolean(
    live && sessionConfig && sessionConfig.server_read_chunk_size !== readChunkSize,
  );
  const protectRisk = protect >= 0.5;
  const plus12Tuning = pitch >= 12;
  const indexRisk = plus12Tuning && indexRatio > 0.45;
  const noiseRisk = plus12Tuning && (noiseScale < 0.4 || noiseScale > 0.6);
  const outputPeak = status?.metrics.output_peak ?? 0;
  const outputPeakTone = outputPeak >= 0.85 || (status?.metrics.limiter_reduction_db ?? 0) > 0 ? "amber" : "sky";

  const routingPatch = useMemo(() => nativeRoutingSettingsPatch({
    inputDeviceId,
    outputDeviceId,
    monitorDeviceId,
    sampleRate,
    readChunkSize,
    crossFadeOverlap,
    extraConvert,
    inputGain,
    outputGain,
    monitorGain,
  }), [
    crossFadeOverlap,
    extraConvert,
    inputDeviceId,
    inputGain,
    monitorDeviceId,
    monitorGain,
    outputDeviceId,
    outputGain,
    readChunkSize,
    sampleRate,
  ]);
  const currentRoutingKey = useMemo(() => routingKey(routingPatch), [routingPatch]);

  useEffect(() => {
    void refresh();
    void refreshPresets();
  }, [refresh, refreshPresets]);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => {
      void refresh();
    }, 750);
    return () => window.clearInterval(id);
  }, [live, refresh]);

  // While a voice-asset download runs in the background, poll so the banner shows
  // progress and the assets flip to "found" the moment they land.
  const assetDownloading = status?.asset_download?.state === "running";
  useEffect(() => {
    if (!assetDownloading) return;
    const id = window.setInterval(() => {
      void refresh();
    }, 1200);
    return () => window.clearInterval(id);
  }, [assetDownloading, refresh]);

  useEffect(() => {
    if (!status) return;
    const nextModelId = selectedNativeModelId(status.models, modelId, status.loaded_model);
    setModelId(nextModelId);
    setOfflineModelId((prev) => selectedNativeModelId(status.models, prev || nextModelId, status.loaded_model) || prev);
    const next = nativeSettingsToVoiceState(status.settings);

    if (!tuningDirty) {
      setPitch(next.pitch);
      setOfflinePitch(next.pitch);
      setSpeakerId(next.speakerId);
      setFormantShift(next.formantShift);
      setOfflineFormant(next.formantShift);
      setInputGateDb(next.inputGateDb);
      setInputHighpassHz(next.inputHighpassHz);
      setInputDenoise(next.inputDenoise);
      setInputDenoiseMix(next.inputDenoiseMix);
      setSilenceThresholdDb(next.silenceThresholdDb);
      setSilenceHoldMs(next.silenceHoldMs);
      setIndexRatio(next.indexRatio);
      setProtect(next.protect);
      setNoiseScale(next.noiseScale);
      setF0Smoothing(next.f0Smoothing);
      setF0Detector(next.f0Detector);
      setPassThrough(next.passThrough);
    }

    if (routingApplyState !== "pending" && routingApplyState !== "applying") {
      setInputDeviceId(next.inputDeviceId);
      setOutputDeviceId(next.outputDeviceId);
      setMonitorDeviceId(next.monitorDeviceId);
      setSampleRate(next.sampleRate);
      setReadChunkSize(next.readChunkSize);
      setCrossFadeOverlap(next.crossFadeOverlap);
      setExtraConvert(next.extraConvert);
      setInputGain(next.inputGain);
      setOutputGain(next.outputGain);
      setMonitorGain(next.monitorGain);
      lastAppliedRoutingKeyRef.current = routingKey(nativeRoutingSettingsPatch(next));
    }
  }, [modelId, routingApplyState, status, tuningDirty]);

  useEffect(() => {
    if (!status) return;
    const sample = {
      input: Math.max(0, Math.min(1, num(status.metrics.input_vu, 0))),
      output: Math.max(0, Math.min(1, num(status.metrics.output_vu, 0))),
    };
    setMeterHistory((prev) => [...prev.slice(-(waveformSlots - 1)), sample]);
  }, [status]);

  useEffect(() => {
    if (!statusLoaded) {
      setRoutingApplyState("idle");
      return;
    }
    if (!lastAppliedRoutingKeyRef.current) {
      lastAppliedRoutingKeyRef.current = currentRoutingKey;
      return;
    }
    if (currentRoutingKey === lastAppliedRoutingKeyRef.current) return;

    setRoutingApplyState("pending");
    const requestKey = currentRoutingKey;
    const seq = routingApplySeq.current + 1;
    routingApplySeq.current = seq;
    const id = window.setTimeout(async () => {
      if (requestKey === lastAppliedRoutingKeyRef.current) {
        setRoutingApplyState("applied");
        return;
      }
      setRoutingApplyState("applying");
      setError("");
      try {
        const next = await api.voiceEngineSettings(routingPatch);
        if (seq !== routingApplySeq.current) return;
        lastAppliedRoutingKeyRef.current = requestKey;
        setStatus(next);
        setRoutingApplyState("applied");
      } catch (err) {
        if (seq !== routingApplySeq.current) return;
        setRoutingApplyState("error");
        setError(parseApiError(err));
      }
    }, 400);
    return () => window.clearTimeout(id);
  }, [currentRoutingKey, routingPatch, statusLoaded]);

  const markTuning = () => setTuningDirty(true);
  const setDraftPitch = (value: number) => {
    const next = clamp(Math.round(value), -24, 24);
    setPitch(next);
    setOfflinePitch(next);
    markTuning();
  };
  const setDraftFormant = (value: number) => {
    const next = clamp(value, -2, 2);
    setFormantShift(next);
    setOfflineFormant(next);
    markTuning();
  };
  const setDraftSpeakerId = (value: number) => {
    setSpeakerId(clamp(Math.round(value), 0, 255));
    markTuning();
  };

  const tuningPatch = (): VoiceEngineSettingsUpdate => nativeTuningSettingsPatch({
    pitch,
    speakerId,
    formantShift,
    inputGateDb,
    inputHighpassHz,
    inputDenoise,
    inputDenoiseMix,
    silenceThresholdDb,
    silenceHoldMs,
    indexRatio,
    protect,
    noiseScale,
    f0Smoothing,
    f0Detector,
    passThrough,
  });

  const fullSettingsPatch = (): VoiceEngineSettingsUpdate => ({
    ...tuningPatch(),
    ...routingPatch,
  });

  const presetSettingsPatch = (): VoiceEngineSettingsUpdate => nativeVoicePresetSettingsPatch({
    pitch,
    speakerId,
    formantShift,
    inputGateDb,
    inputHighpassHz,
    inputDenoise,
    inputDenoiseMix,
    silenceThresholdDb,
    silenceHoldMs,
    indexRatio,
    protect,
    noiseScale,
    f0Smoothing,
    f0Detector,
    sampleRate,
    readChunkSize,
    crossFadeOverlap,
    extraConvert,
    inputGain,
    outputGain,
    monitorGain,
  });

  async function run(label: string, fn: () => Promise<VoiceEngineStatus | null | void>) {
    setBusy(label);
    setError("");
    try {
      const next = await fn();
      if (next) setStatus(next);
    } catch (err) {
      setError(parseApiError(err));
    } finally {
      setBusy("");
    }
  }

  const onApply = () => run("apply", async () => {
    const next = await api.voiceEngineSettings(fullSettingsPatch());
    setTuningDirty(false);
    return next;
  });

  const applyPatch = (label: string, patch: VoiceEngineSettingsUpdate, syncTuning = false) => run(label, async () => {
    const next = await api.voiceEngineSettings(patch);
    if (syncTuning) setTuningDirty(false);
    return next;
  });

  const onLive = (next: boolean) => run(next ? "live-on" : "live-off", async () => {
    if (!next) return api.voiceEngineSessionStop();
    if (!modelId) throw new Error("Select a voice model before starting live mode");
    await api.voiceEngineSettings(fullSettingsPatch());
    setTuningDirty(false);
    return api.voiceEngineSessionStart(modelId);
  });

  const onRestartLive = () => run("live-restart", async () => {
    const nextModelId = modelId || status?.loaded_model;
    if (!nextModelId) throw new Error("Select a voice model before restarting live mode");
    await api.voiceEngineSessionStop();
    await api.voiceEngineSettings(fullSettingsPatch());
    setTuningDirty(false);
    return api.voiceEngineSessionStart(nextModelId);
  });

  const onMonitor = (next: boolean) => {
    if (!next) {
      setMonitorDeviceId(-1);
      return;
    }
    const resolved = resolveMonitorDeviceId(monitorDeviceId, outputDeviceId, outputDevices);
    if (resolved < 0) {
      setError("No output device is available for monitoring");
      return;
    }
    setMonitorDeviceId(resolved);
  };

  const onBypass = (next: boolean) => {
    setPassThrough(next);
    markTuning();
    if (statusLoaded) void applyPatch("bypass", { pass_through: next }, true);
  };

  const onPtt = (next: boolean) => {
    setPtt(next);
    if (!statusLoaded) return;
    if (next) {
      setPassThrough(true);
      void applyPatch("ptt", { pass_through: true }, true);
    } else {
      void applyPatch("ptt", { pass_through: passThrough }, true);
    }
  };

  const onPreset = (preset: (typeof latencyPresets)[number]) => {
    setReadChunkSize(preset.chunk);
    setCrossFadeOverlap(preset.crossFade);
    setExtraConvert(preset.extra);
  };

  const applyQualityProfile = (label: string, profile: Profile, pitchOverride?: number) => {
    const nextPitch = pitchOverride ?? pitch;
    setPitch(nextPitch);
    setOfflinePitch(nextPitch);
    setFormantShift(profile.formantShift);
    setOfflineFormant(profile.formantShift);
    setInputDenoise(profile.inputDenoise);
    setInputDenoiseMix(profile.inputDenoiseMix);
    setInputHighpassHz(profile.inputHighpassHz);
    setInputGateDb(profile.inputGateDb);
    setSilenceThresholdDb(profile.silenceThresholdDb);
    setSilenceHoldMs(profile.silenceHoldMs);
    setIndexRatio(profile.indexRatio);
    setProtect(profile.protect);
    setNoiseScale(profile.noiseScale);
    setF0Smoothing(profile.f0Smoothing);
    const nextF0Detector = "f0Detector" in profile ? profile.f0Detector : f0Detector;
    if ("f0Detector" in profile) setF0Detector(nextF0Detector);
    setReadChunkSize(profile.readChunkSize);
    setCrossFadeOverlap(profile.crossFadeOverlap);
    setExtraConvert(profile.extraConvert);
    setSampleRate(profile.sampleRate);
    void applyPatch(label, {
      pitch: nextPitch,
      input_formant: profile.formantShift,
      input_denoise: profile.inputDenoise,
      input_denoise_mix: profile.inputDenoiseMix,
      input_highpass_hz: profile.inputHighpassHz,
      input_gate_db: profile.inputGateDb,
      silence_threshold_db: profile.silenceThresholdDb,
      silence_hold_ms: profile.silenceHoldMs,
      index_ratio: profile.indexRatio,
      protect: profile.protect,
      noise_scale: profile.noiseScale,
      f0_smoothing: profile.f0Smoothing,
      ...("f0Detector" in profile ? { f0_detector: nextF0Detector } : {}),
      server_read_chunk_size: profile.readChunkSize,
      cross_fade_overlap_size: profile.crossFadeOverlap,
      extra_convert_size: profile.extraConvert,
      server_audio_sample_rate: profile.sampleRate,
    }, true);
  };

  const onRecommended = () => applyQualityProfile("recommended", recommendedVoicePreset);
  const onClear = () => applyQualityProfile("clear-preset", clearVoicePreset);
  const onSmooth = () => applyQualityProfile("smooth-preset", smoothVoicePreset);
  const onFeminine = () => applyQualityProfile("female-preset", feminineVoicePreset, feminineVoicePreset.pitch);

  const selectVoicePreset = (presetId: string) => {
    setSelectedPresetId(presetId);
    const preset = voicePresets.find((item) => item.id === presetId);
    if (preset) setPresetName(preset.name);
  };

  const onSaveVoicePreset = () => run("preset-save", async () => {
    const saved = await api.voiceEnginePresetCreate({
      name: presetName,
      model_id: modelId || null,
      settings: presetSettingsPatch(),
    });
    const next = await api.voiceEnginePresets();
    setVoicePresets(next);
    setSelectedPresetId(saved.id);
    setPresetName(saved.name);
    return null;
  });

  const applyVoicePreset = (preset: VoiceEnginePreset) => run("preset-apply", async () => {
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

  const onUpdateVoicePreset = () => run("preset-update", async () => {
    if (!selectedPreset) throw new Error("Choose a saved preset first");
    const updated = await api.voiceEnginePresetUpdate(selectedPreset.id, {
      name: presetName.trim() || selectedPreset.name,
      model_id: modelId || null,
      settings: presetSettingsPatch(),
    });
    const nextPresets = await api.voiceEnginePresets();
    setVoicePresets(nextPresets);
    setSelectedPresetId(updated.id);
    setPresetName(updated.name);
    setTuningDirty(false);
    return null;
  });

  const onDeleteVoicePreset = () => run("preset-delete", async () => {
    if (!selectedPreset) throw new Error("Choose a saved preset first");
    await api.voiceEnginePresetDelete(selectedPreset.id);
    await refreshPresets();
    setPresetName("");
    return null;
  });

  const onRecording = (next: boolean) => run(next ? "record-on" : "record-off", async () => {
    if (next) {
      setRecordingResult(null);
      return api.voiceEngineRecordingStart();
    }
    const updated = await api.voiceEngineRecordingStop();
    setRecordingResult(updated.recording_result ?? null);
    return updated;
  });

  const onOfflineConvert = async () => {
    if (!offlineFile) {
      setOfflineError("Choose a WAV, FLAC, OGG, or MP3 file first");
      return;
    }
    if (!offlineModelId) {
      setOfflineError("Choose a voice model first");
      return;
    }
    const form = new FormData();
    form.append("file", offlineFile);
    form.append("model_id", offlineModelId);
    form.append("pitch", String(offlinePitch));
    form.append("speaker_id", String(speakerId));
    form.append("index_ratio", String(indexRatio));
    form.append("protect", String(protect));
    form.append("noise_scale", String(noiseScale));
    form.append("f0_smoothing", String(f0Smoothing));
    form.append("input_highpass_hz", String(inputHighpassHz));
    form.append("input_gate_db", String(inputGateDb));
    form.append("input_formant", String(offlineFormant));
    form.append("input_denoise", inputDenoise);
    form.append("input_denoise_mix", String(inputDenoiseMix));
    setOfflineBusy(true);
    setOfflineError("");
    setOfflineResult(null);
    try {
      setOfflineResult(await api.voiceEngineConvert(form));
    } catch (err) {
      setOfflineError(parseApiError(err));
    } finally {
      setOfflineBusy(false);
    }
  };

  useEffect(() => {
    if (!ptt || !statusLoaded) return;
    const onDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || focusIsTextEntry() || event.repeat) return;
      event.preventDefault();
      void api.voiceEngineSettings({ pass_through: false }).then(setStatus).catch(() => {});
    };
    const onUp = (event: KeyboardEvent) => {
      if (event.code !== "Space" || focusIsTextEntry()) return;
      event.preventDefault();
      void api.voiceEngineSettings({ pass_through: true }).then(setStatus).catch(() => {});
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [ptt, statusLoaded]);

  const assetsFound = (status?.assets ?? []).filter((asset) => asset.found).length;
  const totalAssets = status?.assets.length ?? 0;
  const denoiseDtlnMissing = Boolean((status?.assets ?? []).find((asset) => asset.name === "denoise_dtln" && !asset.found));
  const voiceOptions = models.map((m) => ({ value: m.id, label: m.name, hint: `${m.source ?? "local"} ${m.slot}` }));
  const selectedSupportsPitch = selected?.f0 !== false;

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto p-1">
      <header className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-ui-strong">Voice Changer</h2>
            <Badge color={live ? "bg-success-bg text-success-fg" : "ui-chip"}>
              {live ? "live" : "idle"}
            </Badge>
            {tuningDirty ? <Badge color="bg-amber-600/40 text-amber-100">unsaved tuning</Badge> : null}
          </div>
          <p className="mt-1 truncate text-sm text-ui-subtle">
            {selected?.name ?? "No voice selected"} {selected ? "->" : ""} {live ? "microphone lane active" : "ready for setup"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void refresh()} disabled={Boolean(busy)}>Refresh</Button>
          <Button onClick={onApply} disabled={!canApply} tone={tuningDirty ? "primary" : "ghost"}>
            {busy === "apply" ? "Applying..." : tuningDirty ? "Apply Changes" : "Apply"}
          </Button>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.92fr)_minmax(0,1.45fr)]">
        <Panel
          title="Voice And Engine"
          aside={(
            <Badge color={ready ? "bg-emerald-700/55 text-emerald-100" : "bg-amber-600/40 text-amber-100"}>
              {ready ? "ready" : "missing"}
            </Badge>
          )}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <StatusTile label="Engine" value={status?.engine ?? "native-rvc"} tone={ready ? "good" : "warn"} />
            <StatusTile label="Mode" value={status?.stub ? "stub" : "real"} tone={status?.stub ? "info" : "neutral"} />
            <StatusTile label="Device" value={status?.device ?? "..."} />
            <StatusTile label="Assets" value={`${assetsFound}/${totalAssets || "..."}`} tone={ready ? "good" : "warn"} />
          </div>

          <div className="mt-4">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-ui-muted">Voice model</div>
              <Badge>{models.length} slots</Badge>
            </div>
            <Select
              value={modelId}
              onChange={(value) => {
                setModelId(value);
                setOfflineModelId(value);
              }}
              placeholder="no voices"
              options={voiceOptions}
              renderOption={(option) => <VoiceOption option={option} models={models} />}
            />
          </div>

          <div className="ui-card mt-3 rounded-md p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-ui">{selected?.name ?? "No model selected"}</div>
                <div className="mt-1 truncate text-xs text-ui-subtle">
                  loaded: {loadedModel?.name ?? status?.loaded_model ?? "none"}
                </div>
              </div>
              <ModelBadges model={selected} />
            </div>
            {selected ? (
              <div className="mt-3 grid gap-1.5 text-sm sm:grid-cols-2">
                <Row label="Slot" value={selected.slot} />
                <Row label="Size" value={formatBytes(selected.size_bytes)} />
                <Row label="Source" value={selected.source ?? "local"} />
                <Row label="Pitch" value={selected.f0 ? "active" : "model-limited"} ok={selected.f0} />
              </div>
            ) : null}
          </div>

          <button
            type="button"
            onClick={() => setVoicesOpen((open) => !open)}
            className="ui-button mt-3 w-full rounded-md px-2.5 py-1.5 text-left text-xs font-medium"
          >
            {voicesOpen ? "Hide model list" : "Show model list"}
          </button>
          {voicesOpen ? <VoiceSlotList models={models} modelId={modelId} modelDir={modelDirHint} onSelect={setModelId} /> : null}

          <div className="mt-3 grid gap-1.5">
            {(status?.assets ?? []).map((asset) => (
              <div
                key={asset.name}
                title={assetTitle(asset)}
                className="ui-card flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5"
              >
                <span className="min-w-0 truncate text-sm text-ui-muted">{asset.name}</span>
                <span className="flex shrink-0 items-center gap-1.5">
                  <Badge color={asset.found ? "bg-success-bg text-success-fg" : asset.optional ? "ui-chip" : "bg-warn-bg text-warn-fg"}>
                    {asset.found ? "found" : asset.optional ? "optional" : "missing"}
                  </Badge>
                  {asset.source ? <Badge>{asset.source}</Badge> : null}
                </span>
              </div>
            ))}
            {!status?.assets?.length ? <div className="text-sm text-ui-subtle">Loading native assets...</div> : null}
          </div>

          {(() => {
            const dl = status?.asset_download ?? null;
            const missingRequired = (status?.assets ?? []).filter((a) => !a.found && !a.optional);
            if (missingRequired.length === 0 && dl?.state !== "running") return null;
            return (
              <div className="mt-3 rounded-md border border-amber-400/30 bg-amber-400/10 p-3">
                <div className="text-sm font-medium text-amber-100">Shared voice assets needed</div>
                <p className="mt-1 text-xs leading-5 text-amber-100/80">
                  Every voice model uses a shared ContentVec encoder (and RMVPE for the quality pitch path) —
                  these aren't bundled with your voice files. Fetch them once into{" "}
                  <code className="rounded bg-control-active px-1">models/voice/pretrain</code> and any voice model works.
                </p>
                {dl?.state === "running" ? (
                  <div className="mt-2 text-xs text-amber-100/80">
                    Downloading {dl.current?.label ?? "voice assets"}… {dl.progress.total ? `${dl.progress.done}/${dl.progress.total}` : ""}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => void fetchAssets()}
                    disabled={busy === "assets"}
                    className="mt-2 rounded-md bg-amber-500/80 px-3 py-1.5 text-xs font-medium text-black transition hover:bg-amber-400 disabled:opacity-40"
                  >
                    {busy === "assets" ? "Starting…" : "Download voice assets (~560 MB)"}
                  </button>
                )}
                {dl?.state === "error" ? (
                  <div className="mt-2 text-xs text-red-200">
                    {dl.message} — retry the download here, or rerun setup.bat all / ./setup.sh all when the network is stable.
                  </div>
                ) : null}
              </div>
            );
          })()}

          {denoiseDtlnMissing ? (
            <div className="ui-card mt-3 rounded-md p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-ui">Optional DTLN denoise assets</div>
                  <div className="mt-1 text-xs leading-5 text-ui-subtle">
                    Enables the DTLN input denoise mode; files land in{" "}
                    <code className="rounded bg-control-active px-1">models/voice/pretrain/denoise</code>.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void fetchDtlnAssets()}
                  disabled={busy === "dtln-assets" || status?.asset_download?.state === "running"}
                  className="ui-button rounded-md px-3 py-1.5 text-xs font-medium"
                >
                  {busy === "dtln-assets" ? "Starting..." : "Download DTLN"}
                </button>
              </div>
            </div>
          ) : null}
        </Panel>

        <VoiceLiveConsolePanel
          busy={busy}
          canGoLive={canGoLive}
          inputDeviceId={inputDeviceId}
          inputDevices={inputDevices}
          live={live}
          modelId={modelId}
          monitorDeviceId={monitorDeviceId}
          monitorGain={monitorGain}
          monitorOn={monitorOn}
          onLive={onLive}
          onMonitor={onMonitor}
          onRecording={onRecording}
          onRestartLive={onRestartLive}
          outputDeviceId={outputDeviceId}
          outputDevices={outputDevices}
          outputPeak={outputPeak}
          outputPeakTone={outputPeakTone}
          ready={ready}
          recording={recording}
          recordingResult={recordingResult}
          selected={selected}
          setMonitorGain={setMonitorGain}
          status={status}
          statusLoaded={statusLoaded}
        />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <VoiceTuningPanel
          busy={busy}
          canApply={canApply}
          f0Detector={f0Detector}
          f0Smoothing={f0Smoothing}
          formantShift={formantShift}
          indexRatio={indexRatio}
          indexRisk={indexRisk}
          inputDenoise={inputDenoise}
          inputDenoiseMix={inputDenoiseMix}
          inputGateDb={inputGateDb}
          inputHighpassHz={inputHighpassHz}
          markTuning={markTuning}
          noiseRisk={noiseRisk}
          noiseScale={noiseScale}
          onBypass={onBypass}
          onClear={onClear}
          onFeminine={onFeminine}
          onPtt={onPtt}
          onRecommended={onRecommended}
          onSmooth={onSmooth}
          passThrough={passThrough}
          pitch={pitch}
          plus12Tuning={plus12Tuning}
          protect={protect}
          protectRisk={protectRisk}
          ptt={ptt}
          selectedName={selected?.name ?? "no voice selected"}
          selectedSupportsPitch={selectedSupportsPitch}
          setDraftFormant={setDraftFormant}
          setDraftPitch={setDraftPitch}
          setDraftSpeakerId={setDraftSpeakerId}
          setF0Detector={setF0Detector}
          setF0Smoothing={setF0Smoothing}
          setIndexRatio={setIndexRatio}
          setInputDenoise={setInputDenoise}
          setInputDenoiseMix={setInputDenoiseMix}
          setInputGateDb={setInputGateDb}
          setInputHighpassHz={setInputHighpassHz}
          setNoiseScale={setNoiseScale}
          setProtect={setProtect}
          setSilenceHoldMs={setSilenceHoldMs}
          setSilenceThresholdDb={setSilenceThresholdDb}
          silenceHoldMs={silenceHoldMs}
          silenceThresholdDb={silenceThresholdDb}
          speakerId={speakerId}
          statusLoaded={statusLoaded}
        />
        <VoiceRoutingPanel
          busy={busy}
          chunkRestartPending={chunkRestartPending}
          crossFadeOverlap={crossFadeOverlap}
          deviceMissing={deviceMissing}
          extraConvert={extraConvert}
          inputDeviceId={inputDeviceId}
          inputDevices={inputDevices}
          inputGain={inputGain}
          inputRestartPending={inputRestartPending}
          monitorDeviceId={monitorDeviceId}
          monitorRestartPending={monitorRestartPending}
          onPreset={onPreset}
          outputDeviceId={outputDeviceId}
          outputDevices={outputDevices}
          outputGain={outputGain}
          outputIsVirtualCable={outputIsVirtualCable}
          outputRestartPending={outputRestartPending}
          readChunkSize={readChunkSize}
          routingApplyState={routingApplyState}
          sampleRate={sampleRate}
          sampleRateRestartPending={sampleRateRestartPending}
          setCrossFadeOverlap={setCrossFadeOverlap}
          setExtraConvert={setExtraConvert}
          setInputDeviceId={setInputDeviceId}
          setInputGain={setInputGain}
          setMonitorDeviceId={setMonitorDeviceId}
          setOutputDeviceId={setOutputDeviceId}
          setOutputGain={setOutputGain}
          setReadChunkSize={setReadChunkSize}
          setSampleRate={setSampleRate}
          statusLoaded={statusLoaded}
          statusStub={Boolean(status?.stub)}
          virtualCableDetected={virtualCableDetected}
        />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <VoicePresetsPanel
          applyVoicePreset={applyVoicePreset}
          busy={busy}
          canApply={canApply}
          models={models}
          onDeleteVoicePreset={onDeleteVoicePreset}
          onSaveVoicePreset={onSaveVoicePreset}
          onUpdateVoicePreset={onUpdateVoicePreset}
          presetName={presetName}
          selectVoicePreset={selectVoicePreset}
          selectedPreset={selectedPreset}
          selectedPresetId={selectedPresetId}
          setPresetName={setPresetName}
          voicePresets={voicePresets}
        />
        <VoiceOfflineConvertPanel
          models={models}
          offlineBusy={offlineBusy}
          offlineError={offlineError}
          offlineFile={offlineFile}
          offlineFormant={offlineFormant}
          offlineModelId={offlineModelId}
          offlinePitch={offlinePitch}
          offlineResult={offlineResult}
          onOfflineConvert={onOfflineConvert}
          ready={ready}
          setOfflineFile={setOfflineFile}
          setOfflineFormant={setOfflineFormant}
          setOfflineModelId={setOfflineModelId}
          setOfflinePitch={setOfflinePitch}
          voiceOptions={voiceOptions}
        />
        <VoiceDiagnosticsPanel meterHistory={meterHistory} status={status} />
      </div>
    </div>
  );
}
