import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminUsers } from "./AdminUsers";
import { AdminStorage } from "./AdminStorage";
import { AdminGovernance } from "./AdminGovernance";
import { LiveClipApiClient, createIdempotencyKey, errorMessage } from "./api";
import { LoginPage } from "./LoginPage";
import { PROJECT_LIFECYCLE_LABELS } from "./ProjectOperations";
import { ProjectWorkspace } from "./ProjectWorkspace";
import type {
  JobCreateRequest,
  ProjectLifecycle,
  ProjectSearchCriteria,
  ProjectSearchItem,
  ProjectSearchMatch,
  ProjectSnapshot,
  SavedProjectView,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, statusLabel } from "./ui";

type PresetProjectFilter = "all" | "active" | "attention" | "review" | "publish" | "archived";
type ProjectFilter = PresetProjectFilter | "custom";
type AppView = "projects" | "governance" | "users" | "storage";

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

function optionalNumber(value: FormDataEntryValue | null): number | undefined {
  const text = String(value ?? "").trim();
  return text ? Number(text) : undefined;
}

const DEFAULT_PROJECT_SEARCH: ProjectSearchCriteria = {
  query: "",
  lifecycles: [],
  priorities: [],
  roles: [],
  visibilities: [],
  platforms: [],
  assignee: "any",
  assignee_user_id: null,
  due: "any",
  sort: "updated_desc",
};

const FILTER_LIFECYCLES: Record<PresetProjectFilter, ProjectLifecycle[]> = {
  all: [],
  active: ["draft", "processing"],
  attention: ["needs_attention", "changes_requested"],
  review: ["editorial_review", "approval"],
  publish: ["ready_to_publish", "published"],
  archived: ["archived"],
};

const MATCH_LABELS: Record<ProjectSearchMatch["scope"], string> = {
  project: "项目",
  source: "源视频",
  clip_title: "高光标题",
  clip_hook: "高光语句",
  transcript: "内容语句",
  assignee: "执行人",
  lifecycle: "生命周期",
  platform: "发布平台",
};

function filterForCriteria(criteria: ProjectSearchCriteria): ProjectFilter {
  const key = [...criteria.lifecycles].sort().join(",");
  return (
    Object.entries(FILTER_LIFECYCLES).find(
      ([, values]) => [...values].sort().join(",") === key,
    )?.[0] as PresetProjectFilter | undefined
  ) ?? "custom";
}

function projectActionLabel(lifecycle: ProjectLifecycle): string {
  if (["editorial_review", "approval"].includes(lifecycle)) return "继续审核";
  if (lifecycle === "processing") return "查看进度";
  if (lifecycle === "ready_to_publish") return "准备发布";
  if (lifecycle === "published") return "查看项目";
  if (["needs_attention", "changes_requested"].includes(lifecycle)) return "处理问题";
  if (lifecycle === "archived") return "查看归档";
  return "打开项目";
}

