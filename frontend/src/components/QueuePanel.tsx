import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Badge } from "./Badge";
import type { ArbiterNote, Job, QueuePlan } from "../types";

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
const previewCells = Array.from({ length: 16 });
const cellColors = ["bg-white/45", "bg-accent/35", "bg-cyan-300/35", "bg-fuchsia-300/35"];

// Only the "why is the queue blocked" reasons belong in the queue banner;
// transient swaps are shown on the System timeline instead.
const BLOCKING_NOTE_TONES: Record<string, string> = {
  ram_budget: "border-error-border bg-error-bg text-error-fg",
  voice_lane: "border-info-border bg-info-bg text-info-fg",
  resident_pinned: "border-success-border bg-success-bg text-success-fg",
};

export function QueuePanel({ jobs, onChanged, note }: { jobs: Job[]; onChanged: () => void; note?: ArbiterNote | null }) {
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [plan, setPlan] = useState<QueuePlan | null>(null);
  const sorted = useMemo(
    () => [...jobs].sort(
      (a, b) =>
        (order[a.status] - order[b.status])
        || (b.priority - a.priority)
        || Date.parse(a.created_at) - Date.parse(b.created_at),
    ),
    [jobs],
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

  const reorderQueued = async (targetId: string) => {
    if (!draggedId || draggedId === targetId) return;
    const queuedJobs = sorted.filter((job) => job.status === "queued");
    const from = queuedJobs.findIndex((job) => job.id === draggedId);
    const to = queuedJobs.findIndex((job) => job.id === targetId);
    if (from < 0 || to < 0) return;

    const next = [...queuedJobs];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    await Promise.all(next.map((job, i) => api.setPriority(job.id, next.length - i)));
    setDraggedId(null);
    onChanged();
  };

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-panel max-[1240px]:col-span-2 max-[860px]:h-[520px]">
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
            onClick={() => api.clearFinished().then(onChanged)}
            disabled={!finished && !jobs.some((job) => job.status === "error")}
            className="ui-button rounded-md px-2.5 py-1.5 text-xs disabled:opacity-30"
          >
            Clear
          </button>
        </div>
        {note && BLOCKING_NOTE_TONES[note.reason] ? (
          <div className={`mt-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 ${BLOCKING_NOTE_TONES[note.reason]}`}>
            {note.message}
          </div>
        ) : null}
        <QueuePlanPreview plan={plan} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {sorted.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-md border border-dashed border-line text-sm text-ui-subtle">
            Empty queue
          </div>
        ) : (
          <div className="space-y-2">
            {sorted.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                draggedId={draggedId}
                setDraggedId={setDraggedId}
                reorderQueued={reorderQueued}
                onChanged={onChanged}
                note={jobNote(note, job)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function JobCard({
  job,
  draggedId,
  setDraggedId,
  reorderQueued,
  onChanged,
  note,
}: {
  job: Job;
  draggedId: string | null;
  setDraggedId: (id: string | null) => void;
  reorderQueued: (targetId: string) => Promise<void>;
  onChanged: () => void;
  note?: ArbiterNote | null;
}) {
  const progress = Math.round((job.progress || 0) * 100);
  const prompt = String(job.params?.prompt ?? "");

  return (
    <article
      draggable={job.status === "queued"}
      onDragStart={(e) => {
        if (job.status !== "queued") return;
        setDraggedId(job.id);
        e.dataTransfer.effectAllowed = "move";
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
          <span className="min-w-0 truncate font-mono text-xs text-ui-muted" title={job.model_id}>{job.model_id}</span>
        </div>
        <span className={`shrink-0 text-xs ${statusColor[job.status]}`}>{job.status}</span>
      </div>

      {prompt ? (
        <div className="mt-1.5 line-clamp-2 text-xs leading-4 text-ui-subtle" title={prompt}>{prompt}</div>
      ) : null}

      {note ? (
        <div className="mt-1.5 truncate text-[11px] text-ui-subtle" title={note.message}>
          {noteLine(note)}
        </div>
      ) : null}

      {job.status === "running" ? (
        <>
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded bg-control-active">
              <div
                className="h-full bg-accent transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-8 text-right text-[11px] text-ui-subtle">{progress}%</span>
          </div>
          {job.type === "image" ? (
            <DenoisePreview progress={job.progress} note={job.progress_note} />
          ) : null}
          <div className="mt-2 flex justify-end">
            <button
              onClick={() => api.cancelJob(job.id).then(onChanged).catch(() => {})}
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
          <button
            onClick={() => api.setPriority(job.id, job.priority + 1).then(onChanged)}
            className="text-xs text-ui-subtle hover:text-ui-strong"
          >
            Priority {job.priority}
          </button>
          <button
            onClick={() => api.cancelJob(job.id).then(onChanged)}
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

function DenoisePreview({ progress, note }: { progress: number; note?: string | null }) {
  const clamped = Math.min(1, Math.max(0, progress || 0));
  const noiseCells = Math.ceil((1 - clamped) * previewCells.length);
  const pct = Math.round(clamped * 100);

  return (
    <div className="mt-2 flex min-h-16 gap-2 rounded-md border border-line bg-control p-2">
      <div className="relative grid h-14 w-14 shrink-0 grid-cols-4 gap-px overflow-hidden rounded border border-line bg-sunken p-1">
        {previewCells.map((_, i) => (
          <span
            key={i}
            className={`${cellColors[i % cellColors.length]} rounded-[1px] transition-opacity`}
            style={{ opacity: i < noiseCells ? 0.85 : 0.12 }}
          />
        ))}
        <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-ui-inverse drop-shadow">
          {pct}%
        </span>
      </div>
      <div className="min-w-0 flex-1 self-center">
        <div className="truncate text-xs text-ui">{note ?? "denoising"}</div>
        <div className="mt-1 text-[10px] uppercase tracking-wide text-ui-subtle">preview</div>
      </div>
    </div>
  );
}
