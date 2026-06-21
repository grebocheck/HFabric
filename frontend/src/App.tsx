import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiAuth } from "./api/client";
import { useEvents } from "./api/useEvents";
import { ChatPanel } from "./components/ChatPanel";
import type { ChatJump } from "./components/ChatPanel";
import { CodePanel } from "./components/CodePanel";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { EditWorkspace } from "./components/EditWorkspace";
import { ImageComposer } from "./components/ImageComposer";
import { Gallery } from "./components/Gallery";
import { ModelManager } from "./components/ModelManager";
import { ModelStatus, type View } from "./components/ModelStatus";
import { NotesPanel } from "./components/NotesPanel";
import { QueuePanel } from "./components/QueuePanel";
import { ResultPreview } from "./components/ResultPreview";
import { RagPanel } from "./components/RagPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SystemPanel } from "./components/SystemPanel";
import { toast, ToastHost } from "./components/Toast";
import { TranscriptionPanel } from "./components/TranscriptionPanel";
import { TtsPanel } from "./components/TtsPanel";
import { VoicePanel } from "./components/VoicePanel";
import { Welcome } from "./components/Welcome";
import { buildComposerApply } from "./components/imageComposerHelpers";
import type { AppTheme, ArbiterNote, BusEvent, ComposerApply, EditApply, GpuStatus, HealthStatus, ImageItem, Job, Lora, MemPoint, MemSnapshot, Model, Preset } from "./types";

const MEM_HISTORY_MAX = 90; // rolling timeline points (~a few minutes at the poll rate)
const THEME_KEY = "hfabric.theme";
const SECURITY_WARNING_KEY = "hfabric.securityWarning.dismissed";
const WELCOME_KEY = "hfabric.welcome.seen";
const STUB_BANNER_KEY = "hfabric.stubBanner.dismissed";
const THEMES: AppTheme[] = ["dark", "dim", "light"];
const THEME_META: Record<AppTheme, string> = {
  dark: "#000000",
  dim: "#12151b",
  light: "#eef2f7",
};

// A workspace is one top-level tab. Adding a tab = one entry here (label drives
// the header tab + command palette; render() owns the whole main area).
type Workspace = { id: View; label: string; render: () => ReactNode };

function readTheme(): AppTheme {
  const value = localStorage.getItem(THEME_KEY);
  return value === "dark" || value === "dim" || value === "light" ? value : "dark";
}