function ProjectCard({
  project,
  matches,
  onOpen,
}: {
  project: ProjectSnapshot;
  matches: ProjectSearchMatch[];
  onOpen: () => void;
}) {
  return (
    <li className="project-card">
      <button type="button" onClick={onOpen} aria-label={`${project.name}，${projectActionLabel(project.lifecycle)}`}>
        <span className="project-card-main">
          <span className="project-card-topline">
            <StatusBadge status={project.lifecycle} label={PROJECT_LIFECYCLE_LABELS[project.lifecycle]} />
            <span className="project-role">我的角色 · {ROLE_LABELS[project.current_user_role]}</span>
          </span>
          <strong>{project.name}</strong>
          <small>{project.source_filename}</small>
          <span className="project-card-meta">
            <span>{project.visibility === "private" ? "私有项目" : "工作区可见"}</span>
            <span>负责人 {project.owner.display_name}</span>
            <span>执行人 {project.assignee?.display_name ?? "未分配"}</span>
            <span>优先级 {project.priority === "urgent" ? "紧急" : project.priority === "high" ? "高" : project.priority === "low" ? "低" : "普通"}</span>
            <span>{project.members.length} 位成员</span>
            <span>第 {project.generation} 次处理</span>
          </span>
          {matches.length > 0 ? (
            <span className="project-match-list" aria-label="搜索命中位置">
              {matches.slice(0, 3).map((match, index) => (
                <span key={`${match.scope}-${match.clip_id ?? match.release_item_id ?? index}`}>
                  <b>{MATCH_LABELS[match.scope]}</b>
                  {match.text}
                </span>
              ))}
            </span>
          ) : null}
        </span>
        <span className="project-card-action">
          {projectActionLabel(project.lifecycle)} <span aria-hidden="true">→</span>
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
  const [clippingAlgorithm, setClippingAlgorithm] = useState<
    "a" | "b" | "b_v2_experimental" | "semantic_global" | "semantic_windowed"
  >("semantic_windowed");
  const [showSettings, setShowSettings] = useState(false);
  const [activeView, setActiveView] = useState<AppView>("projects");
  const [projectFilter, setProjectFilter] = useState<ProjectFilter>("all");
  const [projectSearchDraft, setProjectSearchDraft] = useState("");
  const [projectCriteria, setProjectCriteria] = useState<ProjectSearchCriteria>(
    DEFAULT_PROJECT_SEARCH,
  );
  const [showSaveView, setShowSaveView] = useState(false);
  const [savedViewName, setSavedViewName] = useState("");
  const [savedViewRetry, setSavedViewRetry] = useState<{
    signature: string;
    requestKey: string;
  } | null>(null);
  const [editingViewId, setEditingViewId] = useState<string | null>(null);
  const [editingViewName, setEditingViewName] = useState("");
  const [deleteViewConfirmationId, setDeleteViewConfirmationId] = useState<string | null>(null);
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
  const projectsQuery = useInfiniteQuery({
    queryKey: ["project-search", authVersion, projectCriteria],
    queryFn: ({ pageParam }) => api.searchProjects(projectCriteria, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: selectedProjectId === null && activeView === "projects" && !sessionQuery.isError,
  });
  const savedViewsQuery = useQuery({
    queryKey: ["saved-project-views", authVersion],
    queryFn: () => api.listSavedProjectViews(),
    enabled: selectedProjectId === null && activeView === "projects" && !sessionQuery.isError,
  });
  const createMutation = useMutation({
    mutationFn: (body: JobCreateRequest) => api.createJob(body),
    onSuccess: (accepted) => {
      setShowCreate(false);
      setSelectedProjectId(accepted.project_id);
      void queryClient.invalidateQueries({ queryKey: ["project-search"] });
    },
  });
  const createSavedViewMutation = useMutation({
    mutationFn: ({
      name,
      criteria,
      requestKey,
    }: {
      name: string;
      criteria: ProjectSearchCriteria;
      requestKey: string;
    }) => api.createSavedProjectView(name, criteria, requestKey),
    onSuccess: () => {
      setSavedViewName("");
      setShowSaveView(false);
      setSavedViewRetry(null);
      void queryClient.invalidateQueries({ queryKey: ["saved-project-views"] });
    },
  });
  const updateSavedViewMutation = useMutation({
    mutationFn: ({ view, name }: { view: SavedProjectView; name: string }) =>
      api.updateSavedProjectView(view.view_id, view.version, name, projectCriteria),
    onSuccess: () => {
      setEditingViewId(null);
      setEditingViewName("");
      setDeleteViewConfirmationId(null);
      void queryClient.invalidateQueries({ queryKey: ["saved-project-views"] });
    },
    onError: () => {
      void queryClient.refetchQueries({ queryKey: ["saved-project-views"], type: "active" });
    },
  });
  const deleteSavedViewMutation = useMutation({
    mutationFn: (view: SavedProjectView) =>
      api.deleteSavedProjectView(view.view_id, view.version),
    onSuccess: () => {
      setEditingViewId(null);
      setEditingViewName("");
      setDeleteViewConfirmationId(null);
      void queryClient.invalidateQueries({ queryKey: ["saved-project-views"] });
    },
    onError: () => {
      void queryClient.refetchQueries({ queryKey: ["saved-project-views"], type: "active" });
    },
  });

  const applyToken = (event: FormEvent) => {
    event.preventDefault();
    queryClient.clear();
    setSelectedProjectId(null);
    setActiveView("projects");
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
    const request: JobCreateRequest = {
      input_path: String(data.get("input_path") ?? ""),
      clipping_algorithm: clippingAlgorithm,
    };
    const topN = optionalInteger(data.get("top_n"));
    const minimum = optionalInteger(data.get("minimum_clip_seconds"));
    const maximum = optionalInteger(data.get("maximum_clip_seconds"));
    const semanticTarget = optionalInteger(data.get("semantic_target_clip_seconds"));
    const semanticThreshold = optionalInteger(data.get("semantic_score_threshold"));
    const semanticBudgetRatio = optionalNumber(data.get("semantic_full_context_budget_ratio"));
    const semanticContextTokens = optionalInteger(data.get("semantic_model_context_tokens"));
    if (topN !== undefined) request.top_n = topN;
    if (minimum !== undefined) request.minimum_clip_seconds = minimum;
    if (maximum !== undefined) request.maximum_clip_seconds = maximum;
    if (semanticTarget !== undefined) request.semantic_target_clip_seconds = semanticTarget;
    if (semanticThreshold !== undefined) request.semantic_score_threshold = semanticThreshold;
    if (semanticBudgetRatio !== undefined) {
      request.semantic_full_context_budget_ratio = semanticBudgetRatio;
    }
    if (semanticContextTokens !== undefined) {
      request.semantic_model_context_tokens = semanticContextTokens;
    }
    if (clippingAlgorithm === "semantic_global" || clippingAlgorithm === "semantic_windowed") {
      request.semantic_profile = String(data.get("semantic_profile")) as "general" | "vocal_coach_live";
    }
    createMutation.mutate(request);
  };

  const applyProjectFilter = (filter: PresetProjectFilter) => {
    setProjectFilter(filter);
    setProjectCriteria((current) => ({
      ...current,
      lifecycles: FILTER_LIFECYCLES[filter],
    }));
  };

  const submitProjectSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProjectCriteria((current) => ({
      ...current,
      query: projectSearchDraft.trim(),
    }));
  };

  const applySavedView = (view: SavedProjectView) => {
    setProjectCriteria(view.criteria);
    setProjectSearchDraft(view.criteria.query);
    setProjectFilter(filterForCriteria(view.criteria));
    setEditingViewId(null);
    setDeleteViewConfirmationId(null);
    updateSavedViewMutation.reset();
    deleteSavedViewMutation.reset();
  };

  const toggleSavedViewCreator = () => {
    if (showSaveView) {
      setSavedViewRetry(null);
      setSavedViewName("");
    } else {
      createSavedViewMutation.reset();
    }
    setShowSaveView(!showSaveView);
  };

  const submitSavedView = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const signature = JSON.stringify({ name: savedViewName, criteria: projectCriteria });
    const requestKey =
      savedViewRetry?.signature === signature
        ? savedViewRetry.requestKey
        : createIdempotencyKey("saved-project-view");
    setSavedViewRetry({ signature, requestKey });
    createSavedViewMutation.mutate({
      name: savedViewName,
      criteria: projectCriteria,
      requestKey,
    });
  };

  const openSavedViewEditor = (view: SavedProjectView) => {
    setEditingViewId(view.view_id);
    setEditingViewName(view.name);
    setDeleteViewConfirmationId(null);
    updateSavedViewMutation.reset();
    deleteSavedViewMutation.reset();
  };

  const closeSavedViewEditor = () => {
    setEditingViewId(null);
    setEditingViewName("");
    setDeleteViewConfirmationId(null);
    updateSavedViewMutation.reset();
    deleteSavedViewMutation.reset();
  };

  const clearProjectFilters = () => {
    setProjectCriteria(DEFAULT_PROJECT_SEARCH);
    setProjectSearchDraft("");
    setProjectFilter("all");
  };

  const projectItems = useMemo(() => {
    const deduplicated = new Map<string, ProjectSearchItem>();
    for (const page of projectsQuery.data?.pages ?? []) {
      for (const item of page.items) deduplicated.set(item.project.project_id, item);
    }
    return [...deduplicated.values()];
  }, [projectsQuery.data?.pages]);
  const firstProjectPage = projectsQuery.data?.pages[0];
  const projectSummary = firstProjectPage?.summary;
  const projectTotal = firstProjectPage?.total_count ?? 0;
  const savedViews = savedViewsQuery.data?.views ?? [];
  const editingView = savedViews.find((view) => view.view_id === editingViewId) ?? null;
  const processingReady = healthQuery.data?.providers.processing_ready === true;
  const currentUser = sessionQuery.data?.user;

  useEffect(() => {
    if (currentUser && currentUser.system_role !== "administrator" && activeView !== "projects") {
      setActiveView("projects");
      setSelectedProjectId(null);
      setShowSettings(false);
    }
  }, [activeView, currentUser]);

  if (sessionQuery.isPending && !activeToken) {
    return <main className="login-shell"><LoadingState>正在验证登录状态…</LoadingState></main>;
  }
  if (sessionQuery.isError && !activeToken) {
    return <LoginPage api={api} onAuthenticated={() => { queryClient.clear(); setActiveView("projects"); setSelectedProjectId(null); setShowSettings(false); setAuthVersion((value) => value + 1); }} />;
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
          {currentUser?.system_role === "administrator" ? <button type="button" className={`nav-item ${activeView === "governance" ? "nav-item-active" : ""}`} onClick={() => { setSelectedProjectId(null); setActiveView("governance"); setShowSettings(false); }}>项目治理</button> : null}
          {currentUser?.system_role === "administrator" ? <button type="button" className={`nav-item ${activeView === "storage" ? "nav-item-active" : ""}`} onClick={() => { setSelectedProjectId(null); setActiveView("storage"); setShowSettings(false); }}>存储管理</button> : null}
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
          {sessionQuery.data?.credential_kind === "session" ? <button type="button" className="button button-secondary" onClick={() => { void api.logout().finally(() => { queryClient.clear(); setActiveView("projects"); setSelectedProjectId(null); setShowSettings(false); setAuthVersion((value) => value + 1); }); }}>退出登录</button> : null}
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
      ) : activeView === "governance" ? (
        <AdminGovernance api={api} />
      ) : activeView === "storage" ? (
        <AdminStorage api={api} administratorUsername={currentUser?.username ?? ""} />
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
            <button type="button" aria-pressed={projectFilter === "all"} onClick={() => applyProjectFilter("all")}>
              <span>我的项目</span><strong>{projectSummary?.visible_total ?? "—"}</strong><small>我有权查看的全部项目</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "attention"} onClick={() => applyProjectFilter("attention")}>
              <span>需要处理</span><strong>{projectSummary?.needs_attention ?? "—"}</strong><small>存在问题或要求修改</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "review"} onClick={() => applyProjectFilter("review")}>
              <span>待选择</span><strong>{projectSummary?.review ?? "—"}</strong><small>挑选高光或处理发布终审</small>
            </button>
            <button type="button" aria-pressed={projectFilter === "publish"} onClick={() => applyProjectFilter("publish")}>
              <span>发布队列</span><strong>{projectSummary?.publish ?? "—"}</strong><small>待发布或已发布项目</small>
            </button>
          </section>

          <section className="panel project-manager" aria-labelledby="project-manager-title">
            <div className="project-manager-heading">
              <div><h2 id="project-manager-title">项目列表</h2><p>只显示当前成员有权访问的项目。</p></div>
              <form className="project-tools" role="search" onSubmit={submitProjectSearch}>
                <label className="project-search"><span>搜索项目</span><input type="search" value={projectSearchDraft} onChange={(event) => setProjectSearchDraft(event.currentTarget.value)} placeholder="项目、源视频、高光内容、执行人或平台" /></label>
                <button type="submit" className="button button-secondary" disabled={projectsQuery.isFetching}>搜索</button>
                <button type="button" className="button button-ghost" onClick={() => void projectsQuery.refetch()} disabled={projectsQuery.isFetching}>刷新</button>
              </form>
            </div>

            <div className="saved-view-bar" aria-label="我的保存视图">
              <span>我的视图</span>
              {savedViewsQuery.isPending ? <small>正在加载…</small> : null}
              {savedViews.map((view) => (
                <span className="saved-view-chip" key={view.view_id}>
                  <button type="button" onClick={() => applySavedView(view)}>{view.name}</button>
                  <button type="button" className="saved-view-edit" aria-label={`管理视图 ${view.name}`} onClick={() => openSavedViewEditor(view)}>•••</button>
                </span>
              ))}
              <button type="button" className="button button-ghost saved-view-create" onClick={toggleSavedViewCreator}>＋ 保存当前视图</button>
              {savedViewsQuery.isError ? <button type="button" className="inline-retry" onClick={() => void savedViewsQuery.refetch()}>视图加载失败，重试</button> : null}
            </div>
            {showSaveView ? (
              <form className="saved-view-editor" onSubmit={submitSavedView}>
                <label>视图名称<input value={savedViewName} onChange={(event) => setSavedViewName(event.currentTarget.value)} required maxLength={80} autoFocus /></label>
                <button type="submit" className="button button-primary" disabled={createSavedViewMutation.isPending}>{createSavedViewMutation.isPending ? "正在保存…" : "保存"}</button>
                <button type="button" className="button button-ghost" onClick={() => { setShowSaveView(false); setSavedViewName(""); setSavedViewRetry(null); createSavedViewMutation.reset(); }}>取消</button>
                {createSavedViewMutation.isError ? <p className="form-error" role="alert">{errorMessage(createSavedViewMutation.error)}</p> : null}
              </form>
            ) : null}
            {editingView ? (
              <form className="saved-view-editor" onSubmit={(event) => { event.preventDefault(); updateSavedViewMutation.reset(); updateSavedViewMutation.mutate({ view: editingView, name: editingViewName }); }}>
                <label>更新保存视图<input value={editingViewName} onChange={(event) => setEditingViewName(event.currentTarget.value)} required maxLength={80} /></label>
                <button type="submit" className="button button-primary" disabled={updateSavedViewMutation.isPending}>更新为当前筛选</button>
                {deleteViewConfirmationId === editingView.view_id ? (
                  <span className="saved-view-delete-confirmation" role="alert">
                    <span>确认删除“{editingView.name}”？项目不会被删除。</span>
                    <button type="button" className="button button-danger" disabled={deleteSavedViewMutation.isPending} onClick={() => { deleteSavedViewMutation.reset(); deleteSavedViewMutation.mutate(editingView); }}>{deleteSavedViewMutation.isPending ? "正在删除…" : "确认删除"}</button>
                    <button type="button" className="button button-ghost" disabled={deleteSavedViewMutation.isPending} onClick={() => setDeleteViewConfirmationId(null)}>保留视图</button>
                  </span>
                ) : (
                  <button type="button" className="button button-danger" onClick={() => setDeleteViewConfirmationId(editingView.view_id)}>删除视图</button>
                )}
                <button type="button" className="button button-ghost" onClick={closeSavedViewEditor}>取消</button>
                {updateSavedViewMutation.isError || deleteSavedViewMutation.isError ? <p className="form-error" role="alert">{errorMessage(updateSavedViewMutation.error ?? deleteSavedViewMutation.error)}</p> : null}
              </form>
            ) : null}
            <div className="project-tabs" role="group" aria-label="项目状态筛选">
              {([
                ["all", "全部"], ["active", "进行中"], ["review", "审核中"], ["publish", "发布"], ["archived", "归档"],
              ] as const).map(([value, label]) => (
                <button key={value} type="button" aria-pressed={projectFilter === value} onClick={() => applyProjectFilter(value)}>{label}</button>
              ))}
            </div>
            <div className="project-advanced-filters" aria-label="项目高级筛选">
              <label>优先级<select value={projectCriteria.priorities[0] ?? ""} onChange={(event) => { const value = event.currentTarget.value as "" | "low" | "normal" | "high" | "urgent"; setProjectCriteria((current) => ({ ...current, priorities: value ? [value] : [] })); }}><option value="">全部</option><option value="urgent">紧急</option><option value="high">高</option><option value="normal">普通</option><option value="low">低</option></select></label>
              <label>执行人<select value={projectCriteria.assignee} onChange={(event) => { const value = event.currentTarget.value as "any" | "me" | "unassigned"; setProjectCriteria((current) => ({ ...current, assignee: value, assignee_user_id: null })); }}><option value="any">全部</option><option value="me">分配给我</option><option value="unassigned">未分配</option></select></label>
              <label>截止时间<select value={projectCriteria.due} onChange={(event) => { const value = event.currentTarget.value as "any" | "overdue" | "today" | "next_7_days" | "unscheduled"; setProjectCriteria((current) => ({ ...current, due: value })); }}><option value="any">全部</option><option value="overdue">已逾期</option><option value="today">今天到期</option><option value="next_7_days">未来 7 天</option><option value="unscheduled">未排期</option></select></label>
              <label>可见范围<select value={projectCriteria.visibilities[0] ?? ""} onChange={(event) => { const value = event.currentTarget.value as "" | "private" | "workspace"; setProjectCriteria((current) => ({ ...current, visibilities: value ? [value] : [] })); }}><option value="">全部</option><option value="private">私有</option><option value="workspace">工作区可见</option></select></label>
              <label>排序<select value={projectCriteria.sort} onChange={(event) => { const value = event.currentTarget.value as ProjectSearchCriteria["sort"]; setProjectCriteria((current) => ({ ...current, sort: value })); }}><option value="updated_desc">最近更新</option><option value="due_asc">截止时间</option><option value="priority_desc">优先级</option><option value="name_asc">项目名称</option></select></label>
              <button type="button" className="button button-ghost" onClick={clearProjectFilters}>清除筛选</button>
            </div>
            <p className="project-result-count" aria-live="polite">{projectsQuery.isPending ? "正在查询项目…" : `找到 ${projectTotal} 个项目，已显示 ${projectItems.length} 个`}</p>
            {sessionQuery.isError && !projectsQuery.isError ? <ErrorState error={sessionQuery.error} onRetry={() => void sessionQuery.refetch()} /> : null}
            {projectsQuery.isPending ? <LoadingState>正在加载你的项目…</LoadingState> : null}
            {projectsQuery.isError ? <ErrorState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} /> : null}
            {!projectsQuery.isPending && !projectsQuery.isError && projectSummary?.visible_total === 0 ? <EmptyState title="还没有项目"><button type="button" className="button button-primary" onClick={() => setShowCreate(true)}>创建第一个视频项目</button></EmptyState> : null}
            {!projectsQuery.isPending && !projectsQuery.isError && (projectSummary?.visible_total ?? 0) > 0 && projectTotal === 0 ? <EmptyState title="没有符合条件的项目"><button type="button" className="button button-secondary" onClick={clearProjectFilters}>清除筛选</button></EmptyState> : null}
            {projectItems.length > 0 ? <ul className="project-grid">{projectItems.map((item) => <ProjectCard key={item.project.project_id} project={item.project} matches={item.matches} onOpen={() => setSelectedProjectId(item.project.project_id)} />)}</ul> : null}
            {projectsQuery.hasNextPage ? <div className="project-load-more"><button type="button" className="button button-secondary" disabled={projectsQuery.isFetchingNextPage} onClick={() => void projectsQuery.fetchNextPage()}>{projectsQuery.isFetchingNextPage ? "正在加载…" : "加载更多项目"}</button></div> : null}
          </section>
        </main>
      )}

      {showCreate ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}>
          <section className="panel create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-title">
            <div className="section-heading"><div><p className="eyebrow">新建项目</p><h2 id="create-title">导入一段本地视频</h2></div><button type="button" className="button button-ghost" onClick={() => setShowCreate(false)}>取消</button></div>
            <form className="create-form" onSubmit={createProject}>
              <label>本地视频绝对路径<input name="input_path" type="text" required maxLength={4_096} placeholder="/Users/you/Videos/live.mp4" autoFocus /></label>
              <fieldset className="algorithm-picker">
                <legend>切片算法</legend>
                <label className={clippingAlgorithm === "a" ? "selected" : ""}>
                  <input type="radio" name="clipping_algorithm" value="a" checked={clippingAlgorithm === "a"} onChange={() => setClippingAlgorithm("a")} />
                  <span><strong>A · 经典算法</strong><small>规则粗选后逐条 AI 编辑，适合复现以前的结果。</small></span>
                </label>
                <label className={clippingAlgorithm === "b" ? "selected" : ""}>
                  <input type="radio" name="clipping_algorithm" value="b" checked={clippingAlgorithm === "b"} onChange={() => setClippingAlgorithm("b")} />
                  <span><strong>B v1 · 历史语义窗口</strong><small>冻结的 120/60 秒历史算法，用于复现和对比。</small></span>
                </label>
                <label className={clippingAlgorithm === "semantic_global" ? "selected" : ""}>
                  <input type="radio" name="clipping_algorithm" value="semantic_global" checked={clippingAlgorithm === "semantic_global"} onChange={() => setClippingAlgorithm("semantic_global")} />
                  <span><strong>Full-first · 对照</strong><small>优先整篇理解，用于与新的窗口模式比较。</small></span>
                </label>
                <label className={clippingAlgorithm === "semantic_windowed" ? "selected" : ""}>
                  <input type="radio" name="clipping_algorithm" value="semantic_windowed" checked={clippingAlgorithm === "semantic_windowed"} onChange={() => setClippingAlgorithm("semantic_windowed")} />
                  <span><strong>重叠语义窗口 · 推荐</strong><small>120秒窗口、60秒重叠，每窗可发现多条；跨边界话题由全局Agent接力。</small></span>
                </label>
                <label className={clippingAlgorithm === "b_v2_experimental" ? "selected" : ""}>
                  <input type="radio" name="clipping_algorithm" value="b_v2_experimental" checked={clippingAlgorithm === "b_v2_experimental"} onChange={() => setClippingAlgorithm("b_v2_experimental")} />
                  <span><strong>B v2 · 实验</strong><small>保留两阶段时间邻接归并实验，不作为默认方案。</small></span>
                </label>
              </fieldset>
              <div className={clippingAlgorithm !== "a" ? "field-five" : "field-triple"} key={clippingAlgorithm}>
                <label>高光数量<input name="top_n" type="number" min="1" max="100" step="1" defaultValue="15" /></label>
                <label>最短秒数<input name="minimum_clip_seconds" type="number" min="1" max="600" step="1" defaultValue={clippingAlgorithm === "semantic_global" || clippingAlgorithm === "semantic_windowed" ? "45" : clippingAlgorithm === "a" ? "30" : "8"} /></label>
                {clippingAlgorithm !== "a" ? <label>理想切片秒数<input name="semantic_target_clip_seconds" type="number" min="1" max="600" step="1" defaultValue="60" /></label> : null}
                <label>{clippingAlgorithm !== "a" ? "最长切片秒数" : "最长秒数"}<input name="maximum_clip_seconds" type="number" min="1" max={clippingAlgorithm !== "a" ? "600" : "1800"} step="1" defaultValue={clippingAlgorithm === "b" ? "60" : "90"} /></label>
                {clippingAlgorithm !== "a" ? <label>保留分数须高于<input name="semantic_score_threshold" type="number" min="0" max="100" step="1" defaultValue="75" /></label> : null}
              </div>
              {clippingAlgorithm === "semantic_global" ? <div className="field-triple semantic-global-options"><label>内容 Profile<select name="semantic_profile" defaultValue="vocal_coach_live"><option value="vocal_coach_live">声乐教学直播</option><option value="general">通用内容</option></select></label><label>模型上下文 tokens<input name="semantic_model_context_tokens" type="number" min="16000" max="2000000" step="1000" defaultValue="128000" /></label><label>Full-context 预算比例<input name="semantic_full_context_budget_ratio" type="number" min="0.1" max="0.8" step="0.01" defaultValue="0.58" /></label></div> : null}
              {clippingAlgorithm === "semantic_windowed" ? <div className="field-triple semantic-global-options"><label>内容 Profile<select name="semantic_profile" defaultValue="vocal_coach_live"><option value="vocal_coach_live">声乐教学直播</option><option value="general">通用内容</option></select></label><label>分析窗口<input value="120 秒" readOnly /></label><label>相邻重叠<input value="60 秒" readOnly /></label></div> : null}
              {clippingAlgorithm === "semantic_global" ? <p className="hint">优先按真实 tokenizer 判断完整字幕是否安全装入上下文；超预算才使用 10–20 分钟大窗口。Discovery 不评分，Global Review 读取全局证据后统一去重、定界和评分。</p> : null}
              {clippingAlgorithm === "semantic_windowed" ? <p className="hint">Discovery 不评分，只负责发现候选与报告开放边界；重叠只用于保留上下文，同话题、合并和去重由 Global Review 根据 viewer promise 与原字幕判断。</p> : null}
              {clippingAlgorithm === "b" ? <p className="hint">B v1 固定按 120 秒窗口、60 秒步长复现历史结果。</p> : null}
              {clippingAlgorithm === "b_v2_experimental" ? <p className="hint">实验模式保留时间邻接归并，仅用于比较，不是推荐默认。</p> : null}
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
