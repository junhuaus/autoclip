import { HttpResponse, http } from "msw";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { ClipCard, ProjectWorkspace } from "../src/ProjectWorkspace";
import type {
  BatchReviewRequest,
  BatchReviewResponse,
  ClipDetailResponse,
  ClipSummaryResponse,
} from "../src/types";
import { clipDetail, clipSummary, completedRun, project, transcript } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

function secondSummary(): ClipSummaryResponse {
  return {
    ...structuredClone(clipSummary),
    clip: {
      ...structuredClone(clipSummary.clip),
      clip_id: "clip-2",
      candidate_key: "candidate-2",
      title: "第二条高光",
      hook: "第二条应该上屏的高光语句",
      source_start_ms: 20_000,
      source_end_ms: 30_000,
      keywords: [
        {
          text: "第二关键词",
          clip_start_ms: 2_000,
          clip_end_ms: 5_000,
          source_start_ms: 22_000,
          source_end_ms: 25_000,
          timing_precision: "segment",
        },
      ],
    },
    proxy_media_url: "/api/v1/media/asset-proxy-2?expires=9999999999&signature=signed",
    download_video_url: "/api/v1/clips/clip-2/download/video?expires=9999999999&signature=video",
    download_subtitle_url: "/api/v1/clips/clip-2/download/subtitle?expires=9999999999&signature=srt",
  };
}

function secondDetail(): ClipDetailResponse {
  const value = structuredClone(clipDetail);
  value.clip.clip_id = "clip-2";
  value.clip.candidate_key = "candidate-2";
  value.clip.plan.candidate_id = "clip-2";
  value.clip.plan.title = "第二条高光";
  return value;
}

function reviewedDetail(
  value: ClipDetailResponse,
  status: "approved" | "rejected" = "approved",
): ClipDetailResponse {
  const result = structuredClone(value);
  result.clip.review = {
    status,
    reason: status === "rejected" ? "未选入交付" : null,
    decided_at: "2026-08-11T00:00:00Z",
  };
  result.clip.allowed_actions = ["edit", "approve", "reject", "render_proxy"];
  return result;
}

it("seeks only the video belonging to the clicked subtitle or keyword", async () => {
  const user = userEvent.setup();
  const second = secondSummary();
  render(
    <>
      <ClipCard item={clipSummary} onOpen={() => undefined} />
      <ClipCard item={second} onOpen={() => undefined} />
    </>,
  );
  const videos = screen.getAllByLabelText(/预览交付母版/) as HTMLVideoElement[];
  for (const video of videos) {
    Object.defineProperty(video, "readyState", { configurable: true, value: 1 });
    Object.defineProperty(video, "duration", { configurable: true, value: 10 });
  }

  await user.click(screen.getByRole("button", { name: /定位到编辑关键词 第二关键词/ }));
  expect(videos[0].currentTime).toBe(0);
  expect(videos[1].currentTime).toBe(2);

  await user.click(screen.getAllByRole("button", { name: /定位到字幕/ })[0]);
  expect(videos[0].currentTime).toBe(0);
  expect(videos[1].currentTime).toBe(2);
  expect(screen.getAllByText("转写段时间窗").length).toBeGreaterThan(0);
});

it("renders each highlight as one horizontal list row with its sentence and captions last", () => {
  const { container } = render(<ClipCard item={clipSummary} onOpen={() => undefined} />);
  const card = container.querySelector("article.clip-card");
  const main = card?.querySelector(":scope > .clip-card-main");
  const captions = card?.querySelector(":scope > .clip-card-captions");

  expect(card).not.toBeNull();
  expect(main).not.toBeNull();
  expect(captions).not.toBeNull();
  expect(main?.nextElementSibling).toBe(captions);
  expect(screen.getByRole("heading", { name: "高光语句" })).toBeVisible();
  expect(screen.getByText("开头提出关键问题")).toBeVisible();
  expect(screen.getByRole("heading", { name: "编辑关键词" })).toBeVisible();
  expect(screen.getByText("推荐上屏")).toBeVisible();
  expect(screen.getByText("仅供编辑定位")).toBeVisible();
});

