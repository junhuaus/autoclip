import { expect, test, type Route } from "@playwright/test";

import type {
  ClipCommentReplyRequest,
  ClipCommentStatusRequest,
  ClipCommentThread,
  ClipCommentThreadCreateRequest,
  ClipDetailResponse,
  ClipPatchRequest,
  ClipSummaryResponse,
  ProjectSearchCriteria,
  ProjectSnapshot,
  ReleaseItemSnapshot,
  ReviewActionRequest,
  SavedProjectView,
} from "../src/types";
import {
  clipDetail as initialClipDetail,
  clipSummary as initialClipSummary,
  completedRun,
  project as initialProject,
  projectSearchPage,
  succeededDelivery,
} from "../tests/fixtures";

test("creates, reviews, rerenders and downloads one visible delivery flow", async ({ page }, testInfo) => {
  let created = false;
  let deliveryCreated = false;
  let editPackageCreated = false;
  let renderPollCount = 0;
  let releaseItem: ReleaseItemSnapshot | null = null;
  let project: ProjectSnapshot = initialProject;
  let clipDetail: ClipDetailResponse = structuredClone(initialClipDetail);
  let clipSummary: ClipSummaryResponse = structuredClone(initialClipSummary);
  let commentThread: ClipCommentThread | null = null;
  let savedProjectViews: SavedProjectView[] = [];

  await page.context().route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path.startsWith("/api/v1/media/")) {
      await route.fulfill({
        status: request.headers().range ? 206 : 200,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          ...(request.headers().range ? { "Content-Range": "bytes 0-3/4" } : {}),
        },
        body: "mock",
      });
      return;
    }
    if (path === "/api/v1/health" && method === "GET") {
      await route.fulfill({
        json: {
          schema_version: "1",
          status: "ok",
          version: "0.1.0-e2e",
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
        },
      });
      return;
    }
    if (path === "/api/v1/session" && method === "GET") {
      await route.fulfill({
        json: {
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
        },
      });
      return;
    }
    if (path === "/api/v1/deliveries/delivery-1/download") {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        headers: { "Content-Disposition": 'attachment; filename="liveclip-v001.zip"' },
        body: "PK\u0003\u0004mock-liveclip-delivery",
      });
      return;
    }
    if (path === "/api/v1/edit-packages/package-1/download") {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        headers: {
          "Content-Disposition": 'attachment; filename="liveclip-edit-package-v001.zip"',
        },
        body: "PK\u0003\u0004mock-liveclip-edit-package",
      });
      return;
    }
    if (path === "/api/v1/release-packages/release-package-1/download") {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        headers: {
          "Content-Disposition":
            'attachment; filename="liveclip-release-douyin-highlight-release--v001.zip"',
        },
        body: "PK\u0003\u0004mock-liveclip-release-package",
      });
      return;
    }
    if (path === "/api/v1/projects" && method === "GET") {
      await route.fulfill({ json: created ? [project] : [] });
      return;
    }
    if (path === "/api/v1/projects/search" && method === "GET") {
      const query = url.searchParams.get("q") ?? "";
      const visible = created ? [project] : [];
      const matched = visible.filter((item) => !query || item.name.includes(query));
      const page = projectSearchPage(matched, visible);
      if (query && page.items[0]) {
        page.items[0].matches = [{
          scope: "project",
          text: project.name,
          clip_id: null,
          release_item_id: null,
        }];
      }
      await route.fulfill({ json: page });
      return;
    }
    if (path === "/api/v1/project-views" && method === "GET") {
      await route.fulfill({ json: { schema_version: "1", views: savedProjectViews } });
      return;
    }
    if (path === "/api/v1/project-views" && method === "POST") {
      expect(request.headers()["idempotency-key"]).toMatch(
        /^liveclip-web-saved-project-view-/,
      );
      const body = request.postDataJSON() as {
        name: string;
        criteria: ProjectSearchCriteria;
      };
      savedProjectViews = [{
        view_id: "saved-project-view-1",
        name: body.name,
        criteria_schema_version: "1",
        criteria: body.criteria,
        version: 1,
        created_at: "2026-08-16T10:00:00Z",
        updated_at: "2026-08-16T10:00:00Z",
      }];
      await route.fulfill({ status: 201, json: savedProjectViews[0] });
      return;
    }
    if (path === "/api/v1/project-views/saved-project-view-1" && method === "DELETE") {
      expect(url.searchParams.get("expected_version")).toBe("1");
      savedProjectViews = [];
      await route.fulfill({ status: 204 });
      return;
    }
    if (path === "/api/v1/jobs" && method === "POST") {
      created = true;
      await route.fulfill({
        status: 202,
        json: {
          project_id: "project-1",
          run_id: "run-1",
          status: "queued",
          status_url: "/api/v1/jobs/run-1",
        },
      });
      return;
    }
    if (path === "/api/v1/projects/project-1" && method === "GET") {
      await route.fulfill({ json: project });
      return;
    }
    if (path === "/api/v1/projects/project-1/activity" && method === "GET") {
      await route.fulfill({
        json: {
          schema_version: "1",
          project_id: "project-1",
          events: [],
        },
      });
      return;
    }
    if (path === "/api/v1/clips/clip-1/comment-threads" && method === "GET") {
      const current = commentThread ? structuredClone(commentThread) : null;
      if (current) {
        const currentStart = clipDetail.clip.plan.source_start_ms;
        const currentEnd = clipDetail.clip.plan.source_end_ms;
        current.current_revision = clipDetail.clip.current_revision;
        current.is_current_revision =
          current.edit_plan_revision === clipDetail.clip.current_revision;
        current.current_clip_time_ms =
          current.source_time_ms >= currentStart && current.source_time_ms <= currentEnd
            ? current.source_time_ms - currentStart
            : null;
      }
      await route.fulfill({
        json: {
          schema_version: "1",
          clip_id: "clip-1",
          current_revision: clipDetail.clip.current_revision,
          total_count: current ? 1 : 0,
          next_offset: null,
          threads: current ? [current] : [],
        },
      });
      return;
    }
    if (path === "/api/v1/clips/clip-1/comment-threads" && method === "POST") {
      const body = request.postDataJSON() as ClipCommentThreadCreateRequest;
      expect(body.expected_revision).toBe(clipDetail.clip.current_revision);
      const now = "2026-08-15T00:01:00Z";
      const author = {
        user_id: "user-local-admin",
        username: "local-admin",
        display_name: "本机管理员",
      };
      commentThread = {
        thread_id: "comment-thread-1",
        project_id: "project-1",
        clip_id: "clip-1",
        edit_plan_revision: body.expected_revision,
        current_revision: body.expected_revision,
        is_current_revision: true,
        is_current_generation: true,
        source_time_ms: clipDetail.clip.plan.source_start_ms + body.clip_time_ms,
        clip_time_ms: body.clip_time_ms,
        current_clip_time_ms: body.clip_time_ms,
        status: "open",
        version: 1,
        allowed_actions: ["reply", "resolve"],
        created_by: author,
        resolved_by: null,
        created_at: now,
        updated_at: now,
        resolved_at: null,
        comments: [
          {
            comment_id: "comment-1",
            author,
            body: body.body,
            mentions: [],
            created_at: now,
          },
        ],
      };
      await route.fulfill({ status: 201, json: commentThread });
      return;
    }
    if (path === "/api/v1/comment-threads/comment-thread-1/replies" && method === "POST") {
      const body = request.postDataJSON() as ClipCommentReplyRequest;
      if (!commentThread) throw new Error("reply requires a comment thread");
      commentThread.version += 1;
      commentThread.comments.push({
        comment_id: `comment-${commentThread.comments.length + 1}`,
        author: commentThread.created_by,
        body: body.body,
        mentions: [],
        created_at: "2026-08-15T00:02:00Z",
      });
      await route.fulfill({ status: 201, json: commentThread });
      return;
    }
    if (path === "/api/v1/comment-threads/comment-thread-1/status" && method === "POST") {
      const body = request.postDataJSON() as ClipCommentStatusRequest;
      if (!commentThread) throw new Error("status change requires a comment thread");
      expect(body.expected_thread_version).toBe(commentThread.version);
      commentThread.version += 1;
      commentThread.status = body.status;
      commentThread.allowed_actions = body.status === "resolved" ? ["reopen"] : ["reply", "resolve"];
      commentThread.resolved_by = body.status === "resolved" ? commentThread.created_by : null;
      commentThread.resolved_at = body.status === "resolved" ? "2026-08-15T00:03:00Z" : null;
      await route.fulfill({ json: commentThread });
      return;
    }
    if (path === "/api/v1/projects/project-1/members" && method === "POST") {
      await route.fulfill({
        json: {
          schema_version: "1",
          project_id: "project-1",
          members: project.members,
        },
      });
      return;
    }
    if (path === "/api/v1/runs/run-1" && method === "GET") {
      await route.fulfill({ json: completedRun });
      return;
    }
    if (path === "/api/v1/projects/project-1/clips" && method === "GET") {
      await route.fulfill({ json: [clipSummary] });
      return;
    }
    if (path === "/api/v1/projects/project-1/deliveries" && method === "GET") {
      await route.fulfill({ json: deliveryCreated ? [succeededDelivery] : [] });
      return;
    }
    const editPackage = {
      edit_package: {
        edit_package_id: "package-1",
        project_id: "project-1",
        task_id: "edit-package-task-1",
        requested_by_user_id: "user-local-admin",
        version: 1,
        package_version: "v001",
        status: "succeeded",
        clip_count: 1,
        preset: "clean_editing",
        content: "full",
        manifest_asset_id: "edit-package-manifest-1",
        zip_asset_id: "edit-package-zip-1",
        include_zip: true,
        error_code: null,
        safe_error_message: null,
        created_at: "2026-08-15T00:00:00Z",
        completed_at: "2026-08-15T00:00:01Z",
      },
      download_url:
        "/api/v1/edit-packages/package-1/download?expires=9999999999&signature=package-signed",
    };
    if (path === "/api/v1/projects/project-1/edit-packages" && method === "GET") {
      await route.fulfill({ json: editPackageCreated ? [editPackage] : [] });
      return;
    }
    if (path === "/api/v1/release-presets" && method === "GET") {
      await route.fulfill({
        json: {
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
              policy_notes: ["发布前复核账号规则。"],
              official_sources: ["https://example.com/official"],
            },
          ],
        },
      });
      return;
    }
    if (path === "/api/v1/projects/project-1/releases" && method === "GET") {
      await route.fulfill({
        json: {
          schema_version: "1",
          project_id: "project-1",
          releases: releaseItem ? [releaseItem] : [],
          preview_media_urls: releaseItem
            ? { "release-1": "/api/v1/media/proxy-asset-1?expires=9999999999&signature=preview-signed" }
            : {},
        },
      });
      return;
    }
    if (path === "/api/v1/projects/project-1/releases" && method === "POST") {
      expect(request.postDataJSON()).toMatchObject({
        clip_id: "clip-1",
        expected_revision: 2,
        platform: "douyin",
        account_label: "官方主账号",
        caption_mode: "clean_separate",
      });
      releaseItem = {
        release_item_id: "release-1",
        project_id: "project-1",
        clip_id: "clip-1",
        edit_plan_revision: 2,
        current_edit_plan_revision: 2,
        stale: false,
        stale_reason: null,
        platform: "douyin",
        preset_version: "2026-08-15.1",
        account_label: "官方主账号",
        title: "浏览器审核后的标题",
        title_variants: [],
        description: "已完成编辑和审核的发布说明。",
        hashtags: ["直播", "高光"],
        cta: "关注获取更多内容",
        caption_mode: "clean_separate",
        cover_time_ms: 1_000,
        clip_duration_ms: 9_800,
        high_impact_sentence: "开头提出关键问题",
        risk_flags: [],
        preview_asset_id: "proxy-asset-1",
        assignee: null,
        planned_publish_at: "2026-08-16T04:00:00Z",
        approval_status: "approved",
        status: "ready",
        checklist: {
          hook_confirmed: true,
          first_frame_confirmed: true,
          subtitles_confirmed: true,
          music_rights_confirmed: true,
          likeness_confirmed: true,
          personal_data_confirmed: true,
          claims_confirmed: true,
          sponsorship_confirmed: true,
          platform_policy_confirmed: true,
        },
        preflight: {
          schema_version: "liveclip.release-preflight.v1",
          preset_id: "douyin@2026-08-15.1",
          checked_at: "2026-08-15",
          passed: true,
          blocker_count: 0,
          warning_count: 0,
          checks: [
            {
              code: "trusted_media",
              category: "media",
              outcome: "passed",
              message: "媒体已验证。",
            },
          ],
        },
        management_version: 4,
        external_url: null,
        external_id: null,
        published_at: null,
        result_notes: null,
        publication_evidence: null,
        metrics: [],
        packages: [],
        created_at: "2026-08-15T02:00:00Z",
        updated_at: "2026-08-15T02:00:00Z",
      };
      await route.fulfill({ status: 201, json: releaseItem });
      return;
    }
    if (path === "/api/v1/releases/release-1/packages" && method === "POST") {
      expect(request.postDataJSON()).toEqual({
        expected_release_item_version: 4,
        include_zip: true,
      });
      await route.fulfill({
        status: 202,
        json: {
          resource_type: "release_package",
          resource_id: "release-package-1",
          task_id: "release-package-task-1",
          status: "queued",
          status_url: "/api/v1/release-packages/release-package-1",
        },
      });
      return;
    }
    if (path === "/api/v1/release-packages/release-package-1" && method === "GET") {
      await route.fulfill({
        json: {
          schema_version: "1",
          release_package: {
            release_package_id: "release-package-1",
            release_item_id: "release-1",
            project_id: "project-1",
            task_id: "release-package-task-1",
            requested_by_user_id: "user-local-admin",
            version: 1,
            package_version: "v001",
            release_item_version: 4,
            current: true,
            published_artifact: false,
            status: "succeeded",
            preset_version: "2026-08-15.1",
            caption_mode: "clean_separate",
            manifest_asset_id: "release-manifest-1",
            zip_asset_id: "release-zip-1",
            video_sha256: "a".repeat(64),
            manifest_sha256: "b".repeat(64),
            zip_sha256: "c".repeat(64),
            include_zip: true,
            error_code: null,
            safe_error_message: null,
            created_at: "2026-08-15T02:01:00Z",
            completed_at: "2026-08-15T02:01:02Z",
          },
          download_url:
            "/api/v1/release-packages/release-package-1/download?expires=9999999999&signature=release-signed",
          download_kind: "zip",
        },
      });
      return;
    }
    if (path === "/api/v1/projects/project-1/edit-packages" && method === "POST") {
      expect(request.postDataJSON()).toEqual({
        items: [{ clip_id: "clip-1", expected_revision: 1 }],
        preset: "clean_editing",
        content: "full",
        include_zip: true,
      });
      editPackageCreated = true;
      await route.fulfill({
        status: 202,
        json: {
          resource_type: "edit_package",
          resource_id: "package-1",
          task_id: "edit-package-task-1",
          status: "queued",
          status_url: "/api/v1/edit-packages/package-1",
        },
      });
      return;
    }
    if (path === "/api/v1/edit-packages/package-1" && method === "GET") {
      await route.fulfill({ json: editPackage });
      return;
    }
    if (path === "/api/v1/projects/project-1/deliveries" && method === "POST") {
      deliveryCreated = true;
      await route.fulfill({
        status: 202,
        json: {
          resource_type: "delivery",
          resource_id: "delivery-1",
          task_id: "delivery-task-1",
          status: "queued",
          status_url: "/api/v1/deliveries/delivery-1",
        },
      });
      return;
    }
    if (path === "/api/v1/deliveries/delivery-1" && method === "GET") {
      project = { ...project, status: "delivered" };
      await route.fulfill({ json: succeededDelivery });
      return;
    }
    if (path === "/api/v1/clips/clip-1" && method === "GET") {
      await route.fulfill({ json: clipDetail });
      return;
    }
    if (path === "/api/v1/clips/clip-1" && method === "PATCH") {
      const body = request.postDataJSON() as ClipPatchRequest;
      clipDetail = {
        clip: {
          ...clipDetail.clip,
          current_revision: 2,
          revision_epoch: 1,
          plan: {
            ...clipDetail.clip.plan,
            title: body.title ?? clipDetail.clip.plan.title,
            source_start_ms: body.source_start_ms ?? clipDetail.clip.plan.source_start_ms,
            source_end_ms: body.source_end_ms ?? clipDetail.clip.plan.source_end_ms,
          },
          captions: body.captions ?? clipDetail.clip.captions,
          review: { status: "pending_review", reason: null, decided_at: null },
          renders: clipDetail.clip.renders.map((render) => ({ ...render, status: "stale" })),
          allowed_actions: ["edit", "approve", "reject", "render_proxy"],
        },
        asset_urls: {},
      };
      clipSummary = {
        clip: {
          ...clipSummary.clip,
          edit_plan_revision: 2,
          title: clipDetail.clip.plan.title,
          source_start_ms: clipDetail.clip.plan.source_start_ms,
          source_end_ms: clipDetail.clip.plan.source_end_ms,
          proxy_status: "stale",
          proxy_asset_id: null,
        },
        proxy_media_url: null,
        download_video_url: null,
        download_subtitle_url: null,
      };
      await route.fulfill({ json: clipDetail });
      return;
    }
    if (path === "/api/v1/clips/clip-1/review" && method === "POST") {
      const body = request.postDataJSON() as ReviewActionRequest;
      expect(body).toEqual({ expected_revision: 2, status: "approved" });
      clipDetail = {
        ...clipDetail,
        clip: {
          ...clipDetail.clip,
          review: { status: "approved", reason: null, decided_at: "2026-08-04T00:02:00Z" },
          allowed_actions: ["edit", "approve", "reject", "render_proxy", "render_final"],
        },
      };
      clipSummary = {
        ...clipSummary,
        clip: { ...clipSummary.clip, review_status: "approved" },
      };
      await route.fulfill({ json: clipDetail });
      return;
    }
    if (path === "/api/v1/clips/clip-1/render" && method === "POST") {
      await route.fulfill({
        status: 202,
        json: {
          resource_type: "render",
          resource_id: "final-render-1",
          task_id: "final-task-1",
          status: "queued",
          status_url: "/api/v1/renders/final-render-1",
        },
      });
      return;
    }
    if (path === "/api/v1/renders/final-render-1" && method === "GET") {
      renderPollCount += 1;
      const status = renderPollCount > 1 ? "succeeded" : "running";
      if (status === "succeeded") {
        clipDetail = {
          ...clipDetail,
          clip: {
            ...clipDetail.clip,
            renders: [
              {
                ...clipDetail.clip.renders[0],
                render_id: "final-render-1",
                task_id: "final-task-1",
                kind: "final",
                status: "succeeded",
                edit_plan_revision: 2,
                width: 1080,
                height: 1920,
                video_asset_id: "final-video-1",
              },
              ...clipDetail.clip.renders,
            ],
            allowed_actions: ["edit", "approve", "reject", "render_proxy", "render_final", "deliver"],
          },
          asset_urls: {
            "final-video-1": "/api/v1/media/final-video-1?expires=9999999999&signature=final-signed",
          },
        };
        project = { ...project, status: "ready_for_delivery" };
      }
      await route.fulfill({
        json: {
          render_id: "final-render-1",
          task_id: "final-task-1",
          clip_id: "clip-1",
          edit_plan_revision: 2,
          kind: "final",
          status,
        },
      });
      return;
    }

    throw new Error(`Unhandled E2E route: ${method} ${path}`);
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "我的项目" })).toBeVisible();
  await expect(page.getByText("还没有项目")).toBeVisible();
  await expect(page.getByText(/Mock ASR/)).toHaveCount(0);
  await page.getByRole("button", { name: "＋ 新建项目" }).click();
  await expect(page.getByRole("button", { name: "创建并开始处理" })).toBeEnabled();
  await page.getByLabel("本地视频绝对路径").fill("/Users/demo/Videos/live.mp4");
  await page.getByRole("button", { name: "创建并开始处理" }).click();

  await expect(page.getByRole("heading", { name: "直播测试项目" })).toBeVisible();
  await expect(page.getByText("源视频绝对时间")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "转写" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "高光时刻" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "项目成员" })).toBeVisible();
  const firstCard = page.locator("article.clip-card").first();
  await expect(firstCard.getByRole("heading", { name: "高光语句" })).toBeVisible();
  await expect(firstCard.getByText("开头提出关键问题")).toBeVisible();
  await expect(firstCard.getByRole("heading", { name: "编辑关键词" })).toBeVisible();
  await expect(page.getByText("第一条字幕")).toBeVisible();
  await expect(page.getByRole("button", { name: /定位到编辑关键词 中文直播/ })).toBeVisible();
  const mainBox = await firstCard.locator(":scope > .clip-card-main").boundingBox();
  const videoBox = await firstCard.locator("video").boundingBox();
  const bodyBox = await firstCard.locator(".clip-card-body").boundingBox();
  const captionBox = await firstCard.locator(":scope > .clip-card-captions").boundingBox();
  expect(mainBox).not.toBeNull();
  expect(videoBox).not.toBeNull();
  expect(bodyBox).not.toBeNull();
  expect(captionBox).not.toBeNull();
  expect((bodyBox as { x: number }).x).toBeGreaterThan((videoBox as { x: number }).x);
  expect((captionBox as { y: number }).y).toBeGreaterThanOrEqual(
    (mainBox as { y: number; height: number }).y + (mainBox as { height: number }).height - 1,
  );
  const proxy = page.getByLabel("原始高光标题 审核代理");
  await expect(proxy).toHaveAttribute("src", /signature=signed/);
  await expect(firstCard.getByRole("link", { name: "下载 MP4" })).toBeVisible();
  await expect(firstCard.getByRole("link", { name: "下载 SRT" })).toBeVisible();

  await firstCard.getByLabel("选择导出").check();
  await expect(page.getByText("已选 1 条用于剪辑交接")).toBeVisible();
  await page.getByRole("button", { name: "生成所选剪辑交接包" }).click();
  const handoffDownload = page.getByRole("link", { name: "下载剪辑交接 ZIP" });
  await expect(handoffDownload).toHaveAttribute("href", /signature=package-signed/);
  const handoffHref = await handoffDownload.getAttribute("href");
  const handoffArchive = await page.evaluate(async (href) => {
    const response = await fetch(href);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      magic: Array.from(body.slice(0, 2)),
    };
  }, handoffHref as string);
  expect(handoffArchive).toEqual({
    status: 200,
    disposition: 'attachment; filename="liveclip-edit-package-v001.zip"',
    magic: [0x50, 0x4b],
  });

  await page.getByRole("button", { name: "审核和编辑" }).click();
  const editor = page.locator("section.clip-editor");
  await expect(editor).toBeVisible();
  await expect(editor.getByRole("heading", { name: "协作批注" })).toBeVisible();
  await editor.getByLabel("片段时间（秒）").fill("0.500");
  await editor.getByLabel("批注内容").fill("浏览器时间点批注");
  await editor.getByRole("button", { name: "添加时间点批注" }).click();
  await expect(editor.getByText("浏览器时间点批注")).toBeVisible();
  await editor.getByLabel("回复").fill("浏览器协作回复");
  await editor.getByRole("button", { name: "回复" }).click();
  await expect(editor.getByText("浏览器协作回复")).toBeVisible();
  await editor.getByRole("button", { name: "标记已解决" }).click();
  await expect(editor.locator(".comment-status")).toHaveText("已解决");
  await editor.getByLabel("标题").fill("浏览器审核后的标题");
  await editor.getByLabel("源开始（ms）").fill("1200");
  await editor.getByLabel("文本").fill("浏览器逐 cue 修改字幕");
  await editor.getByRole("button", { name: "保存为新 revision" }).click();
  await expect(editor.getByText(/旧 revision 的 1 个渲染已失效/)).toBeVisible();
  await expect(editor.getByText("历史 r1")).toBeVisible();

  await editor.getByRole("button", { name: "批准" }).click();
  await expect(editor.getByText("已批准")).toBeVisible();
  await editor.getByRole("button", { name: "渲染最终视频" }).click();
  await expect(editor.getByText("最终视频渲染状态已更新。")).toBeVisible({ timeout: 8_000 });

  const createDelivery = page.getByRole("button", { name: "创建新交付版本" });
  await expect(createDelivery).toBeEnabled({ timeout: 8_000 });
  await createDelivery.click();
  const downloadLink = page.getByRole("link", { name: "下载 ZIP" });
  await expect(downloadLink).toHaveAttribute("href", /signature=signed/);
  await expect(downloadLink).toHaveAttribute("download", "");
  const downloadHref = await downloadLink.getAttribute("href");
  expect(downloadHref).not.toBeNull();
  const downloaded = await page.evaluate(async (href) => {
    const response = await fetch(href);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      magic: Array.from(body.slice(0, 2)),
    };
  }, downloadHref as string);
  expect(downloaded).toEqual({
    status: 200,
    disposition: 'attachment; filename="liveclip-v001.zip"',
    magic: [0x50, 0x4b],
  });

  await expect(page.getByRole("heading", { name: "发布队列" })).toBeVisible();
  await page.getByRole("button", { name: "＋ 建立发布任务" }).click();
  const releaseForm = page.locator("form.release-create-form");
  await releaseForm.getByLabel("高光时刻").selectOption("clip-1");
  await releaseForm.getByLabel("发布账号").fill("官方主账号");
  await releaseForm.getByLabel("计划发布时间").fill("2026-08-16T12:00");
  await releaseForm.getByRole("button", { name: "建立发布任务" }).click();
  await expect(page.getByText(/抖音 · 官方主账号/)).toBeVisible();
  await page.getByRole("button", { name: "日历" }).click();
  const calendarDateLabel = await page.evaluate(() =>
    new Date("2026-08-16T04:00:00Z").toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "long",
      day: "numeric",
    }),
  );
  await expect(page.getByRole("heading", { name: calendarDateLabel })).toBeVisible();
  await page.getByRole("button", { name: "生成平台包" }).click();
  const releaseDownload = page.getByRole("link", { name: "下载平台 ZIP" });
  await expect(releaseDownload).toHaveAttribute("href", /signature=release-signed/);
  const releaseHref = await releaseDownload.getAttribute("href");
  const releaseArchive = await page.evaluate(async (href) => {
    const response = await fetch(href);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      magic: Array.from(body.slice(0, 2)),
    };
  }, releaseHref as string);
  expect(releaseArchive).toEqual({
    status: 200,
    disposition:
      'attachment; filename="liveclip-release-douyin-highlight-release--v001.zip"',
    magic: [0x50, 0x4b],
  });

  await page.getByRole("button", { name: "我的项目", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的项目" })).toBeVisible();
  await expect(page.getByText("发布会精剪")).toHaveCount(0);
  await expect(page.getByText("直播测试项目")).toBeVisible();
  await expect(page.getByText("负责人 本机管理员")).toBeVisible();
  const projectSearch = page.getByPlaceholder(
    "项目、源视频、高光内容、执行人或平台",
  );
  await projectSearch.fill("直播测试");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByLabel("搜索命中位置")).toContainText("直播测试项目");
  await page.getByRole("button", { name: "＋ 保存当前视图" }).click();
  await page.getByLabel("视图名称").fill("我的直播视图");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "我的直播视图", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(projectSearch).toHaveValue("");
  await page.getByRole("button", { name: "我的直播视图", exact: true }).click();
  await expect(projectSearch).toHaveValue("直播测试");
  await page.getByRole("button", { name: "管理视图 我的直播视图" }).click();
  await page.getByRole("button", { name: "删除视图" }).click();
  await expect(page.getByText("确认删除“我的直播视图”？项目不会被删除。")).toBeVisible();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByRole("button", { name: "我的直播视图", exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("project-dashboard.png"), fullPage: true });
});
