import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer(
  http.get("/api/v1/session", () =>
    HttpResponse.json({
      schema_version: "1",
      user: {
        user_id: "user-local-admin",
        username: "local-admin",
        display_name: "本机管理员",
      },
    }),
  ),
  http.get("/api/v1/health", () =>
    HttpResponse.json({
      schema_version: "1",
      status: "ok",
      version: "0.1.0-test",
      database: "ok",
      providers: {
        mode: "mock",
        asr_provider: "mock",
        llm_provider: "mock",
        asr_ready: true,
        llm_ready: true,
        processing_ready: true,
        blocking_issues: [],
        warnings: ["MOCK_ASR_SELECTED", "MOCK_LLM_SELECTED"],
      },
    }),
  ),
);
