import { type FormEvent, type ReactNode, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  LiveClipApiClient,
  LiveClipApiError,
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
  DualProfileTextWarning,
  ProjectSnapshot,
  ShareLinkSnapshot,
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

type TextField = "title" | "hook" | "summary";
const TEXT_FIELDS: TextField[] = ["title", "hook", "summary"];
const FIELD_LABELS: Record<TextField, string> = {
  title: "客户标题",
  hook: "高光钩子",
  summary: "内容摘要",
};

interface CheckedText {
  text: DualProfileClipText;
  warnings: DualProfileTextWarning[];
}

/** Warnings from a 409 CUSTOMER_TEXT_WARNING response, located in the submitted text. */
export function warningsFromConflict(
  error: unknown,
  submitted: DualProfileClipText,
): DualProfileTextWarning[] | null {
  if (!(error instanceof LiveClipApiError) || error.code !== "CUSTOMER_TEXT_WARNING") return null;
  return error.details.flatMap((item) => {
    const [field, start, end] = item.location as [TextField, number, number];
    if (!TEXT_FIELDS.includes(field) || typeof start !== "number" || typeof end !== "number") {
      return [];
    }
    const kind = item.type.endsWith(".narration") ? "narration" : "strong";
    return [{ field, kind, start, end, match: submitted[field].slice(start, end), message: "" }];
  });
}

function HighlightedText({ text, warnings }: { text: string; warnings: DualProfileTextWarning[] }) {
  const parts: Array<{ value: string; marked: boolean }> = [];
  let cursor = 0;
  for (const warning of [...warnings].sort((a, b) => a.start - b.start)) {
    if (warning.start < cursor) continue;
    if (warning.start > cursor) parts.push({ value: text.slice(cursor, warning.start), marked: false });
    parts.push({ value: text.slice(warning.start, warning.end), marked: true });
    cursor = warning.end;
  }
  if (cursor < text.length) parts.push({ value: text.slice(cursor), marked: false });
  return (
    <span className="dual-profile-warning-text">
      {parts.map((part, index) =>
        part.marked ? <mark key={index}>{part.value}</mark> : <span key={index}>{part.value}</span>,
      )}
    </span>
  );
}

function FieldWarnings({
  field,
  text,
  warnings,
}: {
  field: TextField;
  text: string;
  warnings: DualProfileTextWarning[];
}) {
  const own = warnings.filter((warning) => warning.field === field);
  if (own.length === 0) return null;
  const strong = own.some((warning) => warning.kind === "strong");
  return (
    <div
      className={`dual-profile-text-warning ${strong ? "is-strong" : "is-narration"}`}
      role="note"
      aria-label={`${FIELD_LABELS[field]}文案提示`}
    >
      <strong>{strong ? "疑似审核备注，请改写" : "叙述收尾方式，建议改写"}</strong>
      <HighlightedText text={text} warnings={own} />
      {own.some((warning) => warning.message) ? (
        <ul>
          {own
            .filter((warning) => warning.message)
            .map((warning) => (
              <li key={`${warning.start}-${warning.kind}`}>{warning.message}</li>
            ))}
        </ul>
      ) : null}
    </div>
  );
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
  onSubmit: (
    overrides: Pick<DualProfileDecisionRequest, "title" | "hook" | "summary">,
    acknowledgeWarnings: boolean,
  ) => Promise<void>;
}) {
  const [draft, setDraft] = useState<DualProfileClipText>(() => ({ ...clip.effective }));
  const [checked, setChecked] = useState<CheckedText>(() => ({
    text: { ...clip.effective },
    warnings: clip.text_warnings,
  }));
  const [keepOriginal, setKeepOriginal] = useState(false);
  const invalid = TEXT_FIELDS.some((field) => draft[field].trim().length === 0);
  // Warnings apply to a field only while its text is still the checked text.
  const visible = checked.warnings.filter(
    (warning) => draft[warning.field].trim() === checked.text[warning.field],
  );
  const hasStrong = visible.some((warning) => warning.kind === "strong");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (invalid) return;
    const submitted: DualProfileClipText = {
      title: draft.title.trim(),
      hook: draft.hook.trim(),
      summary: draft.summary.trim(),
    };
    try {
      await onSubmit(approvalOverrides(clip.original, draft), hasStrong && keepOriginal);
    } catch (error) {
      const warnings = warningsFromConflict(error, submitted);
      if (warnings) {
        setChecked({ text: submitted, warnings });
        setKeepOriginal(false);
      }
    }
  };
  const field = (name: TextField, control: ReactNode) => (
    <div className="dual-profile-field">
      <label>
        {FIELD_LABELS[name]}
        {control}
      </label>
      <FieldWarnings field={name} text={draft[name].trim()} warnings={visible} />
    </div>
  );
  return (
    <form
      className="dual-profile-approval-form"
      aria-label={`批准 ${clip.effective.title}`}
      onSubmit={(event) => void submit(event)}
    >
      <p className="hint">
        客户看到的标题、钩子和摘要；已预填当前生效文案，修改后即为改写，原模型文案保持不变。
      </p>
      {field(
        "title",
        <input
          value={draft.title}
          maxLength={limits.title}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, title: value }));
          }}
        />,
      )}
      {field(
        "hook",
        <textarea
          value={draft.hook}
          maxLength={limits.hook}
          rows={2}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, hook: value }));
          }}
        />,
      )}
      {field(
        "summary",
        <textarea
          value={draft.summary}
          maxLength={limits.summary}
          rows={3}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((current) => ({ ...current, summary: value }));
          }}
        />,
      )}
      {hasStrong ? (
        <label className="dual-profile-keep-original">
          <input
            type="checkbox"
            checked={keepOriginal}
            onChange={(event) => setKeepOriginal(event.currentTarget.checked)}
          />
          仍然保留原文
        </label>
      ) : null}
      <div className="dual-profile-form-actions">
        <button
          type="submit"
          className="button button-primary"
          disabled={busy || invalid || (hasStrong && !keepOriginal)}
        >
          确认批准
        </button>
        <button type="button" className="button button-ghost" disabled={busy} onClick={onCancel}>
          取消
        </button>
      </div>
      {hasStrong && !keepOriginal ? (
        <p className="hint disabled-reason">请改写标记的文字，或勾选“仍然保留原文”。</p>
      ) : null}
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
  onDecide: (body: DualProfileDecisionRequest) => Promise<void>;
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
                  void onDecide({
                    action: event.currentTarget.checked ? "select" : "deselect",
                  }).catch(() => undefined)
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
          {clip.text_warnings.length > 0 ? (
            <p
              className={`dual-profile-warning-badge ${clip.text_warnings.some((warning) => warning.kind === "strong") ? "is-strong" : "is-narration"}`}
            >
              {clip.text_warnings.some((warning) => warning.kind === "strong")
                ? "文案含疑似审核备注，批准前请改写"
                : "文案叙述了收尾方式，建议改写"}
            </p>
          ) : null}
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
                onClick={() => void onDecide({ action: "reject" }).catch(() => undefined)}
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
              onSubmit={async (overrides, acknowledgeWarnings) => {
                await onDecide({
                  action: "approve",
                  ...overrides,
                  ...(acknowledgeWarnings ? { acknowledge_warnings: true } : {}),
                });
                setApproving(false);
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
                      onDecide={async (body) => {
                        await decisionMutation.mutateAsync({ clipId: clip.import_clip_id, body });
                      }}
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

const SHARE_STATUS_LABELS: Record<ShareLinkSnapshot["status"], string> = {
  active: "有效",
  expired: "已过期",
  revoked: "已撤销",
};
const SHARE_DAY_OPTIONS = [1, 3, 7, 14, 30];

export function ShareLinksPanel({
  api,
  project,
  delivery,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  delivery: CustomerDeliverySnapshot;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["share-links", project.project_id, delivery.delivery_id];
  const [days, setDays] = useState(7);
  const [created, setCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const canDeliver = project.allowed_actions.includes("deliver");
  const linksQuery = useQuery({
    queryKey,
    queryFn: () => api.listShareLinks(project.project_id, delivery.delivery_id),
  });
  const createMutation = useMutation({
    mutationFn: () => api.createShareLink(project.project_id, delivery.delivery_id, days),
    onSuccess: (result) => {
      setCreated(result.url);
      setCopied(false);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const revokeMutation = useMutation({
    mutationFn: (linkId: string) => api.revokeShareLink(project.project_id, linkId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });
  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="share-links" aria-label={`${delivery.delivery_version} 分享链接`}>
      {canDeliver ? (
        <div className="share-link-create">
          <label>
            有效期
            <select value={days} onChange={(event) => setDays(Number(event.currentTarget.value))}>
              {SHARE_DAY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value} 天
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button button-secondary"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建分享链接
          </button>
        </div>
      ) : null}
      {created ? (
        <div className="share-link-created" role="status">
          <label>
            分享链接（只显示这一次）
            <input readOnly value={created} onFocus={(event) => event.currentTarget.select()} />
          </label>
          <button type="button" className="button button-primary" onClick={() => void copy()}>
            {copied ? "已复制" : "复制"}
          </button>
          <p className="hint">链接只显示这一次，请立即复制保存；关闭后无法再次查看。</p>
          <p className="hint share-lan-warning">
            仅限同一局域网（Wi-Fi）内的设备访问，传输未加密，请勿在公共 Wi-Fi 下使用；不在同一网络的客户请发送离线 ZIP。
          </p>
          <button type="button" className="button button-ghost" onClick={() => setCreated(null)}>
            我已保存，隐藏链接
          </button>
        </div>
      ) : null}
      {createMutation.isError ? (
        <p className="form-error" role="alert">
          {errorMessage(createMutation.error)}
        </p>
      ) : null}
      {linksQuery.data && linksQuery.data.length > 0 ? (
        <ul className="share-link-list" aria-label={`${delivery.delivery_version} 分享链接列表`}>
          {linksQuery.data.map((link) => (
            <li key={link.link_id}>
              <StatusBadge
                status={link.status === "active" ? "succeeded" : link.status === "revoked" ? "failed" : "stale"}
                label={SHARE_STATUS_LABELS[link.status]}
              />
              <span>
                到期 {new Date(link.expires_at).toLocaleString("zh-CN")} · {link.created_by} 创建 · 访问{" "}
                {link.view_count} 次 · 下载 {link.download_count} 次
              </span>
              {canDeliver && link.status === "active" ? (
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={revokeMutation.isPending}
                  onClick={() => revokeMutation.mutate(link.link_id)}
                >
                  撤销
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
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
  const flagged = selected.filter((clip) => clip.text_warnings.length > 0);
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
        {flagged.length > 0 ? (
          <div className="dual-profile-text-warning is-narration" role="note" aria-label="交付文案提示">
            <strong>以下切片的客户文案仍有提示（仅供参考，不阻止生成）：</strong>
            <ul>
              {flagged.map((clip) => (
                <li key={clip.import_clip_id}>
                  {clip.effective.title} ·{" "}
                  {clip.text_warnings.some((warning) => warning.kind === "strong")
                    ? "疑似审核备注"
                    : "叙述收尾方式"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
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
              {delivery.status === "succeeded" ? (
                <ShareLinksPanel api={api} project={project} delivery={delivery} />
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
