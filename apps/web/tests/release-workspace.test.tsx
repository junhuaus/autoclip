import { HttpResponse, http } from "msw";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { ReleaseWorkspace } from "../src/ReleaseWorkspace";
import type { PlatformPreset, ReleaseItemSnapshot } from "../src/types";
import { clipSummary, project } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

const checklist = {
  hook_confirmed: true,
  first_frame_confirmed: true,
  subtitles_confirmed: true,
  music_rights_confirmed: true,
  likeness_confirmed: true,
  personal_data_confirmed: true,
  claims_confirmed: true,
  sponsorship_confirmed: true,
  platform_policy_confirmed: true,
};

const readyRelease: ReleaseItemSnapshot = {
  release_item_id: "release-1",
  project_id: "project-1",
  clip_id: "clip-1",
  edit_plan_revision: 1,
  current_edit_plan_revision: 1,
  stale: false,
  stale_reason: null,
  platform: "douyin",
  preset_version: "2026-08-15.1",
  account_label: "官方主账号",
  title: "原始高光标题",
  title_variants: ["高光备选标题"],
  description: "一段完整的发布说明。",
  hashtags: ["直播", "高光"],
  cta: "关注获取更多内容",
  caption_mode: "clean_separate",
  cover_time_ms: 1_000,
  clip_duration_ms: 10_000,
  high_impact_sentence: "开头提出关键问题",
  risk_flags: [],
  preview_asset_id: "proxy-asset-1",
  assignee: null,
  planned_publish_at: "2026-08-16T04:00:00Z",
  approval_status: "approved",
  status: "ready",
  checklist,
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
  created_at: "2026-08-15T00:00:00Z",
  updated_at: "2026-08-15T01:00:00Z",
};

const currentPackage: ReleaseItemSnapshot["packages"][number] = {
  release_package_id: "release-package-current",
  release_item_id: "release-1",
  project_id: "project-1",
  task_id: "release-task-current",
  requested_by_user_id: "user-local-admin",
  version: 1,
  package_version: "v001",
  release_item_version: 4,
  current: true,
  published_artifact: false,
  status: "succeeded",
  preset_version: "2026-08-15.1",
  caption_mode: "clean_separate",
  manifest_asset_id: "release-manifest-current",
  zip_asset_id: "release-zip-current",
  video_sha256: "a".repeat(64),
  manifest_sha256: "b".repeat(64),
  zip_sha256: "c".repeat(64),
  include_zip: true,
  error_code: null,
  safe_error_message: null,
  created_at: "2026-08-15T02:00:00Z",
  completed_at: "2026-08-15T02:00:02Z",
};

const PREVIEW_URL =
  "/api/v1/media/proxy-asset-1?expires=9999999999&signature=preview-signed";

const historicalDouyinPreset: PlatformPreset = {
  platform: "douyin",
  version: "2026-08-14.1",
  checked_at: "2026-08-14",
  label: "抖音历史规则",
  recommended_width: 720,
  recommended_height: 1280,
  minimum_width: 360,
  minimum_height: 640,
  maximum_dimension: null,
  maximum_duration_ms: null,
  maximum_file_bytes: null,
  safe_zone: {
    top: 0.12,
    right: 0.09,
    bottom: 0.25,
    left: 0.09,
    basis: "历史平台界面遮挡保守值",
  },
  account_policy_confirmation_required: true,
  policy_notes: ["按该平台包生成时的规则复核。"],
  official_sources: ["https://example.com/history"],
};

const currentDouyinPreset: PlatformPreset = {
  ...historicalDouyinPreset,
  version: "2026-08-15.1",
  checked_at: "2026-08-15",
  label: "抖音",
  recommended_width: 1080,
  recommended_height: 1920,
  safe_zone: {
    top: 0.08,
    right: 0.08,
    bottom: 0.2,
    left: 0.08,
    basis: "当前平台界面遮挡保守值",
  },
};

