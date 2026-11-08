import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { DualProfileImportDialog, approvalOverrides } from "../src/DualProfileReview";
import { ProjectWorkspace } from "../src/ProjectWorkspace";
import type {
  CustomerDeliveryCreateRequest,
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
} from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

function serveWorkspace(
  project: ProjectSnapshot = dualProfileProject,
  clips: DualProfileReviewClip[] = [dualProfileShortClip, dualProfileLessonClip],
) {
  server.use(
    http.get("/api/v1/projects/dual-1", () => HttpResponse.json(project)),
    http.get("/api/v1/projects/dual-1/members", () =>
      HttpResponse.json({ project_id: "dual-1", members: project.members }),
    ),
    http.get("/api/v1/projects/dual-1/dual-profile-import", () =>
      HttpResponse.json(dualProfileReview(clips)),
    ),
    http.get("/api/v1/projects/dual-1/customer-deliveries", () => HttpResponse.json([])),
  );
}

function renderWorkspace() {
  return renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="dual-1" onBack={() => undefined} />,
  );
}

function card(title: string) {
  return screen.getByRole("article", { name: new RegExp(title) });
}

it("renders imported results in 短片 and 小课 groups without any pipeline run request", async () => {
  serveWorkspace();
  renderWorkspace();

  expect(await screen.findByRole("heading", { name: "短片（1）" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "小课（1）" })).toBeInTheDocument();
  const shortList = screen.getByRole("list", { name: "短片列表" });
  const lessonList = screen.getByRole("list", { name: "小课列表" });
  expect(within(shortList).getByText("自动入选")).toBeInTheDocument();
  expect(within(lessonList).getByText("需人工审核")).toBeInTheDocument();
  expect(within(lessonList).getByText("已改写")).toBeInTheDocument();
  expect(within(lessonList).getByText("medical_claim")).toBeInTheDocument();
  expect(within(lessonList).getByText(/小课内部理由/)).toBeInTheDocument();
  expect(within(shortList).getByLabelText("短片原标题 预览")).toHaveAttribute(
    "src",
    "/api/v1/media/asset-short-video?expires=9999999999&signature=signed",
  );
  expect(screen.queryByText("正在加载 Pipeline 状态…")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "高光时刻" })).not.toBeInTheDocument();
});

it("gates 选入交付 on eligibility and posts select for a deliverable clip", async () => {
  let body: DualProfileDecisionRequest | null = null;
  serveWorkspace();
  server.use(
    http.post(
      "/api/v1/projects/dual-1/dual-profile-import/clips/clip-short/decisions",
      async ({ request }) => {
        body = (await request.json()) as DualProfileDecisionRequest;
        return HttpResponse.json(
          dualProfileReview([
            { ...dualProfileShortClip, selected_for_delivery: true },
            dualProfileLessonClip,
          ]),
        );
      },
    ),
  );
  const user = userEvent.setup();
  renderWorkspace();
  await screen.findByRole("heading", { name: "短片（1）" });

  const lessonCheckbox = within(card("审核改写标题")).getByRole("checkbox", { name: "选入交付" });
  expect(lessonCheckbox).toBeDisabled();
  expect(within(card("审核改写标题")).getByText("不通过的切片不能选入交付")).toBeInTheDocument();

  const shortCheckbox = within(card("短片原标题")).getByRole("checkbox", { name: "选入交付" });
  expect(shortCheckbox).toBeEnabled();
  await user.click(shortCheckbox);
  await waitFor(() => expect(body).toEqual({ action: "select" }));
  await waitFor(() =>
    expect(within(card("短片原标题")).getByRole("checkbox", { name: "选入交付" })).toBeChecked(),
  );
});

