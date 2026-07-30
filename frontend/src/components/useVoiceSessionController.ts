import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { toast } from "./Toast";
import type { MeterSample } from "./VoiceMeters";
import type { RoutingApplyState } from "./VoicePanelParts";
import { useVoiceOfflineConversion } from "./useVoiceOfflineConversion";
import { useVoicePresets } from "./useVoicePresets";
import { clamp, focusIsTextEntry, parseApiError, routingKey } from "./VoicePanelControls";
import {
  feminineVoicePreset,
  latencyPresets,
  lowLatencyVoicePreset,
  nativeRoutingSettingsPatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
  nativeVoicePresetSettingsPatch,
  num,
  qualityVoicePreset,
  resolveMonitorDeviceId,
  selectedNativeModelId,
  stableVoicePreset,
  waveformSlots,
} from "./voiceHelpers";
import type {
  VoiceAudioDevice,
  VoiceEngineRecordingResult,
  VoiceEngineSettingsUpdate,
  VoiceEngineStatus,
} from "../types";

type Profile =
  | typeof stableVoicePreset
  | typeof lowLatencyVoicePreset
  | typeof qualityVoicePreset
  | typeof feminineVoicePreset;

const virtualCablePattern =
  /\b(vb-cable|vb-audio|voicemeeter|virtual cable|cable input|cable output|blackhole|loopback|soundflower)\b/i;

function looksLikeVirtualCable(device: VoiceAudioDevice | undefined): boolean {
  if (!device) return false;
  return virtualCablePattern.test(`${device.name} ${device.host_api}`);
}

