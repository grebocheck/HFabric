import { describe, expect, expectTypeOf, it } from "vitest";

import type {
  ChatSendBody,
  CivitaiSearchResponse,
  ImageStats,
  LlmConfig,
  Model,
  RagSearchResponse,
  TtsGenerateBody,
} from "../types";
import type { components, paths } from "../types.generated";
import { api } from "./client";

type Api = components["schemas"];
type JsonResponse<Operation> = Operation extends {
  responses: {
    200: { content: { "application/json": infer Body } };
  };
} ? Body : never;
type JsonRequest<Operation> = Operation extends {
  requestBody: { content: { "application/json": infer Body } };
} ? Body : never;

describe("generated API contract", () => {
  it("keeps canonical response aliases connected to OpenAPI components", () => {
    expectTypeOf<Model>().toEqualTypeOf<Api["ModelOut"]>();
    expectTypeOf<ImageStats>().toEqualTypeOf<Api["ImageStatsOut"]>();
    expectTypeOf<CivitaiSearchResponse>().toEqualTypeOf<Api["CivitaiSearchOut"]>();
    expectTypeOf<LlmConfig>().toEqualTypeOf<Api["LlmConfigOut"]>();
    expectTypeOf<RagSearchResponse>().toEqualTypeOf<Api["RagSearchOut"]>();
  });

  it("keeps request aliases connected to OpenAPI components", () => {
    expectTypeOf<ChatSendBody>().toEqualTypeOf<Api["ChatSend"]>();
    expectTypeOf<TtsGenerateBody>().toEqualTypeOf<Api["TtsGenerateIn"]>();
    expectTypeOf<Parameters<typeof api.setLlmConfig>[0]>()
      .toEqualTypeOf<Api["LlmConfigUpdate"]>();
    expectTypeOf<Parameters<typeof api.updateImage>[1]>()
      .toEqualTypeOf<Api["ImageUpdateIn"]>();
  });

  it("does not require values supplied by backend defaults", () => {
    const minimalChat: ChatSendBody = { model_id: "llm/demo" };
    const minimalTts: TtsGenerateBody = { model_id: "tts/demo", text: "Hello" };

    expect(minimalChat).toEqual({ model_id: "llm/demo" });
    expect(minimalTts).toEqual({ model_id: "tts/demo", text: "Hello" });
  });

  it("uses generated schemas for client return signatures", () => {
    expectTypeOf(api.listModels)
      .returns.toEqualTypeOf<
        Promise<JsonResponse<paths["/api/models"]["get"]>>
      >();
    expectTypeOf(api.rescanModels)
      .returns.toEqualTypeOf<
        Promise<JsonResponse<paths["/api/models/rescan"]["post"]>>
      >();
    expectTypeOf(api.imageStats)
      .returns.toEqualTypeOf<
        Promise<JsonResponse<paths["/api/images/stats"]["get"]>>
      >();
    expectTypeOf(api.searchRag)
      .returns.toEqualTypeOf<
        Promise<JsonResponse<paths["/api/rag/search"]["post"]>>
      >();
  });

  it("uses generated operation request bodies in client signatures", () => {
    expectTypeOf<Parameters<typeof api.setLlmConfig>[0]>()
      .toEqualTypeOf<JsonRequest<paths["/api/llm/config"]["post"]>>();
    expectTypeOf<Parameters<typeof api.updateImage>[1]>()
      .toEqualTypeOf<JsonRequest<paths["/api/images/{image_id}"]["patch"]>>();
    expectTypeOf<Parameters<typeof api.searchRag>[0]>()
      .toEqualTypeOf<JsonRequest<paths["/api/rag/search"]["post"]>>();
  });
});