it("prefills the approval form with the effective text and keeps earlier overrides", async () => {
  let body: DualProfileDecisionRequest | null = null;
  serveWorkspace();
  server.use(
    http.post(
      "/api/v1/projects/dual-1/dual-profile-import/clips/clip-lesson/decisions",
      async ({ request }) => {
        body = (await request.json()) as DualProfileDecisionRequest;
        return HttpResponse.json(dualProfileReview());
      },
    ),
  );
  const user = userEvent.setup();
  renderWorkspace();
  await screen.findByRole("heading", { name: "小课（1）" });

  await user.click(within(card("审核改写标题")).getByRole("button", { name: "批准" }));
  const form = screen.getByRole("form", { name: "批准 审核改写标题" });
  expect(within(form).getByLabelText("客户标题")).toHaveValue("审核改写标题");
  expect(within(form).getByLabelText("高光钩子")).toHaveValue("小课原钩子");
  expect(within(form).getByLabelText("内容摘要")).toHaveValue("小课原摘要");
  const summary = within(form).getByLabelText("内容摘要");
  await user.clear(summary);
  await user.type(summary, "  新的客户摘要 ");
  await user.click(within(form).getByRole("button", { name: "确认批准" }));

  await waitFor(() =>
    expect(body).toEqual({ action: "approve", title: "审核改写标题", summary: "新的客户摘要" }),
  );
});

it("hides review actions and selection for a viewer", async () => {
  serveWorkspace({
    ...dualProfileProject,
    current_user_role: "viewer",
    allowed_actions: ["read"],
  });
  renderWorkspace();
  await screen.findByRole("heading", { name: "短片（1）" });

  expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "不通过" })).not.toBeInTheDocument();
  expect(within(card("短片原标题")).getByRole("checkbox", { name: "选入交付" })).toBeDisabled();
  expect(within(card("短片原标题")).getByText("当前角色不能选择交付内容")).toBeInTheDocument();
});