export default function App() {
  const [models, setModels] = useState<Model[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [loras, setLoras] = useState<Lora[]>([]);
  const [lorasLoading, setLorasLoading] = useState(true);
  const [gpu, setGpu] = useState<GpuStatus>({ resident: null, model_id: null, model: null, family: null, warm: [] });
  const [mem, setMem] = useState<MemSnapshot | null>(null);
  const [memHistory, setMemHistory] = useState<MemPoint[]>([]);
  const [arbiterNote, setArbiterNote] = useState<ArbiterNote | null>(null);
  // latest resident model name, read inside the mem.status handler without
  // making it depend on (and re-subscribe to) gpu state.
  const gpuRef = useRef<GpuStatus>(gpu);
  useEffect(() => { gpuRef.current = gpu; }, [gpu]);
  const [view, setView] = useState<View>(() => (localStorage.getItem("hfabric.view") as View) || "images");
  const [theme, setTheme] = useState<AppTheme>(() => readTheme());
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [securityWarningDismissed, setSecurityWarningDismissed] = useState(() => localStorage.getItem(SECURITY_WARNING_KEY) === "1");
  const [welcomeSeen, setWelcomeSeen] = useState(() => localStorage.getItem(WELCOME_KEY) === "1");
  const [stubBannerDismissed, setStubBannerDismissed] = useState(() => localStorage.getItem(STUB_BANNER_KEY) === "1");
  const [authLocked, setAuthLocked] = useState(false);
  const [authTokenDraft, setAuthTokenDraft] = useState(() => apiAuth.getToken());
  const [authRevision, setAuthRevision] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const tabIdsRef = useRef<View[]>([]);
  const [chatJump, setChatJump] = useState<ChatJump | null>(null);

  const [promptDraft, setPromptDraft] = useState("");
  // LLM composer draft, lifted so it survives tab switches (ChatPanel unmounts
  // when you leave the LLM tab).
  const [chatDraft, setChatDraft] = useState("");
  // History self-fetches; bump this to make it reload after a new image lands.
  const [imageEpoch, setImageEpoch] = useState(0);
  // A "reproduce from History" request handed to the image composer.
  const [composerApply, setComposerApply] = useState<ComposerApply | null>(null);
  const [editApply, setEditApply] = useState<EditApply | null>(null);
  // The Images tab hosts both plain generation and the edit workspace, toggled
  // in-place instead of living on a separate top-level tab.
  const [imageMode, setImageMode] = useState<"generate" | "edit">("generate");
  const postureToastShown = useRef(false);

  const refreshJobs = useCallback(() => api.listJobs().then(setJobs).catch(() => {}), []);
  const refreshImages = useCallback((q?: string) => api.listImages(q).then(setImages).catch(() => {}), []);
  const refreshModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      setModels(await api.listModels());
    } catch {
      // The UI keeps its last known model list if the backend is momentarily down.
    } finally {
      setModelsLoading(false);
    }
  }, []);
  const refreshLoras = useCallback(async () => {
    setLorasLoading(true);
    try {
      setLoras(await api.listLoras());
    } catch {
      // Same stale-list behavior as models.
    } finally {
      setLorasLoading(false);
    }
  }, []);
  const refreshModelCatalog = useCallback(async () => {
    // A browser refresh doubles as a filesystem rescan, so checkpoints copied
    // into models/* while the backend is running appear without a server restart.
    try {
      await api.rescanModels();
    } catch {
      // Still show the last in-memory registry if a rescan fails transiently.
    }
    await Promise.all([refreshModels(), refreshLoras()]);
  }, [refreshLoras, refreshModels]);
  const refreshPresets = useCallback(async () => {
    setPresetsLoading(true);
    try {
      setPresets(await api.listPresets());
    } catch {
      // Presets are optional polish; failed refresh should not block generation.
    } finally {
      setPresetsLoading(false);
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const next = await api.health();
      setHealth(next);
      if (
        next.security.exposed
        && !next.security.token_required
        && !securityWarningDismissed
        && !postureToastShown.current
      ) {
        postureToastShown.current = true;
        toast.error("Security warning: backend is reachable from the network without HFAB_API_TOKEN.", { duration: 12000 });
      }
    } catch {
      // Health is best-effort; the app keeps trying through normal refreshes.
    }
  }, [securityWarningDismissed]);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth, authRevision]);

  useEffect(() => apiAuth.subscribe((event) => {
    setAuthTokenDraft(event.token);
    if (event.unauthorized) setAuthLocked(true);
  }), []);

  useEffect(() => {
    void refreshModelCatalog();
    refreshJobs();
    refreshImages();
    refreshPresets();
  }, [refreshModelCatalog, refreshJobs, refreshImages, refreshPresets, authRevision]);

  const onEvent = useCallback(
    (e: BusEvent) => {
      switch (e.type) {
        case "gpu.status":
          setGpu({
            resident: (e.resident as string) ?? null,
            model_id: (e.model_id as string) ?? null,
            model: (e.model as string) ?? null,
            family: (e.family as string) ?? null,
            warm: Array.isArray(e.warm) ? (e.warm as GpuStatus["warm"]) : [],
            lanes: Array.isArray(e.lanes) ? (e.lanes as GpuStatus["lanes"]) : [],
          });
          break;
        case "job.progress":
          setJobs((prev) =>
            prev.map((j) => (
              j.id === e.job_id
                ? {
                    ...j,
                    progress: e.progress as number,
                    progress_note: typeof e.note === "string" ? e.note : j.progress_note,
                  }
                : j
            )),
          );
          break;
        case "job.created":
        case "job.started":
        case "job.cancelled":
          refreshJobs();
          break;
        case "job.error":
          refreshJobs();
          toast.error(`Job failed${typeof e.error === "string" && e.error ? `: ${e.error}` : ""}`);
          break;
        case "job.done":
          refreshJobs();
          if (e.job_type === "image" || e.job_type === "upscale") {
            refreshImages();
            setImageEpoch((n) => n + 1);
            toast.success(e.job_type === "upscale" ? "Upscale ready" : "Image ready", { onClick: () => setView("history") });
          }
          break;
        case "image.ready":
          refreshImages();
          setImageEpoch((n) => n + 1);
          break;
        case "mem.status": {
          const snap: MemSnapshot = {
            ram: (e.ram as MemSnapshot["ram"]) ?? null,
            vram: (e.vram as MemSnapshot["vram"]) ?? null,
          };
          setMem(snap);
          setMemHistory((prev) => [
            ...prev,
            { ts: e.ts, ram: snap.ram, vram: snap.vram, resident: gpuRef.current.model },
          ].slice(-MEM_HISTORY_MAX));
          break;
        }
        case "arbiter.note":
          setArbiterNote({
            reason: String(e.reason ?? ""),
            message: String(e.message ?? ""),
            model_id: typeof e.model_id === "string" ? e.model_id : undefined,
            model: typeof e.model === "string" ? e.model : undefined,
            family: typeof e.family === "string" ? e.family : undefined,
            target_model_id: typeof e.target_model_id === "string" ? e.target_model_id : undefined,
            target_model: typeof e.target_model === "string" ? e.target_model : undefined,
            target_family: typeof e.target_family === "string" ? e.target_family : undefined,
            unload_model_id: typeof e.unload_model_id === "string" ? e.unload_model_id : undefined,
            unload_model: typeof e.unload_model === "string" ? e.unload_model : undefined,
            predicted_gb: typeof e.predicted_gb === "number" ? e.predicted_gb : undefined,
            available_gb: typeof e.available_gb === "number" ? e.available_gb : undefined,
            ts: e.ts,
          });
          if (e.reason === "ram_budget") toast.error(String(e.message ?? "Load refused by RAM guard"));
          break;
      }
    },
    [refreshJobs, refreshImages],
  );

  const { connected } = useEvents(onEvent);
  const lockVisible = Boolean(health?.security.token_required && (authLocked || !authTokenDraft.trim()));
  const saveToken = useCallback(() => {
    apiAuth.setToken(authTokenDraft);
    setAuthLocked(false);
    setAuthRevision((n) => n + 1);
  }, [authTokenDraft]);
  const clearToken = useCallback(() => {
    setAuthTokenDraft("");
    apiAuth.clearToken();
    setAuthLocked(false);
    setAuthRevision((n) => n + 1);
  }, []);
  const dismissSecurityWarning = useCallback(() => {
    localStorage.setItem(SECURITY_WARNING_KEY, "1");
    setSecurityWarningDismissed(true);
  }, []);
  const dismissWelcome = useCallback(() => {
    localStorage.setItem(WELCOME_KEY, "1");
    setWelcomeSeen(true);
  }, []);
  const dismissStubBanner = useCallback(() => {
    localStorage.setItem(STUB_BANNER_KEY, "1");
    setStubBannerDismissed(true);
  }, []);

  const onFree = useCallback(() => api.freeGpu().catch(() => {}), []);
  const cycleTheme = useCallback(() => {
    setTheme((current) => THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
  }, []);

  // Reproduce a History image in the composer. The stored snapshot keys the
  // model by *name*; resolve it back to a live model id when one matches.
  const onReproduce = useCallback(
    (image: ImageItem, opts: { keepSeed: boolean }) => {
      setComposerApply(buildComposerApply(image, models, opts));
      setView("images");
      toast.success(opts.keepSeed ? "Loaded into composer" : "Loaded as variation (new seed)");
    },
    [models],
  );

  const onEdit = useCallback(
    (image: ImageItem) => {
      const base = buildComposerApply(image, models, { keepSeed: true });
      setEditApply({
        ...base,
        image_id: image.id,
        source_url: image.url,
        width: image.width ?? undefined,
        height: image.height ?? undefined,
      });
      setImageMode("edit");
      setView("images");
      toast.success("Loaded into Edit");
    },
    [models],
  );

  const onUpscale = useCallback(
    async (image: ImageItem, scale: 2 | 4) => {
      const upscaler = models.find((model) => model.job_type === "upscale" && model.available);
      if (!upscaler) {
        toast.error("No upscaler model is available");
        return;
      }
      try {
        await api.createJobs([{ type: "upscale", model_id: upscaler.id, params: { image_id: image.id, scale } }]);
        refreshJobs();
        toast.success(`Queued upscale ${scale}x`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Could not queue upscale");
      }
    },
    [models, refreshJobs],
  );

  // remember the last active tab
  useEffect(() => { localStorage.setItem("hfabric.view", view); }, [view]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme !== "light");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_META[theme]);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // global shortcuts: Ctrl/Cmd+K opens the palette; Alt+1..N switches tabs
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (e.altKey && /^[1-9]$/.test(e.key)) {
        const target = tabIdsRef.current[Number(e.key) - 1];
        if (target) { e.preventDefault(); setView(target); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const imageJobs = jobs.filter((j) => j.type === "image" || j.type === "upscale");
  const hasImageModels = models.some((m) => m.job_type === "image");
  const busy = jobs.some((j) => j.status === "running");
  // Changes whenever the pending queue changes, so the System tab can refetch
  // the swap-plan preview without polling.
  const queueKey = useMemo(
    () => jobs
      .filter((j) => j.status === "queued" || j.status === "running")
      .map((j) => `${j.id}:${j.status}:${j.priority}`)
      .join("|"),
    [jobs],
  );

  // --- workspace registry: the single source for tabs + main rendering ---
  const workspaces: Workspace[] = [
    {
      id: "images",
      label: "Images",
      render: () => (
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
          <div className="mb-3 flex shrink-0 items-center gap-1 self-start rounded-lg border border-line bg-control p-1">
            {([["generate", "Generate"], ["edit", "Edit"]] as const).map(([id, modeLabel]) => (
              <button
                key={id}
                onClick={() => setImageMode(id)}
                className={`rounded-md px-3 py-1 text-sm font-medium transition ${
                  imageMode === id
                    ? "bg-accent text-ui-inverse shadow-sm"
                    : "text-ui-muted hover:bg-control-hover hover:text-ui"
                }`}
              >
                {modeLabel}
              </button>
            ))}
          </div>
          {imageMode === "generate" ? (
            <div className="grid min-h-0 flex-1 grid-cols-[390px_minmax(0,1fr)_330px] grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden max-[1240px]:grid-cols-[380px_minmax(0,1fr)] max-[1240px]:grid-rows-[minmax(0,1fr)_300px] max-[860px]:block max-[860px]:overflow-y-auto">
              <ImageComposer
                models={models}
                modelsLoading={modelsLoading}
                loras={loras}
                lorasLoading={lorasLoading}
                presets={presets}
                presetsLoading={presetsLoading}
                onPresetsChanged={refreshPresets}
                promptDraft={promptDraft}
                setPromptDraft={setPromptDraft}
                apply={composerApply}
              />
              <ResultPreview
                images={images}
                onOpenHistory={() => setView("history")}
                onReproduce={onReproduce}
                onEdit={onEdit}
                onUpscale={onUpscale}
                generating={imageJobs.some((j) => j.status === "running")}
                hasImageModels={hasImageModels}
                modelsLoading={modelsLoading}
                onGetModels={() => setView("models")}
              />
              <QueuePanel jobs={imageJobs} onChanged={refreshJobs} note={arbiterNote} />
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-hidden">
              <EditWorkspace
                models={models}
                modelsLoading={modelsLoading}
                loras={loras}
                presets={presets}
                jobs={imageJobs}
                images={images}
                apply={editApply}
                onQueued={refreshJobs}
                onGetModels={() => setView("models")}
              />
            </div>
          )}
        </main>
      ),
    },
    {
      id: "history",
      label: "History",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <Gallery models={models} reloadSignal={imageEpoch} onReproduce={onReproduce} onEdit={onEdit} onUpscale={onUpscale} />
        </main>
      ),
    },
    {
      id: "llm",
      label: "LLM",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <ChatPanel models={models} modelsLoading={modelsLoading} jump={chatJump} draft={chatDraft} setDraft={setChatDraft} />
        </main>
      ),
    },
    {
      id: "notes",
      label: "Notes",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <NotesPanel />
        </main>
      ),
    },
    {
      id: "tts",
      label: "TTS",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <TtsPanel />
        </main>
      ),
    },
    {
      id: "transcription",
      label: "Transcribe",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <TranscriptionPanel />
        </main>
      ),
    },
    {
      id: "code",
      label: "Code",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <CodePanel
            models={models}
            modelsLoading={modelsLoading}
            onOpenChat={(conversationId, jobId) => {
              setChatJump({ conversationId, jobId, nonce: Date.now() });
              setView("llm");
            }}
          />
        </main>
      ),
    },
    {
      id: "rag",
      label: "RAG",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <RagPanel
            models={models}
            modelsLoading={modelsLoading}
            onOpenChat={(conversationId, jobId) => {
              setChatJump({ conversationId, jobId, nonce: Date.now() });
              setView("llm");
            }}
          />
        </main>
      ),
    },
    {
      id: "voice",
      label: "Voice",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <VoicePanel />
        </main>
      ),
    },
    {
      id: "models",
      label: "Models",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <ModelManager onModelsChanged={() => { void refreshModels(); void refreshLoras(); }} />
        </main>
      ),
    },
    {
      id: "system",
      label: "System",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <SystemPanel gpu={gpu} mem={mem} history={memHistory} note={arbiterNote} queueKey={queueKey} imageSignal={imageEpoch} version={health?.version} />
        </main>
      ),
    },
    {
      id: "settings",
      label: "Settings",
      render: () => (
        <main className="flex-1 overflow-hidden p-4">
          <SettingsPanel />
        </main>
      ),
    },
  ];
  const active = workspaces.find((w) => w.id === view) ?? workspaces[0];
  tabIdsRef.current = workspaces.map((w) => w.id);

  const commands = useMemo<Command[]>(() => [
    ...workspaces.map((w) => ({ id: `go-${w.id}`, label: `Go to ${w.label}`, hint: "tab", run: () => setView(w.id) })),
    { id: "theme", label: "Cycle Theme", hint: theme, run: cycleTheme },
    { id: "free", label: "Free GPU", hint: "unload models", run: onFree },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [cycleTheme, onFree, theme]);

  return (
    <div className="flex h-screen flex-col">
      <ModelStatus
        gpu={gpu}
        connected={connected}
        busy={busy}
        mem={mem}
        view={view}
        theme={theme}
        tabs={workspaces.map(({ id, label }) => ({ id, label }))}
        onView={setView}
        onFree={onFree}
        onTheme={cycleTheme}
        onPalette={() => setPaletteOpen(true)}
      />

      {health?.security.exposed && !health.security.token_required && !securityWarningDismissed ? (
        <div className="flex items-center gap-3 border-b border-error-border bg-error-bg px-4 py-2 text-sm text-error-fg">
          <span className="min-w-0 flex-1">
            Security warning: backend is bound to a non-loopback host without HFAB_API_TOKEN.
          </span>
          <button
            onClick={dismissSecurityWarning}
            className="rounded border border-error-border px-2 py-1 text-xs text-error-fg hover:bg-error-bg"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {health?.stub_mode && !stubBannerDismissed ? (
        <div className="flex items-center gap-3 border-b border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-fg">
          <span className="min-w-0 flex-1">
            STUB mode — results are mock placeholders. Install the GPU dependencies and restart for real generation.
          </span>
          <button
            onClick={dismissStubBanner}
            className="rounded border border-warn-border px-2 py-1 text-xs text-warn-fg hover:bg-warn-bg"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {active.render()}

      <CommandPalette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />
      {lockVisible ? (
        <AuthLockScreen
          token={authTokenDraft}
          onToken={setAuthTokenDraft}
          onSubmit={saveToken}
          onClear={clearToken}
          unauthorized={authLocked}
        />
      ) : null}
      {!lockVisible && !welcomeSeen && health ? (
        <Welcome stubMode={health.stub_mode} onClose={dismissWelcome} />
      ) : null}
      <ToastHost />
    </div>
  );
}

function AuthLockScreen({
  token,
  onToken,
  onSubmit,
  onClear,
  unauthorized,
}: {
  token: string;
  onToken: (value: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  unauthorized: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4 backdrop-blur-sm">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="w-full max-w-sm rounded-lg border border-line bg-surface p-4 shadow-popover"
      >
        <h2 className="text-base font-semibold text-ui-strong">API token required</h2>
        <p className="mt-1 text-sm leading-5 text-ui-muted">
          Enter the HFAB_API_TOKEN configured for this backend.
        </p>
        {unauthorized ? <p className="mt-2 text-xs text-error-fg">The last request was rejected with 401.</p> : null}
        <input
          type="password"
          value={token}
          onChange={(event) => onToken(event.target.value)}
          autoFocus
          className="ui-field mt-4 w-full rounded-md px-3 py-2 text-sm"
          placeholder="Bearer token"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClear}
            className="ui-button rounded-md px-3 py-1.5 text-sm"
          >
            Clear
          </button>
          <button
            type="submit"
            disabled={!token.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-ui-inverse hover:bg-accent-hover disabled:opacity-40"
          >
            Unlock
          </button>
        </div>
      </form>
    </div>
  );
}
