import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { App } from "../src/App";
import type { ProjectSearchCriteria, ProjectSnapshot, SavedProjectView } from "../src/types";
import { project, projectSearchPage } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

const secondProject: ProjectSnapshot = {
  ...project,
  project_id: "project-2",
  name: "第二个直播项目",
  source_filename: "second-live.mp4",
};

it("loads authorized project pages from the server without browser-side slicing", async () => {
  const seenCursors: Array<string | null> = [];
  server.use(
    http.get("/api/v1/projects/search", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      seenCursors.push(cursor);
      const page =
        cursor === "page-two"
          ? projectSearchPage([secondProject], [project, secondProject])
          : projectSearchPage([project], [project, secondProject], "page-two");
      return HttpResponse.json({ ...page, total_count: 2 });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);

  expect(await screen.findByText("直播测试项目")).toBeVisible();
  expect(screen.queryByText("第二个直播项目")).not.toBeInTheDocument();
  expect(screen.getByText("找到 2 个项目，已显示 1 个")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "加载更多项目" }));

  expect(await screen.findByText("第二个直播项目")).toBeVisible();
  expect(screen.getByText("找到 2 个项目，已显示 2 个")).toBeVisible();
  expect(seenCursors).toEqual([null, "page-two"]);
});

it("saves, applies, updates and deletes a private project view with version fences", async () => {
  const urgentCriteria: ProjectSearchCriteria = {
    query: "高光标题",
    lifecycles: ["editorial_review", "approval"],
    priorities: ["urgent"],
    roles: [],
    visibilities: [],
    platforms: [],
    assignee: "me",
    assignee_user_id: null,
    due: "any",
    sort: "priority_desc",
  };
  let views: SavedProjectView[] = [];
  let createIdempotencyKey: string | null = null;
  let updateBody: Record<string, unknown> | null = null;
  const searchRequests: string[] = [];
  server.use(
    http.get("/api/v1/projects/search", ({ request }) => {
      searchRequests.push(request.url);
      return HttpResponse.json(projectSearchPage([project]));
    }),
    http.get("/api/v1/project-views", () =>
      HttpResponse.json({ schema_version: "1", views }),
    ),
    http.post("/api/v1/project-views", async ({ request }) => {
      createIdempotencyKey = request.headers.get("Idempotency-Key");
      const body = (await request.json()) as {
        name: string;
        criteria: ProjectSearchCriteria;
      };
      views = [
        {
          view_id: "view-1",
          name: body.name,
          criteria_schema_version: "1",
          criteria: body.criteria,
          version: 1,
          created_at: "2026-08-16T10:00:00Z",
          updated_at: "2026-08-16T10:00:00Z",
        },
      ];
      return HttpResponse.json(views[0], { status: 201 });
    }),
    http.patch("/api/v1/project-views/view-1", async ({ request }) => {
      updateBody = (await request.json()) as Record<string, unknown>;
      views = [{ ...views[0], name: String(updateBody.name), version: 2 }];
      return HttpResponse.json(views[0]);
    }),
    http.delete("/api/v1/project-views/view-1", ({ request }) => {
      expect(new URL(request.url).searchParams.get("expected_version")).toBe("2");
      views = [];
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);
  await screen.findByText("直播测试项目");

  await user.selectOptions(screen.getByLabelText("优先级"), "urgent");
  await user.selectOptions(screen.getByLabelText("执行人"), "me");
  await user.click(screen.getByRole("button", { name: "审核中" }));
  const search = screen.getByPlaceholderText("项目、源视频、高光内容、执行人或平台");
  await user.type(search, urgentCriteria.query);
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() =>
    expect(searchRequests.some((value) => value.includes("q=%E9%AB%98%E5%85%89%E6%A0%87%E9%A2%98"))).toBe(true),
  );

  await user.click(screen.getByRole("button", { name: "＋ 保存当前视图" }));
  const saveEditor = screen.getByLabelText("视图名称").closest("form");
  expect(saveEditor).not.toBeNull();
  await user.type(within(saveEditor!).getByLabelText("视图名称"), "紧急审核");
  await user.click(within(saveEditor!).getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("button", { name: "紧急审核" })).toBeVisible();
  expect(createIdempotencyKey).toMatch(/^liveclip-web-saved-project-view-/);

  await user.click(screen.getByRole("button", { name: "管理视图 紧急审核" }));
  const updateEditor = screen.getByLabelText("更新保存视图").closest("form");
  expect(updateEditor).not.toBeNull();
  await user.clear(within(updateEditor!).getByLabelText("更新保存视图"));
  await user.type(within(updateEditor!).getByLabelText("更新保存视图"), "今天要审");
  await user.click(within(updateEditor!).getByRole("button", { name: "更新为当前筛选" }));
  expect(await screen.findByRole("button", { name: "今天要审" })).toBeVisible();
  expect(updateBody).toMatchObject({ expected_version: 1, name: "今天要审" });

  await user.click(screen.getByRole("button", { name: "管理视图 今天要审" }));
  const deleteEditor = screen.getByLabelText("更新保存视图").closest("form");
  await user.click(within(deleteEditor!).getByRole("button", { name: "删除视图" }));
  expect(within(deleteEditor!).getByText("确认删除“今天要审”？项目不会被删除。")).toBeVisible();
  await user.click(within(deleteEditor!).getByRole("button", { name: "确认删除" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "今天要审" })).not.toBeInTheDocument(),
  );
});