function releaseList(
  releases: ReleaseItemSnapshot[],
  previewMediaUrls: Record<string, string> | undefined = Object.fromEntries(
    releases
      .filter((release) => release.preview_asset_id !== null)
      .map((release) => [release.release_item_id, PREVIEW_URL]),
  ),
) {
  return {
    schema_version: "1",
    project_id: "project-1",
    releases,
    preview_media_urls: previewMediaUrls,
  };
}

it("creates a platform release task from an unrejected pending highlight", async () => {
  let created: ReleaseItemSnapshot | null = null;
  let requestBody: unknown = null;
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList(created ? [created] : [])),
    ),
    http.post("/api/v1/projects/project-1/releases", async ({ request }) => {
      requestBody = await request.json();
      created = { ...readyRelease, status: "draft", approval_status: "draft" };
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(await screen.findByText("还没有发布任务")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "＋ 建立发布任务" }));
  expect(screen.getByRole("option", { name: /待内容审核/ })).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("高光时刻"), "clip-1");
  await user.type(screen.getByLabelText("发布账号"), "官方主账号");
  await user.click(screen.getByRole("button", { name: "建立发布任务" }));

  await waitFor(() =>
    expect(requestBody).toMatchObject({
      clip_id: "clip-1",
      expected_revision: 1,
      platform: "douyin",
      account_label: "官方主账号",
      caption_mode: "clean_separate",
    }),
  );
  expect(await screen.findByText(/抖音 · 官方主账号/)).toBeInTheDocument();
});

it("only offers owners and editors as release assignees", async () => {
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([])),
    ),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={{
        ...project,
        members: [
          ...project.members,
          { user_id: "editor-1", username: "editor", display_name: "剪辑甲", role: "editor" },
          { user_id: "reviewer-1", username: "reviewer", display_name: "审核乙", role: "reviewer" },
          { user_id: "viewer-1", username: "viewer", display_name: "访客丙", role: "viewer" },
        ],
      }}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText("还没有发布任务");
  await user.click(screen.getByRole("button", { name: "＋ 建立发布任务" }));
  const assignees = within(screen.getByLabelText("发布执行人"));
  expect(assignees.getByRole("option", { name: "本机管理员 · 负责人" })).toBeInTheDocument();
  expect(assignees.getByRole("option", { name: "剪辑甲 · 编辑" })).toBeInTheDocument();
  expect(assignees.queryByRole("option", { name: /审核乙/ })).not.toBeInTheDocument();
  expect(assignees.queryByRole("option", { name: /访客丙/ })).not.toBeInTheDocument();
});

it("requires an exact current successful package before recording publication", async () => {
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([readyRelease])),
    ),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={{ ...project, lifecycle: "ready_to_publish" }}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText(/抖音 · 官方主账号/);
  await user.click(screen.getByText("记录外部发布结果"));
  expect(screen.getByText("先生成并完成当前版本的平台 ZIP，才能记录发布。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认已在外部发布" })).toBeDisabled();
});

it("pins the selected platform package when recording publication", async () => {
  let statusBody: unknown = null;
  const releaseWithPackage = { ...readyRelease, packages: [currentPackage] };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([releaseWithPackage])),
    ),
    http.post("/api/v1/releases/release-1/status", async ({ request }) => {
      statusBody = await request.json();
      return HttpResponse.json(releaseWithPackage);
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={{ ...project, lifecycle: "ready_to_publish" }}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText(/抖音 · 官方主账号/);
  await user.click(screen.getByText("记录外部发布结果"));
  await waitFor(() =>
    expect(screen.getByLabelText("实际发布包")).toHaveValue("release-package-current"),
  );
  fireEvent.change(screen.getByLabelText("实际发布时间"), {
    target: { value: "2026-08-15T18:30" },
  });
  await user.type(screen.getByLabelText("平台内容 ID"), "douyin-post-123");
  await user.click(screen.getByRole("button", { name: "确认已在外部发布" }));

  await waitFor(() =>
    expect(statusBody).toMatchObject({
      expected_management_version: 4,
      target: "published",
      release_package_id: "release-package-current",
      external_id: "douyin-post-123",
      published_at: new Date("2026-08-15T18:30").toISOString(),
    }),
  );
});

