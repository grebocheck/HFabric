import { api } from "../api/client";
import type { Job } from "../types";

const statusColor: Record<string, string> = {
  queued: "text-white/50",
  running: "text-violet-300",
  done: "text-emerald-400",
  error: "text-red-400",
  cancelled: "text-white/30",
};

const order: Record<string, number> = { running: 0, queued: 1, error: 2, done: 3, cancelled: 4 };

export function QueuePanel({ jobs, onChanged }: { jobs: Job[]; onChanged: () => void }) {
  const sorted = [...jobs].sort(
    (a, b) => (order[a.status] - order[b.status]) || (b.priority - a.priority),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <h2 className="text-sm font-semibold text-white/70">Queue</h2>
        <button
          onClick={() => api.clearFinished().then(onChanged)}
          className="text-xs text-white/40 hover:text-white/80"
        >
          clear finished
        </button>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto pr-1">
        {sorted.length === 0 && <div className="px-1 text-sm text-white/30">empty</div>}
        {sorted.map((job) => (
          <div key={job.id} className="rounded-md border border-white/10 bg-black/20 p-2 text-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    job.type === "llm" ? "bg-emerald-700" : "bg-violet-700"
                  }`}
                >
                  {job.type}
                </span>
                <span className="truncate font-mono text-xs text-white/50">{job.model_id}</span>
              </div>
              <span className={`text-xs ${statusColor[job.status]}`}>{job.status}</span>
            </div>

            {job.params?.prompt != null && (
              <div className="mt-1 truncate text-xs text-white/40">{String(job.params.prompt)}</div>
            )}

            {job.status === "running" && (
              <div className="mt-1.5 h-1 overflow-hidden rounded bg-white/10">
                <div
                  className="h-full bg-violet-500 transition-all"
                  style={{ width: `${Math.round(job.progress * 100)}%` }}
                />
              </div>
            )}

            {job.status === "error" && (
              <div className="mt-1 truncate text-xs text-red-400/80" title={job.error ?? ""}>{job.error}</div>
            )}

            {job.status === "queued" && (
              <div className="mt-1.5 flex gap-2">
                <button
                  onClick={() => api.setPriority(job.id, job.priority + 1).then(onChanged)}
                  className="text-xs text-white/40 hover:text-white/90"
                >
                  ↑ priority ({job.priority})
                </button>
                <button
                  onClick={() => api.cancelJob(job.id).then(onChanged)}
                  className="text-xs text-red-400/70 hover:text-red-300"
                >
                  cancel
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
