import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminUsers } from "./AdminUsers";
import { LiveClipApiClient, errorMessage } from "./api";
import { LoginPage } from "./LoginPage";
import { ProjectWorkspace } from "./ProjectWorkspace";
import type { JobCreateRequest, ProjectSnapshot, ProjectStatus } from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, statusLabel } from "./ui";

type ProjectFilter = "all" | "active" | "attention" | "pending_review" | "delivered";
type AppView = "projects" | "users";

const ROLE_LABELS = {
  owner: "负责人",
  editor: "编辑",
  reviewer: "审核",
  viewer: "只读",
} as const;

function optionalInteger(value: FormDataEntryValue | null): number | undefined {
  const text = String(value ?? "").trim();
  return text ? Number.parseInt(text, 10) : undefined;
}

function projectNeedsAttention(project: ProjectSnapshot): boolean {
  return project.status === "pending_review" || project.status === "failed";
}

function matchesProjectFilter(project: ProjectSnapshot, filter: ProjectFilter): boolean {
  if (filter === "all") return true;
  if (filter === "attention") return projectNeedsAttention(project);
  if (filter === "pending_review") return project.status === "pending_review";
  if (filter === "delivered") return project.status === "delivered";
  return project.status === "processing" || project.status === "ready_for_delivery";
}

function projectActionLabel(status: ProjectStatus): string {
  if (status === "pending_review") return "继续审核";
  if (status === "processing") return "查看进度";
  if (status === "ready_for_delivery") return "准备交付";
  if (status === "delivered") return "查看交付";
  if (status === "failed") return "处理问题";
  return "打开项目";
}

function ProjectCard({ project, onOpen }: { project: ProjectSnapshot; onOpen: () => void }) {
  return (
    <li className="project-card">
      <button type="button" onClick={onOpen} aria-label={`${project.name}，${projectActionLabel(project.status)}`}>
        <span className="project-card-main">
          <span className="project-card-topline">
            <StatusBadge status={project.status} />
            <span className="project-role">我的角色 · {ROLE_LABELS[project.current_user_role]}</span>
          </span>
          <strong>{project.name}</strong>
          <small>{project.source_filename}</small>
          <span className="project-card-meta">
            <span>{project.visibility === "private" ? "私有项目" : "工作区可见"}</span>
            <span>负责人 {project.owner.display_name}</span>
            <span>{project.members.length} 位成员</span>
            <span>第 {project.generation} 次处理</span>
          </span>
        </span>
        <span className="project-card-action">
          {projectActionLabel(project.status)} <span aria-hidden="true">→</span>
        </span>
      </button>
    </li>
  );
}

