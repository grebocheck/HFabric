import {
  useCallback,
  useRef,
  useState,
  type ClipboardEvent,
  type Dispatch,
  type MutableRefObject,
  type RefObject,
  type SetStateAction,
} from "react";
import { api } from "../api/client";
import { useEvents } from "../api/useEvents";
import type { BusEvent, ChatAttachment, ChatConversation, ChatMessage, ChatSendBody, Model } from "../types";
import { pickImageModel } from "./chatHelpers";

export type ChatStats = { tokens: number; tps: number; ttft: number };

export function useConversation() {
  const [convs, setConvs] = useState<ChatConversation[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);

  const refreshConvs = useCallback(async () => {
    setConvsLoading(true);
    try {
      setConvs(await api.listConversations());
    } catch {
      // Keep stale conversations visible if refresh fails.
    } finally {
      setConvsLoading(false);
    }
  }, []);

  return { convs, setConvs, convsLoading, refreshConvs };
}

export function useChatStream({
  refreshConvs,
  setBusy,
  setMessages,
}: {
  refreshConvs: () => Promise<void>;
  setBusy: (busy: boolean) => void;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
}) {
  const activeJob = useRef<string | null>(null);
  const sendStart = useRef(0);
  const firstAt = useRef<number | null>(null);
  const tokCount = useRef(0);
  const [stats, setStats] = useState<ChatStats | null>(null);

  const beginStream = useCallback(() => {
    setBusy(true);
    setStats(null);
    sendStart.current = Date.now();
    firstAt.current = null;
    tokCount.current = 0;
  }, [setBusy]);

  const setActiveJob = useCallback((jobId: string | null) => {
    activeJob.current = jobId;
  }, []);

  const trackJump = useCallback((jobId: string | null | undefined) => {
    activeJob.current = jobId ?? null;
    if (!jobId) return;
    setBusy(true);
    setStats(null);
    sendStart.current = Date.now();
    firstAt.current = null;
    tokCount.current = 0;
  }, [setBusy]);

  const onChatEvent = useCallback((e: BusEvent) => {
    if (e.job_id !== activeJob.current) return;
    if (e.type === "llm.token") {
      if (firstAt.current === null) firstAt.current = Date.now();
      tokCount.current += 1;
      setMessages((p) => appendToLastAssistant(p, e.token as string));
    } else if (e.type === "job.done") {
      const childJob = typeof e.tool_child_job_id === "string" ? e.tool_child_job_id : null;
      if (childJob) {
        activeJob.current = childJob;
        setBusy(true);
        if (typeof e.text === "string") setMessages((p) => setLastAssistant(p, e.text as string));
        return;
      }
      activeJob.current = null;
      setBusy(false);
      if (typeof e.text === "string") setMessages((p) => setLastAssistant(p, e.text as string));
      if (firstAt.current && tokCount.current > 0) {
        const secs = Math.max(0.001, (Date.now() - firstAt.current) / 1000);
        setStats({ tokens: tokCount.current, tps: tokCount.current / secs, ttft: firstAt.current - sendStart.current });
      }
      void refreshConvs();
    } else if (e.type === "job.error") {
      activeJob.current = null;
      setBusy(false);
      setMessages((p) => setLastAssistant(p, `\u26a0 ${(e.error as string) ?? "generation failed"}`, true));
    } else if (e.type === "job.progress") {
      const pct = Math.round(((e.progress as number) ?? 0) * 100);
      setMessages((p) => setLastAssistant(p, `*generating image\u2026 ${pct}%*`));
    } else if (e.type === "job.cancelled") {
      activeJob.current = null;
      setBusy(false);
    }
  }, [refreshConvs, setBusy, setMessages]);

  useEvents(onChatEvent);

  return { activeJob, beginStream, setActiveJob, setStats, stats, trackJump };
}

export function appendToLastAssistant(msgs: ChatMessage[], token: string): ChatMessage[] {
  const out = [...msgs];
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === "assistant") { out[i] = { ...out[i], content: out[i].content + token }; return out; }
  }
  return out;
}

