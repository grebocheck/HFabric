import { lazy, Suspense, useMemo, type ReactNode } from "react";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { Dialog } from "./components/Dialog";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ModelStatus } from "./components/ModelStatus";
import { ToastHost } from "./components/Toast";
import { Welcome } from "./components/Welcome";
import { SkeletonRows } from "./components/WorkspaceChrome";
import { useAppController } from "./useAppController";
import {
  loadChat,
  loadCode,
  loadEdit,
  loadGallery,
  loadImages,
  loadModels,
  loadNotes,
  loadQueue,
  loadRag,
  loadResult,
  loadSettings,
  loadSystem,
  loadTranscription,
  loadTts,
  loadVideo,
  loadVoice,
  prefetchWorkspace,
} from "./workspaceLoaders";
import { VIEW_IDS, WORKSPACES, type View } from "./workspaces";

const ChatPanel = lazy(() => loadChat().then((module) => ({ default: module.ChatPanel })));
const CodePanel = lazy(() => loadCode().then((module) => ({ default: module.CodePanel })));
const EditWorkspace = lazy(() => loadEdit().then((module) => ({ default: module.EditWorkspace })));
const ImageComposer = lazy(() => loadImages().then((module) => ({ default: module.ImageComposer })));
const Gallery = lazy(() => loadGallery().then((module) => ({ default: module.Gallery })));
const ModelManager = lazy(() => loadModels().then((module) => ({ default: module.ModelManager })));
const NotesPanel = lazy(() => loadNotes().then((module) => ({ default: module.NotesPanel })));
const QueuePanel = lazy(() => loadQueue().then((module) => ({ default: module.QueuePanel })));
const ResultPreview = lazy(() => loadResult().then((module) => ({ default: module.ResultPreview })));
const RagPanel = lazy(() => loadRag().then((module) => ({ default: module.RagPanel })));
const SettingsPanel = lazy(() => loadSettings().then((module) => ({ default: module.SettingsPanel })));
const SystemPanel = lazy(() => loadSystem().then((module) => ({ default: module.SystemPanel })));
const TranscriptionPanel = lazy(() =>
  loadTranscription().then((module) => ({ default: module.TranscriptionPanel })),
);
const TtsPanel = lazy(() => loadTts().then((module) => ({ default: module.TtsPanel })));
const VoicePanel = lazy(() => loadVoice().then((module) => ({ default: module.VoicePanel })));
const VideoComposer = lazy(() => loadVideo().then((module) => ({ default: module.VideoComposer })));
const VideoHistory = lazy(() => loadVideo().then((module) => ({ default: module.VideoHistory })));
const VideoResult = lazy(() => loadVideo().then((module) => ({ default: module.VideoResult })));

