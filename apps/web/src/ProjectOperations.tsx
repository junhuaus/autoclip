import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage } from "./api";
import type {
  ProjectLifecycle,
  ProjectManagementRequest,
  ProjectSnapshot,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "./ui";

export const PROJECT_LIFECYCLE_LABELS: Record<ProjectLifecycle, string> = {
  draft: "草稿",
  processing: "处理中",
  needs_attention: "需要处理",
  editorial_review: "编辑审核",
  changes_requested: "待修改",
  approval: "终审",
  ready_to_publish: "待发布",
  published: "已发布",
  archived: "已归档",
};

const PRIORITY_LABELS = {
  low: "低",
  normal: "普通",
  high: "高",
  urgent: "紧急",
} as const;

const ACTIVITY_LABELS: Record<string, string> = {
  "project.management_updated": "更新项目设置",
  "project.lifecycle_changed": "推进项目阶段",
  "project.restored": "恢复项目",
  "project.member_added": "添加项目成员",
  "project.member_role_changed": "调整项目角色",
  "project.member_removed": "移除项目成员",
  "comment.thread_created": "添加时间点批注",
  "comment.reply_created": "回复协作批注",
  "comment.thread_resolved": "解决协作批注",
  "comment.thread_reopened": "重新打开协作批注",
  "project.ownership_transferred": "移交项目负责人",
  "pipeline.completed": "AI 处理完成",
  "pipeline.failed": "AI 处理失败",
  "pipeline.cancelled": "AI 处理已取消",
  "pipeline.retried": "重新开始 AI 处理",
};

function dateTimeLocalValue(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function eventSummary(before: Record<string, unknown> | null, after: Record<string, unknown> | null) {
  const from = typeof before?.lifecycle === "string" ? before.lifecycle : null;
  const to = typeof after?.lifecycle === "string" ? after.lifecycle : null;
  if (from && to && from in PROJECT_LIFECYCLE_LABELS && to in PROJECT_LIFECYCLE_LABELS) {
    return `${PROJECT_LIFECYCLE_LABELS[from as ProjectLifecycle]} → ${PROJECT_LIFECYCLE_LABELS[to as ProjectLifecycle]}`;
  }
  return "项目记录已更新";
}

export function ProjectOperations({
  api,
  project,
  onChanged,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  onChanged: (project: ProjectSnapshot) => void;
}) {
  const canManage = project.allowed_actions.includes("manage_project");
  const [visibility, setVisibility] = useState(project.visibility);
  const [assigneeId, setAssigneeId] = useState(project.assignee?.user_id ?? "");
  const [priority, setPriority] = useState(project.priority);
  const [dueAt, setDueAt] = useState(dateTimeLocalValue(project.due_at));
  const [targetLifecycle, setTargetLifecycle] = useState<ProjectLifecycle | "">("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    setVisibility(project.visibility);
    setAssigneeId(project.assignee?.user_id ?? "");
    setPriority(project.priority);
    setDueAt(dateTimeLocalValue(project.due_at));
    setTargetLifecycle("");
  }, [project]);

  const activityQuery = useQuery({
    queryKey: ["project-activity", project.project_id],
    queryFn: () => api.listProjectActivity(project.project_id),
  });
  const managementMutation = useMutation({
    mutationFn: (body: ProjectManagementRequest) =>
      api.updateProjectManagement(project.project_id, body),
    onSuccess: (updated) => {
      onChanged(updated);
      void activityQuery.refetch();
    },
  });
  const lifecycleMutation = useMutation({
    mutationFn: ({ target, note }: { target: ProjectLifecycle; note: string }) =>
      api.transitionProjectLifecycle(project.project_id, {
        expected_management_version: project.management_version,
        target,
        reason: note,
      }),
    onSuccess: (updated) => {
      setReason("");
      onChanged(updated);
      void activityQuery.refetch();
    },
  });

  const saveManagement = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    managementMutation.mutate({
      expected_management_version: project.management_version,
      visibility,
      assignee_user_id: assigneeId || null,
      priority,
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
    });
  };
  const moveLifecycle = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!targetLifecycle || !reason.trim()) return;
    lifecycleMutation.mutate({ target: targetLifecycle, note: reason.trim() });
  };

  return (
    <section className="panel project-operations" aria-labelledby="project-operations-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">项目运营</p>
          <h2 id="project-operations-title">任务与生命周期</h2>
        </div>
        <StatusBadge
          status={project.lifecycle}
          label={PROJECT_LIFECYCLE_LABELS[project.lifecycle]}
        />
      </div>

      <div className="project-operations-grid">
        <form className="project-management-form" onSubmit={saveManagement}>
          <h3>项目设置</h3>
          <label>
            当前执行人
            <select value={assigneeId} disabled={!canManage} onChange={(event) => setAssigneeId(event.target.value)}>
              <option value="">暂不分配</option>
              {project.members.map((member) => (
                <option key={member.user_id} value={member.user_id}>{member.display_name} · @{member.username}</option>
              ))}
            </select>
          </label>
          <label>
            优先级
            <select value={priority} disabled={!canManage} onChange={(event) => setPriority(event.target.value as ProjectSnapshot["priority"])}>
              {Object.entries(PRIORITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            截止时间
            <input type="datetime-local" value={dueAt} disabled={!canManage} onChange={(event) => setDueAt(event.target.value)} />
          </label>
          <label>
            可见范围
            <select value={visibility} disabled={!canManage} onChange={(event) => setVisibility(event.target.value as ProjectSnapshot["visibility"])}>
              <option value="private">仅项目成员</option>
              <option value="workspace">工作区成员可查看</option>
            </select>
          </label>
          {canManage ? <button type="submit" className="button button-primary" disabled={managementMutation.isPending}>{managementMutation.isPending ? "保存中…" : "保存项目设置"}</button> : <p className="hint">只有项目负责人可以修改运营设置。</p>}
          {managementMutation.isError ? <p className="form-error" role="alert">{errorMessage(managementMutation.error)}</p> : null}
        </form>

        <form className="project-lifecycle-form" onSubmit={moveLifecycle}>
          <h3>推进项目</h3>
          <p>当前阶段：<strong>{PROJECT_LIFECYCLE_LABELS[project.lifecycle]}</strong></p>
          {canManage && project.allowed_lifecycle_transitions.length > 0 ? (
            <>
              <label>
                下一阶段
                <select required value={targetLifecycle} onChange={(event) => setTargetLifecycle(event.target.value as ProjectLifecycle)}>
                  <option value="">请选择</option>
                  {project.allowed_lifecycle_transitions.map((target) => <option key={target} value={target}>{PROJECT_LIFECYCLE_LABELS[target]}</option>)}
                </select>
              </label>
              <label>
                操作说明
                <textarea required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明推进、退回或归档原因" />
              </label>
              <button type="submit" className={targetLifecycle === "archived" ? "button button-danger-ghost" : "button button-secondary"} disabled={lifecycleMutation.isPending || !targetLifecycle || !reason.trim()}>{lifecycleMutation.isPending ? "提交中…" : targetLifecycle === project.lifecycle_before_archive ? "恢复项目" : "确认推进"}</button>
            </>
          ) : <p className="hint">当前账号没有可执行的阶段操作。</p>}
          {lifecycleMutation.isError ? <p className="form-error" role="alert">{errorMessage(lifecycleMutation.error)}</p> : null}
        </form>

        <div className="project-activity" aria-labelledby="project-activity-title">
          <h3 id="project-activity-title">最近活动</h3>
          {activityQuery.isPending ? <LoadingState>正在加载活动…</LoadingState> : null}
          {activityQuery.isError ? <ErrorState error={activityQuery.error} onRetry={() => void activityQuery.refetch()} /> : null}
          {activityQuery.data?.events.length === 0 ? <EmptyState title="暂无项目活动" /> : null}
          {activityQuery.data?.events.length ? (
            <ol>
              {activityQuery.data.events.slice(0, 8).map((event) => (
                <li key={event.event_id}>
                  <span aria-hidden="true" />
                  <div><strong>{ACTIVITY_LABELS[event.action] ?? event.action}</strong><p>{eventSummary(event.before, event.after)}</p><small>{event.actor_username ?? "LiveClip 系统"} · {new Date(event.created_at).toLocaleString("zh-CN")}</small></div>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      </div>
    </section>
  );
}
