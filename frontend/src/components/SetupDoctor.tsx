import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Panel, SectionTitle, SkeletonRows, StatusPill } from "./WorkspaceChrome";
import type { CapabilityProfile, ModelFamily } from "../types";
import {
  compactModelDest,
  familyLabel,
  formatComputeCapability,
  isExperimentalBackend,
  setupDoctorStatus,
  tierLabel,
  type DoctorTone,
} from "./setupDoctorHelpers";

const TONE_CARD: Record<DoctorTone, string> = {
  good: "border-success/30 bg-success/10",
  warn: "border-warn/30 bg-warn/10",
  info: "border-info/30 bg-info/10",
  neutral: "border-border bg-control",
};

// Curated, plain-language feature labels — only the ones a user benefits from
// seeing. The raw feature map stays in the Advanced details block.
const FEATURE_LABELS: [string, string][] = [
  ["torch_compile", "torch.compile fast path"],
  ["nunchaku_cuda", "Nunchaku fp4 (FLUX/Qwen/Z)"],
  ["blackwell_fast_paths", "Blackwell-only fast paths"],
  ["video_diffusers_cuda", "CUDA video pipelines"],
  ["video_fp8_fast_paths", "Video fp8 fast paths"],
  ["video_light_fallback", "Video fallback path"],
  ["cuda_llama_binaries", "CUDA llama.cpp binaries"],
  ["metal_llama_binaries", "Metal llama.cpp binaries"],
  ["prefer_cpu_offload", "CPU offload (low VRAM)"],
];

