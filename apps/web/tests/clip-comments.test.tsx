import { useState } from "react";
import { HttpResponse, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { ClipComments } from "../src/ClipComments";
import type {
  ClipCommentReplyRequest,
  ClipCommentStatusRequest,
  ClipCommentThread,
  ClipCommentThreadCreateRequest,
} from "../src/types";
import { project } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

function threadFixture(): ClipCommentThread {
  return {
    thread_id: "thread-1",
    project_id: "project-1",
    clip_id: "clip-1",
    edit_plan_revision: 1,
    current_revision: 1,
    is_current_revision: true,
    is_current_generation: true,
    source_time_ms: 3_500,
    clip_time_ms: 2_500,
    current_clip_time_ms: 2_500,
    status: "open",
    version: 1,
    allowed_actions: ["reply", "resolve"],
    created_by: {
      user_id: "user-local-admin",
      username: "local-admin",
      display_name: "本机管理员",
    },
    resolved_by: null,
    created_at: "2026-08-15T12:00:00Z",
    updated_at: "2026-08-15T12:00:00Z",
    resolved_at: null,
    comments: [
      {
        comment_id: "comment-1",
        author: {
          user_id: "user-local-admin",
          username: "local-admin",
          display_name: "本机管理员",
        },
        body: "这里需要补一个转场",
        mentions: [],
        created_at: "2026-08-15T12:00:00Z",
      },
    ],
  };
}

it("captures the player time, creates a revision-bound thread, replies and resolves it", async () => {
  let current: ClipCommentThread | null = null;
  let createBody: ClipCommentThreadCreateRequest | null = null;
  let replyBody: ClipCommentReplyRequest | null = null;
  let statusBody: ClipCommentStatusRequest | null = null;
  const editor = {
    user_id: "editor-1",
    username: "lin-editor",
    display_name: "林编辑",
    role: "editor" as const,
  };
  server.use(
    http.get("/api/v1/clips/clip-1/comment-threads", () =>
      HttpResponse.json({
        schema_version: "1",
        clip_id: "clip-1",
        current_revision: 1,
        total_count: current ? 1 : 0,
        next_offset: null,
        threads: current ? [current] : [],
      }),
    ),
    http.post("/api/v1/clips/clip-1/comment-threads", async ({ request }) => {
      createBody = (await request.json()) as ClipCommentThreadCreateRequest;
      current = threadFixture();
      current.comments[0].mentions = [
        { user_id: editor.user_id, username: editor.username, display_name: editor.display_name },
      ];
      return HttpResponse.json(current, { status: 201 });
    }),
    http.post("/api/v1/comment-threads/thread-1/replies", async ({ request }) => {
      replyBody = (await request.json()) as ClipCommentReplyRequest;
      const next = structuredClone(current as ClipCommentThread);
      next.version = 2;
      next.comments.push({
        comment_id: "comment-2",
        author: { user_id: editor.user_id, username: editor.username, display_name: editor.display_name },
        body: replyBody.body,
        mentions: [],
        created_at: "2026-08-15T12:01:00Z",
      });
      current = next;
      return HttpResponse.json(next, { status: 201 });
    }),
    http.post("/api/v1/comment-threads/thread-1/status", async ({ request }) => {
      statusBody = (await request.json()) as ClipCommentStatusRequest;
      const next = structuredClone(current as ClipCommentThread);
      next.status = "resolved";
      next.version = 3;
      next.allowed_actions = ["reopen"];
      next.resolved_at = "2026-08-15T12:02:00Z";
      next.resolved_by = {
        user_id: editor.user_id,
        username: editor.username,
        display_name: editor.display_name,
      };
      current = next;
      return HttpResponse.json(next);
    }),
  );
  const user = userEvent.setup();
  const seek = vi.fn();
  renderWithClient(
    <ClipComments
      api={new LiveClipApiClient()}
      clipId="clip-1"
      currentRevision={1}
      durationMs={10_000}
      members={[...project.members, editor]}
      canCreate
      getCurrentTimeMs={() => 2_500}
      onSeek={seek}
    />,
  );

  await screen.findByText("当前筛选下还没有批注");
  await user.click(screen.getByRole("button", { name: "使用播放器当前时间" }));
  expect(screen.getByLabelText("片段时间（秒）")).toHaveValue(2.5);
  await user.type(screen.getByLabelText("批注内容"), "这里需要补一个转场");
  await user.selectOptions(screen.getByLabelText("提醒项目成员（可多选）"), editor.user_id);
  await user.click(screen.getByRole("button", { name: "添加时间点批注" }));

  await waitFor(() =>
    expect(createBody).toEqual({
      expected_revision: 1,
      clip_time_ms: 2_500,
      body: "这里需要补一个转场",
      mentioned_user_ids: [editor.user_id],
    }),
  );
  expect(await screen.findByText("这里需要补一个转场")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "00:02.500" }));
  expect(seek).toHaveBeenCalledWith(2_500);

  await user.type(screen.getByLabelText("回复"), "已收到，会在这里调整");
  await user.click(screen.getByRole("button", { name: "回复" }));
  await waitFor(() =>
    expect(replyBody).toEqual({ body: "已收到，会在这里调整", mentioned_user_ids: [] }),
  );
  expect(replyBody).not.toHaveProperty("expected_thread_version");
  expect(await screen.findByText("已收到，会在这里调整")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "标记已解决" }));
  await waitFor(() =>
    expect(statusBody).toEqual({ expected_thread_version: 2, status: "resolved" }),
  );
  expect(await screen.findByText("已解决")).toBeVisible();
  expect(screen.getByRole("button", { name: "重新打开" })).toBeEnabled();
});

