import { useState } from "react";

import { api } from "../api/client";
import type { VoiceEngineConvertResult } from "../types";
import { parseApiError } from "./VoicePanelControls";

type OfflineConversionSettings = {
  speakerId: number;
  indexRatio: number;
  protect: number;
  noiseScale: number;
  f0Smoothing: number;
  inputHighpassHz: number;
  inputDenoise: "off" | "dtln";
  inputDenoiseMix: number;
};

export function useVoiceOfflineConversion(settings: OfflineConversionSettings) {
  const [offlineFile, setOfflineFile] = useState<File | null>(null);
  const [offlineModelId, setOfflineModelId] = useState("");
  const [offlinePitch, setOfflinePitch] = useState(0);
  const [offlineBusy, setOfflineBusy] = useState(false);
  const [offlineError, setOfflineError] = useState("");
  const [offlineResult, setOfflineResult] = useState<VoiceEngineConvertResult | null>(null);

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
    form.append("speaker_id", String(settings.speakerId));
    form.append("index_ratio", String(settings.indexRatio));
    form.append("protect", String(settings.protect));
    form.append("noise_scale", String(settings.noiseScale));
    form.append("f0_smoothing", String(settings.f0Smoothing));
    form.append("input_highpass_hz", String(settings.inputHighpassHz));
    form.append("input_gate_db", "-90");
    form.append("input_formant", "0");
    form.append("input_denoise", settings.inputDenoise);
    form.append("input_denoise_mix", String(settings.inputDenoiseMix));

    setOfflineBusy(true);
    setOfflineError("");
    setOfflineResult(null);
    try {
      setOfflineResult(await api.voiceEngineConvert(form));
    } catch (error) {
      setOfflineError(parseApiError(error));
    } finally {
      setOfflineBusy(false);
    }
  };

  return {
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
  };
}
