import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, apiAssetUrl, apiAuth } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("ApiError", () => {
  it("preserves structured backend error fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: "invalid_model",
      message: "Model is unavailable",
      details: { model_id: "missing" },
      request_id: "req-42",
    }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    })));

    const error = await api.listModels().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: "invalid_model",
      message: "Model is unavailable",
      details: { model_id: "missing" },
      requestId: "req-42",
      request_id: "req-42",
    });
  });

  it("normalizes FastAPI detail errors and request-id headers", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Not found" }),
      { status: 404, headers: { "x-request-id": "req-header" } },
    )));

    const error = await api.listJobs().catch((value: unknown) => value);
    expect(error).toMatchObject({
      status: 404,
      message: "Not found",
      requestId: "req-header",
    });
  });

  it("includes the failing field in request-validation messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: "validation_error",
      message: "Request validation failed",
      details: [
        { loc: ["body", 0, "width"], msg: "Input should be a multiple of 16", type: "multiple_of" },
        { loc: ["body", 0, "height"], msg: "Input should be a multiple of 16", type: "multiple_of" },
      ],
    }), { status: 422 })));

    const error = await api.listJobs().catch((value: unknown) => value);
    expect(error).toMatchObject({
      status: 422,
      message: "Request validation failed: width: Input should be a multiple of 16 (+1 more)",
    });
  });
});

describe("browser asset authentication", () => {
  it("never appends the long-lived bearer to an asset URL", () => {
    localStorage.setItem("hfabric.apiToken", "do-not-leak");

    expect(apiAssetUrl("/api/images/example")).toBe("/api/images/example");
    expect(apiAssetUrl("/api/videos/example?download=1")).toBe("/api/videos/example?download=1");
  });

  it("exchanges the bearer for an HttpOnly session before publishing auth state", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ expires_at: 1234 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await apiAuth.setToken("  secret-token  ");

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/asset-session", expect.objectContaining({
      method: "POST",
      credentials: "include",
      headers: expect.any(Headers),
    }));
    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
    expect(apiAuth.getToken()).toBe("secret-token");
  });
});