it("applies a custom lifecycle view without mislabeling it as the all-project preset", async () => {
  const customView: SavedProjectView = {
    view_id: "view-custom",
    name: "草稿与审批",
    criteria_schema_version: "1",
    criteria: {
      ...projectSearchPage([]).criteria,
      lifecycles: ["draft", "approval"],
    },
    version: 1,
    created_at: "2026-08-16T10:00:00Z",
    updated_at: "2026-08-16T10:00:00Z",
  };
  const searchRequests: string[] = [];
  server.use(
    http.get("/api/v1/project-views", () =>
      HttpResponse.json({ schema_version: "1", views: [customView] }),
    ),
    http.get("/api/v1/projects/search", ({ request }) => {
      searchRequests.push(request.url);
      return HttpResponse.json(projectSearchPage([project]));
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);

  await user.click(await screen.findByRole("button", { name: "草稿与审批" }));
  await waitFor(() => {
    const lastRequest = new URL(searchRequests.at(-1)!);
    expect(lastRequest.searchParams.getAll("lifecycle")).toEqual(["draft", "approval"]);
  });
  const presetGroup = screen.getByRole("group", { name: "项目状态筛选" });
  expect(
    within(presetGroup)
      .getAllByRole("button")
      .every((button) => button.getAttribute("aria-pressed") === "false"),
  ).toBe(true);
});

it("reuses the same create key after a lost response", async () => {
  const requestKeys: string[] = [];
  let attempts = 0;
  let views: SavedProjectView[] = [];
  server.use(
    http.get("/api/v1/project-views", () =>
      HttpResponse.json({ schema_version: "1", views }),
    ),
    http.post("/api/v1/project-views", async ({ request }) => {
      attempts += 1;
      requestKeys.push(request.headers.get("Idempotency-Key") ?? "");
      const body = (await request.json()) as {
        name: string;
        criteria: ProjectSearchCriteria;
      };
      views = [{
        view_id: "view-replayed",
        name: body.name,
        criteria_schema_version: "1",
        criteria: body.criteria,
        version: 1,
        created_at: "2026-08-16T10:00:00Z",
        updated_at: "2026-08-16T10:00:00Z",
      }];
      if (attempts === 1) return HttpResponse.error();
      return HttpResponse.json(views[0], { status: 201 });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);
  await screen.findByText("还没有项目");

  await user.click(screen.getByRole("button", { name: "＋ 保存当前视图" }));
  await user.type(screen.getByLabelText("视图名称"), "我的恢复视图");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(await screen.findByRole("button", { name: "我的恢复视图" })).toBeVisible();
  expect(requestKeys).toHaveLength(2);
  expect(requestKeys[1]).toBe(requestKeys[0]);
});

it("refreshes a saved view after a version conflict so retry uses the current CAS", async () => {
  const criteria = projectSearchPage([]).criteria;
  let views: SavedProjectView[] = [{
    view_id: "view-cas",
    name: "待处理",
    criteria_schema_version: "1",
    criteria,
    version: 1,
    created_at: "2026-08-16T10:00:00Z",
    updated_at: "2026-08-16T10:00:00Z",
  }];
  const attemptedVersions: number[] = [];
  const deleteVersions: number[] = [];
  server.use(
    http.get("/api/v1/project-views", () =>
      HttpResponse.json({ schema_version: "1", views }),
    ),
    http.patch("/api/v1/project-views/view-cas", async ({ request }) => {
      const body = (await request.json()) as {
        expected_version: number;
        name: string;
      };
      attemptedVersions.push(body.expected_version);
      if (body.expected_version === 1) {
        views = [{ ...views[0], version: 2, name: "其他终端已更新" }];
        return HttpResponse.json(
          {
            error: {
              code: "PROJECT_DISCOVERY_CONFLICT",
              message: "保存视图已变化，请重试",
              retryable: true,
              correlation_id: "request-conflict",
              details: [],
            },
          },
          { status: 409 },
        );
      }
      views = [{ ...views[0], name: body.name, version: 3 }];
      return HttpResponse.json(views[0]);
    }),
    http.delete("/api/v1/project-views/view-cas", ({ request }) => {
      const expectedVersion = Number(new URL(request.url).searchParams.get("expected_version"));
      deleteVersions.push(expectedVersion);
      if (expectedVersion === 3) {
        views = [{ ...views[0], name: "删除前已同步", version: 4 }];
        return HttpResponse.json(
          {
            error: {
              code: "PROJECT_DISCOVERY_CONFLICT",
              message: "删除前视图已变化，请重试",
              retryable: true,
              correlation_id: "delete-conflict",
              details: [],
            },
          },
          { status: 409 },
        );
      }
      views = [];
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);

  await user.click(await screen.findByRole("button", { name: "管理视图 待处理" }));
  const name = screen.getByLabelText("更新保存视图");
  await user.clear(name);
  await user.type(name, "我的最终视图");
  await user.click(screen.getByRole("button", { name: "更新为当前筛选" }));
  expect(await screen.findByText("保存视图已变化，请重试")).toBeVisible();
  await waitFor(() => expect(screen.getByRole("button", { name: "其他终端已更新" })).toBeVisible());
  await user.click(screen.getByRole("button", { name: "更新为当前筛选" }));

  expect(await screen.findByRole("button", { name: "我的最终视图" })).toBeVisible();
  expect(attemptedVersions).toEqual([1, 2]);

  await user.click(screen.getByRole("button", { name: "管理视图 我的最终视图" }));
  await user.click(screen.getByRole("button", { name: "删除视图" }));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByText("删除前视图已变化，请重试")).toBeVisible();
  await waitFor(() => expect(screen.getByRole("button", { name: "删除前已同步" })).toBeVisible());
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "删除前已同步" })).not.toBeInTheDocument(),
  );
  expect(deleteVersions).toEqual([3, 4]);
});
