import type { CapabilityProfile, ModelFamily } from "../types";

export type DoctorTone = "good" | "warn" | "info" | "neutral";

export interface DoctorStatus {
  headline: string;
  detail: string;
  tone: DoctorTone;
}

/**
 * Plain-language one-liner for the Setup doctor headline (P20.6). Intentionally
 * avoids CUDA/ROCm jargon in the headline and explains the trade-off in detail.
 */
export function setupDoctorStatus(cap: CapabilityProfile | null): DoctorStatus {
  if (!cap) {
    return {
      headline: "Detecting hardware…",
      detail: "Probing the local machine for a supported accelerator.",
      tone: "neutral",
    };
  }

  const gpuName = cap.primary_gpu?.name?.trim();

  // A forced STUB on real GPU hardware is a deliberate dev choice, not a fault.
  if (cap.configured_stub_mode && cap.selected_profile !== "cpu-safe") {
    return {
      headline: "STUB mode is on",
      detail: gpuName
        ? `${gpuName} can run real models, but stub mode forces placeholder output for this process.`
        : "Stub mode forces placeholder output for this process.",
      tone: "warn",
    };
  }

  if (cap.backend === "cuda") {
    return {
      headline: "NVIDIA GPU detected, using the CUDA build",
      detail: gpuName
        ? `${gpuName} is set up with the CUDA PyTorch wheels.`
        : "CUDA PyTorch wheels are installed.",
      tone: "good",
    };
  }

  if (cap.backend === "rocm") {
    return {
      headline: "AMD GPU detected, ROCm build active",
      detail: gpuName
        ? `${gpuName} runs through the Linux ROCm PyTorch build; CUDA-only features are disabled.`
        : "The Linux ROCm PyTorch build is active; CUDA-only features are disabled.",
      tone: "good",
    };
  }

  return {
    headline: "GPU path unavailable, using CPU-safe mode",
    detail: gpuName
      ? `${gpuName} has no supported accelerator path here, so models render in CPU-safe placeholder mode.`
      : "No supported GPU accelerator was found, so models render in CPU-safe placeholder mode.",
    tone: "warn",
  };
}

const TIER_LABELS: Record<string, string> = {
  large_24gb_plus: "24 GB+ (large)",
  rich_16gb_plus: "16 GB+ (rich)",
  balanced_12gb: "12 GB (balanced)",
  safe_8gb: "8 GB (safe)",
  low_vram: "under 8 GB (low VRAM)",
  unknown: "unknown",
};

export function tierLabel(tier: string | undefined | null): string {
  if (!tier) return "unknown";
  return TIER_LABELS[tier] ?? tier;
}

export function formatComputeCapability(tuple: number[] | undefined | null): string | null {
  if (!tuple || tuple.length < 2) return null;
  return `${tuple[0]}.${tuple[1]}`;
}

const FAMILY_LABELS: Record<ModelFamily, string> = {
  flux: "FLUX",
  flux2: "FLUX.2",
  "qwen-image": "Qwen-Image",
  "z-image": "Z-Image",
  sdxl: "SDXL",
  gguf: "GGUF",
  unknown: "Unknown",
};

export function familyLabel(family: ModelFamily): string {
  return FAMILY_LABELS[family] ?? family;
}
