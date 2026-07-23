import { Badge } from "./Badge";
import { DiagnosticsCompact, Panel } from "./VoicePanelControls";
import type { MeterSample } from "./VoiceMeters";
import { formatMs } from "./voiceHelpers";
import type { VoiceEngineStatus } from "../types";

export function VoiceDiagnosticsPanel({
  meterHistory,
  status,
}: {
  meterHistory: MeterSample[];
  status: VoiceEngineStatus | null;
}) {
  return (
    <Panel
      title="Diagnostics"
      aside={<Badge>{formatMs(status?.metrics.total_ms ?? status?.metrics.chunk_ms)}</Badge>}
    >
      <DiagnosticsCompact status={status} samples={meterHistory} />
    </Panel>
  );
}
