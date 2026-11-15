import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { api, ApiError } from "../api/client";
import { useBusEvents } from "../api/useEvents";
import type { BusEvent, ChatMessage } from "../types";

export type ChatStats = { tokens: number; tps: number; ttft: number };

export function useChatStream({ activeConversation, refreshConvs, setBusy, setMessages }: {
  activeConversation: MutableRefObject<string | null>;
  refreshConvs: () => Promise<void>;
  setBusy: (busy: boolean) => void;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
}) {
  const activeJob = useRef<string | null>(null);
  const assistantId = useRef<string | null>(null);
  const revision = useRef(0);
  const eventRevision = useRef(0);
  const awaitingJob = useRef(false);
  const sendStart = useRef(0);
  const firstAt = useRef<number | null>(null);
  const tokCount = useRef(0);
  const [stats, setStats] = useState<ChatStats | null>(null);

  const resetStream = useCallback(() => {
    revision.current += 1;
    activeJob.current = null;
    assistantId.current = null;
    awaitingJob.current = false;
    firstAt.current = null;
    tokCount.current = 0;
    sendStart.current = Date.now();
    setBusy(false);
    setStats(null);
  }, [setBusy]);

  const beginStream = useCallback(() => {
    revision.current += 1;
    awaitingJob.current = true;
    activeJob.current = null;
    assistantId.current = null;
    setBusy(true);
    setStats(null);
    sendStart.current = Date.now();
    firstAt.current = null;
    tokCount.current = 0;
    return revision.current;
  }, [setBusy]);
  const isCurrentStream = useCallback((value: number) => revision.current === value, []);

  const setActiveJob = useCallback((id: string | null, messageId?: string) => {
    activeJob.current = id;
    assistantId.current = messageId ?? null;
    awaitingJob.current = false;
  }, []);

  const restoreStream = useCallback((messages: ChatMessage[], jobHint?: string) => {
    const assistants = [...messages].reverse().filter((message) => message.role === "assistant");
    const pending = assistants.find((message) => message.job_id === jobHint && jobHint)
      ?? assistants.find((message) => message.job_id)
      ?? (jobHint ? assistants[0] : undefined);
    activeJob.current = jobHint ?? pending?.job_id ?? null;
    assistantId.current = pending?.id ?? null;
    setBusy(Boolean(activeJob.current));
  }, [setBusy]);

  const reconcile = useCallback(async () => {
    const conversationId = activeConversation.current;
    if (!conversationId || awaitingJob.current) return;
    const currentRevision = revision.current;
    const currentEvent = eventRevision.current;
    let jobId = activeJob.current;
    let running = false;
    // A tool call may have completed while disconnected and queued a child.
    for (let depth = 0; jobId && depth < 16; depth += 1) {
      let job;
      try {
        job = await api.getJob(jobId);
      } catch (error) {
        // Finished queue rows can be cleared while their durable chat remains.
        if (error instanceof ApiError && error.status === 404) {
          jobId = null;
          break;
        }
        throw error;
      }
      const child = job.result?.child_job_id;
      if (job.status === "done" && typeof child === "string" && child !== jobId) {
        jobId = child;
      } else {
        running = job.status === "queued" || job.status === "running";
        break;
      }
    }
    const detail = await api.getConversation(conversationId);
    if (activeConversation.current !== conversationId || revision.current !== currentRevision || eventRevision.current !== currentEvent) return;
    setMessages((previous) => detail.messages.map((message) => {
      const partial = previous.find((item) => item.id === message.id);
      return running && message.id === assistantId.current && !message.content && partial
        ? { ...message, content: partial.content }
        : message;
    }));
    if (jobId) {
      activeJob.current = running ? jobId : null;
      setBusy(running);
    } else {
      restoreStream(detail.messages);
    }
    await refreshConvs();
  }, [activeConversation, refreshConvs, restoreStream, setBusy, setMessages]);

  const updateAssistant = useCallback((content: string, append = false, error = false) => {
    const id = assistantId.current;
    if (!id) return;
    setMessages((messages) => messages.map((message) => message.id === id
      ? { ...message, content: append ? message.content + content : content, error }
      : message));
  }, [setMessages]);

  const onChatEvent = useCallback((event: BusEvent) => {
    if (!activeJob.current || event.job_id !== activeJob.current) return;
    eventRevision.current += 1;
    if (event.type === "llm.token") {
      if (firstAt.current === null) firstAt.current = Date.now();
      tokCount.current += 1;
      updateAssistant(String(event.token ?? ""), true);
    } else if (event.type === "job.progress") {
      updateAssistant(`*generating image… ${Math.round(Number(event.progress ?? 0) * 100)}%*`);
    } else if (event.type === "job.done") {
      if (typeof event.text === "string") updateAssistant(event.text);
      const child = typeof event.tool_child_job_id === "string" ? event.tool_child_job_id : null;
      activeJob.current = child;
      setBusy(Boolean(child));
      if (!child) {
        if (firstAt.current && tokCount.current) {
          const seconds = Math.max(0.001, (Date.now() - firstAt.current) / 1000);
          setStats({ tokens: tokCount.current, tps: tokCount.current / seconds, ttft: firstAt.current - sendStart.current });
        }
        void refreshConvs();
      }
    } else if (event.type === "job.error" || event.type === "job.cancelled") {
      activeJob.current = null;
      setBusy(false);
      updateAssistant(event.type === "job.error" ? `⚠ ${String(event.error ?? "generation failed")}` : "_(cancelled)_", false, event.type === "job.error");
    }
  }, [refreshConvs, setBusy, updateAssistant]);
  useBusEvents(onChatEvent, reconcile);

  return { activeJob, beginStream, isCurrentStream, reconcile, resetStream, restoreStream, setActiveJob, stats };
}
