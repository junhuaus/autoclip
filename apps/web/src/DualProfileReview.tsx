import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  LiveClipApiClient,
  createIdempotencyKey,
  errorMessage,
  signedUrlRefreshInterval,
} from "./api";
import { EmptyState, ErrorState, LoadingState, StatusBadge, formatMs } from "./ui";
import type {
  CustomerDeliverySnapshot,
  DualProfileClipText,
  DualProfileDecisionAction,
  DualProfileDecisionRequest,
  DualProfileReviewClip,
  DualProfileReviewResponse,
  DualProfileReviewView,
  ProjectSnapshot,
} from "./types";

const DECISION_LABELS: Record<DualProfileDecisionAction, string> = {
  approve: "批准",
  reject: "不通过",
  select: "选入交付",
  deselect: "取消选入",
};

const REVIEW_STATE_LABELS: Record<DualProfileReviewClip["review_state"], string> = {
  pending: "待审核",
  approved: "已批准",
  rejected: "不通过",
};

function durationLabel(durationMs: number): string {
  const totalSeconds = Math.round(durationMs / 1_000);
  const minutes = Math.floor(totalSeconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

/** Only fields that differ from the model original are sent as overrides. */
export function approvalOverrides(
  original: DualProfileClipText,
  draft: DualProfileClipText,
): Pick<DualProfileDecisionRequest, "title" | "hook" | "summary"> {
  const result: Pick<DualProfileDecisionRequest, "title" | "hook" | "summary"> = {};
  for (const field of ["title", "hook", "summary"] as const) {
    const value = draft[field].trim();
    if (value !== original[field]) result[field] = value;
  }
  return result;
}

function ApprovalForm({
  clip,
  limits,
  busy,
  onCancel,
  onSubmit,
}: {
  clip: DualProfileReviewClip;
  limits: DualProfileReviewView["text_limits"];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (overrides: Pick<DualProfileDecisionRequest, "title" | "hook" | "summary">) => void;
}) {
  const [draft, setDraft] = useState<DualProfileClipText>(() => ({ ...clip.effective }));
  const invalid = (["title", "hook", "summary"] as const).some(
    (field) => draft[field].trim().length === 0,
  );
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!invalid) onSubmit(approvalOverrides(clip.original, draft));
  };
  return (
    <form
      className="dual-profile-approval-form"
      aria-label={`批准 ${clip.effective.title}`}
      onSubmit={submit}
    >
      <p className="hint">
        客户看到的标题、钩子和摘要；已预填当前生效文案，修改后即为改写，原模型文案保持不变。
      </p>
      <label>
        客户标题
        <input
          value={draft.title}
          maxLength={limits.title}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, title: value }));
          }}
        />
      </label>
      <label>
        高光钩子
        <textarea
          value={draft.hook}
          maxLength={limits.hook}
          rows={2}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, hook: value }));
          }}
        />
      </label>
      <label>
        内容摘要
        <textarea
          value={draft.summary}
          maxLength={limits.summary}
          rows={3}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, summary: value }));
          }}
        />
      </label>
      <div className="dual-profile-form-actions">
        <button type="submit" className="button button-primary" disabled={busy || invalid}>
          确认批准
        </button>
        <button type="button" className="button button-ghost" disabled={busy} onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}

