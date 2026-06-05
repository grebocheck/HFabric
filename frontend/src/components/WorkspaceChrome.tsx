import type { ReactNode } from "react";

type Tone = "neutral" | "good" | "warn" | "bad" | "info";

const toneClass: Record<Tone, string> = {
  neutral: "bg-white/10 text-white/60",
  good: "bg-success/20 text-success-fg",
  warn: "bg-warn/20 text-warn-fg",
  bad: "bg-error/20 text-error-fg",
  info: "bg-info/20 text-info-fg",
};

export function WorkspaceHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex shrink-0 items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="text-xs font-medium uppercase tracking-wide text-white/35">{eyebrow}</div> : null}
        <h2 className="truncate text-lg font-semibold text-white/85">{title}</h2>
        {subtitle ? <p className="mt-1 max-w-3xl text-sm leading-5 text-white/45">{subtitle}</p> : null}
        {children ? <div className="mt-2 flex flex-wrap items-center gap-1.5">{children}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">{actions}</div> : null}
    </header>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-panel border border-line bg-surface shadow-panel ${className}`}>{children}</section>;
}

export function SectionTitle({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-white/75">{title}</div>
        {subtitle ? <div className="mt-0.5 truncate text-xs text-white/35">{subtitle}</div> : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}

export function StatusPill({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return (
    <span className={`inline-flex max-w-full items-center rounded px-1.5 py-0.5 text-xs ${toneClass[tone]}`}>
      <span className="truncate">{label}</span>
    </span>
  );
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center px-4 text-center">
      <div className="text-sm font-medium text-white/45">{title}</div>
      {body ? <div className="mt-1 max-w-sm text-xs leading-5 text-white/30">{body}</div> : null}
    </div>
  );
}

export function SkeletonLine({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton rounded ${className}`} />;
}

export function SkeletonRows({
  rows = 4,
  className = "",
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
          <SkeletonLine className={`h-3 ${i % 3 === 0 ? "w-4/5" : i % 3 === 1 ? "w-2/3" : "w-11/12"}`} />
          <SkeletonLine className="mt-2 h-2 w-1/2 opacity-70" />
        </div>
      ))}
    </div>
  );
}

export function InfoRows({ rows, labelWidth = 76 }: { rows: { label: string; value: string; mono?: boolean; tone?: Tone }[]; labelWidth?: number }) {
  return (
    <div className="space-y-1.5 rounded-md border border-white/10 bg-black/20 p-3 text-xs">
      {rows.map((row) => (
        <div key={row.label} className="grid min-w-0 gap-2" style={{ gridTemplateColumns: `${labelWidth}px minmax(0,1fr)` }}>
          <span className="text-white/35">{row.label}</span>
          <span
            className={`truncate ${row.mono ? "font-mono" : ""} ${
              row.tone === "good" ? "text-emerald-300/80"
                : row.tone === "warn" ? "text-amber-300/80"
                  : row.tone === "bad" ? "text-red-300/80"
                    : "text-white/65"
            }`}
            title={row.value}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}