export function useVoiceSessionController() {
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
  const [silenceThresholdDb, setSilenceThresholdDb] = useState(-54);
  const [silenceHoldMs, setSilenceHoldMs] = useState(200);
  const [indexRatio, setIndexRatio] = useState(0.35);
  const [protect, setProtect] = useState(0.33);
  const [noiseScale, setNoiseScale] = useState(0.35);
  const [f0Smoothing, setF0Smoothing] = useState(0.2);
  const [f0Detector, setF0Detector] = useState("fcpe");
  const [passThrough, setPassThrough] = useState(false);
  const [ptt, setPtt] = useState(false);
  const [inputDeviceId, setInputDeviceId] = useState(-1);
  const [outputDeviceId, setOutputDeviceId] = useState(-1);
  const [monitorDeviceId, setMonitorDeviceId] = useState(-1);
  const [sampleRate, setSampleRate] = useState(48000);
  const [readChunkSize, setReadChunkSize] = useState(90);
  const [crossFadeOverlap, setCrossFadeOverlap] = useState(0.03);
  const [extraConvert, setExtraConvert] = useState(1);
  const [inputGain, setInputGain] = useState(1);
  const [outputGain, setOutputGain] = useState(1);
  const [monitorGain, setMonitorGain] = useState(1);
  const [meterHistory, setMeterHistory] = useState<MeterSample[]>([]);
  const [voicesOpen, setVoicesOpen] = useState(false);
  const [tuningDirty, setTuningDirty] = useState(false);
  const [routingApplyState, setRoutingApplyState] = useState<RoutingApplyState>("idle");
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
  } = useVoiceOfflineConversion({
    speakerId,
    indexRatio,
    protect,
    noiseScale,
    f0Smoothing,
    inputHighpassHz,
    inputDenoise,
    inputDenoiseMix,
  });
  const [recordingResult, setRecordingResult] = useState<VoiceEngineRecordingResult | null>(null);
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
    presetSettings: () => presetSettingsPatch(),
    setModelId,
    setOfflineModelId,
    setTuningDirty,
  });
  const sessionConfig = status?.session_config ?? null;
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
    live &&
    sessionConfig &&
    (sessionConfig.server_monitor_device_id == null || sessionConfig.server_monitor_device_id < 0
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
  const outputPeak = status?.metrics.output_peak ?? 0;
  const outputPeakTone: "amber" | "sky" =
    outputPeak >= 0.85 || (status?.metrics.limiter_reduction_db ?? 0) > 0 ? "amber" : "sky";

  const routingPatch = useMemo(
    () =>
      nativeRoutingSettingsPatch({
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
      }),
    [
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
    ],
  );
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
    setOfflineModelId(
      (prev) => selectedNativeModelId(status.models, prev || nextModelId, status.loaded_model) || prev,
    );
    const next = nativeSettingsToVoiceState(status.settings);
    const nextModel = status.models.find((model) => model.id === nextModelId);

    if (!tuningDirty) {
      setPitch(next.pitch);
      setOfflinePitch(next.pitch);
      setSpeakerId(next.speakerId);
      setFormantShift(0);
      setInputGateDb(-90);
      setInputHighpassHz(next.inputHighpassHz);
      setInputDenoise(next.inputDenoise);
      setInputDenoiseMix(next.inputDenoiseMix);
      setSilenceThresholdDb(next.silenceThresholdDb);
      setSilenceHoldMs(next.silenceHoldMs);
      setIndexRatio(nextModel?.has_index ? next.indexRatio : 0);
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
  }, [
    modelId,
    routingApplyState,
    setOfflineModelId,
    setOfflinePitch,
    status,
    tuningDirty,
  ]);

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
  const setDraftSpeakerId = (value: number) => {
    setSpeakerId(clamp(Math.round(value), 0, 255));
    markTuning();
  };

  const tuningPatch = (): VoiceEngineSettingsUpdate =>
    nativeTuningSettingsPatch({
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

  const presetSettingsPatch = (): VoiceEngineSettingsUpdate =>
    nativeVoicePresetSettingsPatch({
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

  const onApply = () =>
    run("apply", async () => {
      const next = await api.voiceEngineSettings(fullSettingsPatch());
      setTuningDirty(false);
      return next;
    });

  const applyPatch = (label: string, patch: VoiceEngineSettingsUpdate, syncTuning = false) =>
    run(label, async () => {
      const next = await api.voiceEngineSettings(patch);
      if (syncTuning) setTuningDirty(false);
      return next;
    });

  const onLive = (next: boolean) =>
    run(next ? "live-on" : "live-off", async () => {
      if (!next) return api.voiceEngineSessionStop();
      if (!modelId) throw new Error("Select a voice model before starting live mode");
      await api.voiceEngineSettings(fullSettingsPatch());
      setTuningDirty(false);
      return api.voiceEngineSessionStart(modelId);
    });

  const onRestartLive = () =>
    run("live-restart", async () => {
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
    const nextIndexRatio = selected?.has_index ? profile.indexRatio : 0;
    setPitch(nextPitch);
    setOfflinePitch(nextPitch);
    setFormantShift(0);
    setInputDenoise(profile.inputDenoise);
    setInputDenoiseMix(profile.inputDenoiseMix);
    setInputHighpassHz(profile.inputHighpassHz);
    setInputGateDb(profile.inputGateDb);
    setSilenceThresholdDb(profile.silenceThresholdDb);
    setSilenceHoldMs(profile.silenceHoldMs);
    setIndexRatio(nextIndexRatio);
    setProtect(profile.protect);
    setNoiseScale(profile.noiseScale);
    setF0Smoothing(profile.f0Smoothing);
    const nextF0Detector = profile.f0Detector;
    setF0Detector(nextF0Detector);
    setReadChunkSize(profile.readChunkSize);
    setCrossFadeOverlap(profile.crossFadeOverlap);
    setExtraConvert(profile.extraConvert);
    setSampleRate(profile.sampleRate);
    void applyPatch(
      label,
      {
        pitch: nextPitch,
        input_formant: 0,
        input_denoise: profile.inputDenoise,
        input_denoise_mix: profile.inputDenoiseMix,
        input_highpass_hz: profile.inputHighpassHz,
        input_gate_db: profile.inputGateDb,
        silence_threshold_db: profile.silenceThresholdDb,
        silence_hold_ms: profile.silenceHoldMs,
        index_ratio: nextIndexRatio,
        protect: profile.protect,
        noise_scale: profile.noiseScale,
        f0_smoothing: profile.f0Smoothing,
        f0_detector: nextF0Detector,
        server_read_chunk_size: profile.readChunkSize,
        cross_fade_overlap_size: profile.crossFadeOverlap,
        extra_convert_size: profile.extraConvert,
        server_audio_sample_rate: profile.sampleRate,
      },
      true,
    );
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
      void api
        .voiceEngineSettings({ pass_through: false })
        .then(setStatus)
        .catch((error: unknown) => {
          toast.error(error instanceof Error ? error.message : "Could not enable push-to-talk");
        });
    };
    const onUp = (event: KeyboardEvent) => {
      if (event.code !== "Space" || focusIsTextEntry()) return;
      event.preventDefault();
      void api
        .voiceEngineSettings({ pass_through: true })
        .then(setStatus)
        .catch((error: unknown) => {
          toast.error(error instanceof Error ? error.message : "Could not release push-to-talk");
        });
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
      onModelChange: (value: string) => {
        setModelId(value);
        setOfflineModelId(value);
      },
      onModelListToggle: () => setVoicesOpen((open) => !open),
      onModelSelect: setModelId,
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
      setMonitorGain,
      status,
      statusLoaded,
    },
    tuning: {
      busy,
      canApply,
      f0Detector,
      f0Smoothing,
      indexRatio,
      indexRisk,
      inputDenoise,
      inputDenoiseMix,
      inputHighpassHz,
      markTuning,
      onBypass,
      onFeminine,
      onLowLatency,
      onPtt,
      onQuality,
      onStable,
      passThrough,
      pitch,
      protect,
      protectRisk,
      ptt,
      selectedHasIndex: Boolean(selected?.has_index),
      selectedName: selected?.name ?? "no voice selected",
      selectedSupportsPitch,
      setDraftPitch,
      setDraftSpeakerId,
      setF0Detector,
      setF0Smoothing,
      setIndexRatio,
      setInputDenoise,
      setInputDenoiseMix,
      setInputHighpassHz,
      setProtect,
      setSilenceHoldMs,
      setSilenceThresholdDb,
      silenceHoldMs,
      silenceThresholdDb,
      speakerId,
      statusLoaded,
    },
    routing: {
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
