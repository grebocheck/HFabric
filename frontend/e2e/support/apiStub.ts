import type { Page, Route } from "@playwright/test";

type StubOptions = {
  fakeWebSocket?: boolean;
  routes?: Record<string, { status?: number; body: unknown }>;
  tokenRequired?: boolean;
  welcomeSeen?: boolean;
};

export type ObservedRequest = {
  method: string;
  path: string;
  authorization: string | undefined;
};

const EMPTY_GPU = {
  resident: null,
  model_id: null,
  model: null,
  family: null,
  warm: [],
  lanes: [],
  pin: null,
};

const ARRAY_ROUTES = new Set([
  "/api/chat/conversations",
  "/api/images",
  "/api/jobs",
  "/api/loras",
  "/api/models",
  "/api/notes",
  "/api/presets",
  "/api/videos",
]);

function payloadFor(
  route: Route,
  tokenRequired: boolean,
  overrides: StubOptions["routes"] = {},
): { status: number; body: unknown } {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  const override = overrides[`${request.method()} ${path}`] ?? overrides[path];
  if (override) return { status: override.status ?? 200, body: override.body };

  if (path === "/api/health") {
    return {
      status: 200,
      body: {
        status: "ok",
        version: "e2e",
        stub_mode: true,
        models: 0,
        gpu: EMPTY_GPU,
        mem: { ram: null, vram: null },
        security: { exposed: false, token_required: tokenRequired },
      },
    };
  }
  if (path === "/api/gpu") return { status: 200, body: EMPTY_GPU };
  if (path === "/api/models/rescan") {
    return {
      status: 200,
      body: { models: 0, image_models: 0, video_models: 0, llm_models: 0, loras: 0 },
    };
  }
  if (path === "/api/images/stats") {
    return {
      status: 200,
      body: {
        total: 0,
        favorites: 0,
        models: [],
        families: [],
        sizes: [],
        loras: [],
        tags: [],
      },
    };
  }
  if (path === "/api/jobs/plan") {
    return {
      status: 200,
      body: { queued: 0, swaps: 0, current_model: null, steps: [] },
    };
  }
  if (ARRAY_ROUTES.has(path)) return { status: 200, body: [] };
  if (path === "/api/downloads") {
    return {
      status: 200,
      body: { items: [], active: [], disk: { free_mb: null, models_root: "" } },
    };
  }
  return { status: 200, body: {} };
}

export async function installApiStub(page: Page, options: StubOptions = {}): Promise<ObservedRequest[]> {
  const observed: ObservedRequest[] = [];
  const tokenRequired = options.tokenRequired ?? false;

  await page.addInitScript(
    ({ welcomeSeen }) => {
      if (window.sessionStorage.getItem("hfabric.e2e.initialized") !== "1") {
        window.localStorage.clear();
        if (welcomeSeen) window.localStorage.setItem("hfabric.welcome.seen", "1");
        window.sessionStorage.setItem("hfabric.e2e.initialized", "1");
      }
    },
    { welcomeSeen: options.welcomeSeen ?? false },
  );

  if (options.fakeWebSocket) {
    await page.addInitScript(() => {
      type SocketHandler = ((event: Event) => void) | null;
      class StubWebSocket {
        static latest: StubWebSocket | null = null;
        onopen: SocketHandler = null;
        onclose: SocketHandler = null;
        onerror: SocketHandler = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        private closed = false;

        constructor() {
          StubWebSocket.latest = this;
          setTimeout(() => {
            if (!this.closed) this.onopen?.(new Event("open"));
          }, 10);
        }

        close() {
          if (this.closed) return;
          this.closed = true;
          this.onclose?.(new Event("close"));
        }
      }

      Object.defineProperty(window, "WebSocket", {
        configurable: true,
        value: StubWebSocket,
      });
      (window as typeof window & { __closeHfabricSocket?: () => void }).__closeHfabricSocket = () => {
        StubWebSocket.latest?.close();
      };
    });
  }

  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      observed.push({
        method: request.method(),
        path: new URL(request.url()).pathname,
        authorization: request.headers().authorization,
      });
      const response = payloadFor(route, tokenRequired, options.routes);
      await route.fulfill({
        status: response.status,
        contentType: "application/json",
        body: JSON.stringify(response.body),
      });
    },
  );

  return observed;
}
