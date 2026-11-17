import { usePreference } from "../lib/preferences";
import { usePreferences } from "../lib/preferences";
import { preferences } from "../settings/workspacePreferences";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { appQueryCache } from "../api/queryCache";
import { storage } from "../lib/storage";
import type { ChatAttachment, ChatMessage, LlmApiServerStatus, LlmConfig, Model, Preset } from "../types";
import {
  chatSampling,
  conversationSettings,
  personaSettings,
  type ChatSettingsDraft,
  downloadJson,
  hasActiveSelection,
  loadPromptHistory,
  parseImportBundle,
  PROMPT_HISTORY_KEY,
  promptHistoryLimit,
} from "./chatHelpers";
import { useChatActions, useConversation } from "./ChatPanelHooks";
import { useChatStream } from "./useChatStream";
import { toast } from "./Toast";

export type ChatJump = { conversationId: string; jobId?: string; nonce: number };
export type ChatPanelProps = {
  models: Model[];
  modelsLoading?: boolean;
  jump?: ChatJump | null;
  draft: string;
  setDraft: (value: string) => void;
};

export function useChatPanelController({
  models,
  modelsLoading = false,
  jump,
  draft,
  setDraft,
}: ChatPanelProps) {
  const llmModels = useMemo(() => models.filter((model) => model.job_type === "llm"), [models]);

  const { convs, convsLoading, refreshConvs, setConvs } = useConversation();
  const [activeId, setActiveIdState] = useState<string | null>(null);
  const activeConversation = useRef<string | null>(null);
  const selectionRevision = useRef(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  // The composer draft is lifted to App so it survives tab switches (this panel
  // unmounts when you navigate away).
  const input = draft;
  const setInput = setDraft;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [convQuery, setConvQuery] = usePreference(preferences.chatUi, "convQuery");
  const [promptHistory, setPromptHistory] = useState<string[]>(() => loadPromptHistory());
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentsUploading, setAttachmentsUploading] = useState(false);
  const [attachmentNote, setAttachmentNote] = useState("");

  const [settings, setSettings] = usePreferences(preferences.chat);
  const updateSettings = useCallback((patch: Partial<ChatSettingsDraft>) => {
    setSettings((current) => ({ ...current, ...patch }));
  }, [setSettings]);
  const { modelId, system, imageTool, documentTool, ragTopK } = settings;
  const [showAdvanced, setShowAdvanced] = usePreference(preferences.chatUi, "showAdvanced");

  // personas (stored as llm presets)
  const [personas, setPersonas] = useState<Preset[]>([]);
  const [personasLoading, setPersonasLoading] = useState(true);
  const [personaId, setPersonaId] = usePreference(preferences.chatUi, "personaId");
  const [personaName, setPersonaName] = useState("");

  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [llmServer, setLlmServer] = useState<LlmApiServerStatus | null>(null);
  const [ctxDraft, setCtxDraft] = useState<number | null>(null);
  const [configBusy, setConfigBusy] = useState(false);
  const [serverBusy, setServerBusy] = useState(false);
  const [cfgNote, setCfgNote] = useState("");
  const [importNote, setImportNote] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const stickToBottom = useRef(true);
  const {
    activeJob,
    beginStream,
    isCurrentStream,
    reconcile,
    resetStream,
    restoreStream,
    setActiveJob,
    stats,
  } = useChatStream({
    activeConversation,
    refreshConvs,
    setBusy,
    setMessages,
  });
  const setActiveId = useCallback(
    (id: string | null) => {
      preferences.chatUi.set((current) => ({ ...current, conversationId: id ?? "" }));
      selectionRevision.current += 1;
      activeConversation.current = id;
      resetStream();
      setActiveIdState(id);
    },
    [resetStream],
  );
  useEffect(
    () => () => {
      selectionRevision.current += 1;
      activeConversation.current = null;
    },
    [],
  );
  const refreshPersonas = useCallback(async () => {
    setPersonasLoading(true);
    try {
      const p = await api.listPresets();
      setPersonas(p.filter((x) => x.type === "llm"));
    } catch {
      // Persona presets are optional; failed refresh should not disturb chat.
    } finally {
      setPersonasLoading(false);
    }
  }, []);
  const selectedModel = useMemo(() => llmModels.find((m) => m.id === modelId), [llmModels, modelId]);
  const quickModels = useMemo(() => {
    const current = llmModels.find((m) => m.id === modelId);
    const loaded = llmModels.filter((m) => m.loaded || m.warm);
    const rest = llmModels.filter((m) => !loaded.some((x) => x.id === m.id));
    const out: Model[] = [];
    for (const model of [current, ...loaded, ...rest]) {
      if (model && !out.some((item) => item.id === model.id)) out.push(model);
    }
    return out.slice(0, 4);
  }, [llmModels, modelId]);
  const quickPersonas = useMemo(() => personas.slice(0, 4), [personas]);
  const visiblePromptHistory = useMemo(
    () => promptHistory.filter((item) => item !== input.trim()).slice(0, 4),
    [input, promptHistory],
  );
  const pendingAssistantId = useMemo(() => {
    if (!busy) return null;
    return [...messages].reverse().find((m) => m.role === "assistant")?.id ?? null;
  }, [busy, messages]);

  const rememberPrompt = useCallback((content: string) => {
    const text = content.trim();
    if (!text) return;
    setPromptHistory((prev) => {
      const next = [text, ...prev.filter((item) => item !== text)].slice(0, promptHistoryLimit);
      return next;
    });
  }, []);

  useEffect(() => {
    refreshConvs();
    refreshPersonas();
    api
      .getLlmConfig()
      .then((c) => {
        setCfg(c);
        setCtxDraft((p) => p ?? c.ctx);
      })
      .catch((error: unknown) => console.warn("Could not load LLM config", error));
    api
      .getLlmServer()
      .then(setLlmServer)
      .catch((error: unknown) => console.warn("Could not load LLM server status", error));
  }, [refreshConvs, refreshPersonas]);

  useEffect(() => {
    if (!modelId && llmModels[0]) updateSettings({ modelId: llmModels[0].id });
  }, [llmModels, modelId, updateSettings]);

  useEffect(() => {
    storage.set(PROMPT_HISTORY_KEY, JSON.stringify(promptHistory));
  }, [promptHistory]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const updateScrollStickiness = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  }, []);

  useEffect(() => {
    if (!stickToBottom.current || hasActiveSelection()) return;
    scrollToBottom("auto");
  }, [messages, scrollToBottom]);

  // auto-grow the composer up to a cap, then scroll inside it
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const selectConversation = useCallback(
    async (id: string, jobHint?: string) => {
      const restoring = preferences.chatUi.get().conversationId === id;
      stickToBottom.current = true;
      setActiveId(id);
      const revision = selectionRevision.current;
      setMessages([]);
      setBusy(true);
      setEditingId(null);
      try {
        const d = await api.getConversation(id);
        if (selectionRevision.current !== revision) return;
        setMessages(d.messages);
        restoreStream(d.messages, jobHint);
        if (jobHint || d.messages.some((message) => message.job_id)) {
          void reconcile().catch((error: unknown) =>
            toast.error(error instanceof Error ? error.message : "Could not synchronize chat"),
          );
        }
        setAttachments([]);
        setAttachmentNote("");
        setSettings((current) => restoring ? current : conversationSettings(current, d));
      } catch (error) {
        if (selectionRevision.current !== revision) return;
        setMessages([]);
        setBusy(false);
        toast.error(error instanceof Error ? error.message : "Could not load conversation");
      }
    },
    [reconcile, restoreStream, setActiveId, setSettings],
  );

  useEffect(() => {
    if (!activeId && convs[0]) {
      const saved = preferences.chatUi.get().conversationId;
      void selectConversation(convs.find((conversation) => conversation.id === saved)?.id ?? convs[0].id);
    }
  }, [convs, activeId, selectConversation]);

  useEffect(() => {
    if (!jump?.conversationId) return;
    refreshConvs();
    void selectConversation(jump.conversationId, jump.jobId);
  }, [jump, refreshConvs, selectConversation]);

  const newChat = useCallback(async () => {
    const revision = ++selectionRevision.current;
    const c = await api.createConversation({ model_id: modelId || llmModels[0]?.id });
    stickToBottom.current = true;
    setConvs((p) => [c, ...p]);
    if (selectionRevision.current !== revision) return;
    setActiveId(c.id);
    setMessages([]);
    setAttachments([]);
    setAttachmentNote("");
    setEditingId(null);
  }, [modelId, llmModels, setActiveId, setConvs]);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        setConvs((p) => p.filter((c) => c.id !== id));
        if (activeConversation.current === id) {
          setActiveId(null);
          setMessages([]);
          setAttachments([]);
          setAttachmentNote("");
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Could not delete conversation");
      }
    },
    [setActiveId, setConvs],
  );

  const sampling = useCallback(() => chatSampling(settings), [settings]);

  const {
    applyImagePromptSnippet,
    onPaste,
    regenerate,
    saveEdit,
    send,
    startEdit,
    stop: stopGeneration,
    uploadAttachments,
  } = useChatActions({
    activeId,
    activeJob,
    attachments,
    attachmentsUploading,
    beginStream,
    isCurrentStream,
    reconcile,
    busy,
    documentTool,
    editingId,
    editText,
    imageTool,
    input,
    inputRef,
    llmModels,
    messages,
    modelId,
    models,
    ragTopK,
    rememberPrompt,
    sampling,
    setActiveId,
    setActiveJob,
    setAttachmentNote,
    setAttachments,
    setAttachmentsUploading,
    setBusy,
    setConvs,
    setEditText,
    setEditingId,
    setInput,
    setLibraryOpen,
    setMessages,
    stickToBottom,
  });

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const applyLlmConfig = async (body: Parameters<typeof api.setLlmConfig>[0]) => {
    setCfgNote("");
    setConfigBusy(true);
    try {
      const next = await api.setLlmConfig(body);
      setCfg(next);
      if (body.ctx != null) setCtxDraft(next.ctx);
      const base = next.reloaded
        ? "applied — model reloaded"
        : next.changed
          ? "applied (next load)"
          : "no change";
      setCfgNote(next.note ? `${base} · ${next.note}` : base);
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update");
    } finally {
      setConfigBusy(false);
    }
  };
  const applyCtx = async () => {
    if (ctxDraft != null) await applyLlmConfig({ ctx: ctxDraft });
  };
  const applyBackend = (backend: string) => void applyLlmConfig({ backend });
  const applyContextType = (context_type: string) => void applyLlmConfig({ context_type });
  const activeBackend = cfg?.backends.find((b) => b.id === cfg.backend) ?? null;
  // Only offer context types the active backend can actually run (e.g. turbo3/4
  // disappear unless the TurboQuant backend is selected).
  const ctxTypeOptions = (cfg?.context_types ?? []).filter(
    (ct) => !activeBackend || activeBackend.context_types.includes(ct.id),
  );

  const toggleLlmServer = async (enabled: boolean) => {
    setCfgNote("");
    setServerBusy(true);
    try {
      const next = await api.setLlmServer({ enabled, ...(enabled && modelId ? { model_id: modelId } : {}) });
      setLlmServer(next);
      const nextCfg = await api.getLlmConfig();
      setCfg(nextCfg);
      setCtxDraft(nextCfg.ctx);
      setCfgNote(
        enabled
          ? next.available
            ? "OpenAI API ready"
            : (next.note ?? "API server enabled")
          : "API server stopped",
      );
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update API server");
    } finally {
      setServerBusy(false);
    }
  };

  const copyLlmServerUrl = async () => {
    if (!llmServer?.base_url) return;
    try {
      await navigator.clipboard?.writeText(llmServer.base_url);
      setCfgNote("API base URL copied");
    } catch {
      setCfgNote("could not copy API URL");
    }
  };

  // --- personas ---
  const applyPersona = (id: string) => {
    setPersonaId(id);
    const p = personas.find((x) => x.id === id);
    if (!p) return;
    setSettings((current) => personaSettings(current, p.params ?? {}));
  };

  const savePersona = async () => {
    const name = personaName.trim();
    if (!name) return;
    try {
      await api.createPreset(name, "llm", { ...sampling(), system: system.trim() });
      setPersonaName("");
      refreshPersonas();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save persona");
    }
  };

  const deletePersona = async () => {
    if (!personaId) return;
    try {
      await api.deletePreset(personaId);
      setPersonaId("");
      refreshPersonas();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete persona");
    }
  };

  const exportChat = () => {
    if (!messages.length) return;
    const title = convs.find((c) => c.id === activeId)?.title ?? "chat";
    const md = `# ${title}\n\n` + messages.map((m) => `**${m.role}:**\n\n${m.content}\n`).join("\n---\n\n");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.slice(0, 40).replace(/[^a-z0-9]+/gi, "-") || "chat"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportJson = async () => {
    const activeConv = convs.find((c) => c.id === activeId);
    const conversations = activeConv
      ? [
          {
            title: activeConv.title,
            model_id: activeConv.model_id,
            system: activeConv.system,
            params: activeConv.params,
            created_at: activeConv.created_at,
            updated_at: activeConv.updated_at,
            messages: messages.map((m) => ({
              role: m.role,
              content: m.content,
              attachments: m.attachments ?? [],
              error: m.error,
              created_at: m.created_at,
            })),
          },
        ]
      : [];
    let allPresets: Preset[];
    try {
      allPresets = await api.listPresets();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load presets for export");
      return;
    }
    const presets = allPresets.map((p) => ({ name: p.name, type: p.type, params: p.params }));
    const title = activeConv?.title ?? "chat";
    const slug = title.slice(0, 40).replace(/[^a-z0-9]+/gi, "-") || "hfabric";
    downloadJson(`${slug}.hfabric.json`, {
      format: "hfabric.bundle.v1",
      exported_at: new Date().toISOString(),
      conversations,
      presets,
    });
  };

  const importJson = useCallback(
    async (file: File | null) => {
      if (!file) return;
      setImportNote("");
      try {
        const bundle = parseImportBundle(JSON.parse(await file.text()));
        const parts: string[] = [];
        let firstImportedConversation: string | null = null;

        if (bundle.conversations.length) {
          const res = await api.importConversations(bundle.conversations);
          firstImportedConversation = res.conversations[0]?.id ?? null;
          parts.push(`${res.imported} chat${res.imported === 1 ? "" : "s"}`);
        }

        if (bundle.presets.length) {
          const res = await api.importPresets(bundle.presets, "rename");
          appQueryCache.invalidate("presets");
          parts.push(`${res.imported} preset${res.imported === 1 ? "" : "s"}`);
        }

        if (!parts.length) {
          setImportNote("nothing importable in file");
          return;
        }

        await refreshConvs();
        await refreshPersonas();
        if (firstImportedConversation) await selectConversation(firstImportedConversation);
        setImportNote(`imported ${parts.join(", ")}`);
      } catch (err) {
        setImportNote(err instanceof Error ? err.message : "import failed");
      } finally {
        if (importInputRef.current) importInputRef.current.value = "";
      }
    },
    [refreshConvs, refreshPersonas, selectConversation],
  );

  const filteredConvs = convQuery.trim()
    ? convs.filter((c) => c.title.toLowerCase().includes(convQuery.trim().toLowerCase()))
    : convs;

  const attachmentTokens = attachments.reduce(
    (n, item) => n + (item.kind === "image" ? 1024 : Math.min(8192, Math.ceil(item.size_bytes / 4))),
    0,
  );
  const approxTokens =
    Math.ceil((system.length + input.length + messages.reduce((n, m) => n + m.content.length, 0)) / 4) +
    attachmentTokens;

  return {
    activeBackend,
    activeId,
    applyBackend,
    applyContextType,
    applyCtx,
    applyImagePromptSnippet,
    applyPersona,
    approxTokens,
    attachmentNote,
    attachments,
    attachmentsUploading,
    busy,
    cfg,
    cfgNote,
    convQuery,
    convs,
    convsLoading,
    copyLlmServerUrl,
    ctxDraft,
    configBusy,
    ctxTypeOptions,
    deleteConversation,
    deletePersona,
    editText,
    editingId,
    exportChat,
    exportJson,
    filteredConvs,
    importInputRef,
    importJson,
    importNote,
    input,
    inputRef,
    libraryOpen,
    llmModels,
    llmServer,
    messages,
    models,
    modelsLoading,
    settings,
    updateSettings,
    newChat,
    onKeyDown,
    onPaste,
    pendingAssistantId,
    personaId,
    personaName,
    personas,
    personasLoading,
    quickModels,
    quickPersonas,
    regenerate,
    saveEdit,
    savePersona,
    scrollRef,
    selectedModel,
    selectConversation,
    send,
    serverBusy,
    setAttachments,
    setConvQuery,
    setCtxDraft,
    setEditText,
    setEditingId,
    setInput,
    setLibraryOpen,
    setPersonaName,
    setShowAdvanced,
    showAdvanced,
    startEdit,
    stats,
    stopGeneration,
    toggleLlmServer,
    updateScrollStickiness,
    uploadAttachments,
    visiblePromptHistory,
  };
}

export type ChatPanelController = ReturnType<typeof useChatPanelController>;
