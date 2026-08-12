import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  LiveClipApiClient,
  createIdempotencyKey,
  errorMessage,
  signedUrlRefreshInterval,
} from "./api";
import { ClipEditor } from "./ClipEditor";
import type {
  ClipSummaryResponse,
  BatchReviewRequest,
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

interface BatchReviewOperation {
  body: BatchReviewRequest;
  requestKey: string;
}

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

export function ClipCard({
  item,
  onOpen,
  selected = false,
  onSelectedChange = () => undefined,
  selectionDisabled = false,
  openDisabled = false,
}: {
  item: ClipSummaryResponse;
  onOpen: () => void;
  selected?: boolean;
  onSelectedChange?: (selected: boolean) => void;
  selectionDisabled?: boolean;
  openDisabled?: boolean;
}) {
  const { clip } = item;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingSeekMs = useRef<number | null>(null);

  const seekTo = (startMs: number) => {
    const video = videoRef.current;
    if (!video || !item.proxy_media_url) return;
    if (video.readyState < 1) {
      pendingSeekMs.current = startMs;
      return;
    }
    const requestedSeconds = startMs / 1_000;
    video.currentTime = Number.isFinite(video.duration)
      ? Math.min(Math.max(0, requestedSeconds), video.duration)
      : Math.max(0, requestedSeconds);
  };

  const applyPendingSeek = () => {
    if (pendingSeekMs.current === null) return;
    const startMs = pendingSeekMs.current;
    pendingSeekMs.current = null;
    seekTo(startMs);
  };

  return (
    <article
      className={`clip-card ${clip.proxy_status === "stale" ? "clip-stale" : ""}`}
      aria-labelledby={`clip-title-${clip.clip_id}`}
    >
      <div className="clip-card-main">
        <div className="clip-card-media">
          {item.proxy_media_url ? (
            <video
              ref={videoRef}
              controls
              preload="metadata"
              src={item.proxy_media_url}
              aria-label={`${clip.title} 审核代理`}
              onLoadedMetadata={applyPendingSeek}
            >
              浏览器不支持 HTML5 视频播放。
            </video>
          ) : (
            <div className="video-placeholder">
              {clip.proxy_status === "stale" ? "旧代理已失效" : "暂无可播放代理"}
            </div>
          )}
        </div>
        <div className="clip-card-body">
          <div className="section-heading compact">
            <label className="clip-select">
              <input
                type="checkbox"
                checked={selected}
                disabled={selectionDisabled}
                onChange={(event) => onSelectedChange(event.target.checked)}
              />
              选择批量审核
            </label>
            <StatusBadge status={clip.review_status} />
          </div>
          <span className="eyebrow">revision {clip.edit_plan_revision}</span>
          <h3 id={`clip-title-${clip.clip_id}`}>{clip.title}</h3>
          <p className="hint">干净切片 · 高光文案独立展示</p>
          <p className="clip-time">{formatMs(clip.source_start_ms)}–{formatMs(clip.source_end_ms)}</p>
          <p>{clip.reason}</p>

          <section
            className="clip-highlight-sentence"
            aria-labelledby={`highlight-sentence-${clip.clip_id}`}
          >
            <div className="metadata-heading">
              <h4 id={`highlight-sentence-${clip.clip_id}`}>高光语句</h4>
              <span>推荐上屏</span>
            </div>
            <blockquote>{clip.hook}</blockquote>
            <p className="hint">AI 从当前高光内容提炼，作为可审核的画面文案。</p>
          </section>

          <section className="clip-keywords" aria-labelledby={`keywords-${clip.clip_id}`}>
            <div className="metadata-heading">
              <h4 id={`keywords-${clip.clip_id}`}>编辑关键词</h4>
              <span>仅供编辑定位</span>
            </div>
            {clip.keywords.length > 0 ? (
              <ul aria-label={`${clip.title} 编辑关键词`}>
                {clip.keywords.map((keyword, index) => (
                  <li key={`${keyword.text}-${keyword.clip_start_ms}-${index}`}>
                    <button
                      type="button"
                      disabled={!item.proxy_media_url}
                      onClick={() => seekTo(keyword.clip_start_ms)}
                      aria-label={`定位到编辑关键词 ${keyword.text}，${formatMs(keyword.clip_start_ms)}`}
                    >
                      <strong>{keyword.text}</strong>
                      <time>{formatMs(keyword.clip_start_ms)}–{formatMs(keyword.clip_end_ms)}</time>
                      <span>{keyword.timing_precision === "word" ? "词级时间" : "转写段时间窗"}</span>
                      <span>
                        源 {formatMs(keyword.source_start_ms)}–{formatMs(keyword.source_end_ms)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="hint">暂无可定位的编辑关键词</p>
            )}
          </section>

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
          <button
            type="button"
            className="button button-primary clip-edit-button"
            disabled={openDisabled}
            onClick={onOpen}
          >
            审核和编辑
          </button>
        </div>
      </div>

      <section
        className="clip-captions clip-card-captions"
        aria-labelledby={`captions-${clip.clip_id}`}
      >
        <div className="metadata-heading">
          <h4 id={`captions-${clip.clip_id}`}>字幕</h4>
          <span>点击跳转到对应画面</span>
        </div>
        {clip.captions.length > 0 ? (
          <ol aria-label={`${clip.title} 字幕`}>
            {clip.captions.map((cue, index) => (
              <li key={`${cue.start_ms}-${cue.end_ms}-${index}`}>
                <button
                  type="button"
                  disabled={!item.proxy_media_url}
                  onClick={() => seekTo(cue.start_ms)}
                  aria-label={`定位到字幕 ${formatMs(cue.start_ms)}：${cue.text}`}
                >
                  <time>{formatMs(cue.start_ms)}–{formatMs(cue.end_ms)}</time>
                  <span>{cue.text}</span>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="hint">暂无字幕</p>
        )}
      </section>
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
  const [selectedClipIds, setSelectedClipIds] = useState<Set<string>>(() => new Set());
  const [batchRejectReason, setBatchRejectReason] = useState("");
  const [batchNotice, setBatchNotice] = useState<string | null>(null);
  const [dirtyClipIds, setDirtyClipIds] = useState<Set<string>>(() => new Set());
  const [failedBatchOperation, setFailedBatchOperation] =
    useState<BatchReviewOperation | null>(null);
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
  const selectedItems = useMemo(
    () =>
      clipsQuery.data?.filter(({ clip }) => selectedClipIds.has(clip.clip_id)) ?? [],
    [clipsQuery.data, selectedClipIds],
  );
  const selectableItems = useMemo(
    () =>
      clipsQuery.data?.filter(({ clip }) =>
        !dirtyClipIds.has(clip.clip_id) &&
        (clip.allowed_actions.includes("approve") || clip.allowed_actions.includes("reject")),
      ) ?? [],
    [clipsQuery.data, dirtyClipIds],
  );
  useEffect(() => {
    if (!clipsQuery.data) return;
    const visibleIds = new Set(clipsQuery.data.map(({ clip }) => clip.clip_id));
    setSelectedClipIds((current) => {
      const next = new Set([...current].filter((clipId) => visibleIds.has(clipId)));
      return next.size === current.size ? current : next;
    });
  }, [clipsQuery.data]);
  useEffect(() => {
    if (dirtyClipIds.size === 0) return;
    setSelectedClipIds((current) => {
      const next = new Set([...current].filter((clipId) => !dirtyClipIds.has(clipId)));
      return next.size === current.size ? current : next;
    });
  }, [dirtyClipIds]);
  const handleEditorDirtyChange = useCallback((clipId: string, dirty: boolean) => {
    setDirtyClipIds((current) => {
      const next = new Set(current);
      if (dirty) next.add(clipId);
      else next.delete(clipId);
      if (next.size === current.size && [...next].every((value) => current.has(value))) {
        return current;
      }
      return next;
    });
  }, []);
  const batchMutation = useMutation({
    mutationFn: (operation: BatchReviewOperation) =>
      api.reviewClipsBatch(projectId, operation.body, operation.requestKey),
    onSuccess: (response) => {
      for (const detail of response.clips) {
        queryClient.setQueryData(["clip", detail.clip.clip_id], detail);
      }
      setBatchNotice(`已原子提交 ${response.clips.length} 条审核决定。`);
      setFailedBatchOperation(null);
      setSelectedClipIds(new Set());
      setBatchRejectReason("");
      void clipsQuery.refetch();
      void projectQuery.refetch();
    },
    onError: async (_error, operation) => {
      setFailedBatchOperation(operation);
      await Promise.all([clipsQuery.refetch(), projectQuery.refetch()]);
      setBatchNotice("审核状态已重新加载。请确认最新 revision；网络失败可重试同一批次。");
    },
  });
  const submitBatch = (status: "approved" | "rejected") => {
    const body: BatchReviewRequest = {
      items: selectedItems.map(({ clip }) => ({
        clip_id: clip.clip_id,
        expected_revision: clip.edit_plan_revision,
        status,
        ...(status === "rejected" ? { reason: batchRejectReason.trim() } : {}),
      })),
    };
    setBatchNotice(null);
    setFailedBatchOperation(null);
    batchMutation.mutate({
      body,
      requestKey: createIdempotencyKey("batch-review"),
    });
  };
  const allSelectableSelected =
    selectableItems.length > 0 &&
    selectableItems.every(({ clip }) => selectedClipIds.has(clip.clip_id));
  const canBatchApprove =
    selectedItems.length > 0 &&
    selectedItems.every(({ clip }) => clip.allowed_actions.includes("approve"));
  const canBatchReject =
    selectedItems.length > 0 &&
    selectedItems.every(({ clip }) => clip.allowed_actions.includes("reject")) &&
    batchRejectReason.trim().length > 0;
  const failedBatchRetrySafe = useMemo(() => {
    if (!failedBatchOperation || !clipsQuery.data) return false;
    const currentClips = new Map(
      clipsQuery.data.map(({ clip }) => [clip.clip_id, clip] as const),
    );
    return failedBatchOperation.body.items.every((item) => {
      const current = currentClips.get(item.clip_id);
      return (
        current !== undefined &&
        current.edit_plan_revision === item.expected_revision &&
        !dirtyClipIds.has(item.clip_id)
      );
    });
  }, [clipsQuery.data, dirtyClipIds, failedBatchOperation]);

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

      <section className="panel" aria-labelledby="clips-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">人工审核</p>
            <h2 id="clips-title">高光时刻</h2>
          </div>
          <span className="metric">已批准 {approvedCount}</span>
        </div>
        {!contentEnabled ? <EmptyState title="高光时刻尚未可用">等待 Pipeline 完成。</EmptyState> : null}
        {contentEnabled && clipsQuery.isPending ? <LoadingState>正在加载高光时刻…</LoadingState> : null}
        {clipsQuery.isError ? <ErrorState error={clipsQuery.error} onRetry={() => void clipsQuery.refetch()} /> : null}
        {clipsQuery.data?.length === 0 ? <EmptyState title="没有高光时刻" /> : null}
        {clipsQuery.data && clipsQuery.data.length > 0 ? (
          <>
            <div className="batch-review-bar" aria-label="批量审核">
              <label>
                <input
                  type="checkbox"
                  checked={allSelectableSelected}
                  disabled={batchMutation.isPending || selectableItems.length === 0}
                  onChange={(event) =>
                    setSelectedClipIds(
                      event.target.checked
                        ? new Set(selectableItems.map(({ clip }) => clip.clip_id))
                        : new Set(),
                    )
                  }
                />
                全选可审核高光
              </label>
              <strong>已选 {selectedItems.length} 条</strong>
              <button
                type="button"
                className="button button-primary"
                disabled={batchMutation.isPending || !canBatchApprove}
                onClick={() => submitBatch("approved")}
              >
                {batchMutation.isPending ? "批量提交中…" : "批量批准"}
              </button>
              <label className="batch-reason">
                批量拒绝原因
                <input
                  value={batchRejectReason}
                  maxLength={1_000}
                  disabled={batchMutation.isPending}
                  onChange={(event) => setBatchRejectReason(event.target.value)}
                  placeholder="拒绝时必填"
                />
              </label>
              <button
                type="button"
                className="button button-danger-ghost"
                disabled={batchMutation.isPending || !canBatchReject}
                onClick={() => submitBatch("rejected")}
              >
                批量拒绝
              </button>
              {batchNotice ? <p role="status">{batchNotice}</p> : null}
              {batchMutation.isError ? (
                <p className="form-error" role="alert">{errorMessage(batchMutation.error)}</p>
              ) : null}
              {batchMutation.isError && failedBatchOperation ? (
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={batchMutation.isPending || !failedBatchRetrySafe}
                  onClick={() => batchMutation.mutate(failedBatchOperation)}
                >
                  重试同一批次
                </button>
              ) : null}
              {batchMutation.isError && failedBatchOperation && !failedBatchRetrySafe ? (
                <p className="hint" role="status">
                  原批次包含未保存编辑、已变化 revision 或已移除候选，不能直接重试；请先处理编辑并重新选择。
                </p>
              ) : null}
              {dirtyClipIds.size > 0 ? (
                <p className="hint" role="status">
                  有 {dirtyClipIds.size} 个高光存在未保存编辑，已从批量审核中排除。
                </p>
              ) : null}
            </div>
            <ol className="highlight-list" aria-label="高光时刻列表">
              {clipsQuery.data.map((item) => (
                <li key={item.clip.clip_id}>
                  <ClipCard
                    item={item}
                    selected={selectedClipIds.has(item.clip.clip_id)}
                    selectionDisabled={
                      batchMutation.isPending || dirtyClipIds.has(item.clip.clip_id)
                    }
                    openDisabled={batchMutation.isPending}
                    onSelectedChange={(selected) =>
                      setSelectedClipIds((current) => {
                        const next = new Set(current);
                        if (selected) next.add(item.clip.clip_id);
                        else next.delete(item.clip.clip_id);
                        return next;
                      })
                    }
                    onOpen={() => setSelectedClipId(item.clip.clip_id)}
                  />
                </li>
              ))}
            </ol>
          </>
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
          onDirtyChange={handleEditorDirtyChange}
          externalBusy={batchMutation.isPending}
        />
      ) : null}

      <DeliveryPanel api={api} project={project} approvedCount={approvedCount} />
    </main>
  );
}
