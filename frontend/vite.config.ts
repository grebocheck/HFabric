import { defineConfig } from "vite";
import type { ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const BACKEND = "127.0.0.1:8260";

// Errors that just mean "the backend isn't up yet" or "this socket closed" —
// all transient and self-healing (the client reconnects once uvicorn binds).
// We don't want them spamming the dev console on every startup; we surface a
// single throttled hint instead so a genuinely-down backend is still visible.
const TRANSIENT = new Set(["ECONNREFUSED", "ECONNRESET", "ECONNABORTED", "ETIMEDOUT", "EPIPE"]);

let lastHint = 0;
function quietProxyErrors(proxy: { on(ev: "error", cb: (err: unknown) => void): void }) {
  proxy.on("error", (err) => {
    const code = (err as { code?: string } | null)?.code;
    if (code && TRANSIENT.has(code)) {
      const now = Date.now();
      if (now - lastHint > 5000) {
        lastHint = now;
        console.log(`[vite] backend ${BACKEND} not reachable yet — proxy will retry…`);
      }
      return;
    }
    console.error("[vite] proxy error:", err);
  });
}

// Dev server proxies API + WebSocket to the FastAPI backend (port 8260),
// so the browser only ever talks to the Vite origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://${BACKEND}`,
        changeOrigin: true,
        configure: (proxy) => quietProxyErrors(proxy),
      } satisfies ProxyOptions,
      "/ws": {
        target: `ws://${BACKEND}`,
        ws: true,
        configure: (proxy) => quietProxyErrors(proxy),
      } satisfies ProxyOptions,
    },
  },
});
