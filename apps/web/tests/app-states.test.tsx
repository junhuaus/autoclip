import { HttpResponse, delay, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "../src/App";
import type { ProjectSnapshot } from "../src/types";
import { project } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

describe("project list states", () => {
  it("shows loading and then a useful empty state", async () => {
    server.use(
      http.get("/api/v1/projects", async () => {
        await delay(80);
        return HttpResponse.json([]);
      }),
    );

    renderWithClient(<App />);

    expect(screen.getByText("正在验证登录状态…")).toBeInTheDocument();
    expect(await screen.findByText("正在加载你的项目…")).toBeInTheDocument();
    expect(await screen.findByText("还没有项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建第一个视频项目" })).toBeEnabled();
    expect(screen.queryByText(/Mock ASR/)).not.toBeInTheDocument();
  });

  it("renders only the stable safe API error and retry affordance", async () => {
    server.use(
      http.get("/api/v1/projects", () =>
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
      http.get("/api/v1/projects", ({ request }) => {
        authorizations.push(request.headers.get("Authorization"));
        return HttpResponse.json([]);
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
      http.get("/api/v1/projects", () => HttpResponse.json([])),
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
      http.get("/api/v1/projects", () => HttpResponse.json([])),
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
      http.get("/api/v1/projects", () => HttpResponse.json([project, deliveredProject])),
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
    expect(within(manager!).queryByText("直播测试项目")).not.toBeInTheDocument();
    expect(within(manager!).getByText("发布会精剪")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "全部" }));
    await user.type(screen.getByPlaceholderText("项目名、源视频或负责人"), "launch-event");
    expect(within(manager!).queryByText("直播测试项目")).not.toBeInTheDocument();
    expect(within(manager!).getByText("发布会精剪")).toBeInTheDocument();
  });
});
