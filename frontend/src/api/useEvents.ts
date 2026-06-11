import { useEffect, useRef, useState } from "react";
import { apiAuth } from "./client";
import type { BusEvent } from "../types";

/**
 * Subscribes to the backend event bus over WebSocket and invokes `onEvent`
 * for every message. Auto-reconnects with a short backoff. Exposes a simple
 * `connected` flag for the UI.
 */
export function useEvents(onEvent: (e: BusEvent) => void): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const [token, setToken] = useState(() => apiAuth.getToken());
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => apiAuth.subscribe((event) => setToken(event.token)), []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const query = token ? `?token=${encodeURIComponent(token)}` : "";
      ws = new WebSocket(`${proto}://${location.host}/ws${query}`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (ev) => {
        try {
          cbRef.current(JSON.parse(ev.data) as BusEvent);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [token]);

  return { connected };
}
