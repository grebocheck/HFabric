import type { VoiceAudioDevice, VoiceEngineSettings, VoiceEngineSettingsUpdate, VoiceModel } from "../types";

export const f0Options = [
  { value: "fcpe", label: "FCPE — realtime" },
  { value: "rmvpe", label: "RMVPE — quality" },
];

export const sampleRates = [16000, 24000, 44100, 48000, 96000];
export const inputHighpassOptions = [
  { value: "0", label: "Off" },
  { value: "60", label: "60 Hz" },
  { value: "80", label: "80 Hz" },
  { value: "120", label: "120 Hz" },
  { value: "160", label: "160 Hz" },
];
export const denoiseOptions = [
  { value: "off", label: "Off" },
  { value: "dtln", label: "DTLN (neural)" },
];

// Every chunk is a multiple of 15: at 48 kHz that maps exactly to the 640
// sample analysis quantum at 16 kHz. The previous 96/133/192 presets produced
// shorter/longer internal blocks and periodically starved the output callback.
export const latencyPresets = [
  { id: "low", label: "Low latency", chunk: 60, crossFade: 0.025, extra: 0.8 },
  { id: "stable", label: "Stable", chunk: 90, crossFade: 0.03, extra: 1.0 },
  { id: "quality", label: "Quality", chunk: 120, crossFade: 0.04, extra: 1.5 },
] as const;

// protect 0.5 turns consonant protection OFF in RVC; 0.25-0.35 keeps unvoiced
// frames close to the source so sibilants stay crisp.
export const stableVoicePreset = {
  inputDenoise: "off" as const,
  inputDenoiseMix: 0,
  inputHighpassHz: 80,
  inputGateDb: -90,
  silenceThresholdDb: -54,
  silenceHoldMs: 200,
  formantShift: 0,
  indexRatio: 0.35,
  protect: 0.33,
  noiseScale: 0.35,
  f0Smoothing: 0.2,
  f0Detector: "fcpe",
  readChunkSize: 90,
  crossFadeOverlap: 0.03,
  extraConvert: 1,
  sampleRate: 48000,
} as const;

export const lowLatencyVoicePreset = {
  inputDenoise: "off" as const,
  inputDenoiseMix: 0,
  inputHighpassHz: 80,
  inputGateDb: -90,
  silenceThresholdDb: -52,
  silenceHoldMs: 150,
  formantShift: 0,
  indexRatio: 0.25,
  protect: 0.33,
  noiseScale: 0.3,
  f0Smoothing: 0.15,
  f0Detector: "fcpe",
  readChunkSize: 60,
  crossFadeOverlap: 0.025,
  extraConvert: 0.8,
  sampleRate: 48000,
} as const;

export const qualityVoicePreset = {
  inputDenoise: "off" as const,
  inputDenoiseMix: 0,
  inputHighpassHz: 80,
  inputGateDb: -90,
  silenceThresholdDb: -56,
  silenceHoldMs: 250,
  formantShift: 0,
  indexRatio: 0.35,
  protect: 0.3,
  noiseScale: 0.35,
  f0Smoothing: 0.2,
  f0Detector: "rmvpe",
  readChunkSize: 120,
  crossFadeOverlap: 0.04,
  extraConvert: 1.5,
  sampleRate: 48000,
} as const;

// Male speaker -> female RVC model: +12 semitones, a slight input-side
// brightness lift so consonants read feminine, mild f0 smoothing against
// octave flips at the higher register.
export const feminineVoicePreset = {
  pitch: 10,
  formantShift: 0,
  inputDenoise: "off" as const,
  inputDenoiseMix: 0,
  inputHighpassHz: 80,
  indexRatio: 0.25,
  protect: 0.33,
  noiseScale: 0.3,
  f0Smoothing: 0.25,
  f0Detector: "fcpe",
  inputGateDb: -90,
  silenceThresholdDb: -54,
  silenceHoldMs: 200,
  readChunkSize: 90,
  crossFadeOverlap: 0.03,
  extraConvert: 1,
  sampleRate: 48000,
} as const;

export const waveformSlots = 64;

export type VoiceControlState = {
  pitch: number;
  speakerId: number;
  formantShift: number;
  inputGateDb: number;
  inputHighpassHz: number;
  inputDenoise: "off" | "dtln";
  inputDenoiseMix: number;
  silenceThresholdDb: number;
  silenceHoldMs: number;
  indexRatio: number;
  protect: number;
  noiseScale: number;
  f0Smoothing: number;
  f0Detector: string;
  passThrough: boolean;
  inputDeviceId: number;
  outputDeviceId: number;
  monitorDeviceId: number;
  sampleRate: number;
  readChunkSize: number;
  crossFadeOverlap: number;
  extraConvert: number;
  inputGain: number;
  outputGain: number;
  monitorGain: number;
};