it("uses one delivery-selection control and hides the separate editing-handoff flow", async () => {
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () =>
      HttpResponse.json([structuredClone(clipSummary)]),
    ),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
  );

  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  expect(await screen.findByLabelText("选入交付")).toBeVisible();
  expect(screen.queryByText("剪辑交接包")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("选择导出")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "网页交付包" })).toBeVisible();
});

it("omits the redundant full transcript panel and does not request it", async () => {
  let transcriptReads = 0;
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => {
      transcriptReads += 1;
      return HttpResponse.json(transcript);
    }),
    http.get("/api/v1/projects/project-1/clips", () =>
      HttpResponse.json([structuredClone(clipSummary)]),
    ),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
  );

  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  await screen.findByRole("heading", { name: "高光时刻" });
  await screen.findByLabelText("原始高光标题 字幕");
  expect(screen.queryByText("源视频绝对时间")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "转写" })).not.toBeInTheDocument();
  expect(transcriptReads).toBe(0);
});

it("lets the owner add a project editor from the collaboration panel", async () => {
  let submitted: unknown = null;
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json([])),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/members", async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json({
        schema_version: "1",
        project_id: "project-1",
        members: [
          ...project.members,
          {
            user_id: "editor-1",
            username: "lin-editor",
            display_name: "林编辑",
            role: "editor",
          },
        ],
      });
    }),
  );
  const user = userEvent.setup();

  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  await user.click(await screen.findByRole("button", { name: "＋ 添加成员" }));
  await user.type(screen.getByLabelText("成员账号"), "lin-editor");
  await user.type(screen.getByLabelText("显示名称"), "林编辑");
  await user.click(screen.getByRole("button", { name: "添加到项目" }));

  await waitFor(() =>
    expect(submitted).toEqual({
      username: "lin-editor",
      display_name: "林编辑",
      role: "editor",
    }),
  );
});

it("lets the owner assign, prioritize and advance a project without client-side transitions", async () => {
  let managementBody: unknown = null;
  let lifecycleBody: unknown = null;
  const managed = {
    ...project,
    priority: "urgent" as const,
    visibility: "workspace" as const,
    management_version: 2,
  };
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json([])),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.patch("/api/v1/projects/project-1/management", async ({ request }) => {
      managementBody = await request.json();
      return HttpResponse.json(managed);
    }),
    http.post("/api/v1/projects/project-1/lifecycle", async ({ request }) => {
      lifecycleBody = await request.json();
      return HttpResponse.json({
        ...managed,
        lifecycle: "approval",
        management_version: 3,
        allowed_lifecycle_transitions: ["changes_requested", "ready_to_publish", "archived"],
      });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  await screen.findByRole("heading", { name: "任务与生命周期" });
  await user.selectOptions(screen.getByLabelText("优先级"), "urgent");
  await user.selectOptions(screen.getByLabelText("可见范围"), "workspace");
  await user.click(screen.getByRole("button", { name: "保存项目设置" }));
  await waitFor(() => expect(managementBody).toMatchObject({
    expected_management_version: 1,
    priority: "urgent",
    visibility: "workspace",
  }));

  await user.selectOptions(screen.getByLabelText("下一阶段"), "approval");
  await user.type(screen.getByLabelText("操作说明"), "内容已完成编辑审核");
  await user.click(screen.getByRole("button", { name: "确认推进" }));
  await waitFor(() => expect(lifecycleBody).toEqual({
    expected_management_version: 2,
    target: "approval",
    reason: "内容已完成编辑审核",
  }));
  expect((await screen.findAllByText("终审")).length).toBeGreaterThan(0);
});

it("requires an explicit confirmation before transferring project ownership", async () => {
  const editor = {
    user_id: "editor-1",
    username: "lin-editor",
    display_name: "林编辑",
    role: "editor" as const,
  };
  let transferredTo: unknown = null;
  let projectView = { ...project, members: [...project.members, editor] };
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(projectView)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json([])),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post(
      "/api/v1/projects/project-1/ownership-transfer",
      async ({ request }) => {
        transferredTo = await request.json();
        projectView = {
          ...projectView,
          owner: { ...editor, role: "owner" },
          members: [
            { ...editor, role: "owner" },
            { ...project.members[0], role: "editor" },
          ],
          current_user_role: "editor",
          allowed_actions: [
            "read",
            "run_pipeline",
            "edit_clip",
            "comment",
            "render",
            "export",
            "deliver",
          ],
        };
        return HttpResponse.json({
          schema_version: "1",
          project_id: "project-1",
          members: projectView.members,
        });
      },
    ),
  );
  const user = userEvent.setup();

  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  await user.click(await screen.findByRole("button", { name: "移交负责人" }));
  expect(screen.getByRole("alertdialog", { name: "确认移交项目负责人" })).toHaveTextContent(
    "你将变为编辑",
  );
  expect(transferredTo).toBeNull();
  await user.click(screen.getByRole("button", { name: "确认移交" }));
  await waitFor(() => expect(transferredTo).toEqual({ new_owner_user_id: "editor-1" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "＋ 添加成员" })).toBeNull());
});

