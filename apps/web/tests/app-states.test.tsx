import { HttpResponse, delay, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../src/App";
import type { ProjectSnapshot } from "../src/types";
import { project, projectSearchPage } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

beforeEach(() => {
  server.use(http.get("/api/v1/completion-presets", () => HttpResponse.json({
    schema_version: "1",
    presets: [],
  })));
});

describe("project list states", () => {
  it("defaults to overlapping semantic windows and keeps comparison modes explicit", async () => {
    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "＋ 新建项目" }));
    expect(screen.getByLabelText(/重叠语义窗口 · 推荐/)).toBeChecked();
    expect(screen.getByLabelText("最短秒数")).toHaveValue(45);
    expect(screen.getByLabelText("理想切片秒数")).toHaveValue(60);
    expect(screen.getByLabelText("最长切片秒数")).toHaveValue(90);
    expect(screen.getByLabelText("内容 Profile")).toHaveValue("vocal_coach_live");
    expect(screen.getByText(/Discovery 不评分/)).toBeInTheDocument();

    await user.click(screen.getByLabelText(/B v1 · 历史语义窗口/));

    expect(screen.getByLabelText(/B v1 · 历史语义窗口/)).toBeChecked();
    expect(screen.getByLabelText("最短秒数")).toHaveValue(8);
    expect(screen.getByLabelText("理想切片秒数")).toHaveValue(60);
    expect(screen.getByLabelText("最长切片秒数")).toHaveValue(60);
    expect(screen.getByLabelText("保留分数须高于")).toHaveValue(75);
    expect(screen.getByText(/120 秒窗口、60 秒步长/)).toBeInTheDocument();

    await user.click(screen.getByLabelText(/B v2 · 实验/));

    expect(screen.getByLabelText("最长切片秒数")).toHaveValue(90);
    expect(screen.getByText(/实验模式保留时间邻接归并/)).toBeInTheDocument();
  });

  it("shows loading and then a useful empty state", async () => {
    server.use(
      http.get("/api/v1/projects/search", async () => {
        await delay(250);
        return HttpResponse.json(projectSearchPage([]));
      }),
    );

    renderWithClient(<App />);

    expect(screen.getByText("正在验证登录状态…")).toBeInTheDocument();
    expect(await screen.findByText("正在加载你的项目…")).toBeInTheDocument();
    expect(await screen.findByText("还没有项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建第一个视频项目" })).toBeEnabled();
    expect(screen.queryByText(/Mock ASR/)).not.toBeInTheDocument();
  });

  it("shows a preset-created Project in the dashboard without refreshing", async () => {
    const user = userEvent.setup();
    const createdProject: ProjectSnapshot = {
      ...project,
      project_id: "preset-project-1",
      name: "方案新建项目",
      status: "processing",
      lifecycle: "processing",
    };
    let created = false;
    let searchCount = 0;
    server.use(
      http.get("/api/v1/completion-presets", () => HttpResponse.json({
        schema_version: "1",
        presets: [{
          schema_version: "1",
          preset_id: "short_highlight_v1",
          display_name_zh: "短高光",
          clip_profile: "short_highlight",
          minimum_clip_seconds: 45,
          target_clip_seconds: 60,
          maximum_clip_seconds: 90,
          default_selection_policy: "default",
          acceptance_status: "experimental",
        }],
      })),
      http.get("/api/v1/projects/search", () => {
        searchCount += 1;
        return HttpResponse.json(projectSearchPage(created ? [createdProject] : []));
      }),
      http.post("/api/v1/completion-goals/from-preset", () => {
        created = true;
        return HttpResponse.json({
          goal: {
            intent_id: "preset-goal-1",
            project_id: createdProject.project_id,
            run_id: "preset-run-1",
            generation: 1,
            requester_user_id: "owner-1",
            actor_user_id: "owner-1",
            options: {
              schema_version: "1", target: "delivery", selection_policy: "default",
              include_zip: true, preset_id: "short_highlight_v1",
            },
            status: "queued",
            version: 1,
            selection_submitted: false,
            delivery_id: null,
            outcome: null,
            blocking_code: null,
            safe_error_message: null,
          },
          download_url: null,
        }, { status: 202 });
      }),
    );

    renderWithClient(<App />);
    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "＋ 新建项目" }));
    const dialog = screen.getByRole("dialog", { name: "导入一段本地视频" });
    await within(dialog).findByText(/短高光 · 实验性/);
    await user.type(within(dialog).getByLabelText("方案视频路径"), "/tmp/preset-source.mp4");
    await user.click(within(dialog).getByRole("button", { name: "按方案创建" }));
    expect(await within(dialog).findByText("处理目标已保存：preset-goal-1")).toBeInTheDocument();
    expect(within(dialog).getByText("当前状态：queued")).toBeInTheDocument();
    expect(within(dialog).queryByText(/下载交付包/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(await screen.findByText("方案新建项目")).toBeInTheDocument();
    expect(searchCount).toBeGreaterThanOrEqual(2);
  });

  it("renders only the stable safe API error and retry affordance", async () => {
    server.use(
      http.get("/api/v1/projects/search", () =>
        HttpResponse.json(
          {
            error: {
              schema_version: "1",
              code: "AUTHENTICATION_REQUIRED",
              message: "Valid Bearer authorization or signed media access is required",
              retryable: false,
              resource_id: null,
              correlation_id: "request-safe-123",
              details: [],
            },
          },
          { status: 401 },
        ),
      ),
    );

    renderWithClient(<App />);

    expect(await screen.findByText("Valid Bearer authorization or signed media access is required")).toBeInTheDocument();
    expect(screen.getByText(/AUTHENTICATION_REQUIRED/)).toHaveTextContent("request-safe-123");
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
  });

  it("keeps the optional Bearer token in memory while sending it to the API", async () => {
    const authorizations: Array<string | null> = [];
    server.use(
      http.get("/api/v1/projects/search", ({ request }) => {
        authorizations.push(request.headers.get("Authorization"));
        return HttpResponse.json(projectSearchPage([]));
      }),
    );
    window.localStorage.clear();
    window.sessionStorage.clear();
    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "打开账户与系统设置" }));
    await user.type(
      screen.getByLabelText(/成员访问 Token/),
      "temporary-browser-token",
    );
    await user.click(screen.getByRole("button", { name: "应用 Token" }));

    await waitFor(() => expect(authorizations).toContain("Bearer temporary-browser-token"));
    expect(screen.getByText("已在内存中启用")).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("temporary-browser-token");
  });

  it("keeps provider diagnostics out of the dashboard and blocks unavailable processing", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({
          schema_version: "1",
          status: "ok",
          version: "0.1.0-test",
          database: "ok",
          providers: {
            mode: "openai-codex",
            asr_provider: "openai",
            llm_provider: "codex_cli",
            asr_ready: false,
            llm_ready: true,
            processing_ready: false,
            blocking_issues: ["OPENAI_ASR_NOT_CONFIGURED"],
            warnings: [],
          },
        }),
      ),
      http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
    );

    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByText("还没有项目");
    expect(screen.queryByText(/OpenAI ASR 尚未配置/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开账户与系统设置" }));
    expect(await screen.findByText(/AI 处理链路未就绪/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "＋ 新建项目" }));
    expect(screen.getByRole("button", { name: "创建并开始处理" })).toBeDisabled();
    expect(screen.getByText(/请在右上角设置中检查配置/)).toBeInTheDocument();
  });

  it("uses the same concise unavailable state for OpenRouter ASR", async () => {
    server.use(
      http.get("/api/v1/health", () =>
        HttpResponse.json({
          schema_version: "1",
          status: "ok",
          version: "0.1.0-test",
          database: "ok",
          providers: {
            mode: "openrouter-codex",
            asr_provider: "openrouter",
            llm_provider: "codex_cli",
            asr_ready: false,
            llm_ready: true,
            processing_ready: false,
            blocking_issues: ["OPENROUTER_ASR_NOT_CONFIGURED"],
            warnings: [],
          },
        }),
      ),
      http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
    );

    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByText("还没有项目");
    expect(screen.queryByText(/OpenRouter Whisper/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开账户与系统设置" }));
    expect(await screen.findByText(/AI 处理链路未就绪/)).toBeInTheDocument();
  });

  it("presents member-scoped projects as a searchable editor dashboard", async () => {
    const deliveredProject: ProjectSnapshot = {
      ...project,
      project_id: "project-delivered",
      name: "发布会精剪",
      source_filename: "launch-event.mov",
      status: "delivered",
      lifecycle: "published",
      current_user_role: "editor",
      members: [
        project.members[0],
        {
          user_id: "editor-1",
          username: "lin-editor",
          display_name: "林编辑",
          role: "editor",
        },
      ],
    };
    server.use(
      http.get("/api/v1/projects/search", ({ request }) => {
        const url = new URL(request.url);
        const lifecycles = url.searchParams.getAll("lifecycle");
        const query = (url.searchParams.get("q") ?? "").toLocaleLowerCase("zh-CN");
        const allProjects = [project, deliveredProject];
        const filtered = allProjects.filter((item) => {
          if (lifecycles.length > 0 && !lifecycles.includes(item.lifecycle)) return false;
          if (!query) return true;
          return `${item.name}\n${item.source_filename}`
            .toLocaleLowerCase("zh-CN")
            .includes(query);
        });
        return HttpResponse.json(projectSearchPage(filtered, allProjects));
      }),
    );
    const user = userEvent.setup();

    renderWithClient(<App />);

    const projectList = await screen.findByRole("heading", { name: "项目列表" });
    const manager = projectList.closest("section");
    expect(manager).not.toBeNull();
    expect(await within(manager!).findByText("直播测试项目")).toBeInTheDocument();
    expect(within(manager!).getByText("发布会精剪")).toBeInTheDocument();
    expect(within(manager!).getByText("我的角色 · 编辑")).toBeInTheDocument();
    expect(within(manager!).getByText("2 位成员")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /发布队列/ }));
    await waitFor(() => expect(within(manager!).queryByText("直播测试项目")).not.toBeInTheDocument());
    expect(await within(manager!).findByText("发布会精剪")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "全部" }));
    await user.type(
      screen.getByPlaceholderText("项目、源视频、高光内容、执行人或平台"),
      "launch-event",
    );
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => expect(within(manager!).queryByText("直播测试项目")).not.toBeInTheDocument());
    expect(await within(manager!).findByText("发布会精剪")).toBeInTheDocument();
  });
});
