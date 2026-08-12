import { expect, test, type Route } from "@playwright/test";

import type {
  ClipDetailResponse,
  ClipPatchRequest,
  ClipSummaryResponse,
  ProjectSnapshot,
  ReviewActionRequest,
} from "../src/types";
import {
  clipDetail as initialClipDetail,
  clipSummary as initialClipSummary,
  completedRun,
  project as initialProject,
  succeededDelivery,
} from "../tests/fixtures";

test("creates, reviews, rerenders and downloads one visible delivery flow", async ({ page }) => {
  let created = false;
  let deliveryCreated = false;
  let renderPollCount = 0;
  let project: ProjectSnapshot = initialProject;
  let clipDetail: ClipDetailResponse = structuredClone(initialClipDetail);
  let clipSummary: ClipSummaryResponse = structuredClone(initialClipSummary);

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
    if (path === "/api/v1/deliveries/delivery-1/download") {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        headers: { "Content-Disposition": 'attachment; filename="liveclip-v001.zip"' },
        body: "PK\u0003\u0004mock-liveclip-delivery",
      });
      return;
    }
    if (path === "/api/v1/projects" && method === "GET") {
      await route.fulfill({ json: created ? [project] : [] });
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
  await expect(page.getByText("还没有项目")).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前 AI 处理链路" })).toBeVisible();
  await expect(page.getByText(/当前使用 Mock ASR/)).toBeVisible();
  await expect(page.getByRole("button", { name: "创建项目并启动处理" })).toBeEnabled();
  await page.getByLabel("本地视频绝对路径").fill("/Users/demo/Videos/live.mp4");
  await page.getByRole("button", { name: "创建项目并启动处理" }).click();

  await expect(page.getByRole("heading", { name: "直播测试项目" })).toBeVisible();
  await expect(page.getByText("源视频绝对时间")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "转写" })).toHaveCount(0);
  await expect(page.getByText("第一条字幕")).toBeVisible();
  await expect(page.getByRole("button", { name: /定位到关键词 中文直播/ })).toBeVisible();
  const proxy = page.getByLabel("原始高光标题 审核代理");
  await expect(proxy).toHaveAttribute("src", /signature=signed/);

  await page.getByRole("button", { name: "审核和编辑" }).click();
  const editor = page.locator("section.clip-editor");
  await expect(editor).toBeVisible();
  await editor.getByLabel("标题").fill("浏览器审核后的标题");
  await editor.getByLabel("源开始（ms）").fill("1200");
  await editor.getByLabel("文本").fill("浏览器逐 cue 修改字幕");
  await editor.getByRole("button", { name: "保存为新 revision" }).click();
  await expect(editor.getByText(/旧 revision 的 1 个渲染已失效/)).toBeVisible();

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
});
