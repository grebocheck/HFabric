import { ModelPicker } from "./ModelPicker";
import { PromptLibrary } from "./PromptLibrary";
import { Select } from "./Select";
import { SkeletonLine, SkeletonRows } from "./WorkspaceChrome";
import { ImageParamForm, LoraCard, Notice } from "./ImageComposerParts";
import { isNunchaku, isZImageTurbo } from "./imageComposerHelpers";
import { useImageComposerController, type ImageComposerProps } from "./useImageComposerController";

const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-[13px]";
const label = "text-[10px] font-medium uppercase tracking-wide text-ui-subtle";
const section = "border-b border-line p-3 last:border-b-0";
const subtleButton = "ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30";

export function ImageComposer(props: ImageComposerProps) {
  const {
    activeRatio,
    applyPreset,
    applyRatio,
    batch,
    canQueue,
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
    presetId,
    presetName,
    presetOptions,
    presetsLoading,
    promptChars,
    promptDraft,
    promptHistoryOpen,
    promptHistoryRef,
    queueLabel,
    ratios: RATIOS,
    savePreset,
    seed,
    selectedFamily,
    selectedImgModel,
    selectedLoras,
    selectedUnavailableReason,
    setBatch,
    setCount,
    setImgModel,
    setLibraryOpen,
    setNegative,
    setPresetId,
    setPresetName,
    setPromptDraft,
    setPromptHistoryOpen,
    setSeed,
    steps,
    toggleLora,
    updateLoraWeight,
    visiblePromptHistory,
    width,
  } = useImageComposerController(props);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel max-[860px]:mb-4 max-[860px]:h-[760px]">
      <div className="border-b border-line px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-ui-strong">Generate</h2>
            <p className="mt-0.5 truncate text-xs text-ui-subtle">
              {width}x{height} / {steps} steps / {selectedLoras.length || "no"} LoRA
            </p>
          </div>
          <span className="shrink-0 rounded-md border border-line bg-control px-2 py-1 text-[11px] uppercase text-ui-muted">
            {selectedFamily ?? "image"}
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className={section}>
          <div className="flex items-center justify-between">
            <label htmlFor="image-prompt" className={label}>
              Prompt
            </label>
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
              <span className="text-[11px] text-ui-subtle">
                {promptChars ? `${promptChars} chars` : "empty"}
              </span>
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
              <div className="rounded-md border border-line bg-control px-3 py-2 text-sm text-ui-subtle">
                no image models
              </div>
            ) : (
              <ModelPicker models={imgModels} value={imgModel} onChange={setImgModel} />
            )}
          </div>
          {selectedImgModel?.slow ? (
            <Notice tone="amber">
              Raw FLUX fp8 is slow and high-memory on 16 GB VRAM. Prefer a nunchaku FLUX entry when available.
            </Notice>
          ) : null}
          {selectedUnavailableReason ? <Notice tone="amber">{selectedUnavailableReason}</Notice> : null}
          {selectedImgModel?.compatibility_warnings?.length ? (
            <Notice tone="sky">{selectedImgModel.compatibility_warnings[0]}</Notice>
          ) : null}
          {selectedFamily === "flux2" && isNunchaku(selectedImgModel) ? (
            <Notice tone="emerald">FLUX.2 nunchaku uses the local SVDQuant transformer sidecar.</Notice>
          ) : selectedFamily === "flux2" ? (
            <Notice tone="sky">
              FLUX.2 klein is tuned here for 768x768, 6 steps, guidance 4.0. Negative prompt is ignored.
            </Notice>
          ) : selectedFamily === "qwen-image" ? (
            <Notice tone="sky">
              Qwen-Image-2512 is tuned here for 1328x1328, 50 steps, true CFG 4.0. The backend defaults to
              bnb-nf4.
            </Notice>
          ) : selectedFamily === "z-image" && isZImageTurbo(selectedImgModel) ? (
            <Notice tone="sky">Z-Image-Turbo is tuned here for 1024x1024, 9 steps, guidance 0.0.</Notice>
          ) : selectedFamily === "z-image" ? (
            <Notice tone="sky">
              Z-Image base is tuned here for 1024x1024, 50 steps, guidance 4.0. The backend defaults to
              bnb-fp4.
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
            <span className="text-[11px] text-ui-subtle">
              {selectedLoras.length ? `${selectedLoras.length} active` : "none active"}
            </span>
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
              <Select
                ariaLabel="Image preset"
                value={presetId}
                options={presetOptions}
                onChange={setPresetId}
                placeholder="unsaved"
              />
            )}
            <button onClick={applyPreset} disabled={!presetId} className={subtleButton}>
              Apply
            </button>
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
            <button onClick={savePreset} disabled={!presetName.trim()} className={subtleButton}>
              Save
            </button>
          </div>
          {presetError ? (
            <div className="mt-1 truncate text-xs text-red-300" title={presetError}>
              {presetError}
            </div>
          ) : null}
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