it("shows a decision conflict returned by the API", async () => {
  serveWorkspace();
  server.use(
    http.post(
      "/api/v1/projects/dual-1/dual-profile-import/clips/clip-short/decisions",
      () =>
        HttpResponse.json(
          {
            error: {
              code: "STATE_CONFLICT",
              message: "only an automatically selected or approved clip can be selected for delivery",
              retryable: false,
              correlation_id: "c-1",
              details: [],
            },
          },
          { status: 409 },
        ),
    ),
  );
  const user = userEvent.setup();
  renderWorkspace();
  await screen.findByRole("heading", { name: "短片（1）" });
  await user.click(within(card("短片原标题")).getByRole("checkbox", { name: "选入交付" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("can be selected for delivery");
});

it("sends only fields that differ from the model original", () => {
  const original = { title: "原", hook: "钩", summary: "摘" };
  expect(approvalOverrides(original, { title: "原", hook: "钩", summary: "摘" })).toEqual({});
  expect(approvalOverrides(original, { title: " 新 ", hook: "钩", summary: "摘" })).toEqual({
    title: "新",
  });
});

it("imports a dual-profile run from the dialog", async () => {
  let body: DualProfileImportRequest | null = null;
  server.use(
    http.post("/api/v1/dual-profile-imports", async ({ request }) => {
      body = (await request.json()) as DualProfileImportRequest;
      return HttpResponse.json(
        { project_id: "dual-1", import_id: "import-1", snapshot: "744f55f73e45152c4f54", clip_count: 12, created: true },
        { status: 201 },
      );
    }),
  );
  const onImported = vi.fn();
  const user = userEvent.setup();
  renderWithClient(
    <DualProfileImportDialog api={new LiveClipApiClient()} onClose={() => undefined} onImported={onImported} />,
  );

  await user.type(screen.getByLabelText("结果目录（服务器本机路径）"), " data/evaluations/run-1 ");
  await user.type(screen.getByLabelText("转写字幕 SRT 路径"), "input/live.srt");
  await user.click(screen.getByRole("button", { name: "导入并开始审核" }));

  await waitFor(() => expect(onImported).toHaveBeenCalledWith("dual-1"));
  expect(body).toEqual({ run_dir: "data/evaluations/run-1", transcript_path: "input/live.srt" });
});

it("gates 生成交付包 until a deliverable clip is selected", async () => {
  serveWorkspace();
  renderWorkspace();
  const button = await screen.findByRole("button", { name: "生成交付包" });
  expect(button).toBeDisabled();
  expect(screen.getByText("请先在上方选入至少一条可交付的切片")).toBeInTheDocument();
});

it("creates a customer delivery with the previewed selection and lists versions", async () => {
  let body: CustomerDeliveryCreateRequest | null = null;
  let idempotencyKey: string | null = null;
  let created = false;
  const selectedLesson = {
    ...dualProfileLessonClip,
    review_state: "approved" as const,
    deliverable: true,
    selected_for_delivery: true,
  };
  serveWorkspace(dualProfileProject, [dualProfileShortClip, selectedLesson]);
  const response = {
    delivery: {
      delivery_id: "cd-1",
      project_id: "dual-1",
      task_id: "task-1",
      version: 1,
      delivery_version: "v001",
      title: "张老师 精选",
      status: "succeeded" as const,
      clip_count: 1,
      short_count: 0,
      lesson_count: 1,
      created_by: "本机管理员",
      created_at: "2026-11-07T12:00:00Z",
      completed_at: "2026-11-07T12:00:05Z",
      zip_asset_id: "asset-zip",
      error_code: null,
      safe_error_message: null,
    },
    download_url: "/api/v1/customer-deliveries/cd-1/download?expires=9999999999&signature=signed",
  };
  server.use(
    http.get("/api/v1/projects/dual-1/customer-deliveries", () =>
      HttpResponse.json(created ? [response] : []),
    ),
    http.post("/api/v1/projects/dual-1/customer-deliveries", async ({ request }) => {
      body = (await request.json()) as CustomerDeliveryCreateRequest;
      idempotencyKey = request.headers.get("Idempotency-Key");
      created = true;
      return HttpResponse.json(response, { status: 202 });
    }),
  );
  const user = userEvent.setup();
  renderWorkspace();

  const preview = await screen.findByLabelText("将包含的切片");
  expect(within(preview).getByText("小课 · 审核改写标题")).toBeInTheDocument();
  const title = screen.getByLabelText("交付标题（客户可见）");
  expect(title).toHaveValue("8-30 双轨结果 精选");
  await user.clear(title);
  await user.type(title, " 张老师 精选 ");
  await user.click(screen.getByRole("button", { name: "生成交付包" }));

  await waitFor(() =>
    expect(body).toEqual({ title: "张老师 精选", expected_clip_ids: ["clip-lesson"] }),
  );
  expect(idempotencyKey).toMatch(/^liveclip-web-customer-delivery-/);
  const versions = await screen.findByRole("list", { name: "客户交付版本列表" });
  expect(within(versions).getByText("v001")).toBeInTheDocument();
  expect(within(versions).getByText("已完成")).toBeInTheDocument();
  expect(within(versions).getByRole("link", { name: "下载 ZIP" })).toHaveAttribute(
    "href",
    response.download_url,
  );
});

const FLAGGED_SUMMARY = "老师示范推气，最后以OK收束。“那口腔”疑为转写错误。";
const flaggedLesson = {
  ...dualProfileLessonClip,
  original: { ...dualProfileLessonClip.original, summary: FLAGGED_SUMMARY },
  effective: { ...dualProfileLessonClip.effective, summary: FLAGGED_SUMMARY },
  text_warnings: [
    { field: "summary" as const, kind: "narration" as const, start: FLAGGED_SUMMARY.indexOf("以OK收束"), end: FLAGGED_SUMMARY.indexOf("以OK收束") + 5, match: "以OK收束", message: "叙述片段如何收尾" },
    { field: "summary" as const, kind: "strong" as const, start: FLAGGED_SUMMARY.indexOf("疑为"), end: FLAGGED_SUMMARY.indexOf("疑为") + 2, match: "疑为", message: "“疑为/疑似”是审核推测，不应给客户看" },
    { field: "summary" as const, kind: "strong" as const, start: FLAGGED_SUMMARY.indexOf("转写"), end: FLAGGED_SUMMARY.indexOf("转写") + 2, match: "转写", message: "提及转写/误转写，属于审核备注" },
  ],
};

it("flags reviewer-style notes in the approval form and sends an explicit acknowledgement", async () => {
  let body: DualProfileDecisionRequest | null = null;
  serveWorkspace(dualProfileProject, [dualProfileShortClip, flaggedLesson]);
  server.use(
    http.post(
      "/api/v1/projects/dual-1/dual-profile-import/clips/clip-lesson/decisions",
      async ({ request }) => {
        body = (await request.json()) as DualProfileDecisionRequest;
        return HttpResponse.json(dualProfileReview([dualProfileShortClip, flaggedLesson]));
      },
    ),
  );
  const user = userEvent.setup();
  renderWorkspace();
  await screen.findByRole("heading", { name: "小课（1）" });
  expect(within(card("审核改写标题")).getByText("文案含疑似审核备注，批准前请改写")).toBeInTheDocument();

  await user.click(within(card("审核改写标题")).getByRole("button", { name: "批准" }));
  const form = screen.getByRole("form", { name: "批准 审核改写标题" });
  const notice = within(form).getByRole("note", { name: "内容摘要文案提示" });
  expect(notice).toHaveTextContent("疑似审核备注，请改写");
  expect([...notice.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
    "以OK收束",
    "疑为",
    "转写",
  ]);
  const confirm = within(form).getByRole("button", { name: "确认批准" });
  expect(confirm).toBeDisabled();
  await user.click(within(form).getByRole("checkbox", { name: "仍然保留原文" }));
  expect(confirm).toBeEnabled();
  await user.click(confirm);

  await waitFor(() =>
    expect(body).toEqual({
      action: "approve",
      title: "审核改写标题",
      acknowledge_warnings: true,
    }),
  );
});

it("clears the notice after a rewrite and shows the server's warnings on a 409", async () => {
  const bodies: DualProfileDecisionRequest[] = [];
  serveWorkspace(dualProfileProject, [dualProfileShortClip, flaggedLesson]);
  server.use(
    http.post(
      "/api/v1/projects/dual-1/dual-profile-import/clips/clip-lesson/decisions",
      async ({ request }) => {
        bodies.push((await request.json()) as DualProfileDecisionRequest);
        return HttpResponse.json(
          {
            error: {
              schema_version: "1",
              code: "CUSTOMER_TEXT_WARNING",
              message: "customer text still contains reviewer-style notes",
              retryable: false,
              resource_id: null,
              correlation_id: "c-2",
              details: [{ location: ["summary", 3, 5], type: "customer_text_warning.strong" }],
            },
          },
          { status: 409 },
        );
      },
    ),
  );
  const user = userEvent.setup();
  renderWorkspace();
  await screen.findByRole("heading", { name: "小课（1）" });
  await user.click(within(card("审核改写标题")).getByRole("button", { name: "批准" }));
  const form = screen.getByRole("form", { name: "批准 审核改写标题" });
  const summary = within(form).getByLabelText("内容摘要");
  await user.clear(summary);
  await user.type(summary, "改写后疑似仍有问题");
  expect(within(form).queryByRole("note", { name: "内容摘要文案提示" })).not.toBeInTheDocument();
  await user.click(within(form).getByRole("button", { name: "确认批准" }));

  const notice = await within(form).findByRole("note", { name: "内容摘要文案提示" });
  expect(notice.querySelector("mark")?.textContent).toBe("疑似");
  expect(bodies[0]).not.toHaveProperty("acknowledge_warnings");
  expect(within(form).getByRole("checkbox", { name: "仍然保留原文" })).not.toBeChecked();
});

it("lists selected clips with text warnings before 生成交付包", async () => {
  serveWorkspace(dualProfileProject, [
    dualProfileShortClip,
    { ...flaggedLesson, review_state: "approved", deliverable: true, selected_for_delivery: true },
  ]);
  renderWorkspace();
  const note = await screen.findByRole("note", { name: "交付文案提示" });
  expect(note).toHaveTextContent("审核改写标题 · 疑似审核备注");
  expect(screen.getByRole("button", { name: "生成交付包" })).toBeEnabled();
});
