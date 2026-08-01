import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { storage } from "../lib/storage";
import type { SelectOption } from "./Select";
import type { ComposerApply, Lora, Model, Preset } from "../types";
import {
  DEFAULT_GUIDANCE,
  DEFAULT_SIZE,
  DEFAULT_STEPS,
  boundedNumberParam,
  imageFamilyDefaults,
  imageModelRank,
  inferTouched,
  isLoraCompatible,
  isModelAvailable,
  loadPromptHistory,
  parseLoraSelections,
  pickDefaultImageModel,
  PROMPT_HISTORY_KEY,
  promptHistoryLimit,
  readSaved,
  STORE_KEY,
  type LoraSelection,
  type SavedComposer,
  type TouchedFields,
} from "./imageComposerHelpers";
import { toast } from "./Toast";
import { useImageDefaultSettings } from "./useImageDefaultSettings";

const RATIOS = [
  { label: "1:1", w: 1, h: 1 },
  { label: "3:4", w: 3, h: 4 },
  { label: "4:3", w: 4, h: 3 },
  { label: "16:9", w: 16, h: 9 },
  { label: "9:16", w: 9, h: 16 },
];

export type ImageComposerProps = {
  models: Model[];
  modelsLoading?: boolean;
  loras: Lora[];
  lorasLoading?: boolean;
  presets: Preset[];
  presetsLoading?: boolean;
  onPresetsChanged: () => void | Promise<void>;
  promptDraft: string;
  setPromptDraft: (value: string) => void;
  apply?: ComposerApply | null;
};

