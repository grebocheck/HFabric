import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../api/client";
import { useEvents } from "../api/useEvents";
import type { BusEvent, ChatConversation, ChatMessage } from "../types";

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
