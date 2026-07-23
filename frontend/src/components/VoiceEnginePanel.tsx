import type { VoiceEngineStatus, VoiceModel } from "../types";
import { Badge } from "./Badge";
import { Select } from "./Select";
import { Row, VoiceSlotList } from "./VoicePanelParts";
import { ModelBadges, Panel, StatusTile, VoiceOption, assetTitle, modelDirHint } from "./VoicePanelControls";
import { formatBytes } from "./voiceHelpers";

type VoiceEnginePanelProps = {
  assetsFound: number;
  busy: string;
  denoiseDtlnMissing: boolean;
  loadedModel: VoiceModel | undefined;
  modelId: string;
  models: VoiceModel[];
  onFetchAssets: () => void;
  onFetchDtlnAssets: () => void;
  onModelChange: (modelId: string) => void;
  onModelListToggle: () => void;
  onModelSelect: (modelId: string) => void;
  ready: boolean;
  selected: VoiceModel | undefined;
  status: VoiceEngineStatus | null;
  totalAssets: number;
  voicesOpen: boolean;
  voiceOptions: Array<{ value: string; label: string; hint: string }>;
};

export function VoiceEnginePanel({
  assetsFound,
  busy,
  denoiseDtlnMissing,
  loadedModel,
  modelId,
  models,
  onFetchAssets,
  onFetchDtlnAssets,
  onModelChange,
  onModelListToggle,
  onModelSelect,
  ready,
  selected,
  status,
  totalAssets,
  voicesOpen,
  voiceOptions,
}: VoiceEnginePanelProps) {
  return (
    <Panel
      title="Voice And Engine"
      aside={
        <Badge color={ready ? "bg-emerald-700/55 text-emerald-100" : "bg-amber-600/40 text-amber-100"}>
          {ready ? "ready" : "missing"}
        </Badge>
      }
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <StatusTile label="Engine" value={status?.engine ?? "native-rvc"} tone={ready ? "good" : "warn"} />
        <StatusTile
          label="Mode"
          value={status?.stub ? "stub" : "real"}
          tone={status?.stub ? "info" : "neutral"}
        />
        <StatusTile label="Device" value={status?.device ?? "..."} />
        <StatusTile
          label="Assets"
          value={`${assetsFound}/${totalAssets || "..."}`}
          tone={ready ? "good" : "warn"}
        />
      </div>

      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <div className="text-xs font-medium text-ui-muted">Voice model</div>
          <Badge>{models.length} slots</Badge>
        </div>
        <Select
          ariaLabel="Voice model"
          value={modelId}
          onChange={onModelChange}
          placeholder="no voices"
          options={voiceOptions}
          renderOption={(option) => <VoiceOption option={option} models={models} />}
        />
      </div>

      <div className="ui-card mt-3 rounded-md p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-ui">
              {selected?.name ?? "No model selected"}
            </div>
            <div className="mt-1 truncate text-xs text-ui-subtle">
              loaded: {loadedModel?.name ?? status?.loaded_model ?? "none"}
            </div>
          </div>
          <ModelBadges model={selected} />
        </div>
        {selected ? (
          <div className="mt-3 grid gap-1.5 text-sm sm:grid-cols-2">
            <Row label="Slot" value={selected.slot} />
            <Row label="Size" value={formatBytes(selected.size_bytes)} />
            <Row label="Source" value={selected.source ?? "local"} />
            <Row label="Pitch" value={selected.f0 ? "active" : "model-limited"} ok={selected.f0} />
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onModelListToggle}
        className="ui-button mt-3 w-full rounded-md px-2.5 py-1.5 text-left text-xs font-medium"
      >
        {voicesOpen ? "Hide model list" : "Show model list"}
      </button>
      {voicesOpen ? (
        <VoiceSlotList models={models} modelId={modelId} modelDir={modelDirHint} onSelect={onModelSelect} />
      ) : null}

      <div className="mt-3 grid gap-1.5">
        {(status?.assets ?? []).map((asset) => (
          <div
            key={asset.name}
            title={assetTitle(asset)}
            className="ui-card flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5"
          >
            <span className="min-w-0 truncate text-sm text-ui-muted">{asset.name}</span>
            <span className="flex shrink-0 items-center gap-1.5">
              <Badge
                color={
                  asset.found
                    ? "bg-success-bg text-success-fg"
                    : asset.optional
                      ? "ui-chip"
                      : "bg-warn-bg text-warn-fg"
                }
              >
                {asset.found ? "found" : asset.optional ? "optional" : "missing"}
              </Badge>
              {asset.source ? <Badge>{asset.source}</Badge> : null}
            </span>
          </div>
        ))}
        {!status?.assets?.length ? (
          <div className="text-sm text-ui-subtle">Loading native assets...</div>
        ) : null}
      </div>

      <AssetDownloadNotice status={status} busy={busy} onFetch={onFetchAssets} />

      {denoiseDtlnMissing ? (
        <div className="ui-card mt-3 rounded-md p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-medium text-ui">Optional DTLN denoise assets</div>
              <div className="mt-1 text-xs leading-5 text-ui-subtle">
                Enables the DTLN input denoise mode; files land in{" "}
                <code className="rounded bg-control-active px-1">models/voice/pretrain/denoise</code>.
              </div>
            </div>
            <button
              type="button"
              onClick={onFetchDtlnAssets}
              disabled={busy === "dtln-assets" || status?.asset_download?.state === "running"}
              className="ui-button rounded-md px-3 py-1.5 text-xs font-medium"
            >
              {busy === "dtln-assets" ? "Starting..." : "Download DTLN"}
            </button>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function AssetDownloadNotice({
  status,
  busy,
  onFetch,
}: {
  status: VoiceEngineStatus | null;
  busy: string;
  onFetch: () => void;
}) {
  const download = status?.asset_download ?? null;
  const missingRequired = (status?.assets ?? []).filter((asset) => !asset.found && !asset.optional);
  if (missingRequired.length === 0 && download?.state !== "running") return null;

  return (
    <div className="mt-3 rounded-md border border-amber-400/30 bg-amber-400/10 p-3">
      <div className="text-sm font-medium text-amber-100">Shared voice assets needed</div>
      <p className="mt-1 text-xs leading-5 text-amber-100/80">
        Every voice model uses a shared ContentVec encoder (and RMVPE for the quality pitch path). Fetch them
        once into <code className="rounded bg-control-active px-1">models/voice/pretrain</code>.
      </p>
      {download?.state === "running" ? (
        <div className="mt-2 text-xs text-amber-100/80">
          Downloading {download.current?.label ?? "voice assets"}…{" "}
          {download.progress.total ? `${download.progress.done}/${download.progress.total}` : ""}
        </div>
      ) : (
        <button
          type="button"
          onClick={onFetch}
          disabled={busy === "assets"}
          className="mt-2 rounded-md bg-amber-500/80 px-3 py-1.5 text-xs font-medium text-black transition hover:bg-amber-400 disabled:opacity-40"
        >
          {busy === "assets" ? "Starting…" : "Download voice assets (~560 MB)"}
        </button>
      )}
      {download?.state === "error" ? (
        <div className="mt-2 text-xs text-red-200">
          {download.message} — retry here or rerun the platform setup when the network is stable.
        </div>
      ) : null}
    </div>
  );
}
