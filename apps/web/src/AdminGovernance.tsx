import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type LiveClipApiClient, errorMessage } from "./api";
import { PROJECT_LIFECYCLE_LABELS } from "./ProjectOperations";
import type {
  AdminProjectSnapshot,
  AdminProjectsResponse,
  ManagedUser,
  PipelineRunStatus,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "./ui";

const PIPELINE_LABELS: Record<PipelineRunStatus, string> = {
  queued: "排队中",
  running: "处理中",
  completed: "处理完成",
  failed: "处理失败",
  cancelled: "已取消",
};

const AUDIT_LABELS: Record<string, string> = {
  "project.ownership_transferred_by_administrator": "管理员移交项目负责人",
  "project.ownership_transferred": "项目负责人移交",
  "project.member_added": "添加项目成员",
  "project.member_removed": "移除项目成员",
  "project.member_role_changed": "修改项目角色",
  "project.management_updated": "更新项目管理信息",
  "project.lifecycle_changed": "变更项目生命周期",
  "project.archived": "归档项目",
  "project.restored": "恢复项目",
  "user.created": "创建成员账号",
  "user.updated": "更新成员账号",
  "user.password_reset": "重置成员密码",
};

function auditLabel(action: string): string {
  return AUDIT_LABELS[action] ?? action;
}

function priorityLabel(priority: AdminProjectSnapshot["priority"]): string {
  if (priority === "urgent") return "紧急";
  if (priority === "high") return "高";
  if (priority === "low") return "低";
  return "普通";
}

function TransferDialog({
  project,
  users,
  isPending,
  error,
  onCancel,
  onConfirm,
}: {
  project: AdminProjectSnapshot;
  users: ManagedUser[];
  isPending: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: (newOwnerUserId: string) => void;
}) {
  const candidates = users.filter(
    (user) => user.is_active && user.user_id !== project.owner.user_id,
  );
  const [newOwnerUserId, setNewOwnerUserId] = useState(candidates[0]?.user_id ?? "");
  const [projectName, setProjectName] = useState("");

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (!isPending && event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        className="panel create-dialog governance-transfer-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="governance-transfer-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">管理员治理操作</p>
            <h2 id="governance-transfer-title">移交“{project.name}”</h2>
          </div>
          <button type="button" className="button button-ghost" disabled={isPending} onClick={onCancel}>取消</button>
        </div>
        <div className="notice governance-scope-note">
          此操作不会把管理员加入项目。新负责人获得项目所有权，原负责人保留为编辑；建议先运行 <code>liveclip db-backup</code> 创建恢复点。
        </div>
        {project.owner.is_active ? null : (
          <p className="notice notice-error" role="status">当前负责人账号已停用，请将项目移交给可登录成员。</p>
        )}
        {candidates.length > 0 ? (
          <>
            <label>新负责人
              <select value={newOwnerUserId} onChange={(event) => setNewOwnerUserId(event.currentTarget.value)}>
                {candidates.map((user) => <option key={user.user_id} value={user.user_id}>{user.display_name} (@{user.username})</option>)}
              </select>
            </label>
            <label>输入完整项目名确认
              <input value={projectName} onChange={(event) => setProjectName(event.currentTarget.value)} autoComplete="off" />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="button button-danger"
                disabled={isPending || !newOwnerUserId || projectName !== project.name}
                onClick={() => onConfirm(newOwnerUserId)}
              >
                {isPending ? "正在移交…" : "确认移交负责人"}
              </button>
              <button type="button" className="button button-ghost" disabled={isPending} onClick={onCancel}>取消</button>
            </div>
          </>
        ) : <EmptyState title="没有可接任的启用成员" />}
        {error ? <p className="form-error" role="alert">{errorMessage(error)}</p> : null}
      </section>
    </div>
  );
}

export function AdminGovernance({ api }: { api: LiveClipApiClient }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [transferProject, setTransferProject] = useState<AdminProjectSnapshot | null>(null);
  const projectsQuery = useQuery({
    queryKey: ["admin-projects"],
    queryFn: () => api.listAdminProjects(),
  });
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.listUsers(),
  });
  const auditQuery = useQuery({
    queryKey: ["admin-audit-events"],
    queryFn: () => api.listAdminAuditEvents(),
  });
  const transferMutation = useMutation({
    mutationFn: ({ projectId, newOwnerUserId }: { projectId: string; newOwnerUserId: string }) =>
      api.transferAdminProjectOwnership(projectId, newOwnerUserId),
    onSuccess: (response) => {
      queryClient.setQueryData<AdminProjectsResponse>(["admin-projects"], (current) => current ? {
        ...current,
        projects: current.projects.map((project) => project.project_id === response.project.project_id ? response.project : project),
      } : current);
      setTransferProject(null);
      void queryClient.invalidateQueries({ queryKey: ["admin-audit-events"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const projects = projectsQuery.data?.projects ?? [];
  const filteredProjects = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("zh-CN");
    if (!needle) return projects;
    return projects.filter((project) => `${project.name}\n${project.source_filename}\n${project.owner.display_name}\n${project.owner.username}`
      .toLocaleLowerCase("zh-CN")
      .includes(needle));
  }, [projects, search]);

  return (
    <main className="admin-page governance-admin-page">
      <section className="dashboard-heading">
        <div>
          <p className="eyebrow">系统管理</p>
          <h1>项目治理</h1>
          <p>在明确的管理员上下文查看全部项目、处理失联负责人并检查审计记录，不获得项目编辑权限。</p>
        </div>
        <button type="button" className="button button-ghost" onClick={() => { void projectsQuery.refetch(); void auditQuery.refetch(); }} disabled={projectsQuery.isFetching || auditQuery.isFetching}>刷新</button>
      </section>

      <section className="panel user-manager governance-projects" aria-labelledby="governance-projects-title">
        <div className="project-manager-heading">
          <div><h2 id="governance-projects-title">全部项目</h2><p>普通“我的项目”仍只显示当前用户拥有或被分配的项目。</p></div>
          <label className="project-search"><span>搜索项目</span><input type="search" value={search} onChange={(event) => setSearch(event.currentTarget.value)} placeholder="项目名、源视频或负责人" /></label>
        </div>
        {projectsQuery.isPending ? <LoadingState>正在加载治理项目…</LoadingState> : null}
        {projectsQuery.isError ? <ErrorState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} /> : null}
        {projectsQuery.data?.projects.length === 0 ? <EmptyState title="还没有项目" /> : null}
        {projects.length > 0 && filteredProjects.length === 0 ? <EmptyState title="没有符合条件的项目" /> : null}
        {filteredProjects.length > 0 ? (
          <div className="user-table-wrap"><table className="user-table governance-table"><thead><tr><th>项目</th><th>负责人</th><th>生命周期</th><th>处理状态</th><th>范围 / 成员</th><th>治理操作</th></tr></thead><tbody>
            {filteredProjects.map((project) => <tr key={project.project_id}>
              <td><strong>{project.name}</strong><small>{project.source_filename}</small></td>
              <td><strong>{project.owner.display_name}</strong><small>@{project.owner.username}</small>{project.owner.is_active ? <span className="active-dot">可登录</span> : <span className="inactive-dot">已停用</span>}</td>
              <td><StatusBadge status={project.lifecycle} label={PROJECT_LIFECYCLE_LABELS[project.lifecycle]} /><small>优先级 {priorityLabel(project.priority)}</small></td>
              <td>{project.pipeline_status ? PIPELINE_LABELS[project.pipeline_status] : "尚未处理"}<small>第 {project.generation} 次处理</small></td>
              <td>{project.visibility === "private" ? "私有" : "工作区可见"}<small>{project.members.length} 位成员</small></td>
              <td><button type="button" className="button button-ghost" disabled={!project.allowed_governance_actions.includes("transfer_ownership")} onClick={() => { transferMutation.reset(); setTransferProject(project); }}>移交负责人</button></td>
            </tr>)}
          </tbody></table></div>
        ) : null}
      </section>

      <section className="panel user-manager governance-audit" aria-labelledby="governance-audit-title">
        <div className="project-manager-heading"><div><h2 id="governance-audit-title">安全与治理审计</h2><p>只展示结构化操作证据，不显示密码、Token 或转写正文。</p></div></div>
        {auditQuery.isPending ? <LoadingState>正在加载审计记录…</LoadingState> : null}
        {auditQuery.isError ? <ErrorState error={auditQuery.error} onRetry={() => void auditQuery.refetch()} /> : null}
        {auditQuery.data?.events.length === 0 ? <EmptyState title="暂无审计记录" /> : null}
        {auditQuery.data?.events.length ? <ol className="governance-audit-list">{auditQuery.data.events.map((event) => <li key={event.event_id}><div><strong>{auditLabel(event.action)}</strong><span>{event.actor_username ? `@${event.actor_username}` : "系统"}</span></div><small>{new Date(event.created_at).toLocaleString("zh-CN")} · {event.project_id ? `项目 ${event.project_id.slice(0, 8)}` : event.target_type}</small></li>)}</ol> : null}
      </section>

      {transferProject ? (
        <TransferDialog
          project={transferProject}
          users={usersQuery.data?.users ?? []}
          isPending={transferMutation.isPending}
          error={usersQuery.error ?? transferMutation.error}
          onCancel={() => setTransferProject(null)}
          onConfirm={(newOwnerUserId) => transferMutation.mutate({ projectId: transferProject.project_id, newOwnerUserId })}
        />
      ) : null}
    </main>
  );
}
