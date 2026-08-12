import { HttpResponse, http } from "msw";
import { act, render, screen, waitFor } from "@testing-library/react";
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
    reason: status === "rejected" ? "批量拒绝" : null,
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
  const videos = screen.getAllByLabelText(/审核代理/) as HTMLVideoElement[];
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
  await user.click((await screen.findAllByRole("button", { name: "审核和编辑" }))[0]);
  await screen.findByRole("button", { name: "关闭详情" });
  await user.click(await screen.findByLabelText("全选可审核高光"));
  await user.click(screen.getByRole("button", { name: "批量批准" }));

  await waitFor(() =>
    expect(batchBody).toEqual({
      items: [
        { clip_id: "clip-1", expected_revision: 1, status: "approved" },
        { clip_id: "clip-2", expected_revision: 1, status: "approved" },
      ],
    }),
  );
  expect(await screen.findByText("已原子提交 2 条审核决定。")).toBeVisible();
  await waitFor(() =>
    expect(
      (client.getQueryData(["clip", "clip-1"]) as ClipDetailResponse).clip.review.status,
    ).toBe("approved"),
  );
  expect(screen.getAllByText("已批准").length).toBeGreaterThan(0);
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
  await user.click(await screen.findByLabelText("全选可审核高光"));
  await user.click(screen.getByRole("button", { name: "批量批准" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("无法连接本机 LiveClip API");
  expect(await screen.findByText(/审核状态已重新加载/)).toBeVisible();
  expect(clipListReads).toBeGreaterThan(1);
  await user.click(screen.getByRole("button", { name: "重试同一批次" }));
  expect(await screen.findByText("已原子提交 2 条审核决定。")).toBeVisible();

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
  await user.click(await screen.findByLabelText("全选可审核高光"));
  await user.click(screen.getByRole("button", { name: "批量批准" }));
  const retryButton = await screen.findByRole("button", { name: "重试同一批次" });
  expect(retryButton).toBeEnabled();

  await user.click((await screen.findAllByRole("button", { name: "审核和编辑" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.clear(titleInput);
  await user.type(titleInput, "失败批次之后的新草稿");

  await waitFor(() => expect(retryButton).toBeDisabled());
  expect(screen.getByText(/原批次包含未保存编辑/)).toBeVisible();
});

it("excludes a candidate with an unsaved editor draft from batch review", async () => {
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
  const selectors = await screen.findAllByLabelText("选择批量审核");
  await user.click(selectors[0]);
  await user.click((await screen.findAllByRole("button", { name: "审核和编辑" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.clear(titleInput);
  await user.type(titleInput, "尚未保存的新标题");

  await waitFor(() => expect(selectors[0]).toBeDisabled());
  expect(selectors[0]).not.toBeChecked();
  expect(screen.getByRole("button", { name: "批量批准" })).toBeDisabled();
  expect(screen.getByText(/存在未保存编辑，已从批量审核中排除/)).toBeVisible();
});

it("locks the editor while a selected batch review is in flight", async () => {
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
  await user.click((await screen.findAllByRole("button", { name: "审核和编辑" }))[0]);
  const titleInput = await screen.findByLabelText("标题");
  await user.click((await screen.findAllByLabelText("选择批量审核"))[0]);
  await user.click(screen.getByRole("button", { name: "批量批准" }));

  await waitFor(() => expect(titleInput).toBeDisabled());
  for (const openButton of screen.getAllByRole("button", { name: "审核和编辑" })) {
    expect(openButton).toBeDisabled();
  }
  expect(titleInput).toHaveValue("原始高光标题");

  act(() => releaseBatch?.());
  expect(await screen.findByText("已原子提交 1 条审核决定。")).toBeVisible();
  expect(titleInput).toHaveValue("原始高光标题");
});
