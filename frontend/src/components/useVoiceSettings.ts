import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import type { VoiceEngineSettingsUpdate, VoiceEngineStatus } from "../types";
import { parseApiError } from "./VoicePanelControls";
import type { RoutingApplyState } from "./VoicePanelParts";
import {
  nativeRoutingSettingsPatch,
  nativeSettingsToVoicePatch,
  nativeSettingsToVoiceState,
  nativeTuningSettingsPatch,
  type VoiceControlState,
} from "./voiceHelpers";

type SaveSettings = (patch: VoiceEngineSettingsUpdate) => Promise<VoiceEngineStatus>;
type Revisions = Partial<Record<keyof VoiceControlState, number>>;
export type VoiceOperation = (save: SaveSettings) => Promise<VoiceEngineStatus | null | void>;

export function useVoiceSettings() {
  const [state, setState] = useState(() => {
    const draft = nativeSettingsToVoiceState({});
    return { status: null as VoiceEngineStatus | null, draft, confirmed: draft, revisions: {} as Revisions };
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [routingApplyState, setRoutingApplyState] = useState<RoutingApplyState>("idle");
  const alive = useRef(true);
  const statusVersion = useRef(0);
  const pending = useRef(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const revisions = useRef<Revisions>({});
  const routingAttempt = useRef<string | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const updateDraft = useCallback((patch: Partial<VoiceControlState>) => {
    routingAttempt.current = null;
    const next = { ...revisions.current };
    for (const key of Object.keys(patch) as Array<keyof VoiceControlState>) next[key] = (next[key] ?? 0) + 1;
    revisions.current = next;
    setState((current) => ({ ...current, draft: { ...current.draft, ...patch }, revisions: next }));
  }, []);

  const receive = useCallback(
    (status: VoiceEngineStatus, submitted: Partial<VoiceControlState> = {}, sent: Revisions = {}) => {
      if (!alive.current) return;
      setState((current) => {
        const confirmed = nativeSettingsToVoiceState(status.settings);
        const draft = { ...confirmed };
        for (const key of Object.keys(draft) as Array<keyof VoiceControlState>) {
          const changedSinceSend = key in submitted && current.revisions[key] !== sent[key];
          const edited = changedSinceSend || current.draft[key] !== current.confirmed[key];
          const acknowledged = key in submitted && !changedSinceSend && current.draft[key] === submitted[key];
          if (edited && !acknowledged) Object.assign(draft, { [key]: current.draft[key] });
        }
        // Polling metrics should not restart a pending routing debounce.
        const unchanged = (Object.keys(draft) as Array<keyof VoiceControlState>).every(
          (key) => draft[key] === current.draft[key],
        );
        return { ...current, status, confirmed, draft: unchanged ? current.draft : draft };
      });
    },
    [],
  );

  const refresh = useCallback(async () => {
    if (pending.current) return null;
    const request = ++statusVersion.current;
    const current = () => alive.current && !pending.current && statusVersion.current === request;
    try {
      const next = await api.voiceEngineStatus();
      if (!current()) return null;
      receive(next);
      setError("");
      return next;
    } catch (err) {
      if (current()) setError(parseApiError(err) || "failed to load native voice status");
      return null;
    }
  }, [receive]);

  const run = useCallback(
    (label: string, operation: VoiceOperation): Promise<boolean> => {
      ++pending.current;
      ++statusVersion.current;
      const task = queue.current
        .then(async () => {
          if (!alive.current) return false;
          setBusy(label);
          setError("");
          try {
            const next = await operation(async (patch) => {
              const sent = revisions.current;
              const result = await api.voiceEngineSettings(patch);
              receive(result, nativeSettingsToVoicePatch(patch), sent);
              return result;
            });
            if (next) receive(next);
            return true;
          } catch (err) {
            if (alive.current) setError(parseApiError(err));
            return false;
          }
        })
        .finally(() => {
          --pending.current;
          if (alive.current && !pending.current) setBusy("");
        });
      queue.current = task;
      return task;
    },
    [receive],
  );

  const applySettings = useCallback(
    (label: string, patch: VoiceEngineSettingsUpdate) => run(label, (save) => save(patch)),
    [run],
  );

  const { status, draft, confirmed } = state;
  const statusLoaded = Boolean(status);
  const routingPatch = useMemo(() => nativeRoutingSettingsPatch(draft), [draft]);
  const currentRoutingKey = JSON.stringify(routingPatch);
  const confirmedRoutingKey = JSON.stringify(nativeRoutingSettingsPatch(confirmed));
  const tuningDirty =
    JSON.stringify(nativeTuningSettingsPatch(draft)) !== JSON.stringify(nativeTuningSettingsPatch(confirmed));

  useEffect(() => {
    if (!statusLoaded) return;
    if (currentRoutingKey === confirmedRoutingKey) {
      routingAttempt.current = null;
      setRoutingApplyState((current) => (current === "idle" ? "idle" : "applied"));
      return;
    }
    if (busy || routingAttempt.current === currentRoutingKey) return;
    setRoutingApplyState("pending");
    const id = window.setTimeout(async () => {
      routingAttempt.current = currentRoutingKey;
      setRoutingApplyState("applying");
      const success = await applySettings("routing", routingPatch);
      if (alive.current && routingAttempt.current === currentRoutingKey) {
        setRoutingApplyState(success ? "applied" : "error");
      }
    }, 400);
    return () => window.clearTimeout(id);
  }, [applySettings, busy, confirmedRoutingKey, currentRoutingKey, routingPatch, statusLoaded]);

  return {
    status,
    draft,
    error,
    setError,
    busy,
    refresh,
    updateDraft,
    tuningDirty,
    routingApplyState,
    run,
    applySettings,
  };
}
