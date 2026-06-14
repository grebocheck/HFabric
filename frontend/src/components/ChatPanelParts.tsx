import { useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import type { ChatMessage, LlmConfig, Model, Preset } from "../types";
import { AssistantContent } from "./Thinking";
import { SkeletonLine } from "./WorkspaceChrome";
import { modelTitle } from "./chatHelpers";
import type { ChatStats } from "./ChatPanelHooks";

export function MessageList({
  editText,
  editingId,
  fieldClass,
  messages,
  onCancelEdit,
  onSaveEdit,
  onScroll,
  onStartEdit,
  pendingAssistantId,
  scrollRef,
  setEditText,
}: {
  editText: string;
  editingId: string | null;
  fieldClass: string;
  messages: ChatMessage[];
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onScroll: () => void;
  onStartEdit: (message: ChatMessage) => void;
  pendingAssistantId: string | null;
  scrollRef: RefObject<HTMLDivElement | null>;
  setEditText: (value: string) => void;
}) {
  return (
    <div ref={scrollRef} onScroll={onScroll} className="flex-1 space-y-4 overflow-y-auto p-4">
      {messages.length === 0 ? (
        <div className="flex h-full items-center justify-center text-center text-sm text-white/30">
          Start a conversation with the local model.
        </div>
      ) : (
        messages.map((message) => (
          <Bubble
            key={message.id}
            fieldClass={fieldClass}
            msg={message}
            editing={editingId === message.id}
            editText={editText}
            setEditText={setEditText}
            onStartEdit={() => onStartEdit(message)}
            onSaveEdit={onSaveEdit}
            onCancelEdit={onCancelEdit}
            pending={message.id === pendingAssistantId}
          />
        ))
      )}
    </div>
  );
}

export function MessageComposer({
  approxTokens,
  busy,
  cfg,
  documentTool,
  fieldClass,
  imageTool,
  input,
  inputRef,
  messages,
  modelId,
  modelsLoading,
  onInput,
  onKeyDown,
  onRegenerate,
  onSend,
  onStop,
  personas,
  personasLoading,
  personaId,
  quickModels,
  quickPersonas,
  selectedModel,
  setModelId,
  setPromptFromHistory,
  stats,
  visiblePromptHistory,
  applyPersona,
}: {
  approxTokens: number;
  busy: boolean;
  cfg: LlmConfig | null;
  documentTool: boolean;
  fieldClass: string;
  imageTool: boolean;
  input: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  messages: ChatMessage[];
  modelId: string;
  modelsLoading: boolean;
  onInput: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onRegenerate: () => void;
  onSend: () => void;
  onStop: () => void;
  personas: Preset[];
  personasLoading: boolean;
  personaId: string;
  quickModels: Model[];
  quickPersonas: Preset[];
  selectedModel: Model | undefined;
  setModelId: (modelId: string) => void;
  setPromptFromHistory: (prompt: string) => void;
  visiblePromptHistory: string[];
  applyPersona: (id: string) => void;
  stats: ChatStats | null;
}) {
  return (
    <div className="border-t border-white/10 p-3">
      <div className="mb-2 flex flex-col gap-2">
        {modelsLoading && quickModels.length === 0 ? (
          <QuickRail label="Model">
            <SkeletonChips count={3} />
          </QuickRail>
        ) : quickModels.length > 0 ? (
          <QuickRail label="Model">
            {quickModels.map((model) => (
              <QuickChip
                key={model.id}
                active={model.id === modelId}
                onClick={() => setModelId(model.id)}
                title={modelTitle(model)}
              >
                {model.name}
              </QuickChip>
            ))}
            {selectedModel && !quickModels.some((model) => model.id === selectedModel.id) ? (
              <QuickChip active onClick={() => setModelId(selectedModel.id)} title={modelTitle(selectedModel)}>
                {selectedModel.name}
              </QuickChip>
            ) : null}
          </QuickRail>
        ) : null}

        {personasLoading && personas.length === 0 ? (
          <QuickRail label="Persona">
            <SkeletonChips count={2} />
          </QuickRail>
        ) : (personas.length > 0 || personaId) ? (
          <QuickRail label="Persona">
            <QuickChip active={!personaId} onClick={() => applyPersona("")}>None</QuickChip>
            {quickPersonas.map((persona) => (
              <QuickChip key={persona.id} active={persona.id === personaId} onClick={() => applyPersona(persona.id)}>
                {persona.name}
              </QuickChip>
            ))}
          </QuickRail>
        ) : null}

        {visiblePromptHistory.length > 0 ? (
          <QuickRail label="Recent">
            {visiblePromptHistory.map((prompt) => (
              <QuickChip key={prompt} onClick={() => setPromptFromHistory(prompt)} title={prompt}>
                {prompt}
              </QuickChip>
            ))}
          </QuickRail>
        ) : null}
      </div>
      <textarea
        ref={inputRef}
        value={input}
        onChange={(event) => onInput(event.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        placeholder={modelId ? "Message...  (Enter to send, Shift+Enter for newline)" : "no LLM model available"}
        disabled={!modelId}
        className={`${fieldClass} max-h-[200px] resize-none`}
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-white/35">
          ~{approxTokens} / {cfg?.ctx ?? "?"} tokens
          <span className="ml-2 text-white/25">/image &lt;prompt&gt; to generate</span>
          {imageTool && <span className="ml-2 text-white/25">image tool on</span>}
          {documentTool && <span className="ml-2 text-white/25">document tool on</span>}
          {stats && <span className="ml-2 text-white/30">{stats.tps.toFixed(1)} tok/s / TTFT {Math.round(stats.ttft)}ms</span>}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onRegenerate}
            disabled={busy || !messages.some((message) => message.role === "assistant")}
            className="rounded-md border border-white/15 px-2.5 py-1.5 text-xs hover:bg-white/10 disabled:opacity-30"
          >
            Regenerate
          </button>
          {busy ? (
            <button onClick={onStop} className="rounded-md border border-red-400/40 px-4 py-1.5 text-sm font-medium text-red-200 hover:bg-red-400/10">
              Stop
            </button>
          ) : (
            <button
              onClick={onSend}
              disabled={!input.trim() || !modelId}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function QuickRail({ label: railLabel, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="w-12 shrink-0 text-[10px] uppercase tracking-wide text-white/30">{railLabel}</span>
      <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto pb-0.5">{children}</div>
    </div>
  );
}

function SkeletonChips({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <SkeletonLine key={i} className={`h-7 rounded-md ${i === 0 ? "w-28" : i === 1 ? "w-36" : "w-24"}`} />
      ))}
    </>
  );
}

function QuickChip({
  active = false,
  children,
  onClick,
  title,
}: {
  active?: boolean;
  children: string;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title ?? children}
      className={`max-w-44 shrink-0 truncate rounded-md border px-2 py-1 text-xs transition ${
        active
          ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-100"
          : "border-white/10 bg-black/20 text-white/55 hover:border-white/20 hover:bg-white/10 hover:text-white/85"
      }`}
    >
      {children}
    </button>
  );
}

function Bubble({
  msg, editing, editText, setEditText, onStartEdit, onSaveEdit, onCancelEdit, pending, fieldClass,
}: {
  msg: ChatMessage;
  editing: boolean;
  editText: string;
  setEditText: (v: string) => void;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  pending: boolean;
  fieldClass: string;
}) {
  const isUser = msg.role === "user";
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(msg.content).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  if (editing) {
    return (
      <div className="flex justify-end">
        <div className="w-[80%]">
          <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={3} className={`${fieldClass} resize-none`} />
          <div className="mt-1 flex justify-end gap-2">
            <button onClick={onCancelEdit} className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10">Cancel</button>
            <button onClick={onSaveEdit} className="rounded bg-emerald-600 px-2.5 py-1 text-xs font-medium hover:bg-emerald-500">Save &amp; resend</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`group flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 ${
        isUser ? "bg-accent/30 text-white"
          : msg.error ? "border border-red-400/30 bg-red-400/10 text-red-200"
          : "border border-white/10 bg-white/[0.04]"
      }`}>
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
        ) : (
          <AssistantContent content={msg.content} pending={pending} />
        )}
        <div className="mt-1 flex gap-2 opacity-0 transition group-hover:opacity-100">
          <button onClick={copy} className="text-[11px] text-white/40 hover:text-white/80">{copied ? "copied" : "copy"}</button>
          {isUser && !msg.id.startsWith("tmp") && (
            <button onClick={onStartEdit} className="text-[11px] text-white/40 hover:text-white/80">edit</button>
          )}
        </div>
      </div>
    </div>
  );
}
