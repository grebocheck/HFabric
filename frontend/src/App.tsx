import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { useEvents } from "./api/useEvents";
import { ChatPanel } from "./components/ChatPanel";
import { ImageComposer } from "./components/ImageComposer";
import { Gallery } from "./components/Gallery";
import { ModelStatus, type View } from "./components/ModelStatus";
import { QueuePanel } from "./components/QueuePanel";
import { SettingsPanel } from "./components/SettingsPanel";
import type { BusEvent, ChatMessage, GpuStatus, ImageItem, Job, Lora, Model, Preset } from "./types";

export default function App() {
  const [models, setModels] = useState<Model[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loras, setLoras] = useState<Lora[]>([]);
  const [gpu, setGpu] = useState<GpuStatus>({ resident: null, model_id: null, model: null, family: null, warm: [] });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [view, setView] = useState<View>("images");

  // image-tab prompt (manual; the chat tab is independent)
  const [promptDraft, setPromptDraft] = useState("");

  // chat tab state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const messagesRef = useRef<ChatMessage[]>(messages);
  messagesRef.current = messages;
  const chatJobId = useRef<string | null>(null);

  const refreshJobs = useCallback(() => api.listJobs().then(setJobs).catch(() => {}), []);
  const refreshImages = useCallback((q?: string) => api.listImages(q).then(setImages).catch(() => {}), []);
  const refreshPresets = useCallback(() => api.listPresets().then(setPresets).catch(() => {}), []);

  useEffect(() => {
    api.listModels().then(setModels).catch(() => {});
    api.listLoras().then(setLoras).catch(() => {});
    refreshJobs();
    refreshImages();
    refreshPresets();
  }, [refreshJobs, refreshImages, refreshPresets]);

  const onEvent = useCallback(
    (e: BusEvent) => {
      switch (e.type) {
        case "gpu.status":
          setGpu({
            resident: (e.resident as string) ?? null,
            model_id: (e.model_id as string) ?? null,
            model: (e.model as string) ?? null,
            family: (e.family as string) ?? null,
            warm: Array.isArray(e.warm) ? (e.warm as GpuStatus["warm"]) : [],
          });
          break;
        case "job.progress":
          setJobs((prev) =>
            prev.map((j) => (
              j.id === e.job_id
                ? {
                    ...j,
                    progress: e.progress as number,
                    progress_note: typeof e.note === "string" ? e.note : j.progress_note,
                  }
                : j
            )),
          );
          break;
        case "llm.token":
          if (e.job_id === chatJobId.current) {
            setMessages((prev) => appendToLastAssistant(prev, e.token as string));
          }
          break;
        case "job.done":
          if (e.job_id === chatJobId.current) {
            chatJobId.current = null;
            setChatBusy(false);
            // job.done carries the full text — authoritative, so it fixes any
            // tokens that were missed before streaming started.
            if (typeof e.text === "string") setMessages((prev) => setLastAssistant(prev, e.text as string));
          }
          refreshJobs();
          if (e.job_type === "image") refreshImages();
          break;
        case "job.error":
          if (e.job_id === chatJobId.current) {
            chatJobId.current = null;
            setChatBusy(false);
            setMessages((prev) => setLastAssistant(prev, `⚠ ${(e.error as string) ?? "generation failed"}`, true));
          }
          refreshJobs();
          break;
        case "job.created":
        case "job.started":
        case "job.cancelled":
          refreshJobs();
          break;
        case "image.ready":
          refreshImages();
          break;
      }
    },
    [refreshJobs, refreshImages],
  );

  const { connected } = useEvents(onEvent);

  const sendChat = useCallback(
    async (content: string, opts: { model_id: string; system?: string; temperature: number; max_tokens: number }) => {
      const history: ChatMessage[] = [...messagesRef.current, { role: "user", content }];
      setMessages([...history, { role: "assistant", content: "" }]);
      setChatBusy(true);
      try {
        const job = await api.chat({
          model_id: opts.model_id,
          messages: history,
          system: opts.system,
          temperature: opts.temperature,
          max_tokens: opts.max_tokens,
        });
        chatJobId.current = job.id;
      } catch (err) {
        chatJobId.current = null;
        setChatBusy(false);
        setMessages((prev) => setLastAssistant(prev, `⚠ ${err instanceof Error ? err.message : "request failed"}`, true));
      }
    },
    [],
  );

  const clearChat = useCallback(() => {
    chatJobId.current = null;
    setChatBusy(false);
    setMessages([]);
  }, []);

  const onFree = useCallback(() => api.freeGpu().catch(() => {}), []);

  const imageJobs = jobs.filter((j) => j.type === "image");

  return (
    <div className="flex h-screen flex-col">
      <ModelStatus
        gpu={gpu}
        connected={connected}
        view={view}
        onView={setView}
        onFree={onFree}
        onSettings={() => setSettingsOpen(true)}
      />

      {view === "images" ? (
        <main className="grid flex-1 grid-cols-[380px_320px_1fr] gap-4 overflow-hidden p-4">
          <div className="overflow-y-auto">
            <ImageComposer
              models={models}
              loras={loras}
              presets={presets}
              onPresetsChanged={refreshPresets}
              promptDraft={promptDraft}
              setPromptDraft={setPromptDraft}
            />
          </div>
          <QueuePanel jobs={imageJobs} onChanged={refreshJobs} />
          <Gallery images={images} onSearch={refreshImages} />
        </main>
      ) : (
        <main className="flex-1 overflow-hidden p-4">
          <ChatPanel
            models={models}
            messages={messages}
            busy={chatBusy}
            onSend={sendChat}
            onClear={clearChat}
          />
        </main>
      )}

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

function appendToLastAssistant(msgs: ChatMessage[], token: string): ChatMessage[] {
  const out = [...msgs];
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === "assistant") {
      out[i] = { ...out[i], content: out[i].content + token };
      return out;
    }
  }
  return [...out, { role: "assistant", content: token }];
}

function setLastAssistant(msgs: ChatMessage[], content: string, error = false): ChatMessage[] {
  const out = [...msgs];
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === "assistant") {
      out[i] = { ...out[i], content, error };
      return out;
    }
  }
  return [...out, { role: "assistant", content, error }];
}
