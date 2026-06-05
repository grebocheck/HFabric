import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge } from "./Badge";
import type { VoiceStatus } from "../types";

function size(bytes: number): string {
  if (!bytes) return "0 B";
  const gb = bytes / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

export function VoicePanel() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .voiceStatus()
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load status"));
  }, []);

  const models = status?.models ?? [];

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4 overflow-y-auto p-1">
      <header>
        <h2 className="text-lg font-semibold text-white/85">Voice changer</h2>
        <p className="mt-1 text-sm text-white/45">
          RVC (w-okada-style) voice conversion. Offline and real-time conversion land in P6.2 — this
          tab currently detects local voices and the inference engine.
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">{error}</div>
      ) : null}

      <section className="rounded-lg border border-white/10 bg-surface p-4">
        <div className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Engine</div>
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <Row label="Engine" value={(status?.engine ?? "rvc").toUpperCase()} />
          <Row label="Device" value={status?.device ?? "…"} />
          <Row label="PyTorch" value={status?.deps.torch ? "available" : "missing"} ok={status?.deps.torch} />
          <Row label="RVC stack" value={status?.deps.rvc ? "available" : "not installed"} ok={status?.deps.rvc} />
          <Row label="Real-time" value={status?.realtime ? "ready" : "planned (P6.2)"} />
          <Row label="Status" value={status?.ready ? "ready" : "engine/models pending"} ok={status?.ready} />
        </div>
      </section>

      <section className="rounded-lg border border-white/10 bg-surface p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-xs font-medium uppercase tracking-wide text-white/40">Voices</div>
          <Badge>{models.length}</Badge>
        </div>
        {models.length === 0 ? (
          <p className="text-sm leading-6 text-white/40">
            No voices found. Drop an RVC model — a <code className="text-white/60">.pth</code> weight
            (optionally a same-name <code className="text-white/60">.index</code>) — into{" "}
            <code className="text-white/60">{status?.models_dir ?? "models/voice"}</code>.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {models.map((m) => (
              <li
                key={m.id}
                className="flex items-center justify-between gap-2 rounded-md border border-white/10 bg-black/20 px-3 py-2"
              >
                <span className="min-w-0 truncate text-sm text-white/80" title={m.name}>{m.name}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {m.has_index ? (
                    <Badge color="bg-emerald-700/60 text-emerald-100">index</Badge>
                  ) : (
                    <Badge>no index</Badge>
                  )}
                  <span className="font-mono text-xs text-white/35">{size(m.size_bytes)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <>
      <span className="text-white/40">{label}</span>
      <span className={`text-right ${ok === undefined ? "text-white/70" : ok ? "text-emerald-300/80" : "text-amber-300/70"}`}>
        {value}
      </span>
    </>
  );
}
