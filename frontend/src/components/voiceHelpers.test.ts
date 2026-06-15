import { describe, expect, it } from "vitest";

import {
  deviceHint,
  deviceName,
  feminineVoicePreset,
  formatBytes,
  formatMs,
  latencyPresets,
  meter,
  nativeRoutingSettingsPatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
  nativeVoicePresetSettingsPatch,
  num,
  recommendedVoicePreset,
  resolveMonitorDeviceId,
  selectedNativeModelId,
} from "./voiceHelpers";
import type { VoiceAudioDevice, VoiceModel } from "../types";

function device(over: Partial<VoiceAudioDevice> = {}): VoiceAudioDevice {
  return {
    id: "0",
    index: 0,
    name: "Device 0",
    host_api: "WASAPI",
    max_input_channels: 0,
    max_output_channels: 2,
    default_sample_rate: 48000,
    ...over,
  };
}

function model(over: Partial<VoiceModel> = {}): VoiceModel {
  return {
    id: "slot-0",
    slot: "0",
    name: "Voice 0",
    type: "RVC",
    version: "",
    sampling_rate: null,
    f0: false,
    has_index: false,
    size_bytes: 0,
    ...over,
  };
}

describe("settings coercion", () => {
  it("maps native snake_case settings and preserves unselected input/output devices as null patches", () => {
    expect(nativeSettingsToVoiceState({
      pitch: "2",
      input_formant: "1.25",
      input_gate_db: "-55",
      input_highpass_hz: "120",
      input_denoise: "dtln",
      input_denoise_mix: "0.65",
      silence_threshold_db: "-48",
      silence_hold_ms: "400",
      index_ratio: "0.25",
      protect: "0.4",
      noise_scale: "0.33",
      f0_smoothing: "0.2",
      f0_detector: "rmvpe",
      pass_through: true,
      server_input_device_id: null,
      server_output_device_id: 5,
      server_monitor_device_id: -1,
      server_audio_sample_rate: 48000,
      server_read_chunk_size: 192,
      cross_fade_overlap_size: 0.08,
      extra_convert_size: 2,
      server_input_gain: 1.1,
      server_output_gain: 0.8,
      server_monitor_gain: 0.6,
    })).toMatchObject({
      pitch: 2,
      formantShift: 1.25,
      inputGateDb: -55,
      inputHighpassHz: 120,
      inputDenoise: "dtln",
      inputDenoiseMix: 0.65,
      silenceThresholdDb: -48,
      silenceHoldMs: 400,
      indexRatio: 0.25,
      protect: 0.4,
      noiseScale: 0.33,
      f0Smoothing: 0.2,
      f0Detector: "rmvpe",
      passThrough: true,
      inputDeviceId: -1,
      outputDeviceId: 5,
      monitorDeviceId: -1,
      readChunkSize: 192,
      extraConvert: 2,
    });

    expect(nativeRoutingSettingsPatch({
      inputDeviceId: -1,
      outputDeviceId: -1,
      monitorDeviceId: -1,
      sampleRate: 48000,
      readChunkSize: 133,
      crossFadeOverlap: 0.05,
      extraConvert: 2,
      inputGain: 1,
      outputGain: 1,
      monitorGain: 0.5,
    })).toEqual({
      server_input_device_id: null,
      server_output_device_id: null,
      server_monitor_device_id: -1,
      server_audio_sample_rate: 48000,
      server_read_chunk_size: 133,
      cross_fade_overlap_size: 0.05,
      extra_convert_size: 2,
      server_input_gain: 1,
      server_output_gain: 1,
      server_monitor_gain: 0.5,
    });
  });

  it("builds a native tuning settings patch", () => {
    expect(nativeTuningSettingsPatch({
      pitch: -3,
      formantShift: 0.5,
      inputGateDb: -70,
      inputHighpassHz: 80,
      inputDenoise: "dtln",
      inputDenoiseMix: 0.75,
      silenceThresholdDb: -52,
      silenceHoldMs: 250,
      indexRatio: 0.4,
      protect: 0.2,
      noiseScale: 0.5,
      f0Smoothing: 0.1,
      f0Detector: "rmvpe",
      passThrough: false,
    })).toEqual({
      pitch: -3,
      input_formant: 0.5,
      input_gate_db: -70,
      input_highpass_hz: 80,
      input_denoise: "dtln",
      input_denoise_mix: 0.75,
      silence_threshold_db: -52,
      silence_hold_ms: 250,
      index_ratio: 0.4,
      protect: 0.2,
      noise_scale: 0.5,
      f0_smoothing: 0.1,
      f0_detector: "rmvpe",
      pass_through: false,
    });
  });

  it("builds a voice preset settings patch without device ids", () => {
    expect(nativeVoicePresetSettingsPatch({
      pitch: 12,
      speakerId: 0,
      formantShift: 0,
      inputGateDb: -90,
      inputHighpassHz: 80,
      inputDenoise: "off",
      inputDenoiseMix: 0,
      silenceThresholdDb: -72,
      silenceHoldMs: 250,
      indexRatio: 0.33,
      protect: 0.5,
      noiseScale: 0.66666,
      f0Smoothing: 0,
      f0Detector: "rmvpe",
      sampleRate: 48000,
      readChunkSize: 192,
      crossFadeOverlap: 0.05,
      extraConvert: 5,
      inputGain: 1,
      outputGain: 1,
      monitorGain: 0.5,
    })).toEqual({
      pitch: 12,
      speaker_id: 0,
      input_formant: 0,
      input_gate_db: -90,
      input_highpass_hz: 80,
      input_denoise: "off",
      input_denoise_mix: 0,
      silence_threshold_db: -72,
      silence_hold_ms: 250,
      index_ratio: 0.33,
      protect: 0.5,
      noise_scale: 0.66666,
      f0_smoothing: 0,
      f0_detector: "rmvpe",
      server_audio_sample_rate: 48000,
      server_read_chunk_size: 192,
      cross_fade_overlap_size: 0.05,
      extra_convert_size: 5,
      server_input_gain: 1,
      server_output_gain: 1,
      server_monitor_gain: 0.5,
    });
  });

  it("num returns finite numbers only", () => {
    expect(num("4", 0)).toBe(4);
    expect(num("no", 7)).toBe(7);
    expect(num(undefined, 2)).toBe(2);
  });
});

