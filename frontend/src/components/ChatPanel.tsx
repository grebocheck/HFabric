import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChatMessage, LlmConfig, Model } from "../types";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-emerald-500";
const label = "text-xs uppercase tracking-wide text-white/40";

type ChatSettings = {
  model_id: string;
  system: string;
  temperature: number;
  max_tokens: number;
};

const SETTINGS_KEY = "imgfab.chat.settings";

function loadSettings(): Partial<ChatSettings> {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function ChatPanel({
  models,
  messages,
  busy,
  onSend,
  onClear,
}: {
  models: Model[];
  messages: ChatMessage[];
  busy: boolean;
  onSend: (content: string, opts: { model_id: string; system?: string; temperature: number; max_tokens: number }) => void;
  onClear: () => void;
}) {
  const llmModels = models.filter((m) => m.job_type === "llm");
  const saved = loadSettings();

  const [modelId, setModelId] = useState(saved.model_id ?? "");
  const [system, setSystem] = useState(saved.system ?? "");
  const [temperature, setTemperature] = useState(saved.temperature ?? 0.8);
  const [maxTokens, setMaxTokens] = useState(saved.max_tokens ?? 512);
  const [input, setInput] = useState("");

  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [ctxDraft, setCtxDraft] = useState<number | null>(null);
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgNote, setCfgNote] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!modelId && llmModels[0]) setModelId(llmModels[0].id);
  }, [llmModels, modelId]);

  useEffect(() => {
    api.getLlmConfig().then((c) => {
      setCfg(c);
      setCtxDraft((prev) => prev ?? c.ctx);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ model_id: modelId, system, temperature, max_tokens: maxTokens }),
    );
  }, [modelId, system, temperature, maxTokens]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = () => {
    const content = input.trim();
    if (!content || !modelId || busy) return;
    onSend(content, { model_id: modelId, system: system.trim() || undefined, temperature, max_tokens: maxTokens });
    setInput("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const applyCtx = async () => {
    if (ctxDraft == null) return;
    setCfgBusy(true);
    setCfgNote("");
    try {
      const next = await api.setLlmConfig({ ctx: ctxDraft });
      setCfg(next);
      setCtxDraft(next.ctx);
      setCfgNote(next.reloaded ? "applied — model reloaded" : next.changed ? "applied (next load)" : "no change");
    } catch (err) {
      setCfgNote(err instanceof Error ? err.message : "could not update");
    } finally {
      setCfgBusy(false);
    }
  };

  return (
    <div className="flex h-full gap-4">
      {/* --- conversation --- */}
      <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-white/10">
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-center text-sm text-white/30">
              Chat with the local model. Ask it to write image prompts, brainstorm, or anything else,
              then copy what you need.
            </div>
          ) : (
            messages.map((m, i) => <Bubble key={i} msg={m} />)
          )}
          {busy && messages[messages.length - 1]?.role !== "assistant" && (
            <div className="text-xs text-white/40">thinking…</div>
          )}
        </div>

        <div className="border-t border-white/10 p-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            placeholder={modelId ? "Message the model…  (Enter to send, Shift+Enter for newline)" : "no LLM model available"}
            disabled={!modelId}
            className={`${field} resize-none`}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-white/35">
              {busy ? "generating…" : `${messages.length} message${messages.length === 1 ? "" : "s"}`}
            </span>
            <button
              onClick={send}
              disabled={!input.trim() || !modelId || busy}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      </div>

      {/* --- settings --- */}
      <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto rounded-lg border border-white/10 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white/75">Model settings</h2>
          <button
            onClick={onClear}
            disabled={!messages.length}
            className="text-xs text-white/40 hover:text-white/80 disabled:opacity-30"
          >
            new chat
          </button>
        </div>

        <label>
          <div className={label}>Model</div>
          <select value={modelId} onChange={(e) => setModelId(e.target.value)} className={`${field} mt-1`}>
            {llmModels.length === 0 && <option value="">no LLM models</option>}
            {llmModels.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </label>

        <div>
          <div className={label}>Context window (tokens)</div>
          <div className="mt-1 flex gap-2">
            <input
              type="number"
              min={512}
              step={512}
              value={ctxDraft ?? ""}
              onChange={(e) => setCtxDraft(Number(e.target.value))}
              className={field}
            />
            <button
              onClick={applyCtx}
              disabled={cfgBusy || ctxDraft == null || ctxDraft === cfg?.ctx}
              className="shrink-0 rounded-md border border-white/15 px-2.5 py-1 text-xs hover:bg-white/10 disabled:opacity-30"
            >
              {cfgBusy ? "…" : "Apply"}
            </button>
          </div>
          <div className="mt-1 text-[11px] text-white/35">
            current {cfg?.ctx ?? "?"} · ngl {cfg?.ngl ?? "?"} · {cfg?.loaded ? "loaded" : "not loaded"}
          </div>
          {cfgNote && <div className="mt-1 text-[11px] text-emerald-300/80">{cfgNote}</div>}
          {ctxDraft != null && cfg && ctxDraft !== cfg.ctx && cfg.loaded && (
            <div className="mt-1 text-[11px] text-amber-300/80">applying reloads the running model</div>
          )}
        </div>

        <label>
          <div className={label}>Temperature · {temperature.toFixed(2)}</div>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            className="mt-2 w-full accent-emerald-500"
          />
        </label>

        <label>
          <div className={label}>Max tokens</div>
          <input
            type="number"
            min={1}
            max={8192}
            step={64}
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
            className={`${field} mt-1`}
          />
        </label>

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

function Bubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
          isUser
            ? "bg-violet-600/30 text-white"
            : msg.error
              ? "border border-red-400/30 bg-red-400/10 text-red-200"
              : "border border-white/10 bg-white/[0.04] text-white/90"
        }`}
      >
        {msg.content || (isUser ? "" : <span className="text-white/30">…</span>)}
      </div>
    </div>
  );
}