it("uses server capabilities to keep a viewer read-only", async () => {
  const viewerProject = {
    ...project,
    current_user_role: "viewer" as const,
    allowed_actions: ["read"] as const,
  };
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(viewerProject)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () =>
      HttpResponse.json([structuredClone(clipSummary)]),
    ),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(clipDetail)),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
  );
  const user = userEvent.setup();

  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  expect(await screen.findByText("只读 · 1 位成员")).toBeVisible();
  expect(screen.queryByRole("button", { name: "＋ 添加成员" })).not.toBeInTheDocument();
  expect(await screen.findByLabelText("选入交付")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "取消处理" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "导出所选高光" })).toBeDisabled();

  await user.click(await screen.findByRole("button", { name: "编辑详情" }));
  const editorPanel = await screen.findByRole("region", { name: /原始高光标题/ });
  expect(within(editorPanel).getByLabelText("标题")).toBeDisabled();
  expect(within(editorPanel).getByLabelText("评分")).toBeDisabled();
  expect(within(editorPanel).queryByRole("button", { name: "批准" })).not.toBeInTheDocument();
  expect(
    within(editorPanel).getByRole("button", { name: "渲染预览/交付母版" }),
  ).toBeDisabled();
});

it("submits selected candidates through one atomic batch endpoint", async () => {
  const summaries = [structuredClone(clipSummary), secondSummary()];
  let batchBody: BatchReviewRequest | null = null;
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => HttpResponse.json(transcript)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json(summaries)),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(clipDetail)),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/reviews/batch", async ({ request }) => {
      batchBody = (await request.json()) as BatchReviewRequest;
      const response: BatchReviewResponse = {
        schema_version: "1",
        project_id: "project-1",
        clips: [reviewedDetail(clipDetail), reviewedDetail(secondDetail())],
      };
      return HttpResponse.json(response);
    }),
  );

  const user = userEvent.setup();
  const { client } = renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  await user.click((await screen.findAllByRole("button", { name: "编辑详情" }))[0]);
  await screen.findByRole("button", { name: "关闭详情" });
  await user.click(await screen.findByLabelText("全选可交付高光"));

  await waitFor(() =>
    expect(batchBody).toEqual({
      items: [
        { clip_id: "clip-1", expected_revision: 1, status: "approved" },
        { clip_id: "clip-2", expected_revision: 1, status: "approved" },
      ],
    }),
  );
  expect(await screen.findByText("已更新 2 条交付选择。")).toBeVisible();
  await waitFor(() =>
    expect(
      (client.getQueryData(["clip", "clip-1"]) as ClipDetailResponse).clip.review.status,
    ).toBe("approved"),
  );
  expect(screen.getByText(/勾选即保存，不需要审批/)).toBeVisible();
});

