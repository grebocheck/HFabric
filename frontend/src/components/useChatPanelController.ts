import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { storage } from "../lib/storage";
import type {
  ChatAttachment,
  ChatMessage,
  ChatSendBody,
  LlmApiServerStatus,
  LlmConfig,
  Model,
  Preset,
} from "../types";
import {
  DEFAULTS_KEY,
  downloadJson,
  hasActiveSelection,
  loadDefaults,
  loadPromptHistory,
  numOrUndef,
  parseImportBundle,
  parseStop,
  PROMPT_HISTORY_KEY,
  promptHistoryLimit,
  type NumOrEmpty,
} from "./chatHelpers";
import { useChatActions, useChatStream, useConversation } from "./ChatPanelHooks";
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
  const llmModels = models.filter((m) => m.job_type === "llm");
  const saved = loadDefaults();

  const { convs, convsLoading, refreshConvs, setConvs } = useConversation();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  // The composer draft is lifted to App so it survives tab switches (this panel
  // unmounts when you navigate away).
  const input = draft;
  const setInput = setDraft;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [convQuery, setConvQuery] = useState("");
  const [promptHistory, setPromptHistory] = useState<string[]>(() => loadPromptHistory());
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentsUploading, setAttachmentsUploading] = useState(false);
  const [attachmentNote, setAttachmentNote] = useState("");

  // settings (per conversation)
  const [modelId, setModelId] = useState(saved.model_id ?? "");
  const [system, setSystem] = useState("");
  const [temperature, setTemperature] = useState(saved.temperature ?? 0.8);
  const [maxTokens, setMaxTokens] = useState(saved.max_tokens ?? 4096);
  // advanced sampling ("" = unset -> use model default)
  const [topP, setTopP] = useState<NumOrEmpty>("");
  const [topK, setTopK] = useState<NumOrEmpty>("");
  const [minP, setMinP] = useState<NumOrEmpty>("");
  const [repeatPenalty, setRepeatPenalty] = useState<NumOrEmpty>("");
  const [seed, setSeed] = useState<NumOrEmpty>("");
  const [stop, setStop] = useState("");
  const [imageTool, setImageTool] = useState(Boolean(saved.image_tool));
  const [documentTool, setDocumentTool] = useState(Boolean(saved.document_tool));
  const [ragTopK, setRagTopK] = useState(saved.rag_top_k ?? 5);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // personas (stored as llm presets)
  const [personas, setPersonas] = useState<Preset[]>([]);
  const [personasLoading, setPersonasLoading] = useState(true);
  const [personaId, setPersonaId] = useState("");
  const [personaName, setPersonaName] = useState("");

  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [llmServer, setLlmServer] = useState<LlmApiServerStatus | null>(null);
  const [ctxDraft, setCtxDraft] = useState<number | null>(null);
  const [ctxTypeBusy, setCtxTypeBusy] = useState(false);
  const [serverBusy, setServerBusy] = useState(false);
  const [cfgNote, setCfgNote] = useState("");
  const [importNote, setImportNote] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const stickToBottom = useRef(true);
  const { activeJob, beginStream, setActiveJob, setStats, stats, trackJump } = useChatStream({
    refreshConvs,
    setBusy,
    setMessages,
  });
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
    if (!modelId && llmModels[0]) setModelId(llmModels[0].id);
  }, [llmModels, modelId]);

  useEffect(() => {
    storage.set(
      DEFAULTS_KEY,
      JSON.stringify({
        model_id: modelId,
        temperature,
        max_tokens: maxTokens,
        image_tool: imageTool,
        document_tool: documentTool,
        rag_top_k: ragTopK,
      }),
    );
  }, [modelId, temperature, maxTokens, imageTool, documentTool, ragTopK]);

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
    async (id: string) => {
      stickToBottom.current = true;
      setActiveId(id);
      setEditingId(null);
      setStats(null);
      try {
        const d = await api.getConversation(id);
        setMessages(d.messages);
        setAttachments([]);
        setAttachmentNote("");
        if (d.model_id) setModelId(d.model_id);
        setSystem(d.system ?? "");
        const pr = d.params ?? {};
        if (typeof pr.temperature === "number") setTemperature(pr.temperature);
        if (typeof pr.max_tokens === "number") setMaxTokens(pr.max_tokens);
        setTopP(typeof pr.top_p === "number" ? pr.top_p : "");
        setTopK(typeof pr.top_k === "number" ? pr.top_k : "");
        setMinP(typeof pr.min_p === "number" ? pr.min_p : "");
        setRepeatPenalty(typeof pr.repeat_penalty === "number" ? pr.repeat_penalty : "");
        setStop(Array.isArray(pr.stop) ? (pr.stop as string[]).join(", ") : "");
        setImageTool(Boolean(pr.image_tool));
        setDocumentTool(Boolean(pr.document_tool));
        setRagTopK(typeof pr.rag_top_k === "number" ? pr.rag_top_k : 5);
      } catch {
        setMessages([]);
      }
    },
    [setStats],
  );

  useEffect(() => {
    if (!activeId && convs[0]) void selectConversation(convs[0].id);
  }, [convs, activeId, selectConversation]);

  useEffect(() => {
    if (!jump?.conversationId) return;
    trackJump(jump.jobId);
    refreshConvs();
    void selectConversation(jump.conversationId);
  }, [jump, refreshConvs, selectConversation, trackJump]);

  const newChat = useCallback(async () => {
    const c = await api.createConversation({ model_id: modelId || llmModels[0]?.id });
    stickToBottom.current = true;
    setConvs((p) => [c, ...p]);
    setActiveId(c.id);
    setMessages([]);
    setAttachments([]);
    setAttachmentNote("");
    setEditingId(null);
    setStats(null);
  }, [modelId, llmModels, setConvs, setStats]);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        setConvs((p) => p.filter((c) => c.id !== id));
        if (activeId === id) {
          setActiveId(null);
          setMessages([]);
          setAttachments([]);
          setAttachmentNote("");
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Could not delete conversation");
      }
    },
    [activeId, setConvs],
  );

  const sampling = useCallback(
    (): Omit<ChatSendBody, "content" | "model_id"> => ({
      system: system.trim() || undefined,
      temperature,
      max_tokens: maxTokens,
      top_p: numOrUndef(topP),
      top_k: numOrUndef(topK),
      min_p: numOrUndef(minP),
      repeat_penalty: numOrUndef(repeatPenalty),
      seed: numOrUndef(seed),
      stop: parseStop(stop),
    }),
    [system, temperature, maxTokens, topP, topK, minP, repeatPenalty, seed, stop],
  );

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

  const applyCtx = async () => {
    if (ctxDraft == null) return;
    setCfgNote("");
    try {
      const next = await api.setLlmConfig({ ctx: ctxDraft });
      setCfg(next);
      setCtxDraft(next.ctx);
      setCfgNote(
        next.reloaded ? "applied — model reloaded" : next.changed ? "applied (next load)" : "no change",
      );
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update");
    }
  };

  const applyLlmConfig = async (body: { backend?: string; context_type?: string }) => {
    setCfgNote("");
    setCtxTypeBusy(true);
    try {
      const next = await api.setLlmConfig(body);
      setCfg(next);
      const base = next.reloaded
        ? "applied — model reloaded"
        : next.changed
          ? "applied (next load)"
          : "no change";
      setCfgNote(next.note ? `${base} · ${next.note}` : base);
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update");
    } finally {
      setCtxTypeBusy(false);
    }
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
    const pr = p.params ?? {};
    setSystem(typeof pr.system === "string" ? pr.system : "");
    if (typeof pr.temperature === "number") setTemperature(pr.temperature);
    if (typeof pr.max_tokens === "number") setMaxTokens(pr.max_tokens);
    setTopP(typeof pr.top_p === "number" ? pr.top_p : "");
    setTopK(typeof pr.top_k === "number" ? pr.top_k : "");
    setMinP(typeof pr.min_p === "number" ? pr.min_p : "");
    setRepeatPenalty(typeof pr.repeat_penalty === "number" ? pr.repeat_penalty : "");
    setStop(Array.isArray(pr.stop) ? (pr.stop as string[]).join(", ") : "");
  };

  const savePersona = async () => {
    const name = personaName.trim();
    if (!name) return;
    const s = sampling();
    try {
      await api.createPreset(name, "llm", {
        system: system.trim(),
        temperature,
        max_tokens: maxTokens,
        ...(s.top_p !== undefined ? { top_p: s.top_p } : {}),
        ...(s.top_k !== undefined ? { top_k: s.top_k } : {}),
        ...(s.min_p !== undefined ? { min_p: s.min_p } : {}),
        ...(s.repeat_penalty !== undefined ? { repeat_penalty: s.repeat_penalty } : {}),
        ...(s.stop ? { stop: s.stop } : {}),
      });
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

  const exportJson = () => {
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
    const presets = personas.map((p) => ({ name: p.name, type: p.type, params: p.params }));
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
    ctxTypeBusy,
    ctxTypeOptions,
    deleteConversation,
    deletePersona,
    documentTool,
    editText,
    editingId,
    exportChat,
    exportJson,
    filteredConvs,
    imageTool,
    importInputRef,
    importJson,
    importNote,
    input,
    inputRef,
    libraryOpen,
    llmModels,
    llmServer,
    maxTokens,
    messages,
    minP,
    modelId,
    models,
    modelsLoading,
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
    ragTopK,
    regenerate,
    repeatPenalty,
    saveEdit,
    savePersona,
    scrollRef,
    seed,
    selectedModel,
    selectConversation,
    send,
    serverBusy,
    setAttachments,
    setConvQuery,
    setCtxDraft,
    setDocumentTool,
    setEditText,
    setEditingId,
    setImageTool,
    setInput,
    setLibraryOpen,
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
    startEdit,
    stats,
    stop,
    stopGeneration,
    system,
    temperature,
    toggleLlmServer,
    topK,
    topP,
    updateScrollStickiness,
    uploadAttachments,
    visiblePromptHistory,
  };
}

export type ChatPanelController = ReturnType<typeof useChatPanelController>;
