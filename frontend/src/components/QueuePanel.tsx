import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Badge } from "./Badge";
import { ResilientImage } from "./ResilientImage";
import { toast } from "./Toast";
import type { ArbiterNote, ImageItem, Job, Model, QueuePlan } from "../types";

const statusColor: Record<string, string> = {
  queued: "text-ui-muted",
  running: "text-accent",
  done: "text-success-fg",
  error: "text-error-fg",
  cancelled: "text-ui-subtle",
};

const statusBorder: Record<string, string> = {
  queued: "border-l-border-strong",
  running: "border-l-accent",
  done: "border-l-success",
  error: "border-l-error",
  cancelled: "border-l-line",
};

const order: Record<string, number> = { running: 0, queued: 1, error: 2, done: 3, cancelled: 4 };

// Only the "why is the queue blocked" reasons belong in the queue banner;
// transient swaps are shown on the System timeline instead.
const BLOCKING_NOTE_TONES: Record<string, string> = {
  ram_budget: "border-error-border bg-error-bg text-error-fg",
  voice_lane: "border-info-border bg-info-bg text-info-fg",
  resident_pinned: "border-success-border bg-success-bg text-success-fg",
};

export function QueuePanel({ jobs, onChanged, note, models = [], images = [], onSelectImage }: {
  jobs: Job[]; onChanged: () => void | Promise<void>; note?: ArbiterNote | null;
  models?: Model[]; images?: ImageItem[]; onSelectImage?: (id: string) => void;
}) {
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [plan, setPlan] = useState<QueuePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const mutation = useRef(false);
  const sorted = useMemo(
    () => {
      const planned = new Map((plan?.steps.flatMap((step) => step.job_ids ?? []) ?? []).map((id, index) => [id, index]));
      return [...jobs].sort((a, b) => {
        const status = order[a.status] - order[b.status];
        if (status) return status;
        if (a.status !== "queued") return Date.parse(b.finished_at ?? b.created_at) - Date.parse(a.finished_at ?? a.created_at);
        return (planned.get(a.id) ?? Infinity) - (planned.get(b.id) ?? Infinity)
          || b.priority - a.priority || Date.parse(a.created_at) - Date.parse(b.created_at);
      });
    },
    [jobs, plan],
  );
  const running = jobs.filter((job) => job.status === "running").length;
  const queued = jobs.filter((job) => job.status === "queued").length;
  const finished = jobs.filter((job) => job.status === "done" || job.status === "cancelled").length;
  const queueKey = useMemo(
    () => jobs
      .filter((job) => job.status === "queued" || job.status === "running")
      .map((job) => `${job.id}:${job.status}:${job.priority}`)
      .join("|"),
    [jobs],
  );

  useEffect(() => {
    let active = true;
    setPlan(null);
    api.queuePlan()
      .then((next) => {
        if (active) setPlan(next);
      })
      .catch(() => {
        if (active) setPlan(null);
      });
    return () => {
      active = false;
    };
  }, [queueKey]);

  const perform = async (operation: () => Promise<unknown>) => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true);
    try {
      await operation();
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update queue");
    } finally {
      mutation.current = false;
      setBusy(false);
      setDraggedId(null);
    }
  };

  const reorderQueued = async (targetId: string, sourceId = draggedId) => {
    if (!sourceId || sourceId === targetId) return;
    const queuedJobs = sorted.filter((job) => job.status === "queued");
    const from = queuedJobs.findIndex((job) => job.id === sourceId);
    const to = queuedJobs.findIndex((job) => job.id === targetId);
    if (from < 0 || to < 0) return;

    const next = [...queuedJobs];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    await perform(() => api.reorderJobs(next.map((job) => job.id)));
  };

  const queuedJobs = sorted.filter((job) => job.status === "queued");
  const renderJob = (job: Job) => {
    const index = queuedJobs.findIndex((item) => item.id === job.id);
    return <JobCard key={job.id} job={job} draggedId={draggedId} setDraggedId={setDraggedId}
      reorderQueued={reorderQueued} perform={perform} busy={busy} note={jobNote(note, job)}
      position={index >= 0 ? index + 1 : undefined}
      onMoveUp={index > 0 ? () => void reorderQueued(queuedJobs[index - 1].id, job.id) : undefined}
      onMoveDown={index >= 0 && index < queuedJobs.length - 1 ? () => void reorderQueued(queuedJobs[index + 1].id, job.id) : undefined}
      modelName={models.find((model) => model.id === job.model_id)?.name ?? job.model_id}
      image={images.find((image) => image.job_id === job.id)} onSelectImage={onSelectImage} />;
  };

  return (
    <section aria-label="Generation queue" className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel max-[1240px]:col-span-2 max-[860px]:h-auto max-[860px]:min-h-64 max-[860px]:max-h-[70vh]">
      <div className="border-b border-line px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ui-strong">Queue</h2>
            <div className="mt-1 flex gap-2 text-[11px] text-ui-subtle">
              <span>{running} running</span>
              <span>{queued} queued</span>
              <span>{finished} finished</span>
            </div>
          </div>
          <button
            onClick={() => void perform(() => api.clearFinished())}
            disabled={busy || (!finished && !jobs.some((job) => job.status === "error"))}
            className="ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30"
          >
            Clear finished
          </button>
        </div>
        {note && BLOCKING_NOTE_TONES[note.reason] ? (
          <div className={`mt-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 ${BLOCKING_NOTE_TONES[note.reason]}`}>
            {note.message}
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {sorted.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-md border border-dashed border-line text-sm text-ui-subtle">
            Empty queue
          </div>
        ) : (
          <div className="space-y-2">
            {running ? <div className="space-y-2"><QueueHeading>Generating now</QueueHeading>{sorted.filter((job) => job.status === "running").map(renderJob)}</div> : null}
            {queued ? <div className="space-y-2"><QueueHeading>Up next · {queued}</QueueHeading><p className="text-[11px] text-ui-subtle">Drag or use arrows to change the order.</p>{queuedJobs.map(renderJob)}</div> : null}
            {!running && !queued ? <p className="py-3 text-center text-xs text-ui-subtle">All jobs finished</p> : null}
            {jobs.some((job) => job.status === "error") ? <div className="space-y-2"><QueueHeading>Needs attention</QueueHeading>{sorted.filter((job) => job.status === "error").map(renderJob)}</div> : null}
            {finished ? <details className="rounded-md border border-line"><summary className="cursor-pointer px-2.5 py-2 text-xs text-ui-muted">Completed · {finished}</summary><div className="space-y-2 border-t border-line p-2">{sorted.filter((job) => job.status === "done" || job.status === "cancelled").map(renderJob)}</div></details> : null}
            <QueuePlanPreview plan={plan} />
          </div>
        )}
      </div>
    </section>
  );
}

function QueueHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="pt-1 text-[10px] font-semibold uppercase tracking-wide text-ui-subtle">{children}</h3>;
}

function JobCard({
  job,
  draggedId,
  setDraggedId,
  reorderQueued,
  perform, busy, position, onMoveUp, onMoveDown, modelName, image, onSelectImage,
  note,
}: {
  job: Job;
  draggedId: string | null;
  setDraggedId: (id: string | null) => void;
  reorderQueued: (targetId: string) => Promise<void>;
  perform: (operation: () => Promise<unknown>) => Promise<void>;
  busy: boolean; position?: number; onMoveUp?: () => void; onMoveDown?: () => void;
  modelName: string; image?: ImageItem; onSelectImage?: (id: string) => void;
  note?: ArbiterNote | null;
}) {
  const progress = Math.round(Math.min(1, Math.max(0, job.progress || 0)) * 100);
  const prompt = String(job.params?.prompt ?? "");
  const quant = typeof job.params.image_quant === "string" ? job.params.image_quant : "";
  const facts = [
    job.params.width && job.params.height ? `${job.params.width}×${job.params.height}` : "",
    job.params.steps ? `${job.params.steps} steps` : "",
    quant === "none" ? "BF16" : quant.replace("bnb-", "").toUpperCase(),
  ].filter(Boolean).join(" · ");

  return (
    <article
      aria-label={`${modelName} ${job.status}`}
      draggable={job.status === "queued" && !busy}
      onDragStart={(e) => {
        if (job.status !== "queued" || busy) return;
        setDraggedId(job.id);
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", job.id);
      }}
      onDragEnd={() => setDraggedId(null)}
      onDragOver={(e) => {
        if (job.status === "queued" && draggedId) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        void reorderQueued(job.id);
      }}
      className={`animate-fade-in rounded-md border border-l-2 bg-control p-2.5 text-sm transition ${
        draggedId === job.id ? "border-accent/60 opacity-60" : `border-line ${statusBorder[job.status]}`
      } ${job.status === "queued" ? "cursor-grab active:cursor-grabbing" : ""}`}
    >
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Badge color="border-accent/40 bg-accent/15 text-accent-fg">{job.type}</Badge>
          {position ? <span className="text-xs text-ui-subtle">{position}.</span> : null}
          <span className="min-w-0 truncate text-xs font-medium text-ui-muted" title={modelName}>{modelName}</span>
        </div>
        <span className={`shrink-0 text-xs ${statusColor[job.status]}`}>{job.status}</span>
      </div>

      {image ? <button onClick={() => onSelectImage?.(image.id)} disabled={!onSelectImage} aria-label={`Show result: ${prompt || modelName}`} className="mt-2 h-16 w-16 overflow-hidden rounded-md border border-line"><ResilientImage sources={[image.thumb_url, image.url]} alt="" className="h-full w-full object-cover" /></button> : null}

      {prompt ? (
        <div className="mt-1.5 line-clamp-2 text-xs leading-4 text-ui-subtle" title={prompt}>{prompt}</div>
      ) : null}
      {facts ? <div className="mt-1 text-[10px] text-ui-subtle">{facts}</div> : null}

      {note ? (
        <div className="mt-1.5 truncate text-[11px] text-ui-subtle" title={note.message}>
          {noteLine(note)}
        </div>
      ) : null}

      {job.status === "running" ? (
        <>
          <div className="mt-2 flex items-center gap-2">
            <div role="progressbar" aria-label={`Generation progress: ${modelName}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} className="h-1.5 flex-1 overflow-hidden rounded bg-control-active">
              <div
                className="h-full bg-accent transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-8 text-right text-[11px] text-ui-subtle">{progress}%</span>
          </div>
          <p className="mt-2 text-xs leading-4 text-ui-muted">{job.progress_note || (progress ? "Generating…" : "Preparing model…")}</p>
          <div className="mt-2 flex justify-end">
            <button
              disabled={busy}
              onClick={() => void perform(() => api.cancelJob(job.id))}
              className="rounded-md border border-error-border px-2.5 py-1 text-xs text-error-fg hover:bg-error-bg"
            >
              Stop
            </button>
          </div>
        </>
      ) : null}

      {job.status === "error" ? (
        <div className="mt-1.5 line-clamp-2 text-xs text-error-fg" title={job.error ?? ""}>{job.error}</div>
      ) : null}

      {job.status === "queued" ? (
        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex gap-1"><button disabled={busy || !onMoveUp} onClick={onMoveUp} aria-label={`Move job ${position} up`} className="ui-button rounded px-2 py-1 text-xs disabled:opacity-30">↑</button><button disabled={busy || !onMoveDown} onClick={onMoveDown} aria-label={`Move job ${position} down`} className="ui-button rounded px-2 py-1 text-xs disabled:opacity-30">↓</button></div>
          <button
            disabled={busy}
            onClick={() => void perform(() => api.cancelJob(job.id))}
            className="text-xs text-error-fg hover:text-error"
          >
            Cancel
          </button>
        </div>
      ) : null}
    </article>
  );
}

function QueuePlanPreview({ plan }: { plan: QueuePlan | null }) {
  if (!plan || plan.queued === 0) return null;
  return (
    <div className="mt-2 rounded-md border border-line bg-control px-2.5 py-2">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-ui-subtle">
        Plan: {plan.queued} queued / {plan.swaps} swap{plan.swaps === 1 ? "" : "s"}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[11px]">
        <span className="max-w-[110px] truncate text-ui-subtle" title={plan.current_model ?? "idle"}>
          {plan.current_model ?? "idle"}
        </span>
        {plan.steps.map((step, i) => (
          <span key={`${step.model_id}-${i}`} className="inline-flex min-w-0 items-center gap-1">
            <span className="text-ui-subtle">-&gt;</span>
            <span className="max-w-[120px] truncate rounded border border-line bg-raised px-1.5 py-0.5 text-ui-muted" title={step.model_id}>
              {step.model}{step.count > 1 ? ` x${step.count}` : ""}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function jobNote(note: ArbiterNote | null | undefined, job: Job): ArbiterNote | null {
  if (!note || job.status !== "queued") return null;
  const ids = [note.model_id, note.target_model_id].filter(Boolean);
  if (ids.includes(job.model_id)) return note;
  if (!ids.length && note.model === job.model_id) return note;
  return null;
}

function noteLine(note: ArbiterNote): string {
  if (note.reason === "ram_budget") {
    const need = note.predicted_gb == null ? "" : ` (needs ~${note.predicted_gb.toFixed(1)} GB)`;
    return `waiting: RAM budget refused${need}`;
  }
  if (note.reason === "swap") {
    return `swap planned: unload ${note.unload_model ?? "current model"}`;
  }
  if (note.reason === "warm_evict") {
    return `waiting: evict warm ${note.model ?? "model"} for RAM`;
  }
  if (note.reason === "resident_pinned") {
    return "waiting: resident LLM API is pinned";
  }
  return note.message;
}