it("retries a failed batch with the exact same body and idempotency key", async () => {
  const summaries = [structuredClone(clipSummary), secondSummary()];
  const requestKeys: Array<string | null> = [];
  const requestBodies: BatchReviewRequest[] = [];
  let clipListReads = 0;
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => HttpResponse.json(transcript)),
    http.get("/api/v1/projects/project-1/clips", () => {
      clipListReads += 1;
      return HttpResponse.json(summaries);
    }),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/reviews/batch", async ({ request }) => {
      requestKeys.push(request.headers.get("Idempotency-Key"));
      requestBodies.push((await request.json()) as BatchReviewRequest);
      if (requestKeys.length === 1) return HttpResponse.error();
      return HttpResponse.json({
        schema_version: "1",
        project_id: "project-1",
        clips: [reviewedDetail(clipDetail), reviewedDetail(secondDetail())],
      } satisfies BatchReviewResponse);
    }),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  await user.click(await screen.findByLabelText("全选可交付高光"));

  expect(await screen.findByRole("alert")).toHaveTextContent("无法连接本机 LiveClip API");
  expect(await screen.findByText(/选择状态已重新加载/)).toBeVisible();
  expect(clipListReads).toBeGreaterThan(1);
  await user.click(screen.getByRole("button", { name: "重试同一批次" }));
  expect(await screen.findByText("已更新 2 条交付选择。")).toBeVisible();

  expect(requestKeys).toHaveLength(2);
  expect(requestKeys[0]).toBeTruthy();
  expect(requestKeys[1]).toBe(requestKeys[0]);
  expect(requestBodies[1]).toEqual(requestBodies[0]);
});

it("blocks retry when a clip from the failed batch gains an unsaved draft", async () => {
  const summaries = [structuredClone(clipSummary), secondSummary()];
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => HttpResponse.json(transcript)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json(summaries)),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(clipDetail)),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/reviews/batch", () => HttpResponse.error()),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  await user.click(await screen.findByLabelText("全选可交付高光"));
  const retryButton = await screen.findByRole("button", { name: "重试同一批次" });
  expect(retryButton).toBeEnabled();

  await user.click((await screen.findAllByRole("button", { name: "编辑详情" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.clear(titleInput);
  await user.type(titleInput, "失败批次之后的新草稿");

  await waitFor(() => expect(retryButton).toBeDisabled());
  expect(screen.getByText(/原操作包含未保存编辑/)).toBeVisible();
});

it("locks delivery selection while a candidate has an unsaved editor draft", async () => {
  const summaries = [structuredClone(clipSummary), secondSummary()];
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => HttpResponse.json(transcript)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json(summaries)),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(clipDetail)),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  const selectors = await screen.findAllByLabelText("选入交付");
  await user.click((await screen.findAllByRole("button", { name: "编辑详情" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.clear(titleInput);
  await user.type(titleInput, "尚未保存的新标题");

  await waitFor(() => expect(selectors[0]).toBeDisabled());
  expect(selectors[0]).not.toBeChecked();
  expect(screen.getByText(/存在未保存编辑，暂时不能改变选择/)).toBeVisible();
});

it("locks the editor while a selection write is in flight", async () => {
  const summaries = [structuredClone(clipSummary), secondSummary()];
  let releaseBatch: (() => void) | null = null;
  const batchGate = new Promise<void>((resolve) => {
    releaseBatch = resolve;
  });
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/transcript", () => HttpResponse.json(transcript)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json(summaries)),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(clipDetail)),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/reviews/batch", async () => {
      await batchGate;
      return HttpResponse.json({
        schema_version: "1",
        project_id: "project-1",
        clips: [reviewedDetail(clipDetail)],
      } satisfies BatchReviewResponse);
    }),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  await user.click((await screen.findAllByRole("button", { name: "编辑详情" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.click((await screen.findAllByLabelText("选入交付"))[0]);

  await waitFor(() => expect(titleInput).toBeDisabled());
  for (const openButton of screen.getAllByRole("button", { name: "编辑详情" })) {
    expect(openButton).toBeDisabled();
  }
  expect(titleInput).toHaveValue("原始高光标题");

  act(() => releaseBatch?.());
  expect(await screen.findByText("已更新 1 条交付选择。")).toBeVisible();
  expect(titleInput).toHaveValue("原始高光标题");
});
