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
import type { ChatAttachment, ChatConversation, ChatMessage, ChatSendBody, Model } from "../types";
import { pickImageModel } from "./chatHelpers";
import { toast } from "./Toast";

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

function setLastAssistant(msgs: ChatMessage[], content: string, error = false): ChatMessage[] {
  const out = [...msgs];
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === "assistant") { out[i] = { ...out[i], content, error }; return out; }
  }
  return out;
}

function parseImageCommand(value: string): { prompt: string; negative?: string } {
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
  beginStream: () => number;
  isCurrentStream: (revision: number) => boolean;
  reconcile: () => Promise<void>;
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
  setActiveJob: (jobId: string | null, messageId?: string) => void;
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
}: ChatActionArgs) {
  const sending = useRef(false);
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
    const streamRevision = beginStream();
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
      setConvs((p) => [res.conversation, ...p.filter((c) => c.id !== res.conversation.id)]);
      if (!isCurrentStream(streamRevision)) return;
      setActiveJob(res.job_id, res.assistant_message.id);
      setMessages((p) => p.map((m) =>
        m.id === "tmp-u" ? res.user_message : m.id === "tmp-a" ? { ...res.assistant_message, content: "" } : m,
      ));
      void reconcile().catch((error: unknown) => console.warn("Could not synchronize submitted chat", error));
    } catch (err) {
      if (!isCurrentStream(streamRevision)) return;
      setActiveJob(null);
      setBusy(false);
      setMessages((p) => setLastAssistant(p, `⚠ ${err instanceof Error ? err.message : "request failed"}`, true));
    }
  }, [
    beginStream,
    documentTool,
    imageTool,
    isCurrentStream,
    llmModels,
    modelId,
    models,
    ragTopK,
    reconcile,
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
    const streamRevision = beginStream();
    setMessages((p) => [...p, { id: "tmp-u", role: "user", content: `/image ${prompt}` },
      { id: "tmp-a", role: "assistant", content: "" }]);
    try {
      const res = await api.sendChatImage(convId, { prompt, model_id: img.id, negative });
      setConvs((p) => [res.conversation, ...p.filter((c) => c.id !== res.conversation.id)]);
      if (!isCurrentStream(streamRevision)) return;
      setActiveJob(res.job_id, res.assistant_message.id);
      setMessages((p) => p.map((m) =>
        m.id === "tmp-u" ? res.user_message : m.id === "tmp-a" ? { ...res.assistant_message, content: "" } : m,
      ));
      void reconcile().catch((error: unknown) => console.warn("Could not synchronize submitted image", error));
    } catch (err) {
      if (!isCurrentStream(streamRevision)) return;
      setActiveJob(null);
      setBusy(false);
      setMessages((p) => setLastAssistant(p, `⚠ ${err instanceof Error ? err.message : "request failed"}`, true));
    }
  }, [beginStream, isCurrentStream, models, reconcile, setActiveJob, setBusy, setConvs, setMessages, stickToBottom]);

  const send = useCallback(async () => {
    const content = input.trim();
    const outgoingAttachments = attachments;
    if ((!content && outgoingAttachments.length === 0) || busy || attachmentsUploading || sending.current) return;
    sending.current = true;
    let creatingRevision: number | undefined;
    try {
      let cid = activeId;
      if (!cid) {
        const revision = creatingRevision = beginStream();
        const c = await api.createConversation({ model_id: modelId || llmModels[0]?.id });
        setConvs((p) => [c, ...p]);
        if (!isCurrentStream(revision)) return;
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
    } catch (error) {
      if (creatingRevision !== undefined && !isCurrentStream(creatingRevision)) return;
      setBusy(false);
      toast.error(error instanceof Error ? error.message : "Could not create conversation");
    } finally {
      sending.current = false;
    }
  }, [
    activeId,
    attachments,
    attachmentsUploading,
    beginStream,
    busy,
    input,
    isCurrentStream,
    llmModels,
    modelId,
    rememberPrompt,
    setActiveId,
    setAttachmentNote,
    setAttachments,
    setBusy,
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
    try {
      await api.stopLlm();
      if (activeJob.current) await api.cancelJob(activeJob.current);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not stop generation");
    }
  }, [activeJob]);

  const regenerate = useCallback(async () => {
    if (busy || !activeId) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || lastUser.id.startsWith("tmp")) return;
    try {
      await api.truncateFrom(activeId, lastUser.id);
      const idx = messages.findIndex((m) => m.id === lastUser.id);
      setMessages((p) => p.slice(0, idx));
      await submit(lastUser.content, activeId, lastUser.attachments ?? []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not regenerate response");
    }
  }, [activeId, busy, messages, setMessages, submit]);

  const startEdit = useCallback((message: ChatMessage) => {
    setEditingId(message.id);
    setEditText(message.content);
  }, [setEditText, setEditingId]);

  const saveEdit = useCallback(async () => {
    if (!activeId || !editingId) return;
    const content = editText.trim();
    const idx = messages.findIndex((m) => m.id === editingId);
    if (!content || idx < 0) return;
    const editedAttachments = messages[idx]?.attachments ?? [];
    try {
      await api.truncateFrom(activeId, editingId);
      setEditingId(null);
      setMessages((p) => p.slice(0, idx));
      await submit(content, activeId, editedAttachments);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not edit message");
    }
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
