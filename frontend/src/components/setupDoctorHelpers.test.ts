import { describe, expect, it } from "vitest";

import {
  compactModelDest,
  familyLabel,
  formatComputeCapability,
  setupDoctorStatus,
  tierLabel,
} from "./setupDoctorHelpers";
import type { CapabilityProfile } from "../types";

function cap(overrides: Partial<CapabilityProfile>): CapabilityProfile {
  return {
    schema_version: 1,
    selected_profile: "nvidia-cuda",
    active_profile: "nvidia-cuda",
    backend: "cuda",
    configured_stub_mode: false,
    effective_stub_mode: false,
    hardware_tier: "rich_16gb_plus",
    runtime_defaults: {},
    features: {},
    disabled_features: [],
    warnings: [],
    candidates: [],
    sources: {},
    ...overrides,
  };
}

describe("setupDoctorStatus", () => {
  it("returns a detecting state when capability is null", () => {
    const status = setupDoctorStatus(null);
    expect(status.tone).toBe("neutral");
    expect(status.headline).toMatch(/detecting/i);
  });

  it("reports CUDA as a good state with the GPU name", () => {
    const status = setupDoctorStatus(cap({
      backend: "cuda",
      primary_gpu: { name: "NVIDIA GeForce RTX 5070 Ti" },
    }));
    expect(status.tone).toBe("good");
    expect(status.headline).toMatch(/NVIDIA/);
    expect(status.detail).toContain("RTX 5070 Ti");
  });

  it("reports ROCm as active and flags disabled CUDA features", () => {
    const status = setupDoctorStatus(cap({
      backend: "rocm",
      selected_profile: "amd-rocm-linux",
      active_profile: "amd-rocm-linux",
      primary_gpu: { name: "AMD Radeon RX 7900 XTX" },
    }));
    expect(status.tone).toBe("good");
    expect(status.headline).toMatch(/AMD/);
    expect(status.detail).toMatch(/CUDA-only features are disabled/);
  });

  it("reports Apple MPS as active", () => {
    const status = setupDoctorStatus(cap({
      backend: "mps",
      selected_profile: "apple-mps",
      active_profile: "apple-mps",
      primary_gpu: { name: "Apple Silicon GPU" },
    }));
    expect(status.tone).toBe("good");
    expect(status.headline).toMatch(/Apple Silicon/);
    expect(status.detail).toMatch(/PyTorch MPS/);
  });

  it("explains CPU-safe fallback as a warning", () => {
    const status = setupDoctorStatus(cap({
      backend: "cpu",
      selected_profile: "cpu-safe",
      active_profile: "cpu-safe",
      effective_stub_mode: true,
    }));
    expect(status.tone).toBe("warn");
    expect(status.headline).toMatch(/CPU-safe/);
  });

  it("distinguishes a forced stub on capable hardware from a true CPU fallback", () => {
    const status = setupDoctorStatus(cap({
      backend: "cpu",
      selected_profile: "nvidia-cuda",
      active_profile: "cpu-safe",
      configured_stub_mode: true,
      effective_stub_mode: true,
      primary_gpu: { name: "NVIDIA GeForce RTX 5070 Ti" },
    }));
    expect(status.tone).toBe("warn");
    expect(status.headline).toMatch(/STUB/i);
    expect(status.detail).toMatch(/can run real models/);
  });
});

describe("formatting helpers", () => {
  it("formats a compute capability tuple", () => {
    expect(formatComputeCapability([12, 0])).toBe("12.0");
    expect(formatComputeCapability([8, 9])).toBe("8.9");
    expect(formatComputeCapability(undefined)).toBeNull();
    expect(formatComputeCapability([])).toBeNull();
  });

  it("maps tiers to friendly labels and falls back to the raw id", () => {
    expect(tierLabel("rich_16gb_plus")).toMatch(/16 GB/);
    expect(tierLabel("low_vram")).toMatch(/low VRAM/);
    expect(tierLabel("mystery")).toBe("mystery");
    expect(tierLabel(null)).toBe("unknown");
  });

  it("labels model families", () => {
    expect(familyLabel("flux2")).toBe("FLUX.2");
    expect(familyLabel("sdxl")).toBe("SDXL");
    expect(familyLabel("z-image")).toBe("Z-Image");
  });

  it("formats starter model destinations consistently", () => {
    expect(compactModelDest("models\\image", "sdxl.safetensors")).toBe("models/image/sdxl.safetensors");
    expect(compactModelDest("models/llm/", "chat.gguf")).toBe("models/llm/chat.gguf");
  });
});
