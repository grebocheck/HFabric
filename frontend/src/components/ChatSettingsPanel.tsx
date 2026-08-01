import { ModelPicker } from "./ModelPicker";
import { Select } from "./Select";
import { Toggle } from "./Toggle";
import { SkeletonLine } from "./WorkspaceChrome";
import { pickImageModel, type NumOrEmpty } from "./chatHelpers";
import type { ChatPanelController } from "./useChatPanelController";

const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-sm";
const numField = "ui-field w-full rounded-md px-2 py-1 text-xs";
const label = "text-xs uppercase tracking-wide text-ui-subtle";

export function ChatSettingsPanel({ controller }: { controller: ChatPanelController }) {
  const {
    activeBackend,
    applyBackend,
    applyContextType,
    applyCtx,
    applyPersona,
    cfg,
    cfgNote,
    copyLlmServerUrl,
    ctxDraft,
    ctxTypeBusy,
    ctxTypeOptions,
    deletePersona,
    documentTool,
    exportChat,
    exportJson,
    imageTool,
    importInputRef,
    importJson,
    importNote,
    llmModels,
    llmServer,
    maxTokens,
    messages,
    minP,
    modelId,
    models,
    modelsLoading,
    personaId,
    personaName,
    personas,
    personasLoading,
    ragTopK,
    repeatPenalty,
    savePersona,
    seed,
    serverBusy,
    setCtxDraft,
    setDocumentTool,
    setImageTool,
    setMaxTokens,
    setMinP,
    setModelId,
    setPersonaName,
    setRagTopK,
    setRepeatPenalty,
    setSeed,
    setShowAdvanced,
    setStop,
    setSystem,
    setTemperature,
    setTopK,
    setTopP,
    showAdvanced,
    stop,
    system,
    temperature,
    toggleLlmServer,
    topK,
    topP,
  } = controller;

  return (
    <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto rounded-lg border border-line bg-surface p-4 max-[1000px]:w-full max-[1000px]:overflow-visible">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ui">Model settings</h2>
        <div className="flex gap-1">
          <button
            onClick={exportChat}
            disabled={!messages.length}
            className="ui-button rounded px-2 py-1 text-xs disabled:opacity-30"
            title="Export conversation as Markdown"
          >
            MD
          </button>
          <button
            onClick={() => void exportJson()}
            className="ui-button rounded px-2 py-1 text-xs disabled:opacity-30"
            title="Export importable JSON bundle"
          >
            JSON
          </button>
          <button
            onClick={() => importInputRef.current?.click()}
            className="ui-button rounded px-2 py-1 text-xs"
            title="Import JSON bundle"
          >
            Import
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void importJson(e.currentTarget.files?.[0] ?? null)}
          />
        </div>
      </div>
      {importNote && <div className="text-[11px] text-success-fg">{importNote}</div>}

      <label>
        <div className={label}>Model</div>
        {modelsLoading && llmModels.length === 0 ? (
          <SkeletonLine className="mt-1 h-9 w-full rounded-md" />
        ) : (
          <div className="mt-1">
            <ModelPicker
              models={llmModels}
              value={modelId}
              onChange={setModelId}
              placeholder="no LLM models"
            />
          </div>
        )}
      </label>

      <div className="rounded-md border border-line bg-control px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <span>
            <span className="block text-sm font-medium text-ui">OpenAI API</span>
            <span className="block text-xs text-ui-subtle">
              {llmServer?.enabled
                ? `${llmServer.stub ? "stub" : llmServer.available ? "ready" : "starting"} · ${llmServer.model ?? llmServer.model_id ?? "LLM"}`
                : "serve the selected LLM"}
            </span>
          </span>
          <Toggle
            checked={Boolean(llmServer?.enabled)}
            disabled={serverBusy || (!modelId && !llmServer?.enabled)}
            onChange={(value) => void toggleLlmServer(value)}
            ariaLabel="Toggle OpenAI-compatible LLM API"
          />
        </div>
        {llmServer?.enabled ? (
          <div className="mt-2 space-y-1.5 text-[11px]">
            <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2">
              <span className="text-ui-subtle">Base URL</span>
              <code className="truncate rounded bg-raised px-1.5 py-0.5 font-mono text-success-fg">
                {llmServer.base_url}
              </code>
              <button onClick={() => void copyLlmServerUrl()} className="ui-button rounded px-1.5 py-0.5">
                Copy
              </button>
            </div>
            <div className="grid grid-cols-[auto_1fr] gap-2">
              <span className="text-ui-subtle">Model</span>
              <code className="truncate font-mono text-ui-muted">
                {llmServer.model ?? llmServer.model_id}
              </code>
            </div>
            {llmServer.note ? <div className="text-ui-subtle">{llmServer.note}</div> : null}
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-3 rounded-md border border-line bg-control px-3 py-2">
        <span>
          <span className="block text-sm font-medium text-ui">Model image tool</span>
          <span className="block text-xs text-ui-subtle">
            {pickImageModel(models)?.name ?? "no image model"} · /image stays manual
          </span>
        </span>
        <Toggle
          checked={imageTool}
          disabled={!pickImageModel(models)}
          onChange={setImageTool}
          ariaLabel="Enable image generation tool"
        />
      </div>

      <div className="rounded-md border border-line bg-control px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <span>
            <span className="block text-sm font-medium text-ui">Document tool</span>
            <span className="block text-xs text-ui-subtle">model-driven RAG search</span>
          </span>
          <Toggle checked={documentTool} onChange={setDocumentTool} ariaLabel="Enable document tool" />
        </div>
        {documentTool && (
          <label className="mt-2 block">
            <div className={label}>RAG top K</div>
            <input
              type="number"
              min={1}
              max={20}
              value={ragTopK}
              onChange={(e) => setRagTopK(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
              className={`${numField} mt-1`}
            />
          </label>
        )}
      </div>

      <div>
        <div className={label}>Context window (tokens)</div>
        <div className="mt-1 flex gap-2">
          <input
            type="number"
            min={512}
            step={512}
            value={ctxDraft ?? ""}
            onChange={(e) => setCtxDraft(Number(e.target.value))}
            className={numField}
          />
          <button
            onClick={() => void applyCtx()}
            disabled={ctxDraft == null || ctxDraft === cfg?.ctx}
            className="ui-button shrink-0 rounded-md px-2.5 py-1 text-xs disabled:opacity-30"
          >
            Apply
          </button>
        </div>
        <div className="mt-1 text-[11px] text-ui-subtle">
          current {cfg?.ctx ?? "?"} · {cfg?.loaded ? "loaded" : "not loaded"}
        </div>
        {cfgNote && <div className="mt-1 text-[11px] text-success-fg">{cfgNote}</div>}
        {ctxDraft != null && cfg && ctxDraft !== cfg.ctx && cfg.loaded && (
          <div className="mt-1 text-[11px] text-warn-fg">applying reloads the running model</div>
        )}
      </div>

      <div>
        <div className={label}>Llama backend</div>
        <select
          value={cfg?.backend ?? "default"}
          disabled={!cfg || ctxTypeBusy}
          onChange={(e) => applyBackend(e.target.value)}
          className={`${numField} mt-1 disabled:opacity-40`}
        >
          {(cfg?.backends ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
              {!b.available && !cfg?.stub ? " (binary not found)" : ""}
            </option>
          ))}
        </select>
        {activeBackend && !activeBackend.available && !cfg?.stub && (
          <div className="mt-1 text-[11px] text-warn-fg">
            binary not found at <span className="font-mono">{activeBackend.path}</span> — the LLM won't start
            with this backend
          </div>
        )}
      </div>

      <div>
        <div className={label}>Context type (KV cache)</div>
        <select
          value={cfg?.context_type ?? "f16"}
          disabled={!cfg || ctxTypeBusy}
          onChange={(e) => applyContextType(e.target.value)}
          className={`${numField} mt-1 disabled:opacity-40`}
        >
          {ctxTypeOptions.map((ct) => (
            <option key={ct.id} value={ct.id}>
              {ct.label}
            </option>
          ))}
        </select>
        <div className="mt-1 text-[11px] text-ui-subtle">
          quantizes the context to fit a longer window in the same VRAM
        </div>
        {cfg?.context_types.find((ct) => ct.id === cfg.context_type)?.experimental && (
          <div className="mt-1 text-[11px] text-warn-fg">
            TurboQuant types require the TurboQuant backend's patched llama.cpp build
          </div>
        )}
        {cfg && cfg.context_type !== "f16" && cfg.loaded && (
          <div className="mt-1 text-[11px] text-warn-fg">applying reloads the running model</div>
        )}
      </div>

      <label>
        <div className={label}>Temperature · {temperature.toFixed(2)}</div>
        <input
          type="range"
          min={0}
          max={2}
          step={0.05}
          value={temperature}
          onChange={(e) => setTemperature(Number(e.target.value))}
          className="mt-2 w-full accent-emerald-500"
        />
      </label>

      <label>
        <div className={label}>Max tokens</div>
        <input
          type="number"
          min={1}
          max={16384}
          step={64}
          value={maxTokens}
          onChange={(e) => setMaxTokens(Number(e.target.value))}
          className={`${numField} mt-1`}
        />
      </label>

      {/* advanced sampling */}
      <div>
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="flex w-full items-center justify-between text-xs uppercase tracking-wide text-ui-subtle hover:text-ui"
        >
          <span>Advanced sampling</span>
          <span>{showAdvanced ? "▾" : "▸"}</span>
        </button>
        {showAdvanced && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <NumOpt label="top_p" v={topP} set={setTopP} step={0.05} />
            <NumOpt label="top_k" v={topK} set={setTopK} step={1} />
            <NumOpt label="min_p" v={minP} set={setMinP} step={0.01} />
            <NumOpt label="repeat_pen" v={repeatPenalty} set={setRepeatPenalty} step={0.05} />
            <NumOpt label="seed" v={seed} set={setSeed} step={1} />
            <label className="col-span-2">
              <div className={label}>stop (comma-sep)</div>
              <input
                value={stop}
                onChange={(e) => setStop(e.target.value)}
                placeholder="empty = none"
                className={`${numField} mt-1`}
              />
            </label>
          </div>
        )}
      </div>

      {/* persona */}
      <div>
        <div className={label}>Persona</div>
        <div className="mt-1 grid grid-cols-[1fr_auto] gap-2">
          {personasLoading && personas.length === 0 ? (
            <SkeletonLine className="h-8 w-full rounded-md" />
          ) : (
            <Select
              value={personaId}
              onChange={applyPersona}
              placeholder="— none —"
              options={[
                { value: "", label: "— none —" },
                ...personas.map((p) => ({ value: p.id, label: p.name })),
              ]}
            />
          )}
          <button
            onClick={() => void deletePersona()}
            disabled={!personaId}
            className="rounded-md border border-error-border px-2 py-1 text-xs text-error-fg hover:bg-error-bg disabled:opacity-30"
          >
            Del
          </button>
        </div>
        <div className="mt-1 grid grid-cols-[1fr_auto] gap-2">
          <input
            value={personaName}
            onChange={(e) => setPersonaName(e.target.value)}
            placeholder="save current as…"
            className={numField}
          />
          <button
            onClick={() => void savePersona()}
            disabled={!personaName.trim()}
            className="ui-button rounded-md px-2.5 py-1 text-xs disabled:opacity-30"
          >
            Save
          </button>
        </div>
      </div>

      <label className="flex min-h-0 flex-1 flex-col">
        <div className={label}>System prompt</div>
        <textarea
          value={system}
          onChange={(e) => setSystem(e.target.value)}
          placeholder="optional — sets the assistant's behavior"
          className={`${field} mt-1 min-h-24 flex-1 resize-none`}
        />
      </label>
    </aside>
  );
}

function NumOpt({
  label: l,
  v,
  set,
  step,
}: {
  label: string;
  v: NumOrEmpty;
  set: (n: NumOrEmpty) => void;
  step: number;
}) {
  return (
    <label>
      <div className={label}>{l}</div>
      <input
        type="number"
        step={step}
        value={v}
        onChange={(e) => set(e.target.value === "" ? "" : Number(e.target.value))}
        placeholder="default"
        className={`${numField} mt-1`}
      />
    </label>
  );
}
