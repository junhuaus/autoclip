import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage, signedUrlRefreshInterval } from "./api";
import { ClipEditor } from "./ClipEditor";
import type {
  ClipSummaryResponse,
  DeliveryDetailResponse,
  ProjectSnapshot,
  RunSnapshot,
  StageSnapshot,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, formatMs, statusLabel } from "./ui";

const STAGE_LABELS: Record<string, string> = {
  ingest: "导入",
  preprocess: "音频预处理",
  transcribe: "中文转写",
  candidates: "候选生成",
  edit: "AI 编辑",
  proxy_render: "审核代理渲染",
};

function stageDisplayStatus(stage: StageSnapshot): { status: string; label: string } {
  if (stage.status === "queued" && stage.retry_count > 0) {
    return { status: "retrying", label: `重试中 · 第 ${stage.retry_count} 次` };
  }
  return { status: stage.status, label: statusLabel(stage.status) };
}

function RunPanel({
  run,
  busy,
  error,
  onCancel,
  onRetry,
}: {
  run: RunSnapshot;
  busy: boolean;
  error: unknown;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const active = run.status === "queued" || run.status === "running";
  return (
    <section className="panel" aria-labelledby="pipeline-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Pipeline run {run.run_id.slice(0, 8)}</p>
          <h2 id="pipeline-title">处理进度</h2>
        </div>
        <StatusBadge status={run.status} />
      </div>

      <div className="progress-row">
        <progress value={run.progress} max={100} aria-label={`总进度 ${run.progress}%`} />
        <strong>{run.progress}%</strong>
      </div>

      {run.cancellation_requested && run.status !== "cancelled" ? (
        <div className="notice" role="status">
          <StatusBadge status="cancelled" label="取消中" />
          <span>已请求安全取消，Worker 会在下一个安全边界停止。</span>
        </div>
      ) : null}
      {run.status === "cancelled" ? (
        <div className="notice notice-cancelled" role="status">
          <StatusBadge status="cancelled" />
          <span>本次处理已取消，终态不会继续轮询。</span>
        </div>
      ) : null}
      {run.status === "failed" ? (
        <div className="notice notice-error" role="alert">
          <StatusBadge status="failed" />
          <span>{run.safe_error_message ?? "处理失败，可查看阶段错误并尝试后端允许的重试。"}</span>
        </div>
      ) : null}

      <ol className="stage-list">
        {run.stages.map((stage) => {
          const display = stageDisplayStatus(stage);
          return (
            <li key={stage.stage} className={`stage-item stage-${stage.status}`}>
              <div>
                <strong>{STAGE_LABELS[stage.stage] ?? stage.stage}</strong>
                <span>{stage.progress}%</span>
              </div>
              <StatusBadge status={display.status} label={display.label} />
              {stage.safe_error_message ? (
                <p className="form-error">
                  {stage.error_code ? `${stage.error_code} · ` : ""}{stage.safe_error_message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>

      <div className="button-row">
        <button
          type="button"
          className="button button-danger-ghost"
          disabled={busy || !active || run.cancellation_requested}
          onClick={onCancel}
        >
          {run.cancellation_requested ? "正在取消…" : "取消处理"}
        </button>
        <button
          type="button"
          className="button button-secondary"
          disabled={busy || run.status !== "failed"}
          onClick={onRetry}
        >
          {busy && run.status === "failed" ? "重试提交中…" : "重试失败任务"}
        </button>
      </div>
      {error ? <p className="form-error" role="alert">{errorMessage(error)}</p> : null}
    </section>
  );
}

function TranscriptPanel({ api, projectId, enabled }: { api: LiveClipApiClient; projectId: string; enabled: boolean }) {
  const query = useQuery({
    queryKey: ["transcript", projectId],
    queryFn: () => api.getTranscript(projectId),
    enabled,
  });

  return (
    <section className="panel" aria-labelledby="transcript-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">源视频绝对时间</p>
          <h2 id="transcript-title">转写</h2>
        </div>
        {query.data ? <span className="metric">{query.data.segments.length} 段</span> : null}
      </div>
      {!enabled ? <EmptyState title="转写尚未可用">等待 Pipeline 完成。</EmptyState> : null}
      {enabled && query.isPending ? <LoadingState>正在加载转写…</LoadingState> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
      {query.data?.segments.length === 0 ? <EmptyState title="转写为空" /> : null}
      {query.data && query.data.segments.length > 0 ? (
        <>
          <p className="hint">
            {query.data.language} · {query.data.provider}/{query.data.model} · 词级时间：
            {query.data.word_timing_status === "available" ? "可用" : "不可用"}
          </p>
          <ol className="transcript-list">
            {query.data.segments.map((segment) => (
              <li key={segment.segment_id}>
                <time>{formatMs(segment.start_ms)}–{formatMs(segment.end_ms)}</time>
                <p>{segment.text}</p>
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </section>
  );
}

export function ClipCard({ item, onOpen }: { item: ClipSummaryResponse; onOpen: () => void }) {
  const { clip } = item;
  return (
    <article className={`clip-card ${clip.proxy_status === "stale" ? "clip-stale" : ""}`}>
      {item.proxy_media_url ? (
        <video controls preload="metadata" src={item.proxy_media_url} aria-label={`${clip.title} 审核代理`}>
          浏览器不支持 HTML5 视频播放。
        </video>
      ) : (
        <div className="video-placeholder">
          {clip.proxy_status === "stale" ? "旧代理已失效" : "暂无可播放代理"}
        </div>
      )}
      <div className="clip-card-body">
        <div className="section-heading compact">
          <span className="eyebrow">revision {clip.edit_plan_revision}</span>
          <StatusBadge status={clip.review_status} />
        </div>
        <h3>{clip.title}</h3>
        <p className="clip-time">{formatMs(clip.source_start_ms)}–{formatMs(clip.source_end_ms)}</p>
        <p>{clip.reason}</p>
        <div className="badge-row">
          <span className="metric">{clip.score.toFixed(1)} 分</span>
          {clip.proxy_status ? <StatusBadge status={clip.proxy_status} label={`代理${statusLabel(clip.proxy_status)}`} /> : null}
        </div>
        {clip.proxy_status === "stale" ? (
          <p className="stale-copy" role="status">当前 revision 需要重新渲染，旧代理不能用于交付。</p>
        ) : null}
        {clip.risk_flags.length > 0 ? (
          <ul className="risk-list" aria-label="风险标签">
            {clip.risk_flags.map((flag) => <li key={flag}>{flag}</li>)}
          </ul>
        ) : null}
        <button type="button" className="button button-primary" onClick={onOpen}>
          审核和编辑
        </button>
      </div>
    </article>
  );
}

function DeliveryRow({ value }: { value: DeliveryDetailResponse }) {
  const { delivery } = value;
  return (
    <li className="delivery-row">
      <div>
        <strong>{delivery.delivery_version}</strong>
        <span>{delivery.clip_count} 个切片</span>
      </div>
      <StatusBadge status={delivery.status} />
      {delivery.safe_error_message ? <span className="form-error">{delivery.safe_error_message}</span> : null}
      {value.download_url ? (
        <a className="button button-secondary" href={value.download_url} download>
          下载 ZIP
        </a>
      ) : (
        <span className="hint">ZIP 尚不可下载</span>
      )}
    </li>
  );
}

export function DeliveryPanel({
  api,
  project,
  approvedCount,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  approvedCount: number;
}) {
  const queryClient = useQueryClient();
  const [includeZip, setIncludeZip] = useState(true);
  const [activeDeliveryId, setActiveDeliveryId] = useState<string | null>(null);
  const deliveriesQuery = useQuery({
    queryKey: ["deliveries", project.project_id],
    queryFn: () => api.listDeliveries(project.project_id),
    refetchInterval: (query) => {
      const values = query.state.data;
      if (
        values?.some(
          ({ delivery }) => delivery.status === "queued" || delivery.status === "creating",
        )
      ) {
        return 1_000;
      }
      return signedUrlRefreshInterval(values?.map((value) => value.download_url) ?? []);
    },
  });
  const deliveryQuery = useQuery({
    queryKey: ["delivery", activeDeliveryId],
    queryFn: () => api.getDelivery(activeDeliveryId as string),
    enabled: activeDeliveryId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.delivery.status;
      return status === "queued" || status === "creating"
        ? 800
        : signedUrlRefreshInterval([query.state.data?.download_url]);
    },
  });
  const createMutation = useMutation({
    mutationFn: () => api.createDelivery(project.project_id, includeZip),
    onSuccess: (accepted) => {
      setActiveDeliveryId(accepted.resource_id);
      void queryClient.invalidateQueries({ queryKey: ["deliveries", project.project_id] });
    },
  });

  useEffect(() => {
    const status = deliveryQuery.data?.delivery.status;
    if (status === "succeeded" || status === "failed") {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["deliveries", project.project_id] }),
        queryClient.invalidateQueries({ queryKey: ["project", project.project_id] }),
      ]);
    }
  }, [deliveryQuery.data?.delivery.status, project.project_id, queryClient]);

  const activeDelivery = deliveriesQuery.data?.some(
    ({ delivery }) => delivery.status === "queued" || delivery.status === "creating",
  );
  const hasFailedDelivery = deliveriesQuery.data?.some(
    ({ delivery }) => delivery.status === "failed",
  );
  const canCreate = approvedCount > 0 && !activeDelivery && !createMutation.isPending;

  return (
    <section className="panel" aria-labelledby="delivery-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">不可变版本</p>
          <h2 id="delivery-title">交付包</h2>
        </div>
        <span className="metric">已批准 {approvedCount}</span>
      </div>
      <div className="delivery-actions">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={includeZip}
            onChange={(event) => setIncludeZip(event.currentTarget.checked)}
          />
          创建 delivery.zip
        </label>
        <button
          type="button"
          className="button button-primary"
          disabled={!canCreate}
          onClick={() => createMutation.mutate()}
        >
          {createMutation.isPending
            ? "正在提交…"
            : includeZip
              ? hasFailedDelivery
                ? "重试为新交付版本"
                : "创建新交付版本"
              : "创建无 ZIP 交付版本"}
        </button>
      </div>
      {!canCreate ? (
        <p className="hint disabled-reason">
          {approvedCount === 0
            ? "至少批准一个当前 revision 后才能请求交付；最终渲染资格仍由后端校验。"
            : "已有交付任务正在执行，请等待其进入终态。"}
        </p>
      ) : null}
      {deliveryQuery.data ? (
        <div className="notice" aria-live="polite">
          <StatusBadge status={deliveryQuery.data.delivery.status} />
          <span>{deliveryQuery.data.delivery.delivery_version} 状态已更新。</span>
        </div>
      ) : null}
      {createMutation.isError ? <ErrorState error={createMutation.error} /> : null}
      {deliveryQuery.isError ? <ErrorState error={deliveryQuery.error} /> : null}
      {deliveriesQuery.isPending ? <LoadingState>正在加载交付版本…</LoadingState> : null}
      {deliveriesQuery.isError ? <ErrorState error={deliveriesQuery.error} onRetry={() => void deliveriesQuery.refetch()} /> : null}
      {deliveriesQuery.data?.length === 0 ? <EmptyState title="还没有交付版本" /> : null}
      {deliveriesQuery.data && deliveriesQuery.data.length > 0 ? (
        <ul className="delivery-list">
          {deliveriesQuery.data.map((delivery) => <DeliveryRow key={delivery.delivery.delivery_id} value={delivery} />)}
        </ul>
      ) : null}
    </section>
  );
}

export function ProjectWorkspace({
  api,
  projectId,
  onBack,
}: {
  api: LiveClipApiClient;
  projectId: string;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    refetchInterval: (query) => query.state.data?.status === "processing" ? 1_000 : false,
  });
  const runId = projectQuery.data?.current_run_id ?? null;
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId as string),
    enabled: runId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1_000 : false;
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.cancelRun(runId as string),
    onSuccess: (run) => queryClient.setQueryData(["run", run.run_id], run),
  });
  const retryMutation = useMutation({
    mutationFn: () => api.retryRun(runId as string),
    onSuccess: (run) => {
      queryClient.setQueryData(["run", run.run_id], run);
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
  const contentEnabled =
    projectQuery.data?.status !== "imported" && runQuery.data?.status === "completed";
  const clipsQuery = useQuery({
    queryKey: ["clips", projectId],
    queryFn: () => api.listClips(projectId),
    enabled: contentEnabled,
    refetchInterval: (query) =>
      signedUrlRefreshInterval(
        query.state.data?.map((value) => value.proxy_media_url) ?? [],
      ),
  });
  const approvedCount = useMemo(
    () => clipsQuery.data?.filter(({ clip }) => clip.review_status === "approved").length ?? 0,
    [clipsQuery.data],
  );

  if (projectQuery.isPending) {
    return <LoadingState>正在加载项目…</LoadingState>;
  }
  if (projectQuery.isError) {
    return <ErrorState error={projectQuery.error} onRetry={() => void projectQuery.refetch()} />;
  }
  const project = projectQuery.data;

  return (
    <main className="workspace">
      <button type="button" className="button button-ghost back-button" onClick={onBack}>
        ← 返回项目列表
      </button>
      <section className="project-hero">
        <div>
          <p className="eyebrow">项目 {project.project_id.slice(0, 8)} · generation {project.generation}</p>
          <h1>{project.name}</h1>
          <p>{project.source_filename}</p>
        </div>
        <div className="hero-status">
          <StatusBadge status={project.status} />
          <span>已批准 {approvedCount}/{clipsQuery.data?.length ?? 0}</span>
        </div>
      </section>

      {runQuery.isPending ? <LoadingState>正在加载 Pipeline 状态…</LoadingState> : null}
      {runQuery.isError ? <ErrorState error={runQuery.error} onRetry={() => void runQuery.refetch()} /> : null}
      {runQuery.data ? (
        <RunPanel
          run={runQuery.data}
          busy={cancelMutation.isPending || retryMutation.isPending}
          error={cancelMutation.error ?? retryMutation.error}
          onCancel={() => cancelMutation.mutate()}
          onRetry={() => retryMutation.mutate()}
        />
      ) : null}

      <TranscriptPanel api={api} projectId={projectId} enabled={contentEnabled} />

      <section className="panel" aria-labelledby="clips-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">人工审核</p>
            <h2 id="clips-title">高光候选</h2>
          </div>
          <span className="metric">已批准 {approvedCount}</span>
        </div>
        {!contentEnabled ? <EmptyState title="候选尚未可用">等待 Pipeline 完成。</EmptyState> : null}
        {contentEnabled && clipsQuery.isPending ? <LoadingState>正在加载候选…</LoadingState> : null}
        {clipsQuery.isError ? <ErrorState error={clipsQuery.error} onRetry={() => void clipsQuery.refetch()} /> : null}
        {clipsQuery.data?.length === 0 ? <EmptyState title="没有高光候选" /> : null}
        {clipsQuery.data && clipsQuery.data.length > 0 ? (
          <div className="clip-grid">
            {clipsQuery.data.map((item) => (
              <ClipCard key={item.clip.clip_id} item={item} onOpen={() => setSelectedClipId(item.clip.clip_id)} />
            ))}
          </div>
        ) : null}
      </section>

      {selectedClipId ? (
        <ClipEditor
          api={api}
          clipId={selectedClipId}
          onClose={() => setSelectedClipId(null)}
          onChanged={() => {
            void clipsQuery.refetch();
            void projectQuery.refetch();
          }}
        />
      ) : null}

      <DeliveryPanel api={api} project={project} approvedCount={approvedCount} />
    </main>
  );
}