it("keeps the external publication record and exact artifact visible", async () => {
  const publishedAt = "2026-08-15T10:30:00Z";
  const publishedRelease: ReleaseItemSnapshot = {
    ...readyRelease,
    status: "published",
    management_version: 5,
    external_url: "https://example.com/posts/douyin-post-123",
    external_id: "douyin-post-123",
    published_at: publishedAt,
    result_notes: "首发完成，平台审核通过。",
    publication_evidence: {
      schema_version: "liveclip.release-publication-evidence.v1",
      release_package_id: currentPackage.release_package_id,
      package_version: currentPackage.package_version,
      release_item_version: currentPackage.release_item_version,
      preset_version: currentPackage.preset_version,
      caption_mode: currentPackage.caption_mode,
      video_sha256: currentPackage.video_sha256,
      artifact_kind: "zip",
      artifact_sha256: currentPackage.zip_sha256 as string,
      manifest_sha256: currentPackage.manifest_sha256 as string,
      zip_sha256: currentPackage.zip_sha256,
      recorded_at: "2026-08-15T10:31:00Z",
    },
    packages: [{ ...currentPackage, published_artifact: true }],
  };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([publishedRelease])),
    ),
  );
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={{ ...project, lifecycle: "published" }}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  const record = await screen.findByRole("region", { name: "外部发布记录" });
  expect(record).toHaveTextContent(new Date(publishedAt).toLocaleString("zh-CN"));
  expect(record).toHaveTextContent("平台内容 ID douyin-post-123");
  expect(record).toHaveTextContent("首发完成，平台审核通过。");
  expect(within(record).getByRole("link", { name: "打开发布页面" })).toHaveAttribute(
    "href",
    "https://example.com/posts/douyin-post-123",
  );
  expect(screen.getByText(/已发布使用 v001/)).toHaveTextContent("视频校验 aaaaaaaaaaaa…");
  expect(screen.getByText("已发布使用", { selector: "span" })).toBeInTheDocument();
});

it("switches to calendar view and exposes a completed platform ZIP", async () => {
  let packageCreated = false;
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([readyRelease])),
    ),
    http.post("/api/v1/releases/release-1/packages", () => {
      packageCreated = true;
      return HttpResponse.json(
        {
          resource_type: "release_package",
          resource_id: "release-package-1",
          task_id: "release-task-1",
          status: "queued",
          status_url: "/api/v1/release-packages/release-package-1",
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/release-packages/release-package-1", () =>
      HttpResponse.json({
        schema_version: "1",
        release_package: {
          release_package_id: "release-package-1",
          release_item_id: "release-1",
          project_id: "project-1",
          task_id: "release-task-1",
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
          created_at: "2026-08-15T02:00:00Z",
          completed_at: "2026-08-15T02:00:02Z",
        },
        download_url: "/api/v1/release-packages/release-package-1/download?expires=9999999999&signature=signed",
        download_kind: "zip",
      }),
    ),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={{ ...project, lifecycle: "ready_to_publish" }}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(await screen.findByText(/抖音 · 官方主账号/)).toBeInTheDocument();
  expect(screen.getByText("发布审核通过")).toBeInTheDocument();
  await user.click(screen.getByText("发布文案、封面与合规清单"));
  expect(screen.getByText("平台安全区预览")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "定位封面帧（1 秒）" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "日历" }));
  const localCalendarDate = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date(readyRelease.planned_publish_at!));
  expect(
    screen.getByRole("heading", { name: new RegExp(localCalendarDate) }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "生成平台包" }));
  await waitFor(() => expect(packageCreated).toBe(true));
  const download = await screen.findByRole("link", { name: "下载平台 ZIP" });
  expect(download).toHaveAttribute(
    "href",
    "/api/v1/release-packages/release-package-1/download?expires=9999999999&signature=signed",
  );
});