export type VoiceRoutingState = Pick<
  VoiceControlState,
  | "inputDeviceId"
  | "outputDeviceId"
  | "monitorDeviceId"
  | "sampleRate"
  | "readChunkSize"
  | "crossFadeOverlap"
  | "extraConvert"
  | "inputGain"
  | "outputGain"
  | "monitorGain"
>;

export function num(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function nativeSettingsToVoiceState(settings: Partial<Record<keyof VoiceEngineSettings, unknown>>): VoiceControlState {
  const f0 = String(settings.f0_detector ?? "fcpe");
  return {
    pitch: num(settings.pitch, 0),
    speakerId: num(settings.speaker_id, 0),
    formantShift: 0,
    inputGateDb: -90,
    inputHighpassHz: num(settings.input_highpass_hz, 80),
    inputDenoise: settings.input_denoise === "dtln" ? "dtln" : "off",
    inputDenoiseMix: num(settings.input_denoise_mix, 0.75),
    silenceThresholdDb: num(settings.silence_threshold_db, -72),
    silenceHoldMs: num(settings.silence_hold_ms, 250),
    indexRatio: num(settings.index_ratio, 0.35),
    protect: num(settings.protect, 0.5),
    noiseScale: num(settings.noise_scale, 0.35),
    f0Smoothing: num(settings.f0_smoothing, 0.2),
    f0Detector: f0Options.some((o) => o.value === f0) ? f0 : "fcpe",
    passThrough: Boolean(settings.pass_through),
    inputDeviceId: settings.server_input_device_id == null ? -1 : num(settings.server_input_device_id, -1),
    outputDeviceId: settings.server_output_device_id == null ? -1 : num(settings.server_output_device_id, -1),
    monitorDeviceId: settings.server_monitor_device_id == null ? -1 : num(settings.server_monitor_device_id, -1),
    sampleRate: num(settings.server_audio_sample_rate, 48000),
    readChunkSize: num(settings.server_read_chunk_size, 90),
    crossFadeOverlap: num(settings.cross_fade_overlap_size, 0.03),
    extraConvert: num(settings.extra_convert_size, 1),
    inputGain: num(settings.server_input_gain, 1),
    outputGain: num(settings.server_output_gain, 1),
    monitorGain: num(settings.server_monitor_gain, 1),
  };
}

export function nativeRoutingSettingsPatch(state: VoiceRoutingState): VoiceEngineSettingsUpdate {
  return {
    server_input_device_id: state.inputDeviceId >= 0 ? state.inputDeviceId : null,
    server_output_device_id: state.outputDeviceId >= 0 ? state.outputDeviceId : null,
    server_monitor_device_id: state.monitorDeviceId,
    server_audio_sample_rate: state.sampleRate,
    server_read_chunk_size: state.readChunkSize,
    cross_fade_overlap_size: state.crossFadeOverlap,
    extra_convert_size: state.extraConvert,
    server_input_gain: state.inputGain,
    server_output_gain: state.outputGain,
    server_monitor_gain: state.monitorGain,
  };
}

export function nativeTuningSettingsPatch(state: Pick<
  VoiceControlState,
  | "pitch"
  | "speakerId"
  | "formantShift"
  | "inputGateDb"
  | "inputHighpassHz"
  | "inputDenoise"
  | "inputDenoiseMix"
  | "silenceThresholdDb"
  | "silenceHoldMs"
  | "indexRatio"
  | "protect"
  | "noiseScale"
  | "f0Smoothing"
  | "f0Detector"
  | "passThrough"
>): VoiceEngineSettingsUpdate {
  return {
    pitch: state.pitch,
    speaker_id: state.speakerId,
    input_formant: 0,
    input_gate_db: -90,
    input_highpass_hz: state.inputHighpassHz,
    input_denoise: state.inputDenoise,
    input_denoise_mix: state.inputDenoiseMix,
    silence_threshold_db: state.silenceThresholdDb,
    silence_hold_ms: state.silenceHoldMs,
    index_ratio: state.indexRatio,
    protect: state.protect,
    noise_scale: state.noiseScale,
    f0_smoothing: state.f0Smoothing,
    f0_detector: state.f0Detector,
    pass_through: state.passThrough,
  };
}

export function nativeVoicePresetSettingsPatch(state: Pick<
  VoiceControlState,
  | "pitch"
  | "speakerId"
  | "formantShift"
  | "inputGateDb"
  | "inputHighpassHz"
  | "inputDenoise"
  | "inputDenoiseMix"
  | "silenceThresholdDb"
  | "silenceHoldMs"
  | "indexRatio"
  | "protect"
  | "noiseScale"
  | "f0Smoothing"
  | "f0Detector"
  | "sampleRate"
  | "readChunkSize"
  | "crossFadeOverlap"
  | "extraConvert"
  | "inputGain"
  | "outputGain"
  | "monitorGain"
>): VoiceEngineSettingsUpdate {
  return {
    pitch: state.pitch,
    speaker_id: state.speakerId,
    input_formant: 0,
    input_gate_db: -90,
    input_highpass_hz: state.inputHighpassHz,
    input_denoise: state.inputDenoise,
    input_denoise_mix: state.inputDenoiseMix,
    silence_threshold_db: state.silenceThresholdDb,
    silence_hold_ms: state.silenceHoldMs,
    index_ratio: state.indexRatio,
    protect: state.protect,
    noise_scale: state.noiseScale,
    f0_smoothing: state.f0Smoothing,
    f0_detector: state.f0Detector,
    server_audio_sample_rate: state.sampleRate,
    server_read_chunk_size: state.readChunkSize,
    cross_fade_overlap_size: state.crossFadeOverlap,
    extra_convert_size: state.extraConvert,
    server_input_gain: state.inputGain,
    server_output_gain: state.outputGain,
    server_monitor_gain: state.monitorGain,
  };
}

export function selectedNativeModelId(models: VoiceModel[], current: string, loaded: string | null | undefined): string {
  if (current && models.some((m) => m.id === current)) return current;
  if (loaded && models.some((m) => m.id === loaded)) return loaded;
  return models[0]?.id ?? "";
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const gb = bytes / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1e6).toFixed(0)} MB`;
}

export function deviceHint(hostApi: string, rate: number | null): string {
  return [hostApi, rate ? `${rate / 1000}k` : ""].filter(Boolean).join(", ");
}

// A short label + Badge color per Windows host API. The API a device sits on
// is easy to miss in grey hint text, yet input and output MUST share one host
// API or the duplex stream fails to open (PaErrorCode -9993). Colouring the tag
// makes a mismatched pair (e.g. amber MME mic + sky DirectSound output) obvious.
export function hostApiTag(hostApi: string): { label: string; color: string } {
  const api = (hostApi ?? "").toLowerCase();
  if (api.includes("wasapi")) return { label: "WASAPI", color: "bg-emerald-700/50 text-emerald-100" };
  if (api.includes("directsound")) return { label: "DirectSound", color: "bg-sky-700/50 text-sky-100" };
  if (api.includes("wdm")) return { label: "WDM-KS", color: "bg-violet-700/50 text-violet-100" };
  if (api.includes("mme")) return { label: "MME", color: "bg-amber-700/50 text-amber-100" };
  if (!hostApi) return { label: "", color: "" };
  return { label: hostApi, color: "bg-white/10 text-white/65" };
}

export function deviceNumericId(device: Pick<VoiceAudioDevice, "id" | "index">): number {
  return num(device.id, device.index);
}

function findDevice(devices: Pick<VoiceAudioDevice, "id" | "index">[], id: number): Pick<VoiceAudioDevice, "id" | "index"> | undefined {
  return devices.find((device) => deviceNumericId(device) === id);
}

export function deviceName(devices: Pick<VoiceAudioDevice, "id" | "index" | "name">[], id: number, fallback = "Not selected"): string {
  return devices.find((device) => deviceNumericId(device) === id)?.name ?? fallback;
}

export function resolveMonitorDeviceId(
  currentMonitorDeviceId: number,
  selectedOutputDeviceId: number,
  outputDevices: Pick<VoiceAudioDevice, "id" | "index">[],
): number {
  if (currentMonitorDeviceId >= 0) return currentMonitorDeviceId;
  if (selectedOutputDeviceId >= 0 && findDevice(outputDevices, selectedOutputDeviceId)) return selectedOutputDeviceId;
  return outputDevices[0] ? deviceNumericId(outputDevices[0]) : -1;
}

export function meter(value: number): number {
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "...";
  return `${Number(value).toFixed(1)} ms`;
}
