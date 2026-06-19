import { useRef, useState, type ClipboardEvent, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { apiAssetUrl } from "../api/client";
import type { ChatAttachment, ChatMessage, LlmConfig, Model, Preset } from "../types";
import { AssistantContent } from "./Thinking";
import { SkeletonLine } from "./WorkspaceChrome";
import { modelTitle } from "./chatHelpers";
import { formatSize } from "./imageComposerHelpers";
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
        <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
          <p className="text-sm text-ui-muted">Start a conversation with the local model.</p>
          <p className="max-w-sm text-xs leading-5 text-ui-subtle">
            Ask anything, attach an image or document, or type <span className="text-ui-muted">/image</span> to generate a picture.
          </p>
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
  onPromptLibrary,
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
  attachmentNote,
  attachments,
  attachmentsUploading,
  onAttachFiles,
  onPaste,
  onRemoveAttachment,
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
  onPromptLibrary: () => void;
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
  attachmentNote: string;
  attachments: ChatAttachment[];
  attachmentsUploading: boolean;
  onAttachFiles: (files: FileList | File[]) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  onRemoveAttachment: (token: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const addFiles = (files: FileList | null) => {
    if (files?.length) onAttachFiles(files);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };
  return (
    <div
      className="border-t border-line p-3"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        addFiles(event.dataTransfer.files);
      }}
    >
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
      <AttachmentTray attachments={attachments} onRemove={onRemoveAttachment} />
      {attachmentNote ? <div className="mb-2 text-xs text-warn-fg">{attachmentNote}</div> : null}
      <textarea
        ref={inputRef}
        value={input}
        onChange={(event) => onInput(event.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        rows={2}
        placeholder={modelId ? "Message...  (Enter to send, Shift+Enter for newline)" : "no LLM model available"}
        disabled={!modelId}
        className={`${fieldClass} max-h-[200px] resize-none`}
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-ui-subtle">
          ~{approxTokens} / {cfg?.ctx ?? "?"} tokens
          <span className="ml-2 text-ui-subtle">/image &lt;prompt&gt; to generate</span>
          {imageTool && <span className="ml-2 text-ui-subtle">image tool on</span>}
          {documentTool && <span className="ml-2 text-ui-subtle">document tool on</span>}
          {attachmentsUploading && <span className="ml-2 text-ui-subtle">uploading attachment...</span>}
          {stats && <span className="ml-2 text-ui-subtle">{stats.tps.toFixed(1)} tok/s / TTFT {Math.round(stats.ttft)}ms</span>}
        </span>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(event) => addFiles(event.currentTarget.files)}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={busy || attachmentsUploading}
            className="ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30"
          >
            Attach
          </button>
          <button
            onClick={onPromptLibrary}
            disabled={busy}
            className="ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30"
          >
            Library
          </button>
          <button
            onClick={onRegenerate}
            disabled={busy || !messages.some((message) => message.role === "assistant")}
            className="ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30"
          >
            Regenerate
          </button>
          {busy ? (
            <button onClick={onStop} className="rounded-md border border-error-border px-4 py-1.5 text-sm font-medium text-error-fg hover:bg-error-bg">
              Stop
            </button>
          ) : (
            <button
              onClick={onSend}
              disabled={(!input.trim() && attachments.length === 0) || !modelId || attachmentsUploading}
              className="rounded-md bg-success px-4 py-1.5 text-sm font-medium text-ui-inverse hover:bg-success disabled:opacity-40"
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
      <span className="w-12 shrink-0 text-[10px] uppercase tracking-wide text-ui-subtle">{railLabel}</span>
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

function AttachmentTray({
  attachments,
  onRemove,
}: {
  attachments: ChatAttachment[];
  onRemove: (token: string) => void;
}) {
  if (!attachments.length) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {attachments.map((item) => (
        <AttachmentChip key={item.token} attachment={item} onRemove={() => onRemove(item.token)} removable />
      ))}
    </div>
  );
}

function AttachmentList({ attachments }: { attachments?: ChatAttachment[] }) {
  if (!attachments?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {attachments.map((item) => <AttachmentChip key={item.token} attachment={item} />)}
    </div>
  );
}

function AttachmentChip({
  attachment,
  onRemove,
  removable = false,
}: {
  attachment: ChatAttachment;
  onRemove?: () => void;
  removable?: boolean;
}) {
  const isImage = attachment.kind === "image";
  return (
    <span
      className="flex max-w-full items-center gap-2 rounded-md border border-line bg-control px-2 py-1 text-xs text-ui-muted"
      title={attachment.notice ?? attachment.filename}
    >
      {isImage && attachment.url ? (
        <img
          src={apiAssetUrl(attachment.url)}
          alt=""
          className="h-7 w-7 shrink-0 rounded object-cover"
        />
      ) : (
        <span className="shrink-0 rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] uppercase text-ui-subtle">
          {attachment.kind}
        </span>
      )}
      <span className="min-w-0">
        <span className="block max-w-64 truncate">{attachment.filename}</span>
        <span className="block truncate text-[10px] text-ui-subtle">
          {formatSize(attachment.size_bytes)}
          {attachment.notice ? ` · ${attachment.notice}` : ""}
        </span>
      </span>
      {removable ? (
        <button
          type="button"
          onClick={onRemove}
          className="shrink-0 rounded px-1 text-ui-subtle hover:bg-control-hover hover:text-ui"
          title="remove attachment"
        >
          x
        </button>
      ) : null}
    </span>
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
          ? "border-success-border bg-success-bg text-success-fg"
          : "border-line bg-control text-ui-muted hover:border-border-strong hover:bg-control-hover hover:text-ui"
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
            <button onClick={onCancelEdit} className="ui-button rounded px-2 py-1 text-xs">Cancel</button>
            <button onClick={onSaveEdit} className="rounded bg-success px-2.5 py-1 text-xs font-medium text-ui-inverse">Save &amp; resend</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`group flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 ${
        isUser ? "border border-accent/25 bg-accent/10 text-accent-fg"
          : msg.error ? "border border-error-border bg-error-bg text-error-fg"
          : "border border-line bg-control"
      }`}>
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
        ) : (
          <AssistantContent content={msg.content} pending={pending} />
        )}
        <AttachmentList attachments={msg.attachments} />
        <div className="mt-1 flex gap-2 opacity-0 transition group-hover:opacity-100">
          <button onClick={copy} className="text-[11px] text-ui-subtle hover:text-ui">{copied ? "copied" : "copy"}</button>
          {isUser && !msg.id.startsWith("tmp") && (
            <button onClick={onStartEdit} className="text-[11px] text-ui-subtle hover:text-ui">edit</button>
          )}
        </div>
      </div>
    </div>
  );
}
