import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Panel, SectionTitle, SkeletonRows } from "./WorkspaceChrome";
import { toast } from "./Toast";
import { formatSize } from "./imageComposerHelpers";
import type { LlamaState } from "../types";

const subtleButton =
  "rounded-md border border-white/15 px-2.5 py-1 text-xs text-white/65 transition hover:bg-white/10 hover:text-white disabled:opacity-30";
const primaryButton =
  "rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white transition hover:bg-accent-hover disabled:opacity-35";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

// llama.cpp runtime manager (P20.10): install/update the binaries the LLM, RAG,
// TTS, and Vision tabs all depend on, keeping old builds for rollback.
export function LlamaRuntime() {
  const [data, setData] = useState<LlamaState | null>(null);
  const [busy, setBusy] = useState("");
  const prevInstall = useRef("idle");

  const refresh = useCallback(async () => {
    try {
      setData(await api.llamaState());
    } catch {
      /* keep last known state if the backend blips */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const installing = data?.install_status.state === "running";

  // Poll while a background download runs so progress + completion show live.
  useEffect(() => {
    if (!installing) return;
    const timer = setInterval(() => void refresh(), 1500);
    return () => clearInterval(timer);
  }, [installing, refresh]);

  // Toast once when an install finishes or fails.
  useEffect(() => {
    const status = data?.install_status;
    if (!status) return;
    if (prevInstall.current === "running" && status.state === "done") {
      toast.success(status.message || "llama.cpp installed");
    } else if (prevInstall.current === "running" && status.state === "error") {
      toast.error(status.message || "llama.cpp install failed", { duration: 10000 });
    }
    prevInstall.current = status.state;
  }, [data?.install_status]);

  const install = async (tag?: string) => {
    setBusy("install");
    try {
      await api.llamaInstall(tag ? { tag } : {});
      toast.info("Downloading llama.cpp… this can take a minute.");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Could not start install"));
    } finally {
      setBusy("");
    }
  };

  const check = async () => {
    setBusy("check");
    try {
      const update = await api.llamaCheckUpdate();
      if (update.update_available) toast.info(`Update available: ${update.latest_tag}`);
      else if (!update.asset_available) toast.error(`No ${update.variant} build in ${update.latest_tag}`);
      else toast.success("llama.cpp is up to date");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Update check failed"));
    } finally {
      setBusy("");
    }
  };

  const activate = async (id: string) => {
    setBusy(id);
    try {
      setData(await api.llamaActivate(id));
      toast.success(`Activated ${id}`);
    } catch (err) {
      toast.error(errMsg(err, "Could not activate"));
    } finally {
      setBusy("");
    }
  };

  const remove = async (id: string) => {
    setBusy(id);
    try {
      setData(await api.llamaRemove(id));
      toast.success(`Removed ${id}`);
    } catch (err) {
      toast.error(errMsg(err, "Could not remove"));
    } finally {
      setBusy("");
    }
  };

  const update = data?.update;
  const status = data?.install_status;
  const pct = status && status.progress.total > 0
    ? Math.round((status.progress.done / status.progress.total) * 100)
    : null;

  return (
    <Panel>
      <SectionTitle
        title="LLM runtime (llama.cpp)"
        subtitle={data ? `${data.variant} build · keeps ${data.keep_versions} for rollback` : "loading…"}
        actions={
          <div className="flex items-center gap-1.5">
            <button onClick={() => void check()} className={subtleButton} disabled={Boolean(busy) || installing}>
              {busy === "check" ? "Checking…" : "Check update"}
            </button>
            <button onClick={() => void install()} className={primaryButton} disabled={Boolean(busy) || installing}>
              {installing ? "Installing…" : update?.update_available ? `Update → ${update.latest_tag}` : "Install latest"}
            </button>
          </div>
        }
      />
      <div className="space-y-3 p-3 text-xs">
        {!data ? (
          <SkeletonRows rows={3} />
        ) : (
          <>
            {installing ? (
              <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-white/75">
                <div className="mb-1 flex items-center justify-between">
                  <span className="truncate">{status?.message ?? "Downloading…"}</span>
                  {pct != null ? <span className="font-mono text-white/55">{pct}%</span> : null}
                </div>
                {pct != null ? (
                  <div className="h-1.5 overflow-hidden rounded bg-white/10">
                    <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                  </div>
                ) : null}
              </div>
            ) : null}

            {update?.update_available && !installing ? (
              <div className="rounded-md border border-info/25 bg-info/10 px-3 py-1.5 text-info-fg">
                A newer build is available: {update.latest_tag} (current {update.active_tag ?? "none"}).
              </div>
            ) : null}

            {data.versions.length === 0 ? (
              <div className="rounded-md border border-dashed border-white/10 px-3 py-3 text-white/40">
                {data.legacy_binary_present
                  ? "Using a manually-placed binary at bin/llama. Click Install latest to switch to a managed build."
                  : "No llama.cpp installed yet. Click Install latest to download the right build for this machine."}
              </div>
            ) : (
              <ul className="space-y-1.5">
                {data.versions.map((v) => (
                  <li
                    key={v.id}
                    className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 ${
                      v.active ? "border-emerald-500/35 bg-emerald-500/10" : "border-white/10 bg-black/20"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-white/80">{v.tag}</span>
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/50">{v.variant}</span>
                        {v.active ? (
                          <span className="rounded bg-emerald-600/40 px-1.5 py-0.5 text-[10px] text-emerald-100">active</span>
                        ) : null}
                      </div>
                      <div className="mt-0.5 text-[11px] text-white/35">
                        {v.size_bytes ? formatSize(v.size_bytes) : "—"}
                        {v.installed_at ? ` · ${new Date(v.installed_at).toLocaleDateString()}` : ""}
                        {` · ${v.binaries.length} bin`}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {!v.active ? (
                        <button onClick={() => void activate(v.id)} className={subtleButton} disabled={Boolean(busy)}>
                          {busy === v.id ? "…" : "Roll back"}
                        </button>
                      ) : null}
                      {!v.active ? (
                        <button
                          onClick={() => void remove(v.id)}
                          className="rounded-md border border-red-400/25 px-2 py-1 text-xs text-red-300 hover:bg-red-400/10 disabled:opacity-30"
                          disabled={Boolean(busy)}
                        >
                          Remove
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[11px] text-white/30">
              Powers the LLM, RAG, TTS, and Vision tabs. Old builds are kept so a bad update can be rolled back.
            </p>
          </>
        )}
      </div>
    </Panel>
  );
}