it("records a failed external release with an operator-visible reason", async () => {
  let statusBody: unknown = null;
  let currentRelease = readyRelease;
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([currentRelease])),
    ),
    http.post("/api/v1/releases/release-1/status", async ({ request }) => {
      statusBody = await request.json();
      currentRelease = {
        ...readyRelease,
        management_version: 5,
        status: "failed",
        result_notes: "平台审核未通过，等待调整封面",
      };
      return HttpResponse.json(currentRelease);
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[{ ...clipSummary, clip: { ...clipSummary.clip, review_status: "approved" } }]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText(/抖音 · 官方主账号/);
  await user.click(screen.getByText("异常、重试与撤回"));
  await user.type(screen.getByLabelText("操作说明"), "平台审核未通过，等待调整封面");
  await user.click(screen.getByRole("button", { name: "记录发布失败" }));

  await waitFor(() =>
    expect(statusBody).toMatchObject({
      expected_management_version: 4,
      target: "failed",
      result_notes: "平台审核未通过，等待调整封面",
    }),
  );
  expect((await screen.findAllByText("发布失败")).length).toBeGreaterThanOrEqual(1);
});

it("disables release creation when the platform has no current preset", async () => {
  server.use(
    http.get("/api/v1/release-presets", () =>
      HttpResponse.json({
        schema_version: "1",
        current_versions: {},
        presets: [historicalDouyinPreset],
      }),
    ),
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([])),
    ),
  );
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText("还没有发布任务");
  expect(screen.getByRole("button", { name: "＋ 建立发布任务" })).toBeDisabled();
  expect(screen.getByText("当前平台预设不可用，请刷新后重试。")).toBeInTheDocument();
});

it("renders an existing task with its exact historical platform preset", async () => {
  const historicalRelease = {
    ...readyRelease,
    preset_version: historicalDouyinPreset.version,
  };
  server.use(
    http.get("/api/v1/release-presets", () =>
      HttpResponse.json({
        schema_version: "1",
        current_versions: { douyin: currentDouyinPreset.version },
        presets: [currentDouyinPreset, historicalDouyinPreset],
      }),
    ),
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([historicalRelease])),
    ),
  );
  const rendered = renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(
    await screen.findByText("推荐 720×1280 · 安全区：上 12% / 下 25%"),
  ).toBeInTheDocument();
  expect(rendered.container.querySelector(".release-safe-zone")).toHaveStyle({
    inset: "12% 9% 25% 9%",
  });
});

it("syncs a revision-stale release task and resets its approval", async () => {
  let updateBody: unknown = null;
  let currentRelease: ReleaseItemSnapshot = {
    ...readyRelease,
    edit_plan_revision: 1,
    current_edit_plan_revision: 2,
    stale: true,
    stale_reason: "revision_changed",
  };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([currentRelease])),
    ),
    http.patch("/api/v1/releases/release-1", async ({ request }) => {
      updateBody = await request.json();
      currentRelease = {
        ...currentRelease,
        edit_plan_revision: 2,
        stale: false,
        stale_reason: null,
        approval_status: "draft",
        status: "draft",
        management_version: 5,
      };
      return HttpResponse.json(currentRelease);
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(await screen.findByText(/剪辑已从 r1 更新到 r2/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "同步到当前剪辑版本" }));
  await waitFor(() =>
    expect(updateBody).toMatchObject({
      expected_management_version: 4,
      edit_plan_revision: 2,
    }),
  );
  expect(await screen.findByText("文案草稿")).toBeInTheDocument();
});

it("requires a new task when the project pipeline run changed", async () => {
  const runStaleRelease = {
    ...readyRelease,
    stale: true,
    stale_reason: "project_run_changed" as const,
  };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([runStaleRelease])),
    ),
  );
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(
    await screen.findByText(/项目已开始新的处理批次/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "同步到当前剪辑版本" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("主标题")).toBeDisabled();
});

