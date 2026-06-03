import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server proxies API + WebSocket to the FastAPI backend (port 8260),
// so the browser only ever talks to the Vite origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8260", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8260", ws: true },
    },
  },
});