export function useImageComposerController({
  models,
  modelsLoading = false,
  loras,
  lorasLoading = false,
  presets,
  presetsLoading = false,
  onPresetsChanged,
  promptDraft,
  setPromptDraft,
  apply,
}: ImageComposerProps) {
  const imgModels = models
    .filter((m) => m.job_type === "image" && m.family !== "qwen-image-edit" && m.family !== "flux-kontext")
    .sort((a, b) => imageModelRank(a) - imageModelRank(b) || a.name.localeCompare(b.name));

  const saved = useMemo(readSaved, []);
  const [imgModel, setImgModel] = useState(saved.imgModel ?? "");
  const [negative, setNegative] = useState(saved.negative ?? "");
  const [steps, setSteps] = useState(saved.steps ?? DEFAULT_STEPS);
  const [guidance, setGuidance] = useState(saved.guidance ?? DEFAULT_GUIDANCE);
  const [width, setWidth] = useState(saved.width ?? DEFAULT_SIZE);
  const [height, setHeight] = useState(saved.height ?? DEFAULT_SIZE);
  const [seed, setSeed] = useState(saved.seed ?? -1);
  const [batch, setBatch] = useState(saved.batch ?? 1);
  const [selectedLoras, setSelectedLoras] = useState<LoraSelection[]>(saved.selectedLoras ?? []);
  const [count, setCount] = useState(saved.count ?? 1);
  const [presetId, setPresetId] = useState(saved.presetId ?? "");
  const [presetName, setPresetName] = useState("");
  const [presetError, setPresetError] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [promptHistory, setPromptHistory] = useState<string[]>(() => loadPromptHistory());
  const [promptHistoryOpen, setPromptHistoryOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const promptHistoryRef = useRef<HTMLDivElement>(null);
  // Which numeric fields the user has explicitly edited. Untouched fields track
  // family/server defaults; touched ones survive tab switches and family changes.
  const [touched, setTouched] = useState<TouchedFields>(() => inferTouched(saved));
  const serverDefaults = useImageDefaultSettings();

  const selectedImgModel = imgModels.find((m) => m.id === imgModel);
  const selectedFamily = selectedImgModel?.family;
  const imagePresets = presets.filter((p) => p.type === "image");
  const compatibleLoras = loras
    .filter((lora) => isLoraCompatible(lora, selectedImgModel))
    .sort((a, b) => a.name.localeCompare(b.name));

  useEffect(() => {
    if (!imgModel || !isModelAvailable(selectedImgModel)) {
      const preferred = pickDefaultImageModel(imgModels);
      if (preferred && preferred.id !== imgModel) setImgModel(preferred.id);
    }
  }, [imgModels, imgModel, selectedImgModel]);

  useEffect(() => {
    const data: SavedComposer = {
      imgModel,
      negative,
      steps,
      guidance,
      width,
      height,
      seed,
      batch,
      count,
      selectedLoras,
      presetId,
      touched,
    };
    try {
      storage.set(STORE_KEY, JSON.stringify(data));
    } catch {
      // Private-mode or quota errors should not break generation.
    }
  }, [
    imgModel,
    negative,
    steps,
    guidance,
    width,
    height,
    seed,
    batch,
    count,
    selectedLoras,
    presetId,
    touched,
  ]);

  useEffect(() => {
    if (lorasLoading || modelsLoading) return;
    setSelectedLoras((current) =>
      current.filter((selected) => {
        const lora = loras.find((item) => item.id === selected.id);
        return lora ? isLoraCompatible(lora, selectedImgModel) : false;
      }),
    );
  }, [loras, lorasLoading, modelsLoading, selectedImgModel]);

  useEffect(() => {
    if (!presetsLoading && presetId && !imagePresets.some((preset) => preset.id === presetId)) {
      setPresetId("");
    }
  }, [imagePresets, presetId, presetsLoading]);

  // Untouched numeric fields follow the best default for the current selection:
  // the family-specific default (flux2/qwen/z-image) when there is one, else the
  // server-configured writable default. Touched fields are left alone so a user's
  // choice survives remounts (tab switches), family switches, and default changes.
  useEffect(() => {
    const fam = imageFamilyDefaults(selectedFamily, selectedImgModel, serverDefaults);
    const effective = fam ?? {
      steps: serverDefaults.default_steps,
      guidance: serverDefaults.default_guidance,
      width: serverDefaults.default_width,
      height: serverDefaults.default_height,
    };
    if (!touched.steps) setSteps(effective.steps);
    if (!touched.guidance) setGuidance(effective.guidance);
    if (!touched.width) setWidth(effective.width);
    if (!touched.height) setHeight(effective.height);
  }, [selectedFamily, selectedImgModel, serverDefaults, touched]);

  // Field editors that record the user's intent. Editing a field marks it
  // touched so it stops tracking defaults and survives the next remount.
  const clearActivePreset = useCallback(() => setPresetId(""), []);
  const editSteps = useCallback((v: number) => {
    setSteps(v);
    setTouched((t) => ({ ...t, steps: true }));
    clearActivePreset();
  }, [clearActivePreset]);
  const editGuidance = useCallback((v: number) => {
    setGuidance(v);
    setTouched((t) => ({ ...t, guidance: true }));
    clearActivePreset();
  }, [clearActivePreset]);
  const editWidth = useCallback((v: number) => {
    setWidth(v);
    setTouched((t) => ({ ...t, width: true }));
    clearActivePreset();
  }, [clearActivePreset]);
  const editHeight = useCallback((v: number) => {
    setHeight(v);
    setTouched((t) => ({ ...t, height: true }));
    clearActivePreset();
  }, [clearActivePreset]);

  const editImgModel = useCallback((value: string) => {
    setImgModel(value);
    clearActivePreset();
  }, [clearActivePreset]);
  const editNegative = useCallback((value: string) => {
    setNegative(value);
    clearActivePreset();
  }, [clearActivePreset]);
  const editPromptDraft = useCallback((value: string) => {
    setPromptDraft(value);
    clearActivePreset();
  }, [clearActivePreset, setPromptDraft]);
  const editSeed = useCallback((value: number) => {
    setSeed(value);
    clearActivePreset();
  }, [clearActivePreset]);
  const editBatch = useCallback((value: number) => {
    setBatch(value);
    clearActivePreset();
  }, [clearActivePreset]);

  const imageParams = () => ({
    prompt: promptDraft.trim(),
    negative: negative.trim() || undefined,
    steps,
    guidance,
    width,
    height,
    seed,
    batch_size: batch,
    loras: selectedLoras.length ? selectedLoras.map(({ id, weight }) => ({ id, weight })) : undefined,
  });

  const rememberPrompt = useCallback((content: string) => {
    const text = content.trim();
    if (!text) return;
    setPromptHistory((prev) => [text, ...prev.filter((item) => item !== text)].slice(0, promptHistoryLimit));
  }, []);

  const generate = async () => {
    if (!imgModel || !promptDraft.trim() || queueing) return;
    const params = imageParams();
    rememberPrompt(params.prompt);
    setQueueing(true);
    try {
      await api.createJobs(
        Array.from({ length: count }, (_, index) => ({
          type: "image" as const,
          model_id: imgModel,
          params: {
            ...params,
            seed: seed >= 0 ? (seed + index * batch) % 2 ** 31 : -1,
          },
        })),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not queue image generation");
    } finally {
      setQueueing(false);
    }
  };

  const applyRatio = (rw: number, rh: number) => {
    const base =
      imageFamilyDefaults(selectedFamily, selectedImgModel, serverDefaults)?.width ?? serverDefaults.default_width;
    const round64 = (n: number) => Math.max(64, Math.round(n / 64) * 64);
    if (rw >= rh) {
      editWidth(round64(base));
      editHeight(round64((base * rh) / rw));
    } else {
      editHeight(round64(base));
      editWidth(round64((base * rw) / rh));
    }
  };

  const updateLoraWeight = (id: string, weight: number) => {
    clearActivePreset();
    setSelectedLoras((current) => current.map((lora) => (lora.id === id ? { ...lora, weight } : lora)));
  };

  const toggleLora = (lora: Lora, enabled: boolean) => {
    clearActivePreset();
    setSelectedLoras((current) => {
      const exists = current.some((selected) => selected.id === lora.id);
      if (enabled && !exists) return [...current, { id: lora.id, weight: 1 }];
      if (!enabled) return current.filter((selected) => selected.id !== lora.id);
      return current;
    });
  };

  const savePreset = async () => {
    const name = presetName.trim();
    if (!name || !imgModel || presetBusy) return;
    setPresetError("");
    setPresetBusy(true);
    try {
      const created = await api.createPreset(name, "image", { ...imageParams(), model_id: imgModel });
      setPresetName("");
      await onPresetsChanged();
      setPresetId(created.id);
    } catch (err) {
      setPresetError(err instanceof Error ? err.message : "Could not save preset");
    } finally {
      setPresetBusy(false);
    }
  };

  // Load a full param snapshot into the composer. Shared by presets (model
  // identified by id) and History reproduce (model id resolved by the caller).
  const applyParams = (params: Record<string, unknown>, modelId?: string, activePresetId = "") => {
    const targetId = modelId ?? (typeof params.model_id === "string" ? params.model_id : undefined);
    const model = targetId ? imgModels.find((m) => m.id === targetId) : undefined;
    if (activePresetId && targetId && (!model || !isModelAvailable(model))) {
      setPresetError("The model saved in this preset is unavailable. Rescan models or update the preset.");
      return false;
    }
    if (typeof params.prompt === "string") setPromptDraft(params.prompt);
    setNegative(typeof params.negative === "string" ? params.negative : "");
    if (model && isModelAvailable(model)) setImgModel(model.id);
    // A loaded snapshot is an explicit choice: mark the fields touched so the
    // defaults effect doesn't snap them back on the next family resolve/remount.
    editSteps(boundedNumberParam(params.steps, steps, 1, 150, { integer: true }));
    editGuidance(boundedNumberParam(params.guidance, guidance, 0, 30));
    editWidth(boundedNumberParam(params.width, width, 256, 2048, { integer: true, multipleOf: 64 }));
    editHeight(boundedNumberParam(params.height, height, 256, 2048, { integer: true, multipleOf: 64 }));
    setSeed(boundedNumberParam(params.seed, seed, -1, 2 ** 31 - 1, { integer: true }));
    setBatch(boundedNumberParam(params.batch_size, batch, 1, 16, { integer: true }));
    const parsedLoras = parseLoraSelections(params.loras, loras, model ?? selectedImgModel);
    setSelectedLoras(parsedLoras);
    const requestedLoras = Array.isArray(params.loras) ? params.loras.length : 0;
    if (activePresetId && parsedLoras.length < requestedLoras) {
      setPresetError("Some LoRAs saved in this preset are missing or incompatible and were skipped.");
    }
    setPresetId(activePresetId);
    return true;
  };

  const applyPreset = () => {
    if (modelsLoading || lorasLoading || presetBusy) return;
    setPresetError("");
    const preset = imagePresets.find((p) => p.id === presetId);
    if (preset) applyParams(preset.params, undefined, preset.id);
  };

  // External "reproduce from History" request: apply once per nonce.
  const appliedNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!apply || apply.nonce === appliedNonce.current) return;
    appliedNonce.current = apply.nonce;
    applyParams(apply.params, apply.model_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apply]);

  useEffect(() => {
    try {
      storage.set(PROMPT_HISTORY_KEY, JSON.stringify(promptHistory));
    } catch {
      // Private-mode or quota errors should not break recall.
    }
  }, [promptHistory]);

  useEffect(() => {
    if (!promptHistoryOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (promptHistoryRef.current && !promptHistoryRef.current.contains(e.target as Node)) {
        setPromptHistoryOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [promptHistoryOpen]);

  const deletePreset = async () => {
    if (!presetId || presetBusy) return;
    setPresetError("");
    setPresetBusy(true);
    try {
      await api.deletePreset(presetId);
      setPresetId("");
      await onPresetsChanged();
    } catch (err) {
      setPresetError(err instanceof Error ? err.message : "Could not delete preset");
    } finally {
      setPresetBusy(false);
    }
  };

  const presetOptions: SelectOption[] = [
    { value: "", label: "unsaved" },
    ...imagePresets.map((p) => ({ value: p.id, label: p.name })),
  ];

  const selectedUnavailableReason = selectedImgModel?.unavailable_reason ?? "";
  const canQueue =
    Boolean(imgModel) && isModelAvailable(selectedImgModel) && Boolean(promptDraft.trim()) && !queueing;
  const canApplyPreset = Boolean(presetId) && !modelsLoading && !lorasLoading && !presetBusy;
  const canSavePreset =
    Boolean(presetName.trim()) && Boolean(imgModel) && isModelAvailable(selectedImgModel) && !presetBusy;
  const familyDefaults = imageFamilyDefaults(selectedFamily, selectedImgModel, serverDefaults);
  const activeRatio = RATIOS.find((r) => isRatio(width, height, r.w, r.h))?.label ?? "custom";
  const promptChars = promptDraft.trim().length;
  const queueLabel = count > 1 ? `Queue ${count} jobs` : "Queue generation";
  const visiblePromptHistory = promptHistory.filter((item) => item !== promptDraft.trim()).slice(0, 8);

  return {
    activeRatio,
    applyPreset,
    applyRatio,
    batch,
    canApplyPreset,
    canQueue,
    canSavePreset,
    compatibleLoras,
    count,
    deletePreset,
    editGuidance,
    editHeight,
    editSteps,
    editWidth,
    generate,
    guidance,
    height,
    imagePresets,
    imgModel,
    imgModels,
    libraryOpen,
    lorasLoading,
    modelsLoading,
    negative,
    presetError,
    presetBusy,
    presetId,
    presetName,
    presetOptions,
    presetsLoading,
    promptChars,
    promptDraft,
    promptHistoryOpen,
    promptHistoryRef,
    queueLabel,
    queueing,
    ratios: RATIOS,
    savePreset,
    seed,
    selectedFamily,
    selectedImgModel,
    selectedLoras,
    selectedUnavailableReason,
    setBatch: editBatch,
    setCount,
    setImgModel: editImgModel,
    setLibraryOpen,
    setNegative: editNegative,
    setPresetId,
    setPresetName,
    setPromptDraft: editPromptDraft,
    setPromptHistoryOpen,
    setSeed: editSeed,
    steps,
    toggleLora,
    updateLoraWeight,
    visiblePromptHistory,
    width,
    familyDefaults,
  };
}

function isRatio(w: number, h: number, rw: number, rh: number): boolean {
  if (!w || !h) return false;
  return Math.abs(w / h - rw / rh) < 0.02;
}