export function SetupDoctor() {
  const [cap, setCap] = useState<CapabilityProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setBusy(true);
    setError("");
    try {
      setCap(await api.capabilities(refresh));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read capabilities");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const status = setupDoctorStatus(cap);
  const gpu = cap?.primary_gpu;
  const policy = cap?.model_policy;
  const starter = cap?.starter_models;

  return (
    <Panel>
      <SectionTitle
        title="Setup doctor"
        subtitle="What the installer detected and chose for this machine"
        actions={
          <button
            onClick={() => void load(true)}
            disabled={busy}
            className="ui-button rounded-md px-3 py-1.5 text-xs"
          >
            {busy ? "Detecting…" : "Re-run detection"}
          </button>
        }
      />

      <div className="space-y-4 p-4">
        {error ? (
          <div className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-sm text-error-fg">{error}</div>
        ) : null}

        {!cap && !error ? (
          <SkeletonRows rows={3} />
        ) : null}

        {cap ? (
          <>
            <div className={`rounded-lg border px-4 py-3 ${TONE_CARD[status.tone]}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-ui-strong">{status.headline}</h3>
                <div className="flex flex-wrap items-center gap-1.5">
                  {isExperimentalBackend(cap) ? <StatusPill label="Experimental" tone="warn" /> : null}
                  <StatusPill label={cap.label ?? cap.active_profile} tone={status.tone === "warn" ? "warn" : "good"} />
                  {cap.confidence ? <StatusPill label={`${cap.confidence} confidence`} tone="neutral" /> : null}
                </div>
              </div>
              <p className="mt-1 text-sm text-ui-muted">{status.detail}</p>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <DetailCard title="Detected hardware">
                <KeyVals rows={[
                  ["GPU", gpu?.name ?? "none detected"],
                  ["VRAM", gpu?.vram_mb ? `${Math.round(gpu.vram_mb / 1024)} GB` : "—"],
                  ["Architecture", gpu?.architecture ?? "—"],
                  ["Compute cap.", formatComputeCapability(gpu?.compute_capability_tuple) ?? "—"],
                  ["Tier", tierLabel(cap.hardware_tier)],
                ]} />
              </DetailCard>

              <DetailCard title="Selected profile">
                <KeyVals rows={[
                  ["Profile", cap.active_profile],
                  ["Backend", cap.backend],
                  ["Stub mode", cap.effective_stub_mode ? "on" : "off"],
                ]} />
              </DetailCard>

              <DetailCard title="Package status">
                <div className="flex flex-wrap gap-1.5">
                  {FEATURE_LABELS.map(([key, label]) => {
                    const on = Boolean(cap.features?.[key]);
                    return (
                      <span
                        key={key}
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${
                          on ? "bg-success-bg text-success-fg" : "bg-control-active text-ui-subtle line-through"
                        }`}
                        title={on ? `${label}: available` : `${label}: disabled for this profile`}
                      >
                        {on ? "✓" : "✕"} {label}
                      </span>
                    );
                  })}
                </div>
              </DetailCard>
            </div>

            {policy ? (
              <DetailCard title="Recommended models for this hardware">
                <div className="space-y-2">
                  <div className="text-[11px] font-medium text-ui-subtle">Images</div>
                  <FamilyRow label="Recommended" tone="good" families={policy.image.recommended} empty="none" />
                  <FamilyRow label="Advanced" tone="neutral" families={policy.image.advanced} empty="none" />
                  <FamilyRow label="Not supported" tone="bad" families={policy.image.hidden} empty="none" />
                  {policy.video ? (
                    <>
                      <div className="pt-1 text-[11px] font-medium text-ui-subtle">Video</div>
                      <FamilyRow label="Recommended" tone="good" families={policy.video.recommended} empty="none" />
                      <FamilyRow label="Advanced" tone="neutral" families={policy.video.advanced} empty="none" />
                      <FamilyRow label="Not supported" tone="bad" families={policy.video.hidden} empty="none" />
                    </>
                  ) : null}
                  <div className="text-[11px] text-ui-subtle">
                    LLMs: recommend up to ~{policy.llm.max_recommended_params_b}B params.
                  </div>
                  {policy.notes.map((note) => (
                    <p key={note} className="text-[11px] text-ui-subtle">{note}</p>
                  ))}
                </div>
              </DetailCard>
            ) : null}

            {starter ? (
              <DetailCard title="Starter model set">
                {starter.jobs.length ? (
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ui-subtle">
                      <span className="ui-chip rounded px-1.5 py-0.5 font-mono">{starter.profile}</span>
                      <span>{starter.jobs.length} files planned</span>
                    </div>
                    <div className="grid gap-1.5">
                      {starter.jobs.map((job) => (
                        <div key={`${job.repo}/${job.filename}`} className="grid gap-0.5 text-xs md:grid-cols-[220px_minmax(0,1fr)] md:gap-2">
                          <span className="truncate text-ui-muted" title={job.label}>{job.label}</span>
                          <span className="truncate font-mono text-[11px] text-ui-subtle" title={`${job.repo}/${job.filename}`}>
                            {compactModelDest(job.dest, job.filename)}
                          </span>
                        </div>
                      ))}
                    </div>
                    <div className="truncate font-mono text-[11px] text-ui-subtle" title={starter.dry_run_command}>
                      {starter.dry_run_command}
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-ui-subtle">No real-model downloads for CPU-safe/STUB mode.</div>
                )}
              </DetailCard>
            ) : null}

            {cap.warnings.length ? (
              <div className="rounded-md border border-warn/25 bg-warn/10 px-3 py-2 text-xs text-warn-fg">
                <ul className="list-disc space-y-1 pl-4">
                  {cap.warnings.map((w) => <li key={w}>{w}</li>)}
                </ul>
              </div>
            ) : null}

            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-ui-subtle underline-offset-2 hover:text-ui hover:underline"
            >
              {showAdvanced ? "Hide advanced details" : "Show advanced details"}
            </button>

            {showAdvanced ? (
              <div className="space-y-3">
                <DetailCard title="Considered profiles">
                  <div className="space-y-1.5 text-[11px]">
                    {cap.candidates.map((c) => (
                      <div key={c.id} className="flex items-start justify-between gap-2">
                        <span className={`font-mono ${c.id === cap.selected_profile ? "text-accent-fg" : "text-ui-muted"}`}>
                          {c.id}{c.id === cap.selected_profile ? " ◂ selected" : ""}
                        </span>
                        <span className="min-w-0 truncate text-ui-subtle" title={c.reason ?? ""}>{c.reason}</span>
                      </div>
                    ))}
                  </div>
                </DetailCard>
                {cap.disabled_features.length ? (
                  <DetailCard title="Disabled features">
                    <div className="flex flex-wrap gap-1.5">
                      {cap.disabled_features.map((f) => (
                        <span key={f} className="ui-chip rounded px-1.5 py-0.5 font-mono text-[11px]">{f}</span>
                      ))}
                    </div>
                  </DetailCard>
                ) : null}
                {Object.keys(cap.sources ?? {}).length ? (
                  <DetailCard title="Reference docs">
                    <ul className="space-y-1 text-[11px]">
                      {Object.entries(cap.sources).map(([key, url]) => (
                        <li key={key}>
                          <a href={url} target="_blank" rel="noreferrer" className="text-accent-fg hover:underline">{key}</a>
                        </li>
                      ))}
                    </ul>
                  </DetailCard>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </Panel>
  );
}

function DetailCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="ui-card rounded-md p-3">
      <div className="mb-2 text-xs font-medium text-ui-subtle">{title}</div>
      {children}
    </div>
  );
}

function KeyVals({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="space-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
          <dt className="text-ui-subtle">{k}</dt>
          <dd className="truncate text-ui-muted" title={v}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function FamilyRow({
  label,
  tone,
  families,
  empty,
}: {
  label: string;
  tone: "good" | "neutral" | "bad";
  families: ModelFamily[];
  empty: string;
}) {
  const toneClass =
    tone === "good" ? "bg-success/20 text-success-fg"
      : tone === "bad" ? "bg-error/20 text-error-fg"
        : "bg-control-active text-ui-muted";
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 text-xs">
      <span className="text-ui-subtle">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {families.length ? (
          families.map((f) => (
            <span key={f} className={`rounded px-1.5 py-0.5 text-[11px] ${toneClass}`}>{familyLabel(f)}</span>
          ))
        ) : (
          <span className="text-[11px] text-ui-subtle">{empty}</span>
        )}
      </div>
    </div>
  );
}
