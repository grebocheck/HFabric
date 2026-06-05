import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Select } from "./Select";
import { Toggle } from "./Toggle";
import { InfoRows, Panel, SectionTitle, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import type { TtsGenerateResult, TtsStatus } from "../types";

function size(bytes: number): string {
  if (!bytes) return "0 B";
  const gb = bytes / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

export function TtsPanel() {
  const [status, setStatus] = useState<TtsStatus | null>(null);
  const [text, setText] = useState("Hello from HFabric.");
  const [modelId, setModelId] = useState("");
  const [vocoderId, setVocoderId] = useState("");
  const [useGuideTokens, setUseGuideTokens] = useState(false);
  const [result, setResult] = useState<TtsGenerateResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.ttsStatus().then((s) => {
      setStatus(s);
      setModelId((prev) => prev || s.models[0]?.id || "");
    }).catch(() => {});
  }, []);

  const models = status?.models ?? [];
  const ready = Boolean(status?.ready && modelId);
  const canGenerate = ready && Boolean(text.trim()) && !loading;

  async function onGenerate() {
    if (!canGenerate) return;
    setLoading(true);
    setError("");
    try {
      const next = await api.generateTts({
        model_id: modelId,
        text: text.trim(),
        vocoder_id: vocoderId || null,
        use_guide_tokens: useGuideTokens,
      });
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-hidden">
      <WorkspaceHeader
        title="Text to speech"
        subtitle="Generate local WAV narration from the installed llama-tts models."
      >
        <StatusPill label={status?.binary_exists ? "binary found" : "binary missing"} tone={status?.binary_exists ? "good" : "warn"} />
        <StatusPill label={`${models.length} models`} tone={models.length ? "info" : "neutral"} />
        <StatusPill label={ready ? "ready" : "waiting"} tone={ready ? "good" : "neutral"} />
      </WorkspaceHeader>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,340px)_minmax(0,1fr)] gap-3">
        <Panel className="flex min-h-0 flex-col overflow-hidden">
          <SectionTitle title="Voice model" subtitle={status?.binary_exists ? "llama-tts executable available" : "waiting for binary"} />
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">

        <InfoRows
          rows={[
            { label: "Binary", value: status?.binary ?? "...", mono: true, tone: status?.binary_exists ? "good" : "warn" },
            { label: "Models", value: status?.models_dir ?? "...", mono: true },
            { label: "Ready", value: ready ? "yes" : "waiting for model", tone: ready ? "good" : "neutral" },
          ]}
        />

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Model</div>
          <Select
            value={modelId}
            onChange={setModelId}
            placeholder="no TTS models"
            className="mt-1"
            options={models.map((m) => ({ value: m.id, label: m.name, hint: size(m.size_bytes) }))}
          />
        </label>

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Vocoder</div>
          <Select
            value={vocoderId}
            onChange={setVocoderId}
            placeholder="none"
            className="mt-1"
            options={[{ value: "", label: "none" }, ...models.map((m) => ({ value: m.id, label: m.name }))]}
          />
        </label>

        <label className="flex items-center justify-between gap-3 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs text-white/55">
          <span>
            <span className="block text-sm font-medium text-white/70">Guide tokens</span>
            <span className="block text-xs text-white/35">Use model guidance markers when available</span>
          </span>
          <Toggle checked={useGuideTokens} onChange={setUseGuideTokens} />
        </label>
          </div>
      </Panel>

      <Panel className="flex min-w-0 flex-col overflow-hidden">
        <SectionTitle title="Scratch text" subtitle={`${text.trim().length} chars`} />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-0 flex-1 resize-none bg-transparent p-4 text-sm leading-6 text-white/80 outline-none placeholder:text-white/25"
        />
        {result && (
          <div className="border-t border-white/10 p-3">
            <div className="mb-2 flex items-center justify-between text-xs text-white/45">
              <span>{result.duration_seconds.toFixed(1)}s</span>
              <a href={result.url} download className="text-emerald-300 hover:text-emerald-200">
                Download WAV
              </a>
            </div>
            <audio controls src={result.url} className="w-full" />
          </div>
        )}
        <div className="flex items-center justify-between border-t border-white/10 p-3">
          <span
            className={`min-w-0 truncate text-xs ${error ? "text-red-300" : "text-white/35"}`}
            title={error || undefined}
          >
            {error || (ready ? "ready" : "waiting for local model")}
          </span>
          <button
            onClick={onGenerate}
            disabled={!canGenerate}
            className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-30 disabled:hover:bg-emerald-600"
            title={ready ? "Generate WAV" : "Waiting for local TTS model"}
          >
            {loading ? "Generating..." : "Generate"}
          </button>
        </div>
      </Panel>
      </div>
    </div>
  );
}
