export type VideoMode = "t2v" | "i2v";

type ClipSettings = {
  width: number;
  height: number;
  frames: number;
  fps: number;
  steps: number;
  guidance: number;
};

type ClipPreset = ClipSettings & {
  id: string;
  label: string;
  families: string[];
};

export const RESOLUTION_PRESETS = [
  { label: "480p landscape", width: 832, height: 480 },
  { label: "480p portrait", width: 480, height: 832 },
  { label: "720p landscape", width: 1280, height: 704 },
  { label: "720p portrait", width: 704, height: 1280 },
];

export const CLIP_PRESETS: ClipPreset[] = [
  {
    id: "ltx-standard",
    label: "LTX 480p standard",
    families: ["ltx-video"],
    width: 704,
    height: 512,
    frames: 49,
    fps: 24,
    steps: 30,
    guidance: 3,
  },
  {
    id: "ltx-draft",
    label: "LTX 480p draft",
    families: ["ltx-video"],
    width: 704,
    height: 512,
    frames: 25,
    fps: 24,
    steps: 8,
    guidance: 3,
  },
  {
    id: "ltx-portrait",
    label: "LTX portrait",
    families: ["ltx-video"],
    width: 480,
    height: 832,
    frames: 49,
    fps: 24,
    steps: 30,
    guidance: 3,
  },
  {
    id: "wan-standard",
    label: "Wan 480p standard",
    families: ["wan-video"],
    width: 832,
    height: 480,
    frames: 49,
    fps: 24,
    steps: 30,
    guidance: 5,
  },
  {
    id: "wan-draft",
    label: "Wan 480p draft",
    families: ["wan-video"],
    width: 832,
    height: 480,
    frames: 25,
    fps: 24,
    steps: 8,
    guidance: 5,
  },
  {
    id: "wan-portrait",
    label: "Wan portrait",
    families: ["wan-video"],
    width: 480,
    height: 832,
    frames: 49,
    fps: 24,
    steps: 30,
    guidance: 5,
  },
  {
    id: "hunyuan-long",
    label: "FramePack portrait long",
    families: ["hunyuan-video"],
    width: 480,
    height: 832,
    frames: 91,
    fps: 30,
    steps: 30,
    guidance: 9,
  },
  {
    id: "hunyuan-draft",
    label: "FramePack square draft",
    families: ["hunyuan-video"],
    width: 512,
    height: 512,
    frames: 49,
    fps: 30,
    steps: 8,
    guidance: 9,
  },
  {
    id: "cogvideo-standard",
    label: "CogVideoX 480p standard",
    families: ["cogvideo"],
    width: 704,
    height: 480,
    frames: 49,
    fps: 8,
    steps: 30,
    guidance: 6,
  },
  {
    id: "cogvideo-draft",
    label: "CogVideoX 480p draft",
    families: ["cogvideo"],
    width: 704,
    height: 480,
    frames: 25,
    fps: 8,
    steps: 8,
    guidance: 6,
  },
];

// Per-family clip defaults — mirror the backend's validated recipe so queued
// params match what each model was trained on. LTX and Wan 2.2 are both 24 fps
// models; the previous 16 fps default pushed LTX below its trained 24-30 fps
// range and produced motion artifacts.
export const FAMILY_DEFAULT_PRESET: Record<string, string> = {
  "ltx-video": "ltx-standard",
  "wan-video": "wan-standard",
  "hunyuan-video": "hunyuan-long",
  cogvideo: "cogvideo-standard",
};
export const DEFAULT_PRESET = CLIP_PRESETS[0];

export function applyClipSettings(
  preset: ClipSettings,
  setters: {
    setWidth: (value: number) => void;
    setHeight: (value: number) => void;
    setFrames: (value: number) => void;
    setFps: (value: number) => void;
    setSteps: (value: number) => void;
    setGuidance: (value: number) => void;
  },
) {
  setters.setWidth(preset.width);
  setters.setHeight(preset.height);
  setters.setFrames(preset.frames);
  setters.setFps(preset.fps);
  setters.setSteps(preset.steps);
  setters.setGuidance(preset.guidance);
}