export function App() {
  const queryClient = useQueryClient();
  const [tokenDraft, setTokenDraft] = useState("");
  const [activeToken, setActiveToken] = useState("");
  const [authVersion, setAuthVersion] = useState(0);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [activeView, setActiveView] = useState<AppView>("projects");
  const [projectFilter, setProjectFilter] = useState<ProjectFilter>("all");
  const [projectSearch, setProjectSearch] = useState("");
  const api = useMemo(() => new LiveClipApiClient(activeToken), [activeToken]);

  const healthQuery = useQuery({
    queryKey: ["health", authVersion],
    queryFn: () => api.health(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const sessionQuery = useQuery({
    queryKey: ["session", authVersion],
    queryFn: () => api.session(),
  });
  const projectsQuery = useQuery({
    queryKey: ["projects", authVersion],
    queryFn: () => api.listProjects(),
    enabled: selectedProjectId === null && activeView === "projects" && !sessionQuery.isError,
  });
  const createMutation = useMutation({
    mutationFn: (body: JobCreateRequest) => api.createJob(body),
    onSuccess: (accepted) => {
      setShowCreate(false);
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
  const showProjectList = () => {
    setActiveView("projects");
    setSelectedProjectId(null);
    window.scrollTo({ top: 0, behavior: "auto" });
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

  const projects = projectsQuery.data ?? [];
  const filteredProjects = useMemo(() => {
    const search = projectSearch.trim().toLocaleLowerCase("zh-CN");
    return projects.filter((project) => {
      if (!matchesProjectFilter(project, projectFilter)) return false;
      if (!search) return true;
      return `${project.name}\n${project.source_filename}\n${project.owner.display_name}`
        .toLocaleLowerCase("zh-CN")
        .includes(search);
    });
  }, [projectFilter, projectSearch, projects]);
  const processingReady = healthQuery.data?.providers.processing_ready === true;
  const attentionCount = projects.filter(projectNeedsAttention).length;
  const processingCount = projects.filter((project) => project.status === "processing").length;
  const deliveredCount = projects.filter((project) => project.status === "delivered").length;
  const currentUser = sessionQuery.data?.user;

  if (sessionQuery.isPending && !activeToken) {
    return <main className="login-shell"><LoadingState>正在验证登录状态…</LoadingState></main>;
  }
  if (sessionQuery.isError && !activeToken) {
    return <LoginPage api={api} onAuthenticated={() => { queryClient.clear(); setAuthVersion((value) => value + 1); }} />;
  }

  return (
    <div className="app-shell">
      <header className="app-header editor-header">
        <button
          type="button"
          className="brand brand-button"
          onClick={showProjectList}
          aria-label="返回我的项目"
        >
          <span className="brand-mark">LC</span>
          <span className="brand-copy"><strong>LiveClip</strong><span>视频编辑工作台</span></span>
        </button>
        <nav className="primary-nav" aria-label="主导航">
          <button type="button" className={`nav-item ${activeView === "projects" ? "nav-item-active" : ""}`} onClick={showProjectList}>
            我的项目
          </button>
          {currentUser?.system_role === "administrator" ? <button type="button" className={`nav-item ${activeView === "users" ? "nav-item-active" : ""}`} onClick={() => { setSelectedProjectId(null); setActiveView("users"); setShowSettings(false); }}>成员管理</button> : null}
        </nav>
        <div className="header-actions">
          <button type="button" className="button button-primary" onClick={() => setShowCreate(true)}>
            ＋ 新建项目
          </button>
          <button
            type="button"
            className="user-menu"
            aria-label="打开账户与系统设置"
            onClick={() => setShowSettings((value) => !value)}
          >
            <span className="user-avatar">{currentUser?.display_name.slice(0, 1) ?? "本"}</span>
            <span><strong>{currentUser?.display_name ?? "本机用户"}</strong><small>{currentUser?.system_role === "administrator" ? "系统管理员" : "视频编辑者"}</small></span>
            <span aria-hidden="true">⌄</span>
          </button>
        </div>
      </header>

      {showSettings ? (
        <aside className="settings-popover" aria-label="账户与系统设置">
          <div className="section-heading compact">
            <div><p className="eyebrow">账户与系统</p><h2>设置</h2></div>
            <button type="button" className="button button-ghost" onClick={() => setShowSettings(false)}>关闭</button>
          </div>
          <p><strong>当前成员：</strong>{currentUser?.display_name ?? "正在识别…"}</p>
          <p><strong>AI 处理：</strong>{processingReady ? "已就绪" : "需要配置"}</p>
          {sessionQuery.data?.credential_kind === "session" ? <button type="button" className="button button-secondary" onClick={() => { void api.logout().finally(() => { queryClient.clear(); setAuthVersion((value) => value + 1); }); }}>退出登录</button> : null}
          <form className="token-form settings-token-form" onSubmit={applyToken}>
            <label>成员访问 Token
              <input type="password" autoComplete="off" value={tokenDraft} onChange={(event) => setTokenDraft(event.currentTarget.value)} placeholder="仅保存在当前页面内存" />
            </label>
            <button type="submit" className="button button-secondary">应用 Token</button>
            <span className="token-state" aria-live="polite">{activeToken ? "已在内存中启用" : "当前连接无需输入"}</span>
          </form>
          {healthQuery.isError ? <ErrorState error={healthQuery.error} onRetry={() => void healthQuery.refetch()} /> : null}
          {healthQuery.data && !processingReady ? <p className="provider-warning">AI 处理链路未就绪，新项目暂时不能启动。</p> : null}
        </aside>
      ) : null}

      {activeView === "users" ? (
        <AdminUsers api={api} />
      ) : selectedProjectId ? (
        <ProjectWorkspace api={api} projectId={selectedProjectId} onBack={showProjectList} />
      ) : (
        <main className="project-dashboard">
          <section className="dashboard-heading">
            <div>
              <p className="eyebrow">编辑工作区</p>
              <h1>我的项目</h1>
              <p>集中处理你参与的视频项目、审核任务与交付进度。</p>
            </div>
            <button type="button" className="button button-primary dashboard-create" onClick={() => setShowCreate(true)}>
              ＋ 新建视频项目
            </button>
          </section>

          <section className="dashboard-stats" aria-label="项目概览">
            <button type="button" aria-pressed={projectFilter === "all"} onClick={() => setProjectFilter("all")}>
              <span>我的项目</span><strong>{projects.length}</strong><small>我参与的全部项目</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "attention"} onClick={() => setProjectFilter("attention")}>
              <span>需要我处理</span><strong>{attentionCount}</strong><small>待审核或存在问题</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "active"} onClick={() => setProjectFilter("active")}>
              <span>处理中</span><strong>{processingCount}</strong><small>AI 正在生成高光</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "delivered"} onClick={() => setProjectFilter("delivered")}>
              <span>已交付</span><strong>{deliveredCount}</strong><small>可下载的成片版本</small>
            </button>
          </section>

          <section className="panel project-manager" aria-labelledby="project-manager-title">
            <div className="project-manager-heading">
              <div><h2 id="project-manager-title">项目列表</h2><p>只显示当前成员有权访问的项目。</p></div>
              <div className="project-tools">
                <label className="project-search"><span>搜索项目</span><input type="search" value={projectSearch} onChange={(event) => setProjectSearch(event.currentTarget.value)} placeholder="项目名、源视频或负责人" /></label>
                <button type="button" className="button button-ghost" onClick={() => void projectsQuery.refetch()} disabled={projectsQuery.isFetching}>刷新</button>
              </div>
            </div>
            <div className="project-tabs" role="group" aria-label="项目状态筛选">
              {([
                ["all", "全部"], ["active", "进行中"], ["pending_review", "待审核"], ["delivered", "已交付"],
              ] as const).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={projectFilter === value} onClick={() => setProjectFilter(value)}>{label}</button>
              ))}
            </div>
            {sessionQuery.isError && !projectsQuery.isError ? <ErrorState error={sessionQuery.error} onRetry={() => void sessionQuery.refetch()} /> : null}
            {projectsQuery.isPending ? <LoadingState>正在加载你的项目…</LoadingState> : null}
            {projectsQuery.isError ? <ErrorState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} /> : null}
            {projectsQuery.data?.length === 0 ? <EmptyState title="还没有项目"><button type="button" className="button button-primary" onClick={() => setShowCreate(true)}>创建第一个视频项目</button></EmptyState> : null}
            {projects.length > 0 && filteredProjects.length === 0 ? <EmptyState title="没有符合条件的项目"><button type="button" className="button button-secondary" onClick={() => { setProjectFilter("all"); setProjectSearch(""); }}>清除筛选</button></EmptyState> : null}
            {filteredProjects.length > 0 ? <ul className="project-grid">{filteredProjects.map((project) => <ProjectCard key={project.project_id} project={project} onOpen={() => setSelectedProjectId(project.project_id)} />)}</ul> : null}
          </section>
        </main>
      )}

      {showCreate ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}>
          <section className="panel create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-title">
            <div className="section-heading"><div><p className="eyebrow">新建项目</p><h2 id="create-title">导入一段本地视频</h2></div><button type="button" className="button button-ghost" onClick={() => setShowCreate(false)}>取消</button></div>
            <form className="create-form" onSubmit={createProject}>
              <label>本地视频绝对路径<input name="input_path" type="text" required maxLength={4_096} placeholder="/Users/you/Videos/live.mp4" autoFocus /></label>
              <div className="field-triple">
                <label>高光数量<input name="top_n" type="number" min="1" max="100" step="1" defaultValue="15" /></label>
                <label>最短秒数<input name="minimum_clip_seconds" type="number" min="1" max="600" step="1" defaultValue="30" /></label>
                <label>最长秒数<input name="maximum_clip_seconds" type="number" min="1" max="1800" step="1" defaultValue="90" /></label>
              </div>
              <div className="create-assignment"><span>项目负责人</span><strong>{currentUser?.display_name ?? "当前用户"}</strong><small>创建后可在项目内添加编辑与审核成员。</small></div>
              <button type="submit" className="button button-primary" disabled={createMutation.isPending || !processingReady}>{createMutation.isPending ? "正在创建…" : "创建并开始处理"}</button>
              {!processingReady ? <p className="hint">AI 处理链路未就绪，请在右上角设置中检查配置。</p> : null}
              {createMutation.isError ? <p className="form-error" role="alert">{errorMessage(createMutation.error)}</p> : null}
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
