import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChatAttachment, ChatMessage, ChatSendBody, LlmConfig, Model, Preset } from "../types";
import { ModelPicker } from "./ModelPicker";
import { PromptLibrary } from "./PromptLibrary";
import { Select } from "./Select";
import { Toggle } from "./Toggle";
import { SkeletonLine, SkeletonRows } from "./WorkspaceChrome";
import {
  DEFAULTS_KEY,
  downloadJson,
  hasActiveSelection,
  loadDefaults,
  loadPromptHistory,
  numOrUndef,
  parseImportBundle,
  parseStop,
  pickImageModel,
  PROMPT_HISTORY_KEY,
  promptHistoryLimit,
  type NumOrEmpty,
} from "./chatHelpers";
import { setLastAssistant, useChatStream, useConversation } from "./ChatPanelHooks";
import { MessageComposer, MessageList } from "./ChatPanelParts";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-emerald-500";
const numField = "w-full rounded-md bg-black/30 border border-white/10 px-2 py-1 text-xs outline-none focus:border-emerald-500";
const label = "text-xs uppercase tracking-wide text-white/40";

export type ChatJump = { conversationId: string; jobId?: string; nonce: number };

export function ChatPanel({ models, modelsLoading = false, jump, draft, setDraft }: { models: Model[]; modelsLoading?: boolean; jump?: ChatJump | null; draft: string; setDraft: (v: string) => void }) {
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
  const [maxTokens, setMaxTokens] = useState(saved.max_tokens ?? 2048);
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
  const [ctxDraft, setCtxDraft] = useState<number | null>(null);
  const [ctxTypeBusy, setCtxTypeBusy] = useState(false);
  const [cfgNote, setCfgNote] = useState("");
  const [importNote, setImportNote] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const stickToBottom = useRef(true);
  const { activeJob, beginStream, setActiveJob, setStats, stats, trackJump } = useChatStream({ refreshConvs, setBusy, setMessages });
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

  const uploadAttachments = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files).filter((file) => file.size > 0);
    if (!list.length) return;
    setAttachmentsUploading(true);
    setAttachmentNote("");
    try {
      const uploaded = await Promise.all(list.map((file) => api.uploadChatAttachment(file)));
      setAttachments((prev) => [...prev, ...uploaded].slice(0, 12));
    } catch (err) {
      setAttachmentNote(err instanceof Error ? err.message : "attachment upload failed");
    } finally {
      setAttachmentsUploading(false);
    }
  }, []);

  useEffect(() => {
    refreshConvs();
    refreshPersonas();
    api.getLlmConfig().then((c) => { setCfg(c); setCtxDraft((p) => p ?? c.ctx); }).catch(() => {});
  }, [refreshConvs, refreshPersonas]);

  useEffect(() => {
    if (!modelId && llmModels[0]) setModelId(llmModels[0].id);
  }, [llmModels, modelId]);

  useEffect(() => {
    localStorage.setItem(DEFAULTS_KEY, JSON.stringify({
      model_id: modelId,
      temperature,
      max_tokens: maxTokens,
      image_tool: imageTool,
      document_tool: documentTool,
      rag_top_k: ragTopK,
    }));
  }, [modelId, temperature, maxTokens, imageTool, documentTool, ragTopK]);

  useEffect(() => {
    localStorage.setItem(PROMPT_HISTORY_KEY, JSON.stringify(promptHistory));
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

  const selectConversation = useCallback(async (id: string) => {
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
  }, [setStats]);

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

  const deleteConversation = useCallback(async (id: string) => {
    await api.deleteConversation(id).catch(() => {});
    setConvs((p) => p.filter((c) => c.id !== id));
    if (activeId === id) { setActiveId(null); setMessages([]); setAttachments([]); setAttachmentNote(""); }
  }, [activeId, setConvs]);

  const sampling = useCallback((): Omit<ChatSendBody, "content" | "model_id"> => ({
    system: system.trim() || undefined,
    temperature,
    max_tokens: maxTokens,
    top_p: numOrUndef(topP),
    top_k: numOrUndef(topK),
    min_p: numOrUndef(minP),
    repeat_penalty: numOrUndef(repeatPenalty),
    seed: numOrUndef(seed),
    stop: parseStop(stop),
  }), [system, temperature, maxTokens, topP, topK, minP, repeatPenalty, seed, stop]);

  const submit = useCallback(async (content: string, convId: string, outgoingAttachments: ChatAttachment[] = []) => {
    const mdl = modelId || llmModels[0]?.id;
    if (!mdl) return;
    stickToBottom.current = true;
    beginStream();
    setMessages((p) => [
      ...p,
      { id: "tmp-u", role: "user", content, attachments: outgoingAttachments },
      { id: "tmp-a", role: "assistant", content: "" },
    ]);
    try {
      const img = imageTool ? pickImageModel(models) : undefined;
      const res = await api.sendChatMessage(convId, {
        content,
        model_id: mdl,
        attachments: outgoingAttachments.map((item) => ({ token: item.token })),
        ...sampling(),
        ...(imageTool && img ? { image_tool: true, image_model_id: img.id } : {}),
        ...(documentTool ? { document_tool: true, rag_top_k: ragTopK } : {}),
      });
      setActiveJob(res.job_id);
      setMessages((p) => p.map((m) =>
        m.id === "tmp-u" ? res.user_message : m.id === "tmp-a" ? { ...res.assistant_message, content: "" } : m,
      ));
      setConvs((p) => [res.conversation, ...p.filter((c) => c.id !== res.conversation.id)]);
    } catch (err) {
      setActiveJob(null);
      setBusy(false);
      setMessages((p) => setLastAssistant(p, `⚠ ${err instanceof Error ? err.message : "request failed"}`, true));
    }
  }, [beginStream, documentTool, imageTool, modelId, llmModels, models, ragTopK, sampling, setActiveJob, setConvs]);

  const submitImage = useCallback(async (prompt: string, convId: string, negative?: string) => {
    const img = pickImageModel(models);
    stickToBottom.current = true;
    if (!img) {
      setMessages((p) => [...p, { id: "tmp-u", role: "user", content: `/image ${prompt}` },
        { id: "tmp-a", role: "assistant", content: "⚠ no image model available", error: true }]);
      return;
    }
    beginStream();
    setMessages((p) => [...p, { id: "tmp-u", role: "user", content: `/image ${prompt}` },
      { id: "tmp-a", role: "assistant", content: "" }]);
    try {
      const res = await api.sendChatImage(convId, { prompt, model_id: img.id, negative });
      setActiveJob(res.job_id);
      setMessages((p) => p.map((m) =>
        m.id === "tmp-u" ? res.user_message : m.id === "tmp-a" ? { ...res.assistant_message, content: "" } : m,
      ));
      setConvs((p) => [res.conversation, ...p.filter((c) => c.id !== res.conversation.id)]);
    } catch (err) {
      setActiveJob(null);
      setBusy(false);
      setMessages((p) => setLastAssistant(p, `⚠ ${err instanceof Error ? err.message : "request failed"}`, true));
    }
  }, [beginStream, models, setActiveJob, setConvs]);

  const send = useCallback(async () => {
    const content = input.trim();
    const outgoingAttachments = attachments;
    if ((!content && outgoingAttachments.length === 0) || busy || attachmentsUploading) return;
    let cid = activeId;
    if (!cid) {
      const c = await api.createConversation({ model_id: modelId || llmModels[0]?.id });
      setConvs((p) => [c, ...p]);
      setActiveId(c.id);
      cid = c.id;
    }
    setInput("");
    setAttachments([]);
    setAttachmentNote("");
    if (content) rememberPrompt(content);
    const imgCmd = content.match(/^\/(?:image|img)\s+([\s\S]+)/i);
    if (imgCmd && outgoingAttachments.length === 0) {
      const parsed = parseImageCommand(imgCmd[1].trim());
      if (!parsed.prompt) return;
      await submitImage(parsed.prompt, cid, parsed.negative);
    }
    else await submit(content, cid, outgoingAttachments);
  }, [input, attachments, attachmentsUploading, busy, activeId, modelId, llmModels, rememberPrompt, submit, submitImage, setConvs, setInput]);

  const applyImagePromptSnippet = useCallback((body: string, negative?: string | null) => {
    const prompt = body.trim();
    if (!prompt) return;
    const neg = negative?.trim();
    setInput(`/image ${prompt}${neg ? ` --negative ${neg}` : ""}`);
    setLibraryOpen(false);
    inputRef.current?.focus();
  }, [setInput]);

  const stop_ = useCallback(async () => {
    await api.stopLlm().catch(() => {});
    if (activeJob.current) await api.cancelJob(activeJob.current).catch(() => {});
  }, [activeJob]);

  const regenerate = useCallback(async () => {
    if (busy || !activeId) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || lastUser.id.startsWith("tmp")) return;
    await api.truncateFrom(activeId, lastUser.id).catch(() => {});
    const idx = messages.findIndex((m) => m.id === lastUser.id);
    setMessages((p) => p.slice(0, idx));
    await submit(lastUser.content, activeId, lastUser.attachments ?? []);
  }, [busy, activeId, messages, submit]);

  const startEdit = (m: ChatMessage) => { setEditingId(m.id); setEditText(m.content); };
  const saveEdit = useCallback(async () => {
    if (!activeId || !editingId) return;
    const content = editText.trim();
    const idx = messages.findIndex((m) => m.id === editingId);
    setEditingId(null);
    if (!content || idx < 0) return;
    const editedAttachments = messages[idx]?.attachments ?? [];
    await api.truncateFrom(activeId, editingId).catch(() => {});
    setMessages((p) => p.slice(0, idx));
    await submit(content, activeId, editedAttachments);
  }, [activeId, editingId, editText, messages, submit]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = e.clipboardData?.files;
    if (files?.length) void uploadAttachments(files);
  };

  const applyCtx = async () => {
    if (ctxDraft == null) return;
    setCfgNote("");
    try {
      const next = await api.setLlmConfig({ ctx: ctxDraft });
      setCfg(next); setCtxDraft(next.ctx);
      setCfgNote(next.reloaded ? "applied — model reloaded" : next.changed ? "applied (next load)" : "no change");
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update");
    }
  };

  const applyLlmConfig = async (body: { backend?: string; context_type?: string }) => {
    setCfgNote(""); setCtxTypeBusy(true);
    try {
      const next = await api.setLlmConfig(body);
      setCfg(next);
      const base = next.reloaded ? "applied — model reloaded" : next.changed ? "applied (next load)" : "no change";
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
    await api.createPreset(name, "llm", {
      system: system.trim(),
      temperature, max_tokens: maxTokens,
      ...(s.top_p !== undefined ? { top_p: s.top_p } : {}),
      ...(s.top_k !== undefined ? { top_k: s.top_k } : {}),
      ...(s.min_p !== undefined ? { min_p: s.min_p } : {}),
      ...(s.repeat_penalty !== undefined ? { repeat_penalty: s.repeat_penalty } : {}),
      ...(s.stop ? { stop: s.stop } : {}),
    }).catch(() => {});
    setPersonaName("");
    refreshPersonas();
  };

  const deletePersona = async () => {
    if (!personaId) return;
    await api.deletePreset(personaId).catch(() => {});
    setPersonaId("");
    refreshPersonas();
  };

  const exportChat = () => {
    if (!messages.length) return;
    const title = convs.find((c) => c.id === activeId)?.title ?? "chat";
    const md = `# ${title}\n\n` + messages
      .map((m) => `**${m.role}:**\n\n${m.content}\n`)
      .join("\n---\n\n");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.slice(0, 40).replace(/[^a-z0-9]+/gi, "-") || "chat"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportJson = () => {
    const activeConv = convs.find((c) => c.id === activeId);
    const conversations = activeConv ? [{
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
    }] : [];
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

  const importJson = useCallback(async (file: File | null) => {
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
  }, [refreshConvs, refreshPersonas, selectConversation]);

  const filteredConvs = convQuery.trim()
    ? convs.filter((c) => c.title.toLowerCase().includes(convQuery.trim().toLowerCase()))
    : convs;

  const attachmentTokens = attachments.reduce((n, item) => (
    n + (item.kind === "image" ? 1024 : Math.min(8192, Math.ceil(item.size_bytes / 4)))
  ), 0);
  const approxTokens = Math.ceil(
    (system.length + input.length + messages.reduce((n, m) => n + m.content.length, 0)) / 4,
  ) + attachmentTokens;

  return (
    <div className="flex h-full gap-3">
      {/* --- conversations --- */}
      <aside className="flex w-56 shrink-0 flex-col rounded-lg border border-white/10">
        <button onClick={() => void newChat()} className="mx-2 mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500">
          + New chat
        </button>
        <input
          value={convQuery}
          onChange={(e) => setConvQuery(e.target.value)}
          placeholder="search chats"
          className="mx-2 my-2 rounded-md border border-white/10 bg-black/30 px-2 py-1 text-xs outline-none focus:border-emerald-500"
        />
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {convsLoading && convs.length === 0 ? (
            <SkeletonRows rows={7} />
          ) : (
            <>
              {filteredConvs.length === 0 && <div className="px-1 text-xs text-white/30">no conversations</div>}
              {filteredConvs.map((c) => (
                <div
                  key={c.id}
                  onClick={() => void selectConversation(c.id)}
                  className={`group mb-1 flex cursor-pointer items-center justify-between gap-1 rounded-md px-2 py-1.5 text-sm ${
                    activeId === c.id ? "bg-white/15" : "hover:bg-white/5"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-white/80">{c.title}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); void deleteConversation(c.id); }}
                    className="shrink-0 text-white/30 opacity-0 transition hover:text-red-300 group-hover:opacity-100"
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
      <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-white/10">
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
          onStop={() => void stop_()}
          personas={personas}
          personasLoading={personasLoading}
          personaId={personaId}
          quickModels={quickModels}
          quickPersonas={quickPersonas}
          selectedModel={selectedModel}
          setModelId={setModelId}
          setPromptFromHistory={(prompt) => { setInput(prompt); inputRef.current?.focus(); }}
          stats={stats}
          visiblePromptHistory={visiblePromptHistory}
          applyPersona={applyPersona}
          attachmentNote={attachmentNote}
          attachments={attachments}
          attachmentsUploading={attachmentsUploading}
          onAttachFiles={(files) => void uploadAttachments(files)}
          onPaste={onPaste}
          onRemoveAttachment={(token) => setAttachments((prev) => prev.filter((item) => item.token !== token))}
        />
        <PromptLibrary
          open={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          currentPrompt={imagePromptDraft(input)}
          currentNegative=""
          onApply={applyImagePromptSnippet}
        />
      </div>

      {/* --- settings --- */}
      <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto rounded-lg border border-white/10 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white/75">Model settings</h2>
          <div className="flex gap-1">
            <button
              onClick={exportChat}
              disabled={!messages.length}
              className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10 disabled:opacity-30"
              title="Export conversation as Markdown"
            >
              MD
            </button>
            <button
              onClick={exportJson}
              disabled={!activeId && personas.length === 0}
              className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10 disabled:opacity-30"
              title="Export importable JSON bundle"
            >
              JSON
            </button>
            <button
              onClick={() => importInputRef.current?.click()}
              className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10"
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
        {importNote && <div className="text-[11px] text-emerald-300/80">{importNote}</div>}

        <label>
          <div className={label}>Model</div>
          {modelsLoading && llmModels.length === 0 ? (
            <SkeletonLine className="mt-1 h-9 w-full rounded-md" />
          ) : (
            <div className="mt-1">
              <ModelPicker models={llmModels} value={modelId} onChange={setModelId} placeholder="no LLM models" />
            </div>
          )}
        </label>

        <div className="flex items-center justify-between gap-3 rounded-md border border-white/10 bg-black/20 px-3 py-2">
          <span>
            <span className="block text-sm font-medium text-white/70">Model image tool</span>
            <span className="block text-xs text-white/35">{pickImageModel(models)?.name ?? "no image model"} · /image stays manual</span>
          </span>
          <Toggle checked={imageTool} disabled={!pickImageModel(models)} onChange={setImageTool} />
        </div>

        <div className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <span>
              <span className="block text-sm font-medium text-white/70">Document tool</span>
              <span className="block text-xs text-white/35">model-driven RAG search</span>
            </span>
            <Toggle checked={documentTool} onChange={setDocumentTool} />
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
            <input type="number" min={512} step={512} value={ctxDraft ?? ""} onChange={(e) => setCtxDraft(Number(e.target.value))} className={numField} />
            <button onClick={() => void applyCtx()} disabled={ctxDraft == null || ctxDraft === cfg?.ctx}
              className="shrink-0 rounded-md border border-white/15 px-2.5 py-1 text-xs hover:bg-white/10 disabled:opacity-30">
              Apply
            </button>
          </div>
          <div className="mt-1 text-[11px] text-white/35">current {cfg?.ctx ?? "?"} · {cfg?.loaded ? "loaded" : "not loaded"}</div>
          {cfgNote && <div className="mt-1 text-[11px] text-emerald-300/80">{cfgNote}</div>}
          {ctxDraft != null && cfg && ctxDraft !== cfg.ctx && cfg.loaded && (
            <div className="mt-1 text-[11px] text-amber-300/80">applying reloads the running model</div>
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
                {b.label}{!b.available && !cfg?.stub ? " (binary not found)" : ""}
              </option>
            ))}
          </select>
          {activeBackend && !activeBackend.available && !cfg?.stub && (
            <div className="mt-1 text-[11px] text-amber-300/80">
              binary not found at <span className="font-mono">{activeBackend.path}</span> — the LLM won't start with this backend
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
          <div className="mt-1 text-[11px] text-white/35">quantizes the context to fit a longer window in the same VRAM</div>
          {cfg?.context_types.find((ct) => ct.id === cfg.context_type)?.experimental && (
            <div className="mt-1 text-[11px] text-amber-300/80">TurboQuant types require the TurboQuant backend's patched llama.cpp build</div>
          )}
          {cfg && cfg.context_type !== "f16" && cfg.loaded && (
            <div className="mt-1 text-[11px] text-amber-300/80">applying reloads the running model</div>
          )}
        </div>

        <label>
          <div className={label}>Temperature · {temperature.toFixed(2)}</div>
          <input type="range" min={0} max={2} step={0.05} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} className="mt-2 w-full accent-emerald-500" />
        </label>

        <label>
          <div className={label}>Max tokens</div>
          <input type="number" min={1} max={8192} step={64} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} className={`${numField} mt-1`} />
        </label>

        {/* advanced sampling */}
        <div>
          <button onClick={() => setShowAdvanced((v) => !v)} className="flex w-full items-center justify-between text-xs uppercase tracking-wide text-white/40 hover:text-white/70">
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
                <input value={stop} onChange={(e) => setStop(e.target.value)} placeholder="empty = none" className={`${numField} mt-1`} />
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
                options={[{ value: "", label: "— none —" }, ...personas.map((p) => ({ value: p.id, label: p.name }))]}
              />
            )}
            <button onClick={() => void deletePersona()} disabled={!personaId}
              className="rounded-md border border-red-400/25 px-2 py-1 text-xs text-red-300 hover:bg-red-400/10 disabled:opacity-30">
              Del
            </button>
          </div>
          <div className="mt-1 grid grid-cols-[1fr_auto] gap-2">
            <input value={personaName} onChange={(e) => setPersonaName(e.target.value)} placeholder="save current as…" className={numField} />
            <button onClick={() => void savePersona()} disabled={!personaName.trim()}
              className="rounded-md border border-white/15 px-2.5 py-1 text-xs hover:bg-white/10 disabled:opacity-30">
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
    </div>
  );
}

function parseImageCommand(value: string): { prompt: string; negative?: string } {
  const match = value.match(/\s--(?:negative|neg)(?:\s+|=)([\s\S]*)$/i);
  if (!match || match.index == null) return { prompt: value.trim() };
  return {
    prompt: value.slice(0, match.index).trim(),
    negative: match[1].trim() || undefined,
  };
}

function imagePromptDraft(input: string): string {
  const match = input.match(/^\/(?:image|img)\s+([\s\S]+)/i);
  return match ? parseImageCommand(match[1].trim()).prompt : "";
}

function NumOpt({ label: l, v, set, step }: { label: string; v: NumOrEmpty; set: (n: NumOrEmpty) => void; step: number }) {
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
