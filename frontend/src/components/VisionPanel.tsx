import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Select } from "./Select";
import { EmptyState, InfoRows, Panel, SectionTitle, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import type { VisionResult, VisionStatus } from "../types";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-emerald-500";

function size(bytes: number): string {
  if (!bytes) return "0 B";
  const gb = bytes / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

export function VisionPanel() {
  const [status, setStatus] = useState<VisionStatus | null>(null);
  const [modelId, setModelId] = useState("");
  const [projectorId, setProjectorId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState("Describe the image.");
  const [result, setResult] = useState<VisionResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.visionStatus().then((s) => {
      setStatus(s);
      setModelId((prev) => prev || s.models[0]?.id || "");
      setProjectorId((prev) => prev || s.projectors[0]?.id || "");
    }).catch(() => {});
  }, []);

  const preview = useMemo(() => file ? URL.createObjectURL(file) : "", [file]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const ready = Boolean(status?.ready && modelId && projectorId);
  const canAnalyze = ready && Boolean(file) && Boolean(prompt.trim()) && !loading;

  async function analyze() {
    if (!canAnalyze || !file) return;
    setLoading(true);
    setError("");
    try {
      const next = await api.analyzeVision({
        file,
        prompt: prompt.trim(),
        model_id: modelId,
        projector_id: projectorId,
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
        title="Vision"
        subtitle="Analyze an uploaded image with a local multimodal model and projector pair."
      >
        <StatusPill label={status?.binary_exists ? "binary found" : "binary missing"} tone={status?.binary_exists ? "good" : "warn"} />
        <StatusPill label={ready ? "ready" : "waiting"} tone={ready ? "good" : "neutral"} />
        <StatusPill label={file ? file.name : "no image"} tone={file ? "info" : "neutral"} />
      </WorkspaceHeader>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,340px)_minmax(0,1fr)] gap-3">
        <Panel className="flex min-h-0 flex-col overflow-hidden">
          <SectionTitle title="Vision setup" subtitle={status?.ready ? "local multimodal ready" : "waiting for local model"} />
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        <InfoRows
          rows={[
            { label: "Binary", value: status?.binary_exists ? "found" : "missing", tone: status?.binary_exists ? "good" : "warn" },
            { label: "Models", value: status?.models_dir ?? "...", mono: true },
            { label: "GPU", value: status ? `${status.gpu_layers} layers` : "..." },
            { label: "Limit", value: status ? `${status.max_upload_mb} MB` : "..." },
          ]}
        />

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Model</div>
          <Select
            value={modelId}
            onChange={setModelId}
            placeholder="no vision models"
            className="mt-1"
            options={(status?.models ?? []).map((m) => ({ value: m.id, label: m.name, hint: size(m.size_bytes) }))}
          />
        </label>

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Projector</div>
          <Select
            value={projectorId}
            onChange={setProjectorId}
            placeholder="no mmproj models"
            className="mt-1"
            options={(status?.projectors ?? []).map((m) => ({ value: m.id, label: m.name, hint: size(m.size_bytes) }))}
          />
        </label>

        <label>
          <div className="text-xs uppercase tracking-wide text-white/40">Image</div>
          <input
            type="file"
            accept=".png,.jpg,.jpeg,image/png,image/jpeg"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={`${field} mt-1 file:mr-3 file:rounded file:border-0 file:bg-white/10 file:px-2 file:py-1 file:text-xs file:text-white/70`}
          />
        </label>

        <label className="flex min-h-0 flex-1 flex-col">
          <div className="text-xs uppercase tracking-wide text-white/40">Prompt</div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className={`${field} mt-1 min-h-0 flex-1 resize-none`}
          />
        </label>

        <div className="flex items-center justify-between gap-3">
          <span className={`min-w-0 truncate text-xs ${error ? "text-red-300" : "text-white/35"}`} title={error || undefined}>
            {error || (ready ? "ready" : "waiting")}
          </span>
          <button
            onClick={() => void analyze()}
            disabled={!canAnalyze}
            className="shrink-0 rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-30"
          >
            {loading ? "Analyzing..." : "Analyze"}
          </button>
        </div>
          </div>
        </Panel>

      <section className="grid min-h-0 grid-cols-[minmax(280px,0.9fr)_1fr] gap-3">
        <Panel className="flex min-h-0 flex-col overflow-hidden">
          <SectionTitle title="Image" subtitle={file?.name || "No image selected"} />
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black/20 p-3">
            {preview ? (
              <img src={preview} alt="" className="max-h-full max-w-full object-contain" />
            ) : (
              <EmptyState title="No image selected" body="Choose a local PNG or JPG from the setup panel." />
            )}
          </div>
        </Panel>

        <Panel className="flex min-h-0 flex-col overflow-hidden">
          <SectionTitle
            title="Result"
            subtitle={result ? `${result.duration_seconds.toFixed(1)}s` : "Waiting for analysis"}
            actions={result ? (
              <a href={result.metadata_url} download className="text-xs text-emerald-300 hover:text-emerald-200">
                Download JSON
              </a>
            ) : null}
          />
          {result ? (
            <textarea
              readOnly
              value={result.text}
              className="min-h-0 flex-1 resize-none bg-transparent p-4 text-sm leading-6 text-white/80 outline-none"
            />
          ) : (
            <EmptyState title="No result yet" body="Run analysis and the model response will appear here." />
          )}
        </Panel>
      </section>
      </div>
    </div>
  );
}
