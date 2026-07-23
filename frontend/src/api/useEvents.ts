import { useEffect, useRef, useState } from "react";
import { apiAuth } from "./client";
import type { BusEvent } from "../types";

export type EventConnectionState =
  | "connecting"
  | "reconnecting"
  | "offline"
  | "syncing"
  | "ready"
  | "degraded";

export type EventConnection = {
  connected: boolean;
  state: EventConnectionState;
  lastSyncAt: number | null;
  reconnectAttempts: number;
};

export function reconnectDelay(
  attempt: number,
  random = Math.random,
  baseDelayMs = 500,
  maxDelayMs = 30_000,
): number {
  const capped = Math.min(maxDelayMs, baseDelayMs * 2 ** Math.max(0, attempt));
  // ±20% jitter prevents several tabs from reconnecting in lockstep.
  return Math.round(capped * (0.8 + random() * 0.4));
}

/**
 * Subscribes to the event bus and reconciles authoritative state after every
 * successful connection. Retries back off with jitter and pause while the
 * browser is offline or the tab is hidden.
 */
export function useEvents(
  onEvent: (event: BusEvent) => void,
  {
    onConnect,
    onReconnect,
    baseDelayMs = 500,
    maxDelayMs = 30_000,
    random = Math.random,
  }: {
    onConnect?: () => void | Promise<void>;
    onReconnect?: () => void | Promise<void>;
    baseDelayMs?: number;
    maxDelayMs?: number;
    random?: () => number;
  } = {},
): EventConnection {
  const [connection, setConnection] = useState<EventConnection>({
    connected: false,
    state: "connecting",
    lastSyncAt: null,
    reconnectAttempts: 0,
  });
  const [token, setToken] = useState(() => apiAuth.getToken());
  const eventRef = useRef(onEvent);
  const connectRef = useRef(onConnect);
  const reconnectRef = useRef(onReconnect);
  const randomRef = useRef(random);
  eventRef.current = onEvent;
  connectRef.current = onConnect;
  reconnectRef.current = onReconnect;
  randomRef.current = random;

  useEffect(() => apiAuth.subscribe((event) => setToken(event.token)), []);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let connecting = false;
    let attempt = 0;
    let syncRun = 0;
    let hasOpened = false;

    const canRetry = () => navigator.onLine !== false && document.visibilityState !== "hidden";

    const update = (patch: Partial<EventConnection>) => {
      if (!stopped) setConnection((current) => ({ ...current, ...patch }));
    };

    const clearRetry = () => {
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = null;
    };

    const connect = () => {
      clearRetry();
      if (stopped || connecting || socket) return;
      if (!canRetry()) {
        update({ connected: false, state: "offline" });
        return;
      }

      connecting = true;
      update({
        connected: false,
        state: attempt > 0 ? "reconnecting" : "connecting",
        reconnectAttempts: attempt,
      });
      const proto = location.protocol === "https:" ? "wss" : "ws";

      try {
        socket = new WebSocket(`${proto}://${location.host}/ws`);
      } catch (error) {
        connecting = false;
        socket = null;
        console.warn("WebSocket connection could not start", error);
        scheduleReconnect();
        return;
      }

      const currentSocket = socket;
      currentSocket.onopen = () => {
        connecting = false;
        attempt = 0;
        const currentSync = ++syncRun;
        const sync = hasOpened ? reconnectRef.current : connectRef.current;
        hasOpened = true;
        update({ connected: true, state: sync ? "syncing" : "ready", reconnectAttempts: 0 });
        if (!sync) {
          update({ lastSyncAt: Date.now() });
          return;
        }
        Promise.resolve(sync())
          .then(() => {
            if (!stopped && socket === currentSocket && currentSync === syncRun) {
              update({ connected: true, state: "ready", lastSyncAt: Date.now() });
            }
          })
          .catch((error: unknown) => {
            console.error("State reconciliation after WebSocket reconnect failed", error);
            if (!stopped && socket === currentSocket && currentSync === syncRun) {
              update({ connected: true, state: "degraded" });
            }
          });
      };
      currentSocket.onmessage = (event) => {
        try {
          eventRef.current(JSON.parse(event.data) as BusEvent);
        } catch (error) {
          console.warn("Ignored malformed WebSocket event", error);
        }
      };
      currentSocket.onclose = () => {
        if (socket !== currentSocket) return;
        socket = null;
        connecting = false;
        syncRun += 1;
        update({ connected: false });
        scheduleReconnect();
      };
      currentSocket.onerror = () => currentSocket.close();
    };

    function scheduleReconnect() {
      if (stopped || retryTimer !== null) return;
      if (!canRetry()) {
        update({ connected: false, state: "offline", reconnectAttempts: attempt });
        return;
      }
      const delay = reconnectDelay(attempt, randomRef.current, baseDelayMs, maxDelayMs);
      attempt += 1;
      update({ connected: false, state: "reconnecting", reconnectAttempts: attempt });
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, delay);
    }

    const resume = () => {
      if (!canRetry()) {
        clearRetry();
        if (!socket && !connecting) update({ connected: false, state: "offline" });
        return;
      }
      if (!socket && !connecting) connect();
    };
    const handleOffline = () => {
      clearRetry();
      update({ connected: false, state: "offline" });
      socket?.close();
    };

    window.addEventListener("online", resume);
    window.addEventListener("offline", handleOffline);
    document.addEventListener("visibilitychange", resume);
    const assetSessionRefresh = window.setInterval(() => {
      void apiAuth.refreshAssetSession().catch((error: unknown) => {
        console.warn("Asset session refresh failed", error);
      });
    }, 8 * 60 * 1000);
    if (token) {
      void apiAuth.refreshAssetSession()
        .catch((error: unknown) => {
          console.warn("Initial asset session refresh failed", error);
        })
        .finally(connect);
    } else {
      connect();
    }

    return () => {
      stopped = true;
      syncRun += 1;
      clearRetry();
      window.removeEventListener("online", resume);
      window.removeEventListener("offline", handleOffline);
      document.removeEventListener("visibilitychange", resume);
      window.clearInterval(assetSessionRefresh);
      socket?.close();
      socket = null;
    };
  }, [baseDelayMs, maxDelayMs, token]);

  return connection;
}
