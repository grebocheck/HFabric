import { PromptLibrary } from "./PromptLibrary";
import { SkeletonRows } from "./WorkspaceChrome";
import { imagePromptDraft } from "./ChatPanelHooks";
import { MessageComposer, MessageList } from "./ChatPanelParts";
import { ChatSettingsPanel } from "./ChatSettingsPanel";
import type { ChatPanelController } from "./useChatPanelController";

const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-sm";

export function ChatWorkspace({ controller }: { controller: ChatPanelController }) {
  const {
    activeId,
    applyImagePromptSnippet,
    applyPersona,
    approxTokens,
    attachmentNote,
    attachments,
    attachmentsUploading,
    busy,
    cfg,
    convQuery,
    convs,
    convsLoading,
    deleteConversation,
    documentTool,
    editText,
    editingId,
    filteredConvs,
    imageTool,
    input,
    inputRef,
    libraryOpen,
    messages,
    modelId,
    modelsLoading,
    newChat,
    onKeyDown,
    onPaste,
    pendingAssistantId,
    personaId,
    personas,
    personasLoading,
    quickModels,
    quickPersonas,
    regenerate,
    saveEdit,
    scrollRef,
    selectedModel,
    selectConversation,
    send,
    setAttachments,
    setConvQuery,
    setEditText,
    setEditingId,
    setInput,
    setLibraryOpen,
    setModelId,
    startEdit,
    stats,
    stopGeneration,
    updateScrollStickiness,
    uploadAttachments,
    visiblePromptHistory,
  } = controller;

  return (
    <div className="flex h-full min-w-0 gap-3 max-[1000px]:block max-[1000px]:overflow-x-hidden max-[1000px]:overflow-y-auto">
      {/* --- conversations --- */}
      <aside className="flex w-56 shrink-0 flex-col rounded-lg border border-line bg-surface max-[1000px]:mb-3 max-[1000px]:h-56 max-[1000px]:w-full">
        <button
          onClick={() => void newChat()}
          className="mx-2 mt-2 rounded-md bg-success px-3 py-1.5 text-sm font-medium text-ui-inverse"
        >
          + New chat
        </button>
        <input
          value={convQuery}
          onChange={(e) => setConvQuery(e.target.value)}
          placeholder="search chats"
          className="ui-field mx-2 my-2 rounded-md px-2 py-1 text-xs"
        />
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {convsLoading && convs.length === 0 ? (
            <SkeletonRows rows={7} />
          ) : (
            <>
              {filteredConvs.length === 0 && (
                <div className="px-1 text-xs text-ui-subtle">no conversations</div>
              )}
              {filteredConvs.map((c) => (
                <div
                  key={c.id}
                  role="button"
                  tabIndex={0}
                  aria-current={activeId === c.id ? "true" : undefined}
                  onClick={() => void selectConversation(c.id)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void selectConversation(c.id);
                    }
                  }}
                  className={`group mb-1 flex cursor-pointer items-center justify-between gap-1 rounded-md px-2 py-1.5 text-sm ${
                    activeId === c.id ? "bg-white/15" : "hover:bg-white/5"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-ui">{c.title}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void deleteConversation(c.id);
                    }}
                    className="shrink-0 text-ui-subtle opacity-0 transition hover:text-error-fg group-hover:opacity-100"
                    title="delete"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      </aside>

      {/* --- conversation --- */}
      <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-line bg-surface max-[1000px]:mb-3 max-[1000px]:h-[700px]">
        <MessageList
          editText={editText}
          editingId={editingId}
          fieldClass={field}
          messages={messages}
          onCancelEdit={() => setEditingId(null)}
          onSaveEdit={() => void saveEdit()}
          onScroll={updateScrollStickiness}
          onStartEdit={startEdit}
          pendingAssistantId={pendingAssistantId}
          scrollRef={scrollRef}
          setEditText={setEditText}
        />
        <MessageComposer
          approxTokens={approxTokens}
          busy={busy}
          cfg={cfg}
          documentTool={documentTool}
          fieldClass={field}
          imageTool={imageTool}
          input={input}
          inputRef={inputRef}
          messages={messages}
          modelId={modelId}
          modelsLoading={modelsLoading}
          onInput={setInput}
          onKeyDown={onKeyDown}
          onRegenerate={() => void regenerate()}
          onSend={() => void send()}
          onPromptLibrary={() => setLibraryOpen(true)}
          onStop={() => void stopGeneration()}
          personas={personas}
          personasLoading={personasLoading}
          personaId={personaId}
          quickModels={quickModels}
          quickPersonas={quickPersonas}
          selectedModel={selectedModel}
          setModelId={setModelId}
          setPromptFromHistory={(prompt) => {
            setInput(prompt);
            inputRef.current?.focus();
          }}
          stats={stats}
          visiblePromptHistory={visiblePromptHistory}
          applyPersona={applyPersona}
          attachmentNote={attachmentNote}
          attachments={attachments}
          attachmentsUploading={attachmentsUploading}
          onAttachFiles={(files) => void uploadAttachments(files)}
          onPaste={onPaste}
          onRemoveAttachment={(token) =>
            setAttachments((prev) => prev.filter((item) => item.token !== token))
          }
        />
        <PromptLibrary
          open={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          currentPrompt={imagePromptDraft(input)}
          currentNegative=""
          onApply={applyImagePromptSnippet}
        />
      </div>

      <ChatSettingsPanel controller={controller} />
    </div>
  );
}
