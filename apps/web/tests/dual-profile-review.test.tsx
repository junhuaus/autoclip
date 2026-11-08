import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { DualProfileImportDialog, approvalOverrides } from "../src/DualProfileReview";
import { ProjectWorkspace } from "../src/ProjectWorkspace";
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
