import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { ProjectWorkspace } from "../src/ProjectWorkspace";
import type { ClipDetailResponse, ClipPatchRequest, ClipSummaryResponse, ReviewActionRequest } from "../src/types";
import { clipDetail, clipSummary, completedRun, project } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

it("edits title, boundaries and cue text, exposes stale media, then approves the new revision", async () => {
  let currentDetail: ClipDetailResponse = clipDetail;
  let currentSummary: ClipSummaryResponse = clipSummary;
  let patchBody: ClipPatchRequest | null = null;
  let reviewBody: ReviewActionRequest | null = null;

  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json([currentSummary])),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(currentDetail)),
    http.patch("/api/v1/clips/clip-1", async ({ request }) => {
      patchBody = (await request.json()) as ClipPatchRequest;
      const title = patchBody.title ?? currentDetail.clip.plan.title;
      currentDetail = {
        clip: {
          ...currentDetail.clip,
          current_revision: 2,
          revision_epoch: 1,
          plan: {
            ...currentDetail.clip.plan,
            title,
            source_start_ms: patchBody.source_start_ms ?? currentDetail.clip.plan.source_start_ms,
            source_end_ms: patchBody.source_end_ms ?? currentDetail.clip.plan.source_end_ms,
          },
          captions: patchBody.captions ?? currentDetail.clip.captions,
          review: { status: "pending_review", reason: null, decided_at: null },
          renders: currentDetail.clip.renders.map((render) => ({ ...render, status: "stale" })),
          allowed_actions: ["edit", "approve", "reject", "render_proxy"],
        },
        asset_urls: {},
      };
      currentSummary = {
        clip: {
          ...currentSummary.clip,
          edit_plan_revision: 2,
          title,
          source_start_ms: currentDetail.clip.plan.source_start_ms,
          source_end_ms: currentDetail.clip.plan.source_end_ms,
          review_status: "pending_review",
          proxy_status: "stale",
          proxy_asset_id: null,
        },
        proxy_media_url: null,
      };
      return HttpResponse.json(currentDetail);
    }),
    http.post("/api/v1/clips/clip-1/review", async ({ request }) => {
      reviewBody = (await request.json()) as ReviewActionRequest;
      currentDetail = {
        ...currentDetail,
        clip: {
          ...currentDetail.clip,
          review: { status: "approved", reason: null, decided_at: "2026-08-04T00:01:00Z" },
          allowed_actions: ["edit", "approve", "reject", "render_proxy", "render_final"],
        },
      };
      currentSummary = {
        ...currentSummary,
        clip: { ...currentSummary.clip, review_status: "approved" },
      };
      return HttpResponse.json(currentDetail);
    }),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );

  await user.click(await screen.findByRole("button", { name: "审核和编辑" }));
  const editor = await screen.findByRole("region", { name: /原始高光标题/ });
  expect(within(editor).getByText("高光描述（独立元数据）")).toBeInTheDocument();
  expect(within(editor).getByText(/开头提出关键问题/)).toBeInTheDocument();
  expect(within(editor).getByText(/干净审核切片/)).toBeInTheDocument();
  expect(within(editor).getByText("每个 revision 至少保留 1 条字幕 cue。")).toBeVisible();
  expect(within(editor).getByRole("button", { name: "删除此 cue" })).toBeDisabled();
  const titleInput = within(editor).getByLabelText("标题");
  await user.clear(titleInput);
  await user.type(titleInput, "人工修改后的标题");
  const startInput = within(editor).getByLabelText("源开始（ms）");
  await user.clear(startInput);
  await user.type(startInput, "1200");
  const cueText = within(editor).getByLabelText("文本");
  await user.clear(cueText);
  await user.type(cueText, "人工调整后的字幕");
  await user.click(within(editor).getByRole("button", { name: "保存为新 revision" }));

  expect(await within(editor).findByText(/旧 revision 的 1 个渲染已失效/)).toBeInTheDocument();
  expect(patchBody).toEqual({
    expected_revision: 1,
    source_start_ms: 1_200,
    title: "人工修改后的标题",
    captions: [{ start_ms: 0, end_ms: 4_000, text: "人工调整后的字幕" }],
  });

  await user.click(within(editor).getByRole("button", { name: "批准" }));
  await waitFor(() => expect(reviewBody).toEqual({ expected_revision: 2, status: "approved" }));
  expect(await within(editor).findByText("已批准")).toHaveAttribute("data-status", "approved");
  expect(within(editor).getByRole("button", { name: "渲染最终视频" })).toBeEnabled();
});

it("sends a boundary-only patch without stale relative captions", async () => {
  let patchBody: ClipPatchRequest | null = null;
  let currentDetail = clipDetail;
  server.use(
    http.get("/api/v1/projects/project-1", () => HttpResponse.json(project)),
    http.get("/api/v1/runs/run-1", () => HttpResponse.json(completedRun)),
    http.get("/api/v1/projects/project-1/clips", () => HttpResponse.json([clipSummary])),
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.get("/api/v1/clips/clip-1", () => HttpResponse.json(currentDetail)),
    http.patch("/api/v1/clips/clip-1", async ({ request }) => {
      patchBody = (await request.json()) as ClipPatchRequest;
      currentDetail = {
        ...currentDetail,
        clip: {
          ...currentDetail.clip,
          current_revision: 2,
          revision_epoch: 1,
          plan: { ...currentDetail.clip.plan, source_start_ms: 1_200 },
          captions: [{ start_ms: 0, end_ms: 3_800, text: "后端重算后的字幕" }],
        },
      };
      return HttpResponse.json(currentDetail);
    }),
  );

  const user = userEvent.setup();
  renderWithClient(
    <ProjectWorkspace api={new LiveClipApiClient()} projectId="project-1" onBack={() => undefined} />,
  );
  await user.click(await screen.findByRole("button", { name: "审核和编辑" }));
  const editor = await screen.findByRole("region", { name: /原始高光标题/ });
  const startInput = within(editor).getByLabelText("源开始（ms）");
  await user.clear(startInput);
  await user.type(startInput, "1200");
  await user.click(within(editor).getByRole("button", { name: "保存为新 revision" }));

  await waitFor(() =>
    expect(patchBody).toEqual({ expected_revision: 1, source_start_ms: 1_200 }),
  );
  expect(within(editor).getByDisplayValue("后端重算后的字幕")).toBeInTheDocument();
});
