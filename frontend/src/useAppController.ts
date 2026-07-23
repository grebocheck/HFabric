import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiAuth } from "./api/client";
import { appQueryCache } from "./api/queryCache";
import { SNAPSHOT_REFRESH_EVENT } from "./api/sync";
import { useEvents } from "./api/useEvents";
import type { ChatJump } from "./components/ChatPanel";
import { toast } from "./components/Toast";
import { buildComposerApply } from "./components/imageComposerHelpers";
import { readStoredEnum, storage } from "./lib/storage";
import type {
  AppTheme,
  ArbiterNote,
  BusEvent,
  ComposerApply,
  EditApply,
  GpuStatus,
  HealthStatus,
  ImageItem,
  Job,
  Lora,
  MemPoint,
  MemSnapshot,
  Model,
  Preset,
  VideoItem,
} from "./types";
import { prefetchWorkspace } from "./workspaceLoaders";
import { VIEW_IDS, WORKSPACES, type View } from "./workspaces";

const MEM_HISTORY_MAX = 90;
const THEME_KEY = "hfabric.theme";
const SECURITY_WARNING_KEY = "hfabric.securityWarning.dismissed";
const WELCOME_KEY = "hfabric.welcome.seen";
const STUB_BANNER_KEY = "hfabric.stubBanner.dismissed";
const VIEW_KEY = "hfabric.view";
const THEMES: AppTheme[] = ["dark", "dim", "light"];
const THEME_META: Record<AppTheme, string> = {
  dark: "#000000",
  dim: "#12151b",
  light: "#eef2f7",
};