it("shows historical anchors read-only and seeks using the current revision position", async () => {
  const historical = threadFixture();
  historical.edit_plan_revision = 1;
  historical.current_revision = 2;
  historical.is_current_revision = false;
  historical.clip_time_ms = 2_500;
  historical.current_clip_time_ms = 1_500;
  historical.status = "resolved";
  historical.version = 4;
  historical.allowed_actions = [];
  historical.resolved_at = "2026-08-15T12:02:00Z";
  historical.resolved_by = historical.created_by;
  server.use(
    http.get("/api/v1/clips/clip-1/comment-threads", () =>
      HttpResponse.json({
        schema_version: "1",
        clip_id: "clip-1",
        current_revision: 2,
        total_count: 1,
        next_offset: null,
        threads: [historical],
      }),
    ),
  );
  const user = userEvent.setup();
  const seek = vi.fn();
  renderWithClient(
    <ClipComments
      api={new LiveClipApiClient()}
      clipId="clip-1"
      currentRevision={2}
      durationMs={8_000}
      members={project.members}
      canCreate={false}
      createDisabledReason="请先保存当前编辑草稿；新批注必须绑定一个已保存的 revision。"
      getCurrentTimeMs={() => null}
      onSeek={seek}
    />,
  );

  expect(await screen.findByText("历史 r1")).toBeVisible();
  expect(screen.getByText(/当前切片中的位置为 00:01.500/)).toBeVisible();
  expect(screen.getByText(/请先保存当前编辑草稿/)).toBeVisible();
  expect(screen.queryByLabelText("批注内容")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "00:02.500" }));
  expect(seek).toHaveBeenCalledWith(1_500);
  expect(screen.getByText("当前权限或项目状态仅允许查看。")).toBeVisible();
});

