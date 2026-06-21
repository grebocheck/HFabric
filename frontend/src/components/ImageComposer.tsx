import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ModelPicker } from "./ModelPicker";
import { PromptLibrary } from "./PromptLibrary";
import { Select, type SelectOption } from "./Select";
import { SkeletonLine, SkeletonRows } from "./WorkspaceChrome";
import { ImageParamForm, LoraCard, Notice } from "./ImageComposerParts";
import type { ComposerApply, Lora, Model, Preset } from "../types";
import {
  DEFAULT_GUIDANCE,
  DEFAULT_SIZE,
  DEFAULT_STEPS,
  imageFamilyDefaults,
  imageModelRank,
  inferTouched,
  isLoraCompatible,
  isModelAvailable,
  isNunchaku,
  isZImageTurbo,
  loadPromptHistory,
  numberParam,
  pickDefaultImageModel,
  PROMPT_HISTORY_KEY,
  promptHistoryLimit,
  readSaved,
  STORE_KEY,
  type LoraSelection,
  type SavedComposer,
  type TouchedFields,
} from "./imageComposerHelpers";

const field =
  "ui-field w-full rounded-md px-2.5 py-1.5 text-[13px]";
const label = "text-[10px] font-medium uppercase tracking-wide text-ui-subtle";
const section = "border-b border-line p-3 last:border-b-0";
const subtleButton = "ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30";

const RATIOS: Array<{ label: string; w: number; h: number }> = [
  { label: "1:1", w: 1, h: 1 },
  { label: "3:4", w: 3, h: 4 },
  { label: "4:3", w: 4, h: 3 },
  { label: "16:9", w: 16, h: 9 },
  { label: "9:16", w: 9, h: 16 },
];