it("lets an approver revoke approval and return the task for changes", async () => {
  let approvalBody: unknown = null;
  let currentRelease: ReleaseItemSnapshot = readyRelease;
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([currentRelease])),
    ),
    http.post("/api/v1/releases/release-1/approval", async ({ request }) => {
      approvalBody = await request.json();
      currentRelease = {
        ...currentRelease,
        approval_status: "changes_requested",
        status: "draft",
        management_version: 5,
      };
      return HttpResponse.json(currentRelease);
    }),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText("发布审核通过");
  await user.type(screen.getByLabelText("审核或状态说明"), "封面需要重新检查");
  await user.click(screen.getByRole("button", { name: "撤销批准并退回修改" }));
  await waitFor(() =>
    expect(approvalBody).toEqual({
      expected_management_version: 4,
      target: "changes_requested",
      reason: "封面需要重新检查",
    }),
  );
  expect(await screen.findByText("需修改")).toBeInTheDocument();
});

it("shows a failed platform package reason and offers a new retry", async () => {
  let createCount = 0;
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([readyRelease])),
    ),
    http.post("/api/v1/releases/release-1/packages", () => {
      createCount += 1;
      return HttpResponse.json(
        {
          resource_type: "release_package",
          resource_id: "release-package-failed",
          task_id: `release-task-${createCount}`,
          status: "queued",
          status_url: "/api/v1/release-packages/release-package-failed",
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/release-packages/release-package-failed", () =>
      HttpResponse.json({
        schema_version: "1",
        release_package: {
          ...currentPackage,
          release_package_id: "release-package-failed",
          task_id: "release-task-failed",
          current: false,
          status: "failed",
          manifest_asset_id: null,
          zip_asset_id: null,
          manifest_sha256: null,
          zip_sha256: null,
          error_code: "RELEASE_PACKAGE_RENDER_FAILED",
          safe_error_message: "平台视频编码失败，请重试。",
        },
        download_url: null,
        download_kind: null,
      }),
    ),
  );
  const user = userEvent.setup();
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText(/抖音 · 官方主账号/);
  await user.click(screen.getByRole("button", { name: "生成平台包" }));
  expect(await screen.findByText("平台视频编码失败，请重试。")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试生成新版本" }));
  await waitFor(() => expect(createCount).toBe(2));
});

it("disables duplicate package submission while a stored package is active", async () => {
  const activeRelease = {
    ...readyRelease,
    packages: [{ ...currentPackage, status: "queued" as const, current: false }],
  };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([activeRelease])),
    ),
  );
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(
    await screen.findByRole("button", { name: "正在生成…" }),
  ).toBeDisabled();
});

it("uses the exact final render for burned-caption preview", async () => {
  const finalUrl =
    "/api/v1/media/final-asset-1?expires=9999999999&signature=final-signed";
  const burnedRelease = {
    ...readyRelease,
    caption_mode: "burned" as const,
    preview_asset_id: "final-asset-1",
  };
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([burnedRelease], { "release-1": finalUrl })),
    ),
  );
  const rendered = renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  await screen.findByText("最终成片封面帧与平台遮挡检查");
  expect(rendered.container.querySelector("video")).toHaveAttribute("src", finalUrl);
});

it("blocks first-frame confirmation when the exact preview is missing", async () => {
  server.use(
    http.get("/api/v1/projects/project-1/releases", () =>
      HttpResponse.json(releaseList([readyRelease], {})),
    ),
  );
  renderWithClient(
    <ReleaseWorkspace
      api={new LiveClipApiClient()}
      project={project}
      clips={[clipSummary]}
      onProjectChanged={() => undefined}
    />,
  );

  expect(
    await screen.findByText(/当前字幕模式没有可验证的成片预览/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("首帧与封面已确认")).toBeDisabled();
});