it("clears an unsubmitted relative-time draft when the saved revision changes", async () => {
  let createBody: ClipCommentThreadCreateRequest | null = null;
  server.use(
    http.get("/api/v1/clips/clip-1/comment-threads", () =>
      HttpResponse.json({
        schema_version: "1",
        clip_id: "clip-1",
        current_revision: 2,
        total_count: 0,
        next_offset: null,
        threads: [],
      }),
    ),
    http.post("/api/v1/clips/clip-1/comment-threads", async ({ request }) => {
      createBody = (await request.json()) as ClipCommentThreadCreateRequest;
      const created = threadFixture();
      created.edit_plan_revision = createBody.expected_revision;
      created.current_revision = createBody.expected_revision;
      created.clip_time_ms = createBody.clip_time_ms;
      created.current_clip_time_ms = createBody.clip_time_ms;
      created.comments[0].body = createBody.body;
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  const api = new LiveClipApiClient();
  function RevisionHarness() {
    const [revision, setRevision] = useState(1);
    return (
      <>
        <button type="button" onClick={() => setRevision(2)}>模拟保存新 revision</button>
        <ClipComments
          api={api}
          clipId="clip-1"
          currentRevision={revision}
          durationMs={10_000}
          members={project.members}
          canCreate
          getCurrentTimeMs={() => null}
          onSeek={() => undefined}
        />
      </>
    );
  }
  const user = userEvent.setup();
  renderWithClient(<RevisionHarness />);

  await screen.findByText("当前筛选下还没有批注");
  await user.clear(screen.getByLabelText("片段时间（秒）"));
  await user.type(screen.getByLabelText("片段时间（秒）"), "0.500");
  await user.type(screen.getByLabelText("批注内容"), "仍绑定 revision 1 的草稿");
  await user.click(screen.getByRole("button", { name: "模拟保存新 revision" }));

  expect(screen.getByLabelText("片段时间（秒）")).toHaveValue(0);
  expect(screen.getByLabelText("批注内容")).toHaveValue("");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "旧 revision 的批注草稿已清除",
  );
  await user.type(screen.getByLabelText("批注内容"), "revision 2 的新批注");
  await user.click(screen.getByRole("button", { name: "添加时间点批注" }));
  await waitFor(() =>
    expect(createBody).toEqual({
      expected_revision: 2,
      clip_time_ms: 0,
      body: "revision 2 的新批注",
      mentioned_user_ids: [],
    }),
  );
});

it("loads later comment pages instead of hiding threads after the first page", async () => {
  const first = threadFixture();
  first.comments[0].body = "第一页批注";
  const second = threadFixture();
  second.thread_id = "thread-2";
  second.comments[0].comment_id = "comment-2";
  second.comments[0].body = "第二页批注";
  const requestedOffsets: number[] = [];
  server.use(
    http.get("/api/v1/clips/clip-1/comment-threads", ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset") ?? "0");
      requestedOffsets.push(offset);
      return HttpResponse.json({
        schema_version: "1",
        clip_id: "clip-1",
        current_revision: 1,
        total_count: 2,
        next_offset: offset === 0 ? 1 : null,
        threads: offset === 0 ? [first] : [second],
      });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ClipComments
      api={new LiveClipApiClient()}
      clipId="clip-1"
      currentRevision={1}
      durationMs={10_000}
      members={project.members}
      canCreate={false}
      getCurrentTimeMs={() => null}
      onSeek={() => undefined}
    />,
  );

  expect(await screen.findByText("第一页批注")).toBeVisible();
  expect(screen.queryByText("第二页批注")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多批注" }));
  expect(await screen.findByText("第二页批注")).toBeVisible();
  expect(requestedOffsets).toEqual([0, 1]);
});

it("does not carry a relative-time draft into another highlight", async () => {
  const api = new LiveClipApiClient();
  function ClipHarness() {
    const [clipId, setClipId] = useState("clip-1");
    return (
      <>
        <button type="button" onClick={() => setClipId("clip-2")}>切换高光</button>
        <ClipComments
          api={api}
          clipId={clipId}
          currentRevision={1}
          durationMs={10_000}
          members={project.members}
          canCreate
          getCurrentTimeMs={() => null}
          onSeek={() => undefined}
        />
      </>
    );
  }
  const user = userEvent.setup();
  renderWithClient(<ClipHarness />);

  await screen.findByText("当前筛选下还没有批注");
  await user.clear(screen.getByLabelText("片段时间（秒）"));
  await user.type(screen.getByLabelText("片段时间（秒）"), "1.250");
  await user.type(screen.getByLabelText("批注内容"), "属于第一条高光的草稿");
  await user.click(screen.getByRole("button", { name: "切换高光" }));

  expect(screen.getByLabelText("片段时间（秒）")).toHaveValue(0);
  expect(screen.getByLabelText("批注内容")).toHaveValue("");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "上一条高光的批注草稿已清除",
  );
});
