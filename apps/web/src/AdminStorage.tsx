import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type LiveClipApiClient, errorMessage } from "./api";
import type { ProjectPurgePlan } from "./types";
import { EmptyState, ErrorState, LoadingState } from "./ui";

const PURGE_BLOCKER_LABELS: Record<string, string> = {
  project_must_be_archived: "项目必须先归档",
  active_work_must_finish: "仍有处理或导出任务未结束",
  source_reference_inside_generated_project_directory: "有项目把该目录中的文件登记为源视频",
  unsafe_generated_entries_must_be_removed: "目录包含符号链接、挂载点或其他不安全项目",
};

function purgeBlockerLabel(value: string): string {
  return PURGE_BLOCKER_LABELS[value] ?? "项目状态已变化，请重新扫描后再试";
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${unit}`;
}

export function AdminStorage({ api, administratorUsername }: { api: LiveClipApiClient; administratorUsername: string }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [purgePlan, setPurgePlan] = useState<ProjectPurgePlan | null>(null);
  const [projectNameConfirmation, setProjectNameConfirmation] = useState("");
  const [purgePhrase, setPurgePhrase] = useState("");
  const reportQuery = useQuery({
    queryKey: ["admin-storage"],
    queryFn: () => api.storageReport(),
  });
  const cleanupMutation = useMutation({
    mutationFn: () => api.cleanupSafeStorage(),
    onSuccess: (result) => {
      queryClient.setQueryData(["admin-storage"], result.report);
      setConfirming(false);
    },
  });
  const purgePlanMutation = useMutation({
    mutationFn: (projectId: string) => api.projectPurgePlan(projectId),
    onSuccess: (plan) => {
      setPurgePlan(plan);
      setProjectNameConfirmation("");
      setPurgePhrase("");
    },
  });
  const purgeMutation = useMutation({
    mutationFn: (plan: ProjectPurgePlan) => api.purgeProject(plan.project_id, {
      snapshot_fingerprint: plan.snapshot_fingerprint,
      project_name: projectNameConfirmation,
      administrator_username: administratorUsername,
      confirmation_phrase: purgePhrase,
    }),
    onSuccess: () => {
      setPurgePlan(null);
      setProjectNameConfirmation("");
      setPurgePhrase("");
      void queryClient.invalidateQueries({ queryKey: ["admin-storage"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const report = reportQuery.data;

  return (
    <main className="admin-page storage-admin-page">
      <section className="dashboard-heading">
        <div>
          <p className="eyebrow">系统管理</p>
          <h1>存储与保留</h1>
          <p>查看本机项目产物占用、失效文件和异常项。源视频只是只读引用，不在这里删除。</p>
        </div>
        <button type="button" className="button button-ghost" onClick={() => void reportQuery.refetch()} disabled={reportQuery.isFetching}>重新扫描</button>
      </section>
      {reportQuery.isPending ? <LoadingState>正在扫描本机项目存储…</LoadingState> : null}
      {reportQuery.isError ? <ErrorState error={reportQuery.error} onRetry={() => void reportQuery.refetch()} /> : null}
      {report ? <>
        <section className="storage-stats" aria-label="存储概览">
          <article><span>项目目录</span><strong>{formatBytes(report.project_directory_bytes)}</strong><small>{report.projects.length} 个数据库项目</small></article>
          <article><span>数据库</span><strong>{formatBytes(report.database_bytes)}</strong><small>含 WAL / SHM</small></article>
          <article><span>数据库备份</span><strong>{formatBytes(report.migration_backup_bytes + report.database_backup_bytes)}</strong><small>迁移与永久清除恢复点</small></article>
          <article><span>磁盘可用</span><strong>{formatBytes(report.filesystem_free_bytes)}</strong><small>总容量 {formatBytes(report.filesystem_capacity_bytes)}</small></article>
        </section>
        {(report.unknown_project_file_count > 0 || report.unsafe_entry_count > 0 || report.purge_quarantine_file_count > 0) ? <div className="notice notice-error" role="alert">发现 {report.unknown_project_file_count} 个未知项目目录文件、{report.unsafe_entry_count} 个符号链接或非普通项、{report.purge_quarantine_file_count} 个待重试清除文件；系统不会读取未知或不安全内容。</div> : null}
        <section className="panel storage-policy">
          <div><h2>安全保留策略</h2><p>归档只会将项目改为只读，不会删除任何产物。自动清理仅限数据库确认已结束任务的临时工作目录；已提交产物、交付包和源视频永不由该操作删除。永久清除只能用于已归档项目，会先创建数据库恢复点，并且绝不删除外部源视频。</p></div>
          {!confirming ? <button type="button" className="button button-secondary" onClick={() => setConfirming(true)}>清理安全临时文件</button> : <div className="cleanup-confirm"><p><strong>请再次确认：</strong>只清理已结束任务的临时工作目录，并写入审计日志。</p><button type="button" className="button button-primary" disabled={cleanupMutation.isPending} onClick={() => cleanupMutation.mutate()}>{cleanupMutation.isPending ? "正在清理…" : "确认安全清理"}</button><button type="button" className="button button-ghost" onClick={() => setConfirming(false)}>取消</button></div>}
          {cleanupMutation.data ? <p className="notice" role="status">已检查 {cleanupMutation.data.inspected_attempts} 个任务目录和 {cleanupMutation.data.inspected_purge_quarantines} 个已完成清除隔离目录；共清理 {cleanupMutation.data.cleaned_attempts + cleanupMutation.data.cleaned_purge_quarantines} 个，失败 {cleanupMutation.data.failed_attempts + cleanupMutation.data.failed_purge_quarantines} 个。</p> : null}
          {cleanupMutation.isError ? <p className="form-error" role="alert">{errorMessage(cleanupMutation.error)}</p> : null}
        </section>
        <section className="panel user-manager storage-projects">
          <div className="project-manager-heading"><div><h2>项目存储明细</h2><p>“未登记”表示项目目录内没有对应 Asset 记录的文件，只提示，不自动删除。</p></div><small>扫描于 {new Date(report.scanned_at).toLocaleString("zh-CN")}</small></div>
          {report.projects.length === 0 ? <EmptyState title="还没有项目存储" /> : <div className="user-table-wrap"><table className="user-table"><thead><tr><th>项目</th><th>实际占用</th><th>已登记产物</th><th>失效 / 孤立</th><th>未登记</th><th>异常</th><th>保留操作</th></tr></thead><tbody>{report.projects.map((project) => <tr key={project.project_id}><td><strong>{project.project_name}</strong><small>{project.lifecycle}</small></td><td>{formatBytes(project.actual_bytes)}<small>{project.actual_file_count} 个文件</small></td><td>{formatBytes(project.tracked_asset_bytes)}</td><td>{formatBytes(project.stale_render_asset_bytes + project.orphan_asset_bytes)}<small>待处理 {formatBytes(project.pending_asset_bytes)}</small></td><td>{formatBytes(project.untracked_bytes)}<small>{project.untracked_file_count} 个文件</small></td><td>{project.missing_committed_asset_count + project.unsafe_entry_count}</td><td>{project.lifecycle === "archived" ? <button type="button" className="button button-danger" disabled={purgePlanMutation.isPending || purgeMutation.isPending} onClick={() => { purgeMutation.reset(); purgePlanMutation.mutate(project.project_id); }}>准备永久清除</button> : <small>先归档项目</small>}</td></tr>)}</tbody></table></div>}
          {purgeMutation.data ? <p className="notice" role="status">{purgeMutation.data.filesystem_cleanup_pending ? <>“{purgeMutation.data.project_name}”的数据库记录已清除；生成文件仍在安全隔离区，等待安全清理重试。</> : <>已永久清除“{purgeMutation.data.project_name}”。</>} 数据库恢复点：{purgeMutation.data.database_backup_filename}。外部源视频未删除。</p> : null}
          {purgePlanMutation.isError ? <p className="form-error" role="alert">{errorMessage(purgePlanMutation.error)}</p> : null}
          {purgePlan ? <div className="purge-confirm" role="dialog" aria-modal="true" aria-labelledby="purge-title">
            <h3 id="purge-title">永久清除“{purgePlan.project_name}”</h3>
            <p>将删除 {formatBytes(purgePlan.generated_bytes)}、{purgePlan.generated_file_count} 个本地生成文件及项目数据库记录。系统会先创建校验过的数据库备份；源视频“{purgePlan.source_filename ?? "未登记"}”不会被删除。</p>
            {purgePlan.blockers.length > 0 ? <p className="form-error" role="alert">当前不能清除：{purgePlan.blockers.map(purgeBlockerLabel).join("；")}</p> : null}
            <label>输入完整项目名确认<input value={projectNameConfirmation} onChange={(event) => setProjectNameConfirmation(event.target.value)} autoComplete="off" /></label>
            <label>再输入 <code>{purgePlan.confirmation_phrase}</code><input value={purgePhrase} onChange={(event) => setPurgePhrase(event.target.value)} autoComplete="off" /></label>
            <div className="form-actions"><button type="button" className="button button-danger" disabled={!purgePlan.ready || projectNameConfirmation !== purgePlan.project_name || purgePhrase !== purgePlan.confirmation_phrase || purgeMutation.isPending} onClick={() => purgeMutation.mutate(purgePlan)}>{purgeMutation.isPending ? "正在创建恢复点并清除…" : "永久清除项目"}</button><button type="button" className="button button-ghost" disabled={purgeMutation.isPending} onClick={() => setPurgePlan(null)}>取消</button></div>
            {purgeMutation.isError ? <p className="form-error" role="alert">{errorMessage(purgeMutation.error)}</p> : null}
          </div> : null}
        </section>
      </> : null}
    </main>
  );
}