export default function App() {
  const {
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
  } = useAppController();

  const workspaceRenderers: Record<View, () => ReactNode> = {
    images: () => (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2 sm:p-4">
        <div
          role="tablist"
          aria-label="Image mode"
          className="mb-3 flex shrink-0 items-center gap-1 self-start rounded-lg border border-line bg-control p-1"
        >
          {(
            [
              ["generate", "Generate"],
              ["edit", "Edit"],
            ] as const
          ).map(([id, modeLabel]) => (
            <button
              key={id}
              role="tab"
              aria-selected={imageMode === id}
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
          <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(320px,390px)_minmax(0,1fr)_minmax(280px,330px)] grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden max-[1240px]:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] max-[1240px]:grid-rows-[minmax(0,1fr)_300px] max-[860px]:block max-[860px]:overflow-x-hidden max-[860px]:overflow-y-auto max-[480px]:gap-3">
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
              lorasLoading={lorasLoading}
              presets={presets}
              presetsLoading={presetsLoading}
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
    video: () => (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2 sm:p-4">
        <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(320px,390px)_minmax(0,1fr)_minmax(280px,330px)] grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden max-[1240px]:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] max-[1240px]:grid-rows-[minmax(0,1fr)_300px] max-[860px]:block max-[860px]:overflow-x-hidden max-[860px]:overflow-y-auto">
          <VideoComposer
            models={models}
            modelsLoading={modelsLoading}
            onQueued={refreshJobs}
            onGetModels={() => setView("models")}
          />
          <VideoResult
            videos={videos}
            generating={videoJobs.some((job) => job.status === "running")}
            onOpenHistory={() => {
              setHistoryMode("videos");
              setView("history");
            }}
          />
          <QueuePanel jobs={videoJobs} onChanged={refreshJobs} note={arbiterNote} />
        </div>
      </main>
    ),
    history: () => (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2 sm:p-4">
        <div
          role="tablist"
          aria-label="History type"
          className="mb-3 flex shrink-0 items-center gap-1 self-start rounded-lg border border-line bg-control p-1"
        >
          {(
            [
              ["images", "Images"],
              ["videos", "Videos"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={historyMode === id}
              onClick={() => setHistoryMode(id)}
              className={`rounded-md px-3 py-1 text-sm font-medium transition ${historyMode === id ? "bg-accent text-ui-inverse shadow-sm" : "text-ui-muted hover:bg-control-hover hover:text-ui"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          {historyMode === "images" ? (
            <Gallery
              models={models}
              reloadSignal={imageEpoch}
              onReproduce={onReproduce}
              onEdit={onEdit}
              onUpscale={onUpscale}
            />
          ) : (
            <VideoHistory videos={videos} onDeleted={refreshVideos} />
          )}
        </div>
      </main>
    ),
    llm: () => (
      <main className="flex-1 overflow-hidden p-4">
        <ChatPanel
          models={models}
          modelsLoading={modelsLoading}
          jump={chatJump}
          draft={chatDraft}
          setDraft={setChatDraft}
        />
      </main>
    ),
    notes: () => (
      <main className="flex-1 overflow-hidden p-4">
        <NotesPanel />
      </main>
    ),
    tts: () => (
      <main className="flex-1 overflow-hidden p-4">
        <TtsPanel />
      </main>
    ),
    transcription: () => (
      <main className="flex-1 overflow-hidden p-4">
        <TranscriptionPanel />
      </main>
    ),
    code: () => (
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
    rag: () => (
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
    voice: () => (
      <main className="flex-1 overflow-hidden p-4">
        <VoicePanel />
      </main>
    ),
    models: () => (
      <main className="flex-1 overflow-hidden p-4">
        <ModelManager
          onModelsChanged={() => {
            void refreshModels();
            void refreshLoras();
          }}
        />
      </main>
    ),
    system: () => (
      <main className="flex-1 overflow-hidden p-4">
        <SystemPanel
          gpu={gpu}
          mem={mem}
          history={memHistory}
          note={arbiterNote}
          queueKey={queueKey}
          imageSignal={imageEpoch}
          version={health?.version}
        />
      </main>
    ),
    settings: () => (
      <main className="flex-1 overflow-hidden p-4">
        <SettingsPanel />
      </main>
    ),
  };
  const activeRenderer = workspaceRenderers[view] ?? workspaceRenderers.images;
  tabIdsRef.current = [...VIEW_IDS];

  const commands = useMemo<Command[]>(
    () => [
      ...WORKSPACES.map((workspace) => ({
        id: `go-${workspace.id}`,
        label: `Go to ${workspace.label}`,
        hint: "tab",
        run: () => setView(workspace.id),
      })),
      { id: "theme", label: "Cycle Theme", hint: theme, run: cycleTheme },
      { id: "free", label: "Free GPU", hint: "unload models", run: onFree },
    ],
    [cycleTheme, onFree, setView, theme],
  );

  return (
    <div className="flex h-dvh min-w-0 flex-col overflow-hidden">
      <ModelStatus
        gpu={gpu}
        connected={connection.connected}
        connectionState={connection.state}
        lastSyncAt={connection.lastSyncAt}
        busy={busy}
        mem={mem}
        view={view}
        theme={theme}
        tabs={[...WORKSPACES]}
        onView={setView}
        onPrefetch={prefetchWorkspace}
        onFree={onFree}
        onTheme={cycleTheme}
        onPalette={() => setPaletteOpen(true)}
      />

      {health?.security.exposed && !health.security.token_required && !securityWarningDismissed ? (
        <div className="flex items-center gap-3 border-b border-error-border bg-error-bg px-4 py-2 text-sm text-error-fg max-[480px]:items-start">
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
        <div className="flex items-center gap-3 border-b border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-fg max-[480px]:items-start">
          <span className="min-w-0 flex-1">
            STUB mode — results are mock placeholders. Install the GPU dependencies and restart for real
            generation.
          </span>
          <button
            onClick={dismissStubBanner}
            className="rounded border border-warn-border px-2 py-1 text-xs text-warn-fg hover:bg-warn-bg"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {readError ? (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-3 border-b border-warn-border bg-warn-bg px-4 py-2 text-xs text-warn-fg max-[480px]:items-start"
        >
          <span className="min-w-0 flex-1">{readError}</span>
          <button
            onClick={() => {
              void reconcileSnapshot().catch((error: unknown) => {
                console.warn("Manual snapshot retry failed", error);
              });
            }}
            className="ui-button shrink-0 rounded px-2 py-1 text-xs"
          >
            Retry
          </button>
        </div>
      ) : null}

      <div
        id={`workspace-panel-${view}`}
        role="tabpanel"
        aria-labelledby={`workspace-tab-${view}`}
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      >
        <ErrorBoundary key={view} compact fallbackTitle="This workspace could not render">
          <Suspense fallback={<WorkspaceLoading />}>{activeRenderer()}</Suspense>
        </ErrorBoundary>
      </div>

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

function WorkspaceLoading() {
  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-hidden p-2 sm:p-4" aria-busy="true">
      <div className="h-full rounded-lg border border-line bg-surface p-4 shadow-panel">
        <span className="sr-only">Loading workspace</span>
        <SkeletonRows rows={6} />
      </div>
    </main>
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
    <Dialog
      open
      title="API token required"
      closeOnBackdrop={false}
      closeOnEscape={false}
      panelClassName="flex w-full max-w-sm flex-col"
      titleClassName="px-4 pt-4 text-base font-semibold text-ui-strong"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="min-h-0 overflow-y-auto px-4 pb-4"
      >
        <p className="mt-1 text-sm leading-5 text-ui-muted">
          Enter the HFAB_API_TOKEN configured for this backend.
        </p>
        {unauthorized ? (
          <p className="mt-2 text-xs text-error-fg">The last request was rejected with 401.</p>
        ) : null}
        <input
          type="password"
          value={token}
          onChange={(event) => onToken(event.target.value)}
          aria-label="API token"
          autoComplete="current-password"
          className="ui-field mt-4 w-full rounded-md px-3 py-2 text-sm"
          placeholder="Bearer token"
        />
        <div className="mt-4 flex justify-end gap-2 max-[360px]:flex-col-reverse">
          <button
            type="button"
            onClick={onClear}
            className="ui-button rounded-md px-3 py-1.5 text-sm max-[360px]:w-full"
          >
            Clear
          </button>
          <button
            type="submit"
            disabled={!token.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-ui-inverse hover:bg-accent-hover disabled:opacity-40 max-[360px]:w-full"
          >
            Unlock
          </button>
        </div>
      </form>
    </Dialog>
  );
}
