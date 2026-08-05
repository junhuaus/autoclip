import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage } from "./api";
import { ProjectWorkspace } from "./ProjectWorkspace";
import type { JobCreateRequest } from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "./ui";

function optionalInteger(value: FormDataEntryValue | null): number | undefined {
  const text = String(value ?? "").trim();
  return text ? Number.parseInt(text, 10) : undefined;
}

export function App() {
  const queryClient = useQueryClient();
  const [tokenDraft, setTokenDraft] = useState("");
  const [activeToken, setActiveToken] = useState("");
  const [authVersion, setAuthVersion] = useState(0);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const api = useMemo(() => new LiveClipApiClient(activeToken), [activeToken]);

  const healthQuery = useQuery({
    queryKey: ["health", authVersion],
    queryFn: () => api.health(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const projectsQuery = useQuery({
    queryKey: ["projects", authVersion],
    queryFn: () => api.listProjects(),
    enabled: selectedProjectId === null,
  });
  const createMutation = useMutation({
    mutationFn: (body: JobCreateRequest) => api.createJob(body),
    onSuccess: (accepted) => {
      setSelectedProjectId(accepted.project_id);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const applyToken = (event: FormEvent) => {
    event.preventDefault();
    queryClient.clear();
    setSelectedProjectId(null);
    setActiveToken(tokenDraft);
    setAuthVersion((value) => value + 1);
  };

  const createProject = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const request: JobCreateRequest = { input_path: String(data.get("input_path") ?? "") };
    const topN = optionalInteger(data.get("top_n"));
    const minimum = optionalInteger(data.get("minimum_clip_seconds"));
    const maximum = optionalInteger(data.get("maximum_clip_seconds"));
    if (topN !== undefined) request.top_n = topN;
    if (minimum !== undefined) request.minimum_clip_seconds = minimum;
    if (maximum !== undefined) request.maximum_clip_seconds = maximum;
    createMutation.mutate(request);
  };

  const providers = healthQuery.data?.providers;
  const processingReady = providers?.processing_ready === true;
  const usesMockAsr = providers?.asr_provider === "mock";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">LC</span>
          <div>
            <strong>LiveClip</strong>
            <span>本地中文直播审核台</span>
          </div>
        </div>
        <form className="token-form" onSubmit={applyToken}>
          <label>
            本机 API Bearer token（可选）
            <input
              type="password"
              autoComplete="off"
              value={tokenDraft}
              onChange={(event) => setTokenDraft(event.currentTarget.value)}
              placeholder="仅保存在当前页面内存"
            />
          </label>
          <button type="submit" className="button button-secondary">应用</button>
          <span className="token-state" aria-live="polite">
            {activeToken ? "已在内存中启用" : "未配置"}
          </span>
        </form>
      </header>

      {selectedProjectId ? (
        <ProjectWorkspace api={api} projectId={selectedProjectId} onBack={() => setSelectedProjectId(null)} />
      ) : (
        <main className="home-layout">
          <section className="intro-panel">
            <p className="eyebrow">Apple Silicon · Local first</p>
            <h1>把长直播变成可审核、可交付的竖屏高光。</h1>
            <p>
              输入允许媒体根目录下的本地绝对路径。源视频保持只读；长任务交给可恢复 Worker，
              本页持续展示真实状态。
            </p>
          </section>

          <section
            className={`panel provider-panel ${processingReady ? "provider-ready" : "provider-blocked"}`}
            aria-labelledby="provider-title"
          >
            <div className="section-heading compact">
              <div>
                <p className="eyebrow">Content intelligence</p>
                <h2 id="provider-title">当前 AI 处理链路</h2>
              </div>
              {providers ? (
                <span className={`provider-state ${processingReady ? "ready" : "blocked"}`}>
                  {processingReady ? "已就绪" : "未就绪"}
                </span>
              ) : null}
            </div>
            {healthQuery.isPending ? <LoadingState>正在检查 ASR 和编辑 Provider…</LoadingState> : null}
            {healthQuery.isError ? (
              <ErrorState error={healthQuery.error} onRetry={() => void healthQuery.refetch()} />
            ) : null}
            {providers ? (
              <div className="provider-details">
                <p>
                  <strong>ASR：</strong>
                  {providers.asr_provider === "openrouter"
                    ? "OpenRouter Whisper Large V3 中文语音转写"
                    : providers.asr_provider === "openai"
                      ? "OpenAI 中文语音转写"
                      : "Mock 测试转写"}
                  <span aria-label={providers.asr_ready ? "ASR 已就绪" : "ASR 未就绪"}>
                    {providers.asr_ready ? " · 本机预检通过" : " · 未配置"}
                  </span>
                </p>
                <p>
                  <strong>AI 编辑：</strong>
                  {providers.llm_provider === "codex_cli"
                    ? "本机 Codex CLI（云端推理，使用已保存的 ChatGPT 登录）"
                    : providers.llm_provider === "openai"
                      ? "OpenAI Responses API"
                      : "Mock 测试编辑"}
                  <span aria-label={providers.llm_ready ? "AI 编辑已就绪" : "AI 编辑未就绪"}>
                    {providers.llm_ready ? " · 本机预检通过" : " · 未配置"}
                  </span>
                </p>
                <p className="provider-note">
                  “预检通过”只确认本机配置或登录状态；实际云端权限、额度和模型可用性以 Smoke Test
                  或真实任务结果为准。
                </p>
                {usesMockAsr ? (
                  <p className="provider-warning" role="status">
                    当前使用 Mock ASR，候选文字不来自视频真实语音；此模式只用于 Demo 和自动测试。
                  </p>
                ) : null}
                {providers.blocking_issues.includes("OPENAI_ASR_NOT_CONFIGURED") ? (
                  <p className="provider-warning" role="alert">
                    OpenAI ASR 尚未配置。Codex 不能直接听视频；请在本机 .env 配置 OPENAI_API_KEY，
                    然后重启 make dev。
                  </p>
                ) : null}
                {providers.blocking_issues.includes("OPENROUTER_ASR_NOT_CONFIGURED") ? (
                  <p className="provider-warning" role="alert">
                    OpenRouter ASR 尚未配置。请撤销曾暴露的旧 Key，并仅在本机 .env.local 配置新
                    OPENROUTER_API_KEY，然后重启 make dev；Codex 本身不能听视频。
                  </p>
                ) : null}
                {providers.blocking_issues.includes("CODEX_CLI_NOT_READY") ? (
                  <p className="provider-warning" role="alert">
                    本机 Codex CLI 未安装或未登录。请先运行 codex login，再运行 liveclip doctor，
                    然后重启 make dev。
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="panel create-panel" aria-labelledby="create-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">一键创建并启动</p>
                <h2 id="create-title">新项目</h2>
              </div>
            </div>
            <form className="create-form" onSubmit={createProject}>
              <label>
                本地视频绝对路径
                <input
                  name="input_path"
                  type="text"
                  required
                  maxLength={4_096}
                  placeholder="/Users/you/Videos/live.mp4"
                />
              </label>
              <div className="field-triple">
                <label>
                  候选数量
                  <input name="top_n" type="number" min="1" max="100" step="1" defaultValue="15" />
                </label>
                <label>
                  最短秒数
                  <input name="minimum_clip_seconds" type="number" min="1" max="600" step="1" defaultValue="30" />
                </label>
                <label>
                  最长秒数
                  <input name="maximum_clip_seconds" type="number" min="1" max="1800" step="1" defaultValue="90" />
                </label>
              </div>
              <button
                type="submit"
                className="button button-primary"
                disabled={createMutation.isPending || !processingReady}
              >
                {createMutation.isPending ? "正在创建…" : "创建项目并启动处理"}
              </button>
              {!processingReady ? (
                <p className="hint">处理 Provider 就绪后才可启动；先查看上方状态或运行 liveclip doctor。</p>
              ) : null}
              {createMutation.isError ? (
                <p className="form-error" role="alert">{errorMessage(createMutation.error)}</p>
              ) : null}
            </form>
          </section>

          <section className="panel projects-panel" aria-labelledby="projects-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">本机项目</p>
                <h2 id="projects-title">项目列表</h2>
              </div>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void projectsQuery.refetch()}
                disabled={projectsQuery.isFetching}
              >
                刷新
              </button>
            </div>
            {projectsQuery.isPending ? <LoadingState>正在加载项目…</LoadingState> : null}
            {projectsQuery.isError ? <ErrorState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} /> : null}
            {projectsQuery.data?.length === 0 ? (
              <EmptyState title="还没有项目">从上方输入本地视频路径开始。</EmptyState>
            ) : null}
            {projectsQuery.data && projectsQuery.data.length > 0 ? (
              <ul className="project-list">
                {projectsQuery.data.map((project) => (
                  <li key={project.project_id}>
                    <button type="button" onClick={() => setSelectedProjectId(project.project_id)}>
                      <span>
                        <strong>{project.name}</strong>
                        <small>{project.source_filename} · generation {project.generation}</small>
                      </span>
                      <StatusBadge status={project.status} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </main>
      )}
    </div>
  );
}
