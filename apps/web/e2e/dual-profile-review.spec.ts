import { expect, test, type Route } from "@playwright/test";

import type {
  DualProfileDecisionRequest,
  DualProfileImportRequest,
  DualProfileReviewClip,
  ProjectSnapshot,
} from "../src/types";
import {
  dualProfileLessonClip,
  dualProfileProject,
  dualProfileReview,
  dualProfileShortClip,
  projectSearchPage,
} from "../tests/fixtures";

test("imports dual-profile results, approves with an override and selects for delivery", async ({ page }) => {
  let imported = false;
  let importBody: DualProfileImportRequest | null = null;
  const decisions: DualProfileDecisionRequest[] = [];
  const forbiddenRequests: string[] = [];
  const project: ProjectSnapshot = dualProfileProject;
  let shortClip: DualProfileReviewClip = structuredClone(dualProfileShortClip);
  let lessonClip: DualProfileReviewClip = {
    ...structuredClone(dualProfileLessonClip),
    effective: structuredClone(dualProfileLessonClip.original),
    has_override: false,
    review_state: "pending",
    decisions: [],
    risk_tags: [],
  };
  const review = () => dualProfileReview([shortClip, lessonClip]);

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
            warnings: [],
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
    if (path === "/api/v1/completion-presets" && method === "GET") {
      await route.fulfill({ json: { schema_version: "1", presets: [] } });
      return;
    }
    if (path === "/api/v1/projects" && method === "GET") {
      await route.fulfill({ json: imported ? [project] : [] });
      return;
    }
    if (path === "/api/v1/projects/search" && method === "GET") {
      const visible = imported ? [project] : [];
      await route.fulfill({ json: projectSearchPage(visible, visible) });
      return;
    }
    if (path === "/api/v1/project-views" && method === "GET") {
      await route.fulfill({ json: { schema_version: "1", views: [] } });
      return;
    }
    if (path === "/api/v1/dual-profile-imports" && method === "POST") {
      importBody = request.postDataJSON() as DualProfileImportRequest;
      imported = true;
      await route.fulfill({
        status: 201,
        json: {
          project_id: "dual-1",
          import_id: "import-1",
          snapshot: "744f55f73e45152c4f54",
          clip_count: 2,
          created: true,
        },
      });
      return;
    }
    if (path === "/api/v1/projects/dual-1" && method === "GET") {
      await route.fulfill({ json: project });
      return;
    }
    if (path === "/api/v1/projects/dual-1/activity" && method === "GET") {
      await route.fulfill({ json: { schema_version: "1", project_id: "dual-1", events: [] } });
      return;
    }
    if (path === "/api/v1/projects/dual-1/dual-profile-import" && method === "GET") {
      await route.fulfill({ json: review() });
      return;
    }
    const decisionMatch = path.match(
      /^\/api\/v1\/projects\/dual-1\/dual-profile-import\/clips\/([^/]+)\/decisions$/,
    );
    if (decisionMatch && method === "POST") {
      const body = request.postDataJSON() as DualProfileDecisionRequest;
      decisions.push(body);
      const clipId = decisionMatch[1];
      if (clipId === "clip-lesson" && body.action === "approve") {
        lessonClip = {
          ...lessonClip,
          review_state: "approved",
          deliverable: true,
          effective: {
            title: body.title ?? lessonClip.original.title,
            hook: body.hook ?? lessonClip.original.hook,
            summary: body.summary ?? lessonClip.original.summary,
          },
          has_override: Boolean(body.title || body.hook || body.summary),
        };
      } else if (clipId === "clip-lesson" && body.action === "select") {
        if (!lessonClip.deliverable) {
          await route.fulfill({
            status: 409,
            json: {
              error: {
                code: "STATE_CONFLICT",
                message: "only an automatically selected or approved clip can be selected for delivery",
                retryable: false,
                correlation_id: "e2e",
                details: [],
              },
            },
          });
          return;
        }
        lessonClip = { ...lessonClip, selected_for_delivery: true };
      } else if (clipId === "clip-short" && body.action === "select") {
        shortClip = { ...shortClip, selected_for_delivery: true };
      }
      await route.fulfill({ json: review() });
      return;
    }
    if (path.startsWith("/api/v1/runs/") || path.endsWith("/clips")) {
      forbiddenRequests.push(`${method} ${path}`);
      await route.fulfill({ status: 404, json: { error: { code: "RESOURCE_NOT_FOUND", message: "not found", retryable: false, correlation_id: "e2e", details: [] } } });
      return;
    }
    await route.fulfill({ json: {} });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "导入双轨结果" }).click();
  const dialog = page.getByRole("dialog", { name: "导入已完成的双轨切分结果" });
  await dialog.getByLabel("结果目录（服务器本机路径）").fill("data/evaluations/run-1");
  await dialog.getByLabel("转写字幕 SRT 路径").fill("input/live.srt");
  await dialog.getByRole("button", { name: "导入并开始审核" }).click();

  await expect(page.getByRole("heading", { name: "双轨结果审核" })).toBeVisible();
  expect(importBody).toEqual({ run_dir: "data/evaluations/run-1", transcript_path: "input/live.srt" });
  await expect(page.getByRole("heading", { name: "短片（1）" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "小课（1）" })).toBeVisible();

  const lessonCard = page.getByRole("article", { name: /小课原标题/ });
  const lessonSelect = lessonCard.getByRole("checkbox", { name: "选入交付" });
  await expect(lessonSelect).toBeDisabled();
  await expect(lessonCard.getByText("批准后才能选入交付")).toBeVisible();

  await lessonCard.getByRole("button", { name: "批准" }).click();
  const form = page.getByRole("form", { name: "批准 小课原标题" });
  await expect(form.getByLabel("客户标题")).toHaveValue("小课原标题");
  await form.getByLabel("客户标题").fill("给客户看的小课标题");
  await form.getByRole("button", { name: "确认批准" }).click();

  const approvedCard = page.getByRole("article", { name: /给客户看的小课标题/ });
  await expect(approvedCard.getByText("已改写")).toBeVisible();
  await expect(approvedCard.getByText("已批准")).toBeVisible();
  const approvedSelect = approvedCard.getByRole("checkbox", { name: "选入交付" });
  await expect(approvedSelect).toBeEnabled();
  await approvedSelect.click();
  await expect(approvedSelect).toBeChecked();
  await expect(page.getByText("可交付 2 · 已选 1")).toBeVisible();

  expect(decisions).toEqual([
    { action: "approve", title: "给客户看的小课标题" },
    { action: "select" },
  ]);
  await expect(page.getByRole("heading", { name: "客户交付版本" })).toBeVisible();
  expect(forbiddenRequests).toEqual([]);
});