describe("device helpers", () => {
  it("formats host API and sample rate hints", () => {
    expect(deviceHint("WASAPI", 48000)).toBe("WASAPI, 48k");
    expect(deviceHint("", null)).toBe("");
  });

  it("shows the selected device name or a fallback", () => {
    expect(deviceName([device({ id: "5", index: 5, name: "Headphones" })], 5)).toBe("Headphones");
    expect(deviceName([], -1)).toBe("Not selected");
  });

  it("resolves monitor device to current, selected output, first output, or none", () => {
    const outputs = [
      device({ id: "2", index: 2, name: "Cable" }),
      device({ id: "9", index: 9, name: "Headphones" }),
    ];
    expect(resolveMonitorDeviceId(9, 2, outputs)).toBe(9);
    expect(resolveMonitorDeviceId(-1, 2, outputs)).toBe(2);
    expect(resolveMonitorDeviceId(-1, 7, outputs)).toBe(2);
    expect(resolveMonitorDeviceId(-1, -1, [])).toBe(-1);
  });
});

describe("formatters and constants", () => {
  it("selects the current native model and falls back to the loaded model", () => {
    expect(selectedNativeModelId([model({ id: "a" }), model({ id: "b" })], "b", "a")).toBe("b");
    expect(selectedNativeModelId([model({ id: "a" }), model({ id: "b" })], "missing", "b")).toBe("b");
    expect(selectedNativeModelId([], "", "b")).toBe("");
  });

  it("formats sizes/timings/meters", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(2_000_000_000)).toBe("2.00 GB");
    expect(formatMs(12.345)).toBe("12.3 ms");
    expect(formatMs(undefined)).toBe("...");
    expect(meter(1.5)).toBe(100);
    expect(meter(-1)).toBe(0);
  });

  it("exports the existing latency presets", () => {
    expect(latencyPresets.map((preset) => preset.id)).toEqual(["fast", "balanced", "quality"]);
  });

  it("exports the recommended voice preset without pitch", () => {
    expect(recommendedVoicePreset).toMatchObject({
      inputDenoise: "dtln",
      inputDenoiseMix: 0.75,
      inputGateDb: -90,
      silenceThresholdDb: -72,
      silenceHoldMs: 250,
      indexRatio: 0.5,
      protect: 0.33,
      noiseScale: 0.66666,
      f0Smoothing: 0,
      readChunkSize: 133,
      crossFadeOverlap: 0.06,
      extraConvert: 2,
      sampleRate: 48000,
    });
    expect("pitch" in recommendedVoicePreset).toBe(false);
    // protect 0.5 would disable RVC consonant protection; quality presets must
    // keep it strictly below 0.5 so sibilants stay crisp.
    expect(recommendedVoicePreset.protect).toBeLessThan(0.5);
  });

  it("keeps the +12 feminine preset in the validated clarity range", () => {
    expect(feminineVoicePreset).toMatchObject({
      pitch: 12,
      indexRatio: 0.3,
      noiseScale: 0.5,
      protect: 0.33,
      f0Detector: "rmvpe",
    });
    expect(feminineVoicePreset.indexRatio).toBeGreaterThanOrEqual(0.25);
    expect(feminineVoicePreset.indexRatio).toBeLessThanOrEqual(0.35);
    expect(feminineVoicePreset.noiseScale).toBeGreaterThanOrEqual(0.45);
    expect(feminineVoicePreset.noiseScale).toBeLessThanOrEqual(0.55);
  });
});