export function ImageComposer({
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
}: {
  models: Model[];
  modelsLoading?: boolean;
  loras: Lora[];
  lorasLoading?: boolean;
  presets: Preset[];
  presetsLoading?: boolean;
  onPresetsChanged: () => void;
  promptDraft: string;
  setPromptDraft: (v: string) => void;
  apply?: ComposerApply | null;
}) {
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
  const [promptHistory, setPromptHistory] = useState<string[]>(() => loadPromptHistory());
  const [promptHistoryOpen, setPromptHistoryOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const promptHistoryRef = useRef<HTMLDivElement>(null);
  // Which numeric fields the user has explicitly edited. Untouched fields track
  // family/server defaults; touched ones survive tab switches and family changes.
  const [touched, setTouched] = useState<TouchedFields>(() => inferTouched(saved));
  const [serverDefaults, setServerDefaults] = useState({
    default_steps: DEFAULT_STEPS,
    default_guidance: DEFAULT_GUIDANCE,
    default_width: DEFAULT_SIZE,
    default_height: DEFAULT_SIZE,
  });

  const selectedImgModel = imgModels.find((m) => m.id === imgModel);
  const selectedFamily = selectedImgModel?.family;
  const imagePresets = presets.filter((p) => p.type === "image");
  const compatibleLoras = loras
    .filter((lora) => isLoraCompatible(lora, selectedImgModel))
    .sort((a, b) => a.name.localeCompare(b.name));

  const fetchServerDefaults = useCallback(() => {
    api.settingsOverrides()
      .then(({ values }) => setServerDefaults(values))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchServerDefaults();
    const onDefaultsChanged = () => fetchServerDefaults();
    window.addEventListener("hfabric:settings-overrides", onDefaultsChanged);
    return () => window.removeEventListener("hfabric:settings-overrides", onDefaultsChanged);
  }, [fetchServerDefaults]);

  useEffect(() => {
    if (!imgModel || !isModelAvailable(selectedImgModel)) {
      const preferred = pickDefaultImageModel(imgModels);
      if (preferred && preferred.id !== imgModel) setImgModel(preferred.id);
    }
  }, [imgModels, imgModel, selectedImgModel]);

  useEffect(() => {
    const data: SavedComposer = { imgModel, negative, steps, guidance, width, height, seed, batch, count, selectedLoras, presetId, touched };
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(data));
    } catch {
      // Private-mode or quota errors should not break generation.
    }
  }, [imgModel, negative, steps, guidance, width, height, seed, batch, count, selectedLoras, presetId, touched]);

  useEffect(() => {
    setSelectedLoras((current) =>
      current.filter((selected) => {
        const lora = loras.find((item) => item.id === selected.id);
        return lora ? isLoraCompatible(lora, selectedImgModel) : false;
      }),
    );
  }, [loras, selectedImgModel]);

  // Untouched numeric fields follow the best default for the current selection:
  // the family-specific default (flux2/qwen/z-image) when there is one, else the
  // server-configured writable default. Touched fields are left alone so a user's
  // choice survives remounts (tab switches), family switches, and default changes.
  useEffect(() => {
    const fam = imageFamilyDefaults(selectedFamily, selectedImgModel);
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
  const editSteps = useCallback((v: number) => { setSteps(v); setTouched((t) => ({ ...t, steps: true })); }, []);
  const editGuidance = useCallback((v: number) => { setGuidance(v); setTouched((t) => ({ ...t, guidance: true })); }, []);
  const editWidth = useCallback((v: number) => { setWidth(v); setTouched((t) => ({ ...t, width: true })); }, []);
  const editHeight = useCallback((v: number) => { setHeight(v); setTouched((t) => ({ ...t, height: true })); }, []);

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
    if (!imgModel || !promptDraft.trim()) return;
    const params = imageParams();
    rememberPrompt(params.prompt);
    await api.createJobs(Array.from({ length: count }, () => ({ type: "image" as const, model_id: imgModel, params })));
  };

  const applyRatio = (rw: number, rh: number) => {
    const base = imageFamilyDefaults(selectedFamily, selectedImgModel)?.width ?? serverDefaults.default_width;
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
    setSelectedLoras((current) => current.map((lora) => lora.id === id ? { ...lora, weight } : lora));
  };

  const toggleLora = (lora: Lora, enabled: boolean) => {
    setSelectedLoras((current) => {
      const exists = current.some((selected) => selected.id === lora.id);
      if (enabled && !exists) return [...current, { id: lora.id, weight: 1 }];
      if (!enabled) return current.filter((selected) => selected.id !== lora.id);
      return current;
    });
  };

  const savePreset = async () => {
    const name = presetName.trim();
    if (!name) return;
    setPresetError("");
    try {
      await api.createPreset(name, "image", { ...imageParams(), model_id: imgModel });
      setPresetName("");
      onPresetsChanged();
    } catch (err) {
      setPresetError(err instanceof Error ? err.message : "Could not save preset");
    }
  };

  // Load a full param snapshot into the composer. Shared by presets (model
  // identified by id) and History reproduce (model id resolved by the caller).
  const applyParams = (params: Record<string, unknown>, modelId?: string) => {
    if (typeof params.prompt === "string") setPromptDraft(params.prompt);
    setNegative(typeof params.negative === "string" ? params.negative : "");
    const targetId = modelId ?? (typeof params.model_id === "string" ? params.model_id : undefined);
    const model = targetId ? imgModels.find((m) => m.id === targetId) : undefined;
    if (model && isModelAvailable(model)) setImgModel(model.id);
    // A loaded snapshot is an explicit choice: mark the fields touched so the
    // defaults effect doesn't snap them back on the next family resolve/remount.
    editSteps(numberParam(params.steps, steps));
    editGuidance(numberParam(params.guidance, guidance));
    editWidth(numberParam(params.width, width));
    editHeight(numberParam(params.height, height));
    setSeed(numberParam(params.seed, seed));
    setBatch(numberParam(params.batch_size, batch));
    setSelectedLoras(parseLoraSelections(params.loras, loras, model ?? selectedImgModel));
  };

  const applyPreset = () => {
    const preset = imagePresets.find((p) => p.id === presetId);
    if (preset) applyParams(preset.params);
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
      localStorage.setItem(PROMPT_HISTORY_KEY, JSON.stringify(promptHistory));
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
    if (!presetId) return;
    setPresetError("");
    try {
      await api.deletePreset(presetId);
      setPresetId("");
      onPresetsChanged();
    } catch (err) {
      setPresetError(err instanceof Error ? err.message : "Could not delete preset");
    }
  };

  const presetOptions: SelectOption[] = [
    { value: "", label: "unsaved" },
    ...imagePresets.map((p) => ({ value: p.id, label: p.name })),
  ];

  const selectedUnavailableReason = selectedImgModel?.unavailable_reason ?? "";
  const canQueue = Boolean(imgModel) && isModelAvailable(selectedImgModel) && Boolean(promptDraft.trim());
  const activeRatio = RATIOS.find((r) => isRatio(width, height, r.w, r.h))?.label ?? "custom";
  const promptChars = promptDraft.trim().length;
  const queueLabel = count > 1 ? `Queue ${count} jobs` : "Queue generation";
  const visiblePromptHistory = promptHistory.filter((item) => item !== promptDraft.trim()).slice(0, 8);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel max-[860px]:mb-4 max-[860px]:h-[760px]">
      <div className="border-b border-line px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-ui-strong">Generate</h2>
            <p className="mt-0.5 truncate text-xs text-ui-subtle">{width}x{height} / {steps} steps / {selectedLoras.length || "no"} LoRA</p>
          </div>
          <span className="shrink-0 rounded-md border border-line bg-control px-2 py-1 text-[11px] uppercase text-ui-muted">
            {selectedFamily ?? "image"}
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className={section}>
          <div className="flex items-center justify-between">
            <label htmlFor="image-prompt" className={label}>Prompt</label>
            <div className="flex items-center gap-2">
              <div ref={promptHistoryRef} className="relative">
                <button
                  type="button"
                  onClick={() => setPromptHistoryOpen((open) => !open)}
                  disabled={visiblePromptHistory.length === 0}
                  title={visiblePromptHistory.length ? "Recall recent prompt" : "No recent image prompts"}
                  aria-label="Recall recent image prompt"
                  aria-expanded={promptHistoryOpen}
                  className="ui-button h-6 w-6 rounded-md text-sm leading-none disabled:opacity-25"
                >
                  ↑
                </button>
                {promptHistoryOpen ? (
                  <div className="absolute right-0 z-30 mt-1 w-72 overflow-hidden rounded-md border border-line bg-surface-2 py-1 shadow-popover">
                    {visiblePromptHistory.length === 0 ? (
                      <div className="px-2.5 py-1.5 text-sm text-ui-subtle">no recent prompts</div>
                    ) : (
                      visiblePromptHistory.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          onClick={() => {
                            setPromptDraft(prompt);
                            setPromptHistoryOpen(false);
                          }}
                          className="block w-full truncate px-2.5 py-1.5 text-left text-sm text-ui transition hover:bg-control-hover hover:text-ui-strong"
                          title={prompt}
                        >
                          {prompt}
                        </button>
                      ))
                    )}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => setLibraryOpen(true)}
                title="Prompt library"
                aria-label="Open prompt library"
                className="ui-button h-6 rounded-md px-2 text-xs leading-none"
              >
                Library
              </button>
              <span className="text-[11px] text-ui-subtle">{promptChars ? `${promptChars} chars` : "empty"}</span>
            </div>
          </div>
          <textarea
            id="image-prompt"
            value={promptDraft}
            onChange={(e) => setPromptDraft(e.target.value)}
            rows={6}
            placeholder="describe the image..."
            className={`${field} mt-1.5 min-h-32 resize-y leading-5`}
          />
          <label className="mt-3 block">
            <div className={label}>Negative {selectedFamily === "flux2" ? "(ignored by FLUX.2)" : ""}</div>
            <input
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              placeholder="things to avoid..."
              className={`${field} mt-1.5`}
            />
          </label>
          <PromptLibrary
            open={libraryOpen}
            onClose={() => setLibraryOpen(false)}
            currentPrompt={promptDraft}
            currentNegative={negative}
            onApply={(body, neg) => {
              setPromptDraft(promptDraft.trim() ? `${promptDraft.trim()}, ${body}` : body);
              if (neg && neg.trim()) {
                setNegative(negative.trim() ? `${negative.trim()}, ${neg.trim()}` : neg.trim());
              }
            }}
          />
        </section>

        <section className={section}>
          <div className={label}>Model</div>
          <div className="mt-1.5">
            {modelsLoading && imgModels.length === 0 ? (
              <SkeletonLine />
            ) : imgModels.length === 0 ? (
              <div className="rounded-md border border-line bg-control px-3 py-2 text-sm text-ui-subtle">no image models</div>
            ) : (
              <ModelPicker models={imgModels} value={imgModel} onChange={setImgModel} />
            )}
          </div>
          {selectedImgModel?.slow ? (
            <Notice tone="amber">
              Raw FLUX fp8 is slow and high-memory on 16 GB VRAM. Prefer a nunchaku FLUX entry when available.
            </Notice>
          ) : null}
          {selectedUnavailableReason ? (
            <Notice tone="amber">{selectedUnavailableReason}</Notice>
          ) : null}
          {selectedImgModel?.compatibility_warnings?.length ? (
            <Notice tone="sky">{selectedImgModel.compatibility_warnings[0]}</Notice>
          ) : null}
          {selectedFamily === "flux2" && isNunchaku(selectedImgModel) ? (
            <Notice tone="emerald">
              FLUX.2 nunchaku uses the local SVDQuant transformer sidecar.
            </Notice>
          ) : selectedFamily === "flux2" ? (
            <Notice tone="sky">
              FLUX.2 klein is tuned here for 768x768, 6 steps, guidance 4.0. Negative prompt is ignored.
            </Notice>
          ) : selectedFamily === "qwen-image" ? (
            <Notice tone="sky">
              Qwen-Image-2512 is tuned here for 1328x1328, 50 steps, true CFG 4.0. The backend defaults to bnb-nf4.
            </Notice>
          ) : selectedFamily === "z-image" && isZImageTurbo(selectedImgModel) ? (
            <Notice tone="sky">
              Z-Image-Turbo is tuned here for 1024x1024, 9 steps, guidance 0.0.
            </Notice>
          ) : selectedFamily === "z-image" ? (
            <Notice tone="sky">
              Z-Image base is tuned here for 1024x1024, 50 steps, guidance 4.0. The backend defaults to bnb-fp4.
            </Notice>
          ) : null}
        </section>

        <ImageParamForm
          activeRatio={activeRatio}
          batch={batch}
          guidance={guidance}
          height={height}
          labelClass={label}
          onApplyRatio={applyRatio}
          ratios={RATIOS}
          sectionClass={section}
          seed={seed}
          setBatch={setBatch}
          setGuidance={editGuidance}
          setHeight={editHeight}
          setSeed={setSeed}
          setSteps={editSteps}
          setWidth={editWidth}
          steps={steps}
          width={width}
        />

        <section className={section}>
          <div className="flex items-center justify-between gap-2">
            <div className={label}>LoRA</div>
            <span className="text-[11px] text-ui-subtle">{selectedLoras.length ? `${selectedLoras.length} active` : "none active"}</span>
          </div>
          {lorasLoading && selectedImgModel && compatibleLoras.length === 0 ? (
            <div className="mt-1.5">
              <SkeletonRows rows={3} />
            </div>
          ) : compatibleLoras.length ? (
            <div className="mt-1.5 flex max-h-64 flex-col gap-2 overflow-y-auto pr-1">
              {compatibleLoras.map((lora) => {
                const selected = selectedLoras.find((item) => item.id === lora.id);
                return (
                  <LoraCard
                    key={lora.id}
                    lora={lora}
                    selected={selected}
                    onToggle={(enabled) => toggleLora(lora, enabled)}
                    onWeight={(weight) => updateLoraWeight(lora.id, weight)}
                  />
                );
              })}
            </div>
          ) : (
            <div className="mt-1.5 rounded-md border border-line bg-control px-3 py-2 text-sm text-ui-subtle">
              {selectedImgModel ? "no compatible LoRA files" : "pick an image model first"}
            </div>
          )}
        </section>

        <section className={section}>
          <div className={label}>Preset</div>
          <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2">
            {presetsLoading && imagePresets.length === 0 ? (
              <SkeletonLine className="h-9 w-full rounded-md" />
            ) : (
              <Select value={presetId} options={presetOptions} onChange={setPresetId} placeholder="unsaved" />
            )}
            <button onClick={applyPreset} disabled={!presetId} className={subtleButton}>Apply</button>
            <button
              onClick={deletePreset}
              disabled={!presetId}
              className="rounded-md border border-red-400/25 px-2.5 py-1.5 text-xs text-red-300 transition hover:bg-red-400/10 disabled:opacity-30"
            >
              Delete
            </button>
          </div>
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <input
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
              placeholder="preset name"
              className={field}
            />
            <button onClick={savePreset} disabled={!presetName.trim()} className={subtleButton}>Save</button>
          </div>
          {presetError ? <div className="mt-1 truncate text-xs text-red-300" title={presetError}>{presetError}</div> : null}
        </section>
      </div>

      <div className="border-t border-line bg-raised p-3">
        <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-2">
          <label>
            <div className={label}>Jobs</div>
            <input
              type="number"
              value={count}
              min={1}
              onChange={(e) => setCount(Math.max(1, Number(e.target.value)))}
              className="ui-field mt-1 w-full rounded-md px-2 py-2 text-sm"
            />
          </label>
          <button
            onClick={generate}
            disabled={!canQueue}
            title={selectedUnavailableReason || undefined}
            className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ui-inverse transition hover:bg-accent-hover disabled:opacity-40"
          >
            {queueLabel}
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-ui-subtle">
          <span className="truncate">{selectedImgModel?.name ?? "No image model"}</span>
          <span className="shrink-0">{seed === -1 ? "random seed" : `seed ${seed}`}</span>
        </div>
      </div>
    </section>
  );
}

function isRatio(w: number, h: number, rw: number, rh: number): boolean {
  if (!w || !h) return false;
  return Math.abs(w / h - rw / rh) < 0.02;
}

function parseLoraSelections(value: unknown, loras: Lora[], model: Model | undefined): LoraSelection[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const selections: LoraSelection[] = [];
  for (const item of value) {
    const id = typeof item === "string"
      ? item
      : item && typeof item === "object" && "id" in item && typeof item.id === "string"
        ? item.id
        : "";
    if (!id || seen.has(id)) continue;
    const lora = loras.find((candidate) => candidate.id === id);
    if (!lora || !isLoraCompatible(lora, model)) continue;
    const weight = item && typeof item === "object" && "weight" in item
      ? numberParam(item.weight, 1)
      : 1;
    selections.push({ id, weight });
    seen.add(id);
  }
  return selections;
}