export function setLastAssistant(msgs: ChatMessage[], content: string, error = false): ChatMessage[] {
  const out = [...msgs];
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === "assistant") { out[i] = { ...out[i], content, error }; return out; }
  }
  return out;
}

export function parseImageCommand(value: string): { prompt: string; negative?: string } {
  const match = value.match(/\s--(?:negative|neg)(?:\s+|=)([\s\S]*)$/i);
  if (!match || match.index == null) return { prompt: value.trim() };
  return {
    prompt: value.slice(0, match.index).trim(),
    negative: match[1].trim() || undefined,
  };
}

export function imagePromptDraft(input: string): string {
  const match = input.match(/^\/(?:image|img)\s+([\s\S]+)/i);
  return match ? parseImageCommand(match[1].trim()).prompt : "";
}

type ChatActionArgs = {
  activeId: string | null;
  activeJob: MutableRefObject<string | null>;
  attachments: ChatAttachment[];
  attachmentsUploading: boolean;
  beginStream: () => void;
  busy: boolean;
  documentTool: boolean;
  editingId: string | null;
  editText: string;
  imageTool: boolean;
  input: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  llmModels: Model[];
  messages: ChatMessage[];
  modelId: string;
  models: Model[];
  ragTopK: number;
  rememberPrompt: (content: string) => void;
  sampling: () => Omit<ChatSendBody, "content" | "model_id">;
  setActiveId: (id: string | null) => void;
  setActiveJob: (jobId: string | null) => void;
  setAttachmentNote: (note: string) => void;
  setAttachments: Dispatch<SetStateAction<ChatAttachment[]>>;
  setAttachmentsUploading: (uploading: boolean) => void;
  setBusy: (busy: boolean) => void;
  setConvs: Dispatch<SetStateAction<ChatConversation[]>>;
  setEditText: (value: string) => void;
  setEditingId: (id: string | null) => void;
  setInput: (value: string) => void;
  setLibraryOpen: (open: boolean) => void;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  stickToBottom: MutableRefObject<boolean>;
};

export function useChatActions({
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
}: ChatActionArgs) {
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
  }, [setAttachmentNote, setAttachments, setAttachmentsUploading]);

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
  }, [
    beginStream,
    documentTool,
    imageTool,
    llmModels,
    modelId,
    models,
    ragTopK,
    sampling,
    setActiveJob,
    setBusy,
    setConvs,
    setMessages,
    stickToBottom,
  ]);

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
  }, [beginStream, models, setActiveJob, setBusy, setConvs, setMessages, stickToBottom]);

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
    } else {
      await submit(content, cid, outgoingAttachments);
    }
  }, [
    activeId,
    attachments,
    attachmentsUploading,
    busy,
    input,
    llmModels,
    modelId,
    rememberPrompt,
    setActiveId,
    setAttachmentNote,
    setAttachments,
    setConvs,
    setInput,
    submit,
    submitImage,
  ]);

  const applyImagePromptSnippet = useCallback((body: string, negative?: string | null) => {
    const prompt = body.trim();
    if (!prompt) return;
    const neg = negative?.trim();
    setInput(`/image ${prompt}${neg ? ` --negative ${neg}` : ""}`);
    setLibraryOpen(false);
    inputRef.current?.focus();
  }, [inputRef, setInput, setLibraryOpen]);

  const stop = useCallback(async () => {
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
  }, [activeId, busy, messages, setMessages, submit]);

  const startEdit = useCallback((message: ChatMessage) => {
    setEditingId(message.id);
    setEditText(message.content);
  }, [setEditText, setEditingId]);

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
  }, [activeId, editText, editingId, messages, setEditingId, setMessages, submit]);

  const onPaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = event.clipboardData?.files;
    if (files?.length) void uploadAttachments(files);
  }, [uploadAttachments]);

  return {
    applyImagePromptSnippet,
    onPaste,
    regenerate,
    saveEdit,
    send,
    startEdit,
    stop,
    uploadAttachments,
  };
}