function readTheme(): AppTheme {
  return readStoredEnum(THEME_KEY, THEMES, "dark");
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useAppController() {
  const [models, setModels] = useState<Model[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [loras, setLoras] = useState<Lora[]>([]);
  const [lorasLoading, setLorasLoading] = useState(true);
  const [gpu, setGpu] = useState<GpuStatus>({
    resident: null,
    model_id: null,
    model: null,
    family: null,
    warm: [],
  });
  const [mem, setMem] = useState<MemSnapshot | null>(null);
  const [memHistory, setMemHistory] = useState<MemPoint[]>([]);
  const [arbiterNote, setArbiterNote] = useState<ArbiterNote | null>(null);
  // latest resident model name, read inside the mem.status handler without
  // making it depend on (and re-subscribe to) gpu state.
  const gpuRef = useRef<GpuStatus>(gpu);
  useEffect(() => {
    gpuRef.current = gpu;
  }, [gpu]);
  const [view, setView] = useState<View>(() => readStoredEnum(VIEW_KEY, VIEW_IDS, "images"));
  const [theme, setTheme] = useState<AppTheme>(() => readTheme());
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [securityWarningDismissed, setSecurityWarningDismissed] = useState(
    () => storage.get(SECURITY_WARNING_KEY) === "1",
  );
  const [welcomeSeen, setWelcomeSeen] = useState(() => storage.get(WELCOME_KEY) === "1");
  const [stubBannerDismissed, setStubBannerDismissed] = useState(() => storage.get(STUB_BANNER_KEY) === "1");
  const [readError, setReadError] = useState<string | null>(null);
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
  const [historyMode, setHistoryMode] = useState<"images" | "videos">("images");
  const postureToastShown = useRef(false);
  const catalogScanRevision = useRef<number | null>(null);

  const refreshJobs = useCallback(async (force = true) => {
    try {
      setJobs(
        await appQueryCache.fetch("jobs", (signal) => api.listJobs(signal), {
          staleTime: 1_500,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Jobs: ${errorMessage(error, "could not refresh")}`);
    }
  }, []);
  const refreshImages = useCallback(async (q?: string, force = true) => {
    try {
      setImages(
        await appQueryCache.fetch(`images:${q?.trim() ?? ""}`, (signal) => api.listImages(q, signal), {
          staleTime: 5_000,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Images: ${errorMessage(error, "could not refresh")}`);
    }
  }, []);
  const refreshVideos = useCallback(async (force = true) => {
    try {
      setVideos(
        await appQueryCache.fetch("videos", (signal) => api.listVideos(signal), {
          staleTime: 5_000,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Videos: ${errorMessage(error, "could not refresh")}`);
    }
  }, []);
  const refreshModels = useCallback(async (force = true) => {
    setModelsLoading(true);
    try {
      setModels(
        await appQueryCache.fetch("models", (signal) => api.listModels(signal), {
          staleTime: 30_000,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Models: ${errorMessage(error, "could not refresh")}`);
    } finally {
      setModelsLoading(false);
    }
  }, []);
  const refreshLoras = useCallback(async (force = true) => {
    setLorasLoading(true);
    try {
      setLoras(
        await appQueryCache.fetch("loras", (signal) => api.listLoras(signal), {
          staleTime: 30_000,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`LoRAs: ${errorMessage(error, "could not refresh")}`);
    } finally {
      setLorasLoading(false);
    }
  }, []);
  const refreshModelCatalog = useCallback(async () => {
    // A browser refresh doubles as a filesystem rescan, so checkpoints copied
    // into models/* while the backend is running appear without a server restart.
    try {
      await api.rescanModels();
      appQueryCache.invalidate("models");
      appQueryCache.invalidate("loras");
    } catch (error) {
      setReadError(`Model scan: ${errorMessage(error, "could not refresh")}`);
    }
    await Promise.all([refreshModels(), refreshLoras()]);
  }, [refreshLoras, refreshModels]);
  const refreshPresets = useCallback(async (force = true) => {
    setPresetsLoading(true);
    try {
      setPresets(
        await appQueryCache.fetch("presets", (signal) => api.listPresets(signal), {
          staleTime: 30_000,
          force,
        }),
      );
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Presets: ${errorMessage(error, "could not refresh")}`);
    } finally {
      setPresetsLoading(false);
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const next = await api.health();
      setHealth(next);
      if (
        next.security.exposed &&
        !next.security.token_required &&
        !securityWarningDismissed &&
        !postureToastShown.current
      ) {
        postureToastShown.current = true;
        toast.error("Security warning: backend is reachable from the network without HFAB_API_TOKEN.", {
          duration: 12000,
        });
      }
    } catch (error) {
      if (!isAbortError(error)) setReadError(`Health: ${errorMessage(error, "backend unavailable")}`);
    }
  }, [securityWarningDismissed]);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth, authRevision]);

  useEffect(
    () =>
      apiAuth.subscribe((event) => {
        setAuthTokenDraft(event.token);
        if (event.unauthorized) setAuthLocked(true);
      }),
    [],
  );

  useEffect(() => {
    appQueryCache.invalidate();
    void refreshJobs(false);
  }, [authRevision, refreshJobs]);

  useEffect(() => {
    if (view === "images") {
      if (catalogScanRevision.current !== authRevision) {
        catalogScanRevision.current = authRevision;
        void refreshModelCatalog();
      } else {
        void refreshModels(false);
        void refreshLoras(false);
      }
      void refreshImages(undefined, false);
      void refreshPresets(false);
    } else if (view === "video") {
      void refreshModels(false);
      void refreshVideos(false);
    } else if (view === "history") {
      void refreshModels(false);
      if (historyMode === "videos") void refreshVideos(false);
    } else if (view === "llm" || view === "code" || view === "rag") {
      void refreshModels(false);
    }
  }, [
    authRevision,
    historyMode,
    refreshImages,
    refreshLoras,
    refreshModelCatalog,
    refreshModels,
    refreshPresets,
    refreshVideos,
    view,
  ]);

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
            prev.map((j) =>
              j.id === e.job_id
                ? {
                    ...j,
                    progress: e.progress as number,
                    progress_note: typeof e.note === "string" ? e.note : j.progress_note,
                  }
                : j,
            ),
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
            toast.success(e.job_type === "upscale" ? "Upscale ready" : "Image ready", {
              onClick: () => setView("history"),
            });
          } else if (e.job_type === "video") {
            refreshVideos();
            toast.success("Video ready", {
              onClick: () => {
                setHistoryMode("videos");
                setView("history");
              },
            });
          }
          break;
        case "image.ready":
          refreshImages();
          setImageEpoch((n) => n + 1);
          break;
        case "video.ready":
          refreshVideos();
          break;
        case "mem.status": {
          const snap: MemSnapshot = {
            ram: (e.ram as MemSnapshot["ram"]) ?? null,
            vram: (e.vram as MemSnapshot["vram"]) ?? null,
          };
          setMem(snap);
          setMemHistory((prev) =>
            [...prev, { ts: e.ts, ram: snap.ram, vram: snap.vram, resident: gpuRef.current.model }].slice(
              -MEM_HISTORY_MAX,
            ),
          );
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
    [refreshJobs, refreshImages, refreshVideos],
  );

  const reconcileSnapshot = useCallback(async () => {
    const [jobsResult, gpuResult, imagesResult, videosResult, downloadsResult] = await Promise.allSettled([
      api.listJobs(),
      api.gpuStatus(),
      api.listImages(),
      api.listVideos(),
      api.downloadsState(),
    ]);
    if (jobsResult.status === "fulfilled") setJobs(jobsResult.value);
    if (gpuResult.status === "fulfilled") setGpu(gpuResult.value);
    if (imagesResult.status === "fulfilled") {
      setImages(imagesResult.value);
      setImageEpoch((value) => value + 1);
    }
    if (videosResult.status === "fulfilled") setVideos(videosResult.value);
    if (downloadsResult.status === "fulfilled") {
      window.dispatchEvent(new Event(SNAPSHOT_REFRESH_EVENT));
    }

    appQueryCache.invalidate("jobs");
    appQueryCache.invalidate("images:");
    appQueryCache.invalidate("videos");
    const failures = [jobsResult, gpuResult, imagesResult, videosResult, downloadsResult].filter(
      (result) => result.status === "rejected",
    );
    if (failures.length > 0) {
      const first = failures[0] as PromiseRejectedResult;
      const message = errorMessage(first.reason, "snapshot refresh failed");
      setReadError(`Live state may be stale: ${message}`);
      throw new Error(message);
    }
    setReadError(null);
  }, []);

  const syncInitialSnapshot = useCallback(async () => {
    try {
      const [nextJobs, nextGpu] = await Promise.all([api.listJobs(), api.gpuStatus()]);
      setJobs(nextJobs);
      setGpu(nextGpu);
      setReadError(null);
    } catch (error) {
      setReadError(`Live state unavailable: ${errorMessage(error, "snapshot refresh failed")}`);
      throw error;
    }
  }, []);

  const connection = useEvents(onEvent, {
    onConnect: syncInitialSnapshot,
    onReconnect: reconcileSnapshot,
  });
  const lockVisible = Boolean(health?.security.token_required && (authLocked || !apiAuth.getToken()));
  const saveToken = useCallback(async () => {
    try {
      await apiAuth.setToken(authTokenDraft);
      setAuthLocked(false);
      setAuthRevision((n) => n + 1);
    } catch (error) {
      setAuthLocked(true);
      toast.error(errorMessage(error, "could not establish a secure asset session"));
    }
  }, [authTokenDraft]);
  const clearToken = useCallback(async () => {
    try {
      await apiAuth.clearToken();
    } catch (error) {
      toast.error(errorMessage(error, "could not close the asset session"));
    } finally {
      setAuthTokenDraft("");
      setAuthLocked(false);
      setAuthRevision((n) => n + 1);
    }
  }, []);
  const dismissSecurityWarning = useCallback(() => {
    storage.set(SECURITY_WARNING_KEY, "1");
    setSecurityWarningDismissed(true);
  }, []);
  const dismissWelcome = useCallback(() => {
    storage.set(WELCOME_KEY, "1");
    setWelcomeSeen(true);
  }, []);
  const dismissStubBanner = useCallback(() => {
    storage.set(STUB_BANNER_KEY, "1");
    setStubBannerDismissed(true);
  }, []);

  const onFree = useCallback(async () => {
    try {
      await api.freeGpu();
    } catch (error) {
      toast.error(errorMessage(error, "Could not free GPU"));
    }
  }, []);
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
        await api.createJobs([
          { type: "upscale", model_id: upscaler.id, params: { image_id: image.id, scale } },
        ]);
        refreshJobs();
        toast.success(`Queued upscale ${scale}x`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Could not queue upscale");
      }
    },
    [models, refreshJobs],
  );

  // remember the last active tab
  useEffect(() => {
    storage.set(VIEW_KEY, view);
  }, [view]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme !== "light");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_META[theme]);
    storage.set(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const index = WORKSPACES.findIndex((workspace) => workspace.id === view);
    const next = WORKSPACES[(index + 1) % WORKSPACES.length];
    const timer = setTimeout(() => {
      if (next) prefetchWorkspace(next.id);
    }, 1_000);
    return () => clearTimeout(timer);
  }, [view]);

  // global shortcuts: Ctrl/Cmd+K opens the palette; Alt+1..N switches tabs
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (e.altKey && /^[1-9]$/.test(e.key)) {
        const target = tabIdsRef.current[Number(e.key) - 1];
        if (target) {
          e.preventDefault();
          setView(target);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const imageJobs = jobs.filter((j) => j.type === "image" || j.type === "upscale");
  const videoJobs = jobs.filter((j) => j.type === "video");
  const hasImageModels = models.some((m) => m.job_type === "image");
  const busy = jobs.some((j) => j.status === "running");
  // Changes whenever the pending queue changes, so the System tab can refetch
  // the swap-plan preview without polling.
  const queueKey = useMemo(
    () =>
      jobs
        .filter((j) => j.status === "queued" || j.status === "running")
        .map((j) => `${j.id}:${j.status}:${j.priority}`)
        .join("|"),
    [jobs],
  );

  return {
    arbiterNote,
    authLocked,
    authTokenDraft,
    busy,
    chatDraft,
    chatJump,
    clearToken,
    composerApply,
    connection,
    cycleTheme,
    dismissSecurityWarning,
    dismissStubBanner,
    dismissWelcome,
    editApply,
    gpu,
    hasImageModels,
    health,
    historyMode,
    imageEpoch,
    imageJobs,
    imageMode,
    images,
    lockVisible,
    loras,
    lorasLoading,
    mem,
    memHistory,
    models,
    modelsLoading,
    onEdit,
    onFree,
    onReproduce,
    onUpscale,
    paletteOpen,
    presets,
    presetsLoading,
    promptDraft,
    queueKey,
    readError,
    reconcileSnapshot,
    refreshJobs,
    refreshLoras,
    refreshModels,
    refreshPresets,
    refreshVideos,
    saveToken,
    securityWarningDismissed,
    setAuthTokenDraft,
    setChatDraft,
    setChatJump,
    setHistoryMode,
    setImageMode,
    setPaletteOpen,
    setPromptDraft,
    setView,
    stubBannerDismissed,
    tabIdsRef,
    theme,
    videoJobs,
    videos,
    view,
    welcomeSeen,
  };
}
