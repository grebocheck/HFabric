import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TtsStatus } from "../types";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-emerald-500";

function size(bytes: number): string {
  if (!bytes) return "0 B";
  const gb = bytes / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

export function TtsPanel() {
  const [status, setStatus] = useState<TtsStatus | null>(null);
  const [text, setText] = useState("Hello from ImageFabric.");
  const [modelId, setModelId] = useState("");

  useEffect(() => {
    api.ttsStatus().then((s) => {
      setStatus(s);
      setModelId((prev) => prev || s.models[0]?.id || "");
    }).catch(() => {});
  }, []);

  const models = status?.models ?? [];
  const ready = Boolean(status?.ready && modelId);

  return (
    <div className="flex h-full gap-3">
      <aside className="flex w-80 shrink-0 flex-col gap-3 rounded-lg border border-white/10 p-4">
        <div>
          <h2 className="text-sm font-semibold text-white/75">TTS</h2>
          <div className="mt-1 text-xs text-white/35">
            {status?.binary_exists ? "llama-tts found" : "llama-tts missing"}
          </div>
        </div>

        <div className="space-y-1.5 rounded-md border border-white/10 bg-black/20 p-3 text-xs">
          <Row label="Binary" value={status?.binary ?? "..."} mono />
          <Row label="Models" value={status?.models_dir ?? "..."} mono />
          <Row label="Ready" value={ready ? "yes" : "waiting for model"} />
        </div>

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Model</div>
          <select value={modelId} onChange={(e) => setModelId(e.target.value)} className={`${field} mt-1`}>
            {models.length === 0 && <option value="">no TTS models</option>}
            {models.map((m) => <option key={m.id} value={m.id}>{m.name} ({size(m.size_bytes)})</option>)}
          </select>
        </label>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col rounded-lg border border-white/10">
        <div className="border-b border-white/10 px-4 py-3">
          <div className="text-sm font-semibold text-white/75">Scratch text</div>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-0 flex-1 resize-none bg-transparent p-4 text-sm leading-6 text-white/80 outline-none placeholder:text-white/25"
        />
        <div className="flex items-center justify-between border-t border-white/10 p-3">
          <span className="text-xs text-white/35">
            {ready ? "ready" : "waiting for local model"}
          </span>
          <button
            disabled
            className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium opacity-30"
            title="Generation will be enabled once a local TTS model is present"
          >
            Generate
          </button>
        </div>
      </section>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[70px_1fr] gap-2">
      <span className="text-white/35">{label}</span>
      <span className={`truncate text-white/65 ${mono ? "font-mono" : ""}`} title={value}>{value}</span>
    </div>
  );
}
