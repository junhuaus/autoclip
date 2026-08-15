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
        system_role: "administrator",
      },
      credential_kind: "legacy",
      csrf_token: null,
      expires_at: null,
    }),
  ),
  http.get("/api/v1/projects/:projectId/activity", ({ params }) =>
    HttpResponse.json({ schema_version: "1", project_id: params.projectId, events: [] }),
  ),
  http.get("/api/v1/projects/:projectId/edit-packages", () => HttpResponse.json([])),
  http.get("/api/v1/projects/:projectId/releases", ({ params }) =>
    HttpResponse.json({
      schema_version: "1",
      project_id: params.projectId,
      releases: [],
      preview_media_urls: {},
    }),
  ),
  http.get("/api/v1/release-presets", () =>
    HttpResponse.json({
      schema_version: "1",
      current_versions: {
        douyin: "2026-08-15.1",
        xiaohongshu: "2026-08-15.1",
        bilibili_vertical: "2026-08-15.1",
        youtube_shorts: "2026-08-15.1",
        tiktok: "2026-08-15.1",
        generic_vertical: "2026-08-15.1",
      },
      presets: [
        {
          platform: "douyin",
          version: "2026-08-15.1",
          checked_at: "2026-08-15",
          label: "抖音",
          recommended_width: 1080,
          recommended_height: 1920,
          minimum_width: 360,
          minimum_height: 640,
          maximum_dimension: null,
          maximum_duration_ms: null,
          maximum_file_bytes: null,
          safe_zone: {
            top: 0.08,
            right: 0.08,
            bottom: 0.2,
            left: 0.08,
            basis: "平台界面遮挡保守值",
          },
          account_policy_confirmation_required: true,
          policy_notes: ["发布前复核当前账号提示。"],
          official_sources: ["https://example.com/official"],
        },
      ],
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
