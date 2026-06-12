import { describe, expect, it } from "vitest";

import {
  deviceHint,
  deviceName,
  formatBytes,
  formatMs,
  latencyPresets,
  meter,
  nativeRoutingSettingsPatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
  num,
  perfSummary,
  resolveMonitorDeviceId,
  routingSettingsPatch,
  selectedNativeModelId,
  selectedModelId,
  settingsToVoiceState,
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
  it("keeps numeric settings and falls back for invalid values", () => {
    expect(settingsToVoiceState({
      tran: "3",
      formantShift: -0.25,
      indexRatio: "bad",
      protect: undefined,
      f0Detector: "crepe_tiny",
      passThrough: 1,
      serverInputDeviceId: "4",
      serverOutputDeviceId: 8,
      serverMonitorDeviceId: null,
      serverAudioSampleRate: "44100",
      serverReadChunkSize: "96",
      crossFadeOverlapSize: "0.03",
      extraConvertSize: "7",
      serverInputAudioGain: "1.2",
      serverOutputAudioGain: false,
      serverMonitorAudioGain: undefined,
    })).toMatchObject({
      pitch: 3,
      formantShift: -0.25,
      indexRatio: 1,
      protect: 0.5,
      f0Detector: "crepe_tiny",
      passThrough: true,
      inputDeviceId: 4,
      outputDeviceId: 8,
      monitorDeviceId: 0,
      sampleRate: 44100,
      readChunkSize: 96,
      crossFadeOverlap: 0.03,
      extraConvert: 7,
      inputGain: 1.2,
      outputGain: 0,
      monitorGain: 1,
    });
  });

  it("falls back to RMVPE ONNX for unknown f0 detectors", () => {
    expect(settingsToVoiceState({ f0Detector: "not-real" }).f0Detector).toBe("rmvpe_onnx");
  });

  it("builds a routing-only settings patch", () => {
    expect(routingSettingsPatch({
      inputDeviceId: 1,
      outputDeviceId: 2,
      monitorDeviceId: -1,
      sampleRate: 48000,
      readChunkSize: 133,
      crossFadeOverlap: 0.05,
      extraConvert: 5,
      inputGain: 1,
      outputGain: 0.9,
      monitorGain: 0.7,
    })).toEqual({
      server_input_device_id: 1,
      server_output_device_id: 2,
      server_monitor_device_id: -1,
      server_audio_sample_rate: 48000,
      server_read_chunk_size: 133,
      cross_fade_overlap_size: 0.05,
      extra_convert_size: 5,
      server_input_gain: 1,
      server_output_gain: 0.9,
      server_monitor_gain: 0.7,
    });
  });

  it("maps native snake_case settings and preserves unselected input/output devices as null patches", () => {
    expect(nativeSettingsToVoiceState({
      pitch: "2",
      index_ratio: "0.25",
      protect: "0.4",
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
      formantShift: 0,
      indexRatio: 0.25,
      protect: 0.4,
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
      indexRatio: 0.4,
      protect: 0.2,
      f0Detector: "rmvpe",
      passThrough: false,
    })).toEqual({
      pitch: -3,
      index_ratio: 0.4,
      protect: 0.2,
      f0_detector: "rmvpe",
      pass_through: false,
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
  it("selects the current model by slot and falls back to the first model", () => {
    expect(selectedModelId([model({ id: "a", slot: "1" }), model({ id: "b", slot: "2" })], "2")).toBe("b");
    expect(selectedModelId([model({ id: "a", slot: "1" })], "missing")).toBe("a");
    expect(selectedModelId([], null)).toBe("");
    expect(selectedNativeModelId([model({ id: "a" }), model({ id: "b" })], "b", "a")).toBe("b");
    expect(selectedNativeModelId([model({ id: "a" }), model({ id: "b" })], "missing", "b")).toBe("b");
    expect(selectedNativeModelId([], "", "b")).toBe("");
  });

  it("summarizes performance and formats sizes/timings/meters", () => {
    expect(perfSummary(null)).toBe("...");
    expect(perfSummary({ a: 1, b: "x", c: true, d: { nested: true } })).toBe("a:1, b:x, c:true");
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
});
