import { expect, test, type Route } from "@playwright/test";

import type { CustomerDeliveryResponse, ShareLinkSnapshot } from "../src/types";
import {
  dualProfileLessonClip,
  dualProfileProject,
  dualProfileReview,
  dualProfileShortClip,
  projectSearchPage,
} from "../tests/fixtures";

test("creates a customer delivery, shares it once and revokes the link", async ({ page }) => {
  const selectedShort = { ...dualProfileShortClip, selected_for_delivery: true };
  let deliveries: CustomerDeliveryResponse[] = [];
  let links: ShareLinkSnapshot[] = [];
  const shareUrl = "http://192.168.1.20:8766/s/e2e_token_shown_once_bbbbbbbbbbbbbbbbbbbbbbbbbbb";
  const forbidden: string[] = [];

  await page.context().route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (path.startsWith("/api/v1/media/")) {
      return route.fulfill({ status: 200, contentType: "video/mp4", body: "mock" });
    }
    if (path === "/api/v1/health") {
      return json({
        schema_version: "1",
        status: "ok",
        version: "e2e",
        database: "ok",
        providers: {
          mode: "mock",
          asr_provider: "mock",
          llm_provider: "mock",
          asr_ready: true,
          llm_ready: true,
          processing_ready: true,
          blocking_issues: [],
          warnings: [],
        },
      });
    }
    if (path === "/api/v1/session") {
      return json({
        schema_version: "1",
        user: { user_id: "user-local-admin", username: "local-admin", display_name: "本机管理员", system_role: "administrator" },
        credential_kind: "legacy",
        csrf_token: null,
        expires_at: null,
      });
    }
    if (path === "/api/v1/completion-presets") return json({ schema_version: "1", presets: [] });
    if (path === "/api/v1/projects") return json([dualProfileProject]);
    if (path === "/api/v1/projects/search") {
      return json(projectSearchPage([dualProfileProject], [dualProfileProject]));
    }
    if (path === "/api/v1/project-views") return json({ schema_version: "1", views: [] });
    if (path === "/api/v1/projects/dual-1") return json(dualProfileProject);
    if (path === "/api/v1/projects/dual-1/activity") {
      return json({ schema_version: "1", project_id: "dual-1", events: [] });
    }
    if (path === "/api/v1/projects/dual-1/dual-profile-import") {
      return json(dualProfileReview([selectedShort, dualProfileLessonClip]));
    }
    if (path === "/api/v1/projects/dual-1/customer-deliveries" && method === "GET") {
      return json(deliveries);
    }
    if (path === "/api/v1/projects/dual-1/customer-deliveries" && method === "POST") {
      expect(request.postDataJSON()).toEqual({ title: "张老师 精选", expected_clip_ids: ["clip-short"] });
      deliveries = [
        {
          delivery: {
            delivery_id: "cd-1",
            project_id: "dual-1",
            task_id: "task-1",
            version: 1,
            delivery_version: "v001",
            title: "张老师 精选",
            status: "succeeded",
            clip_count: 1,
            short_count: 1,
            lesson_count: 0,
            created_by: "本机管理员",
            created_at: "2026-11-07T12:00:00Z",
            completed_at: "2026-11-07T12:00:05Z",
            zip_asset_id: "asset-zip",
            error_code: null,
            safe_error_message: null,
          },
          download_url: "/api/v1/customer-deliveries/cd-1/download?expires=9999999999&signature=s",
        },
      ];
      return json(deliveries[0], 202);
    }
    if (path === "/api/v1/projects/dual-1/customer-deliveries/cd-1/share-links" && method === "GET") {
      return json(links);
    }
    if (path === "/api/v1/projects/dual-1/customer-deliveries/cd-1/share-links" && method === "POST") {
      expect(request.postDataJSON()).toEqual({ expires_in_days: 7 });
      const link: ShareLinkSnapshot = {
        link_id: "link-1",
        delivery_id: "cd-1",
        project_id: "dual-1",
        delivery_version: "v001",
        created_by: "本机管理员",
        created_at: "2026-11-07T12:00:00Z",
        expires_at: "2026-11-14T12:00:00Z",
        revoked_at: null,
        revoked_by: null,
        status: "active",
        view_count: 0,
        download_count: 0,
        last_accessed_at: null,
      };
      links = [link];
      return json({ link, url: shareUrl }, 201);
    }
    if (path === "/api/v1/projects/dual-1/share-links/link-1/revoke" && method === "POST") {
      links = links.map((value) => ({ ...value, status: "revoked", revoked_at: "2026-11-07T13:00:00Z", revoked_by: "本机管理员" }));
      return json(links[0]);
    }
    forbidden.push(`${method} ${path}`);
    return route.fulfill({ status: 404, json: { error: { code: "RESOURCE_NOT_FOUND", message: "not found", retryable: false, correlation_id: "e2e", details: [] } } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /8-30 双轨结果/ }).first().click();
  await expect(page.getByRole("heading", { name: "客户交付版本" })).toBeVisible();
  const title = page.getByLabel("交付标题（客户可见）");
  await title.fill("张老师 精选");
  await page.getByRole("button", { name: "生成交付包" }).click();
  const shares = page.getByLabel("v001 分享链接");
  await expect(shares).toBeVisible();
  await shares.getByRole("button", { name: "创建分享链接" }).click();
  await expect(shares.getByLabel("分享链接（只显示这一次）")).toHaveValue(shareUrl);
  await expect(shares.getByText(/请勿在公共 Wi-Fi 下使用/)).toBeVisible();
  await shares.getByRole("button", { name: "我已保存，隐藏链接" }).click();
  await expect(shares.getByLabel("分享链接（只显示这一次）")).toHaveCount(0);
  await shares.getByRole("button", { name: "撤销" }).click();
  await expect(shares.getByText("已撤销")).toBeVisible();
  expect(forbidden).toEqual([]);
});