export function ImportedClipCard({
  clip,
  videoUrl,
  subtitleUrl,
  limits,
  canReview,
  canDeliver,
  busy,
  onDecide,
}: {
  clip: DualProfileReviewClip;
  videoUrl: string | undefined;
  subtitleUrl: string | undefined;
  limits: DualProfileReviewView["text_limits"];
  canReview: boolean;
  canDeliver: boolean;
  busy: boolean;
  onDecide: (body: DualProfileDecisionRequest) => void;
}) {
  const [approving, setApproving] = useState(false);
  const titleId = `dual-clip-title-${clip.import_clip_id}`;
  const selectionDisabled = !canDeliver || !clip.deliverable || busy;
  const selectionHint = !clip.deliverable
    ? clip.review_state === "rejected"
      ? "不通过的切片不能选入交付"
      : "批准后才能选入交付"
    : !canDeliver
      ? "当前角色不能选择交付内容"
      : null;
  const risks = [...clip.risk_tags, ...clip.quality_flags];
  return (
    <article
      className={`clip-card ${clip.selected_for_delivery ? "clip-selected" : ""}`}
      aria-labelledby={titleId}
    >
      <div className="clip-card-main">
        <div className="clip-card-media">
          {videoUrl ? (
            <video
              controls
              preload="metadata"
              src={videoUrl}
              aria-label={`${clip.effective.title} 预览`}
            >
              浏览器不支持 HTML5 视频播放。
            </video>
          ) : (
            <div className="video-placeholder">暂无可播放视频</div>
          )}
        </div>
        <div className="clip-card-body">
          <div className="section-heading compact">
            <label className="clip-select clip-delivery-select">
              <input
                type="checkbox"
                checked={clip.selected_for_delivery}
                disabled={selectionDisabled}
                onChange={(event) =>
                  onDecide({ action: event.currentTarget.checked ? "select" : "deselect" })
                }
              />
              选入交付
            </label>
            <StatusBadge
              status={clip.routed_status === "selected" ? "approved" : "pending_review"}
              label={clip.routed_status === "selected" ? "自动入选" : "需人工审核"}
            />
            <StatusBadge
              status={clip.review_state === "rejected" ? "rejected" : clip.review_state === "approved" ? "approved" : "pending_review"}
              label={REVIEW_STATE_LABELS[clip.review_state]}
            />
          </div>
          {selectionHint ? <p className="hint dual-profile-select-hint">{selectionHint}</p> : null}
          <h3 id={titleId}>
            {clip.effective.title}
            {clip.has_override ? <span className="dual-profile-override-tag">已改写</span> : null}
          </h3>
          <p className="clip-time">
            {formatMs(clip.start_ms)}–{formatMs(clip.end_ms)} · 时长 {durationLabel(clip.duration_ms)}
          </p>
          <section className="clip-highlight-sentence" aria-label={`${clip.effective.title} 高光语句`}>
            <div className="metadata-heading">
              <h4>高光语句</h4>
              <span>客户可见</span>
            </div>
            <blockquote>{clip.effective.hook}</blockquote>
          </section>
          <p className="dual-profile-summary">{clip.effective.summary}</p>
          <div className="badge-row">
            <span className="metric">评分 {clip.score.toFixed(1)}</span>
            {subtitleUrl ? (
              <a className="button button-ghost" href={subtitleUrl}>
                字幕 SRT
              </a>
            ) : null}
          </div>
          {risks.length > 0 ? (
            <ul className="risk-list" aria-label={`${clip.effective.title} 风险与质量标记`}>
              {risks.map((value) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          ) : null}
          <p className="hint">审核理由（内部）：{clip.review_reason}</p>
          {canReview && !approving ? (
            <div className="clip-card-actions">
              <button
                type="button"
                className="button button-primary"
                disabled={busy}
                onClick={() => setApproving(true)}
              >
                批准
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={busy || clip.review_state === "rejected"}
                onClick={() => onDecide({ action: "reject" })}
              >
                不通过
              </button>
            </div>
          ) : null}
          {canReview && approving ? (
            <ApprovalForm
              clip={clip}
              limits={limits}
              busy={busy}
              onCancel={() => setApproving(false)}
              onSubmit={(overrides) => {
                setApproving(false);
                onDecide({ action: "approve", ...overrides });
              }}
            />
          ) : null}
          {clip.decisions.length > 0 ? (
            <details className="dual-profile-history">
              <summary>审核记录（{clip.decisions.length}）</summary>
              <ol>
                {clip.decisions.map((decision) => (
                  <li key={decision.sequence}>
                    #{decision.sequence} {DECISION_LABELS[decision.action]} ·{" "}
                    {decision.actor_display_name} ·{" "}
                    <time dateTime={decision.decided_at}>
                      {new Date(decision.decided_at).toLocaleString("zh-CN")}
                    </time>
                    {decision.title_override || decision.hook_override || decision.summary_override
                      ? " · 含文案改写"
                      : ""}
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function DualProfileReviewSection({
  api,
  project,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["dual-profile-review", project.project_id];
  const reviewQuery = useQuery({
    queryKey,
    queryFn: () => api.getDualProfileReview(project.project_id),
    refetchInterval: (query) =>
      signedUrlRefreshInterval(Object.values(query.state.data?.asset_urls ?? {})),
  });
  const [pendingClipId, setPendingClipId] = useState<string | null>(null);
  const decisionMutation = useMutation({
    mutationFn: ({ clipId, body }: { clipId: string; body: DualProfileDecisionRequest }) =>
      api.decideDualProfileClip(project.project_id, clipId, body),
    onMutate: ({ clipId }) => setPendingClipId(clipId),
    onSuccess: (response: DualProfileReviewResponse) => {
      queryClient.setQueryData(queryKey, response);
    },
    onError: () => {
      void reviewQuery.refetch();
    },
    onSettled: () => setPendingClipId(null),
  });
  const canReview = project.allowed_actions.includes("review_clip");
  const canDeliver = project.allowed_actions.includes("deliver");

  if (reviewQuery.isPending) return <LoadingState>正在加载双轨结果…</LoadingState>;
  if (reviewQuery.isError) {
    return <ErrorState error={reviewQuery.error} onRetry={() => void reviewQuery.refetch()} />;
  }
  const { review, asset_urls: assetUrls } = reviewQuery.data;
  return (
    <>
      <section className="panel dual-profile-review" aria-labelledby="dual-profile-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">双轨导入 · 内部审核</p>
            <h2 id="dual-profile-title">双轨结果审核</h2>
          </div>
          <span className="metric">
            可交付 {review.deliverable_count} · 已选 {review.selected_count}
          </span>
        </div>
        <p className="hint">
          来源 {review.source_filename} · 快照 {review.snapshot} · {review.imported_by} 导入。需人工审核的切片批准后才能选入交付；客户只会看到生效的标题、钩子、摘要、视频和字幕。
        </p>
        {decisionMutation.isError ? (
          <p className="form-error" role="alert">
            {errorMessage(decisionMutation.error)}
          </p>
        ) : null}
        {review.groups.map((group) => (
          <section
            key={group.profile}
            className="dual-profile-group"
            aria-labelledby={`dual-group-${group.profile}`}
          >
            <h3 id={`dual-group-${group.profile}`}>
              {group.label}（{group.clips.length}）
            </h3>
            {group.clips.length === 0 ? (
              <EmptyState title={`没有${group.label}`} />
            ) : (
              <ol className="highlight-list" aria-label={`${group.label}列表`}>
                {group.clips.map((clip) => (
                  <li key={clip.import_clip_id}>
                    <ImportedClipCard
                      clip={clip}
                      videoUrl={assetUrls[clip.video_asset_id]}
                      subtitleUrl={assetUrls[clip.subtitle_asset_id]}
                      limits={review.text_limits}
                      canReview={canReview}
                      canDeliver={canDeliver}
                      busy={decisionMutation.isPending && pendingClipId === clip.import_clip_id}
                      onDecide={(body) =>
                        decisionMutation.mutate({ clipId: clip.import_clip_id, body })
                      }
                    />
                  </li>
                ))}
              </ol>
            )}
          </section>
        ))}
      </section>
      <CustomerDeliveryPanel api={api} project={project} review={review} />
    </>
  );
}

const DELIVERY_STATUS_LABELS: Record<CustomerDeliverySnapshot["status"], string> = {
  queued: "排队中",
  creating: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
};

export function CustomerDeliveryPanel({
  api,
  project,
  review,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  review: DualProfileReviewView;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["customer-deliveries", project.project_id];
  const [title, setTitle] = useState(() => `${project.name} 精选`.slice(0, 80));
  const [requestKey, setRequestKey] = useState(() => createIdempotencyKey("customer-delivery"));
  const deliveriesQuery = useQuery({
    queryKey,
    queryFn: () => api.listCustomerDeliveries(project.project_id),
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      if (items.some(({ delivery }) => delivery.status === "queued" || delivery.status === "creating")) {
        return 1_000;
      }
      return signedUrlRefreshInterval(items.map((item) => item.download_url));
    },
  });
  const selected = review.groups.flatMap((group) =>
    group.clips.filter((clip) => clip.selected_for_delivery),
  );
  const createMutation = useMutation({
    mutationFn: () =>
      api.createCustomerDelivery(
        project.project_id,
        { title: title.trim(), expected_clip_ids: selected.map((clip) => clip.import_clip_id) },
        requestKey,
      ),
    onSuccess: () => {
      setRequestKey(createIdempotencyKey("customer-delivery"));
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const canDeliver = project.allowed_actions.includes("deliver");
  const trimmed = title.trim();
  const disabledReason = !canDeliver
    ? "当前角色不能生成客户交付包"
    : selected.length === 0
      ? "请先在上方选入至少一条可交付的切片"
      : trimmed.length === 0
        ? "请填写交付标题"
        : null;
  return (
    <section className="panel" aria-labelledby="customer-delivery-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">客户交付</p>
          <h2 id="customer-delivery-title">客户交付版本</h2>
        </div>
        <span className="metric">已选 {selected.length}</span>
      </div>
      <form
        className="customer-delivery-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!disabledReason) createMutation.mutate();
        }}
      >
        <label>
          交付标题（客户可见）
          <input
            value={title}
            maxLength={80}
            onChange={(event) => setTitle(event.currentTarget.value)}
          />
        </label>
        <div className="customer-delivery-preview" aria-label="将包含的切片">
          <p className="hint">将包含 {selected.length} 条（按生效标题）：</p>
          {selected.length > 0 ? (
            <ol>
              {selected.map((clip) => (
                <li key={clip.import_clip_id}>
                  {clip.profile === "short_highlight" ? "短片" : "小课"} · {clip.effective.title}
                </li>
              ))}
            </ol>
          ) : null}
        </div>
        <button
          type="submit"
          className="button button-primary"
          disabled={disabledReason !== null || createMutation.isPending}
        >
          {createMutation.isPending ? "正在创建…" : "生成交付包"}
        </button>
        {disabledReason ? <p className="hint disabled-reason">{disabledReason}</p> : null}
        {createMutation.isError ? (
          <p className="form-error" role="alert">
            {errorMessage(createMutation.error)}
          </p>
        ) : null}
      </form>
      {deliveriesQuery.isError ? (
        <ErrorState error={deliveriesQuery.error} onRetry={() => void deliveriesQuery.refetch()} />
      ) : null}
      {deliveriesQuery.data && deliveriesQuery.data.length === 0 ? (
        <p className="hint">还没有客户交付版本。</p>
      ) : null}
      {deliveriesQuery.data && deliveriesQuery.data.length > 0 ? (
        <ul className="delivery-list" aria-label="客户交付版本列表">
          {deliveriesQuery.data.map(({ delivery, download_url: downloadUrl }) => (
            <li key={delivery.delivery_id} className="delivery-row">
              <strong>{delivery.delivery_version}</strong>
              <span>{delivery.title}</span>
              <StatusBadge
                status={delivery.status === "succeeded" ? "succeeded" : delivery.status === "failed" ? "failed" : "queued"}
                label={DELIVERY_STATUS_LABELS[delivery.status]}
              />
              <span>
                {delivery.clip_count} 条 · {delivery.created_by} ·{" "}
                {new Date(delivery.created_at).toLocaleString("zh-CN")}
              </span>
              {downloadUrl ? (
                <a className="button button-secondary" href={downloadUrl}>
                  下载 ZIP
                </a>
              ) : null}
              {delivery.status === "failed" && delivery.safe_error_message ? (
                <span className="hint">{delivery.safe_error_message}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function DualProfileImportDialog({
  api,
  onClose,
  onImported,
}: {
  api: LiveClipApiClient;
  onClose: () => void;
  onImported: (projectId: string) => void;
}) {
  const importMutation = useMutation({
    mutationFn: (body: { run_dir: string; transcript_path: string; project_name?: string }) =>
      api.importDualProfileRun(body),
    onSuccess: (result) => onImported(result.project_id),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const runDir = String(form.get("run_dir") ?? "").trim();
    const transcriptPath = String(form.get("transcript_path") ?? "").trim();
    const projectName = String(form.get("project_name") ?? "").trim();
    importMutation.mutate({
      run_dir: runDir,
      transcript_path: transcriptPath,
      ...(projectName ? { project_name: projectName } : {}),
    });
  };
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !importMutation.isPending) onClose();
      }}
    >
      <section
        className="panel create-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dual-import-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">导入双轨结果</p>
            <h2 id="dual-import-title">导入已完成的双轨切分结果</h2>
          </div>
          <button
            type="button"
            className="button button-ghost"
            disabled={importMutation.isPending}
            onClick={onClose}
          >
            取消
          </button>
        </div>
        <form className="create-form" onSubmit={submit}>
          <label>
            结果目录（服务器本机路径）
            <input
              name="run_dir"
              type="text"
              required
              maxLength={4_096}
              placeholder="data/evaluations/dual-profile-benchmark-…"
              autoFocus
            />
          </label>
          <label>
            转写字幕 SRT 路径
            <input name="transcript_path" type="text" required maxLength={4_096} placeholder="input/live-transcript.srt" />
          </label>
          <label>
            项目名称（可选）
            <input name="project_name" type="text" maxLength={200} />
          </label>
          <p className="hint">
            只导入已渲染并通过自动检查的切片；路径必须位于允许的导入目录内，导入会复制视频与字幕，不会改动原结果。
          </p>
          <button type="submit" className="button button-primary" disabled={importMutation.isPending}>
            {importMutation.isPending ? "正在导入…" : "导入并开始审核"}
          </button>
          {importMutation.isError ? (
            <p className="form-error" role="alert">
              {errorMessage(importMutation.error)}
            </p>
          ) : null}
        </form>
      </section>
    </div>
  );
}
