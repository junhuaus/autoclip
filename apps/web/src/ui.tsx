import type { ReactNode } from "react";

import { LiveClipApiError, errorMessage } from "./api";

const STATUS_LABELS: Record<string, string> = {
  imported: "已导入",
  processing: "处理中",
  pending_review: "未选中",
  ready_for_delivery: "可交付",
  delivered: "已交付",
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  succeeded: "成功",
  skipped: "已跳过",
  stale: "已失效",
  approved: "已选中",
  rejected: "未选中",
  creating: "创建中",
  draft: "草稿",
  needs_attention: "需要处理",
  editorial_review: "编辑审核",
  changes_requested: "待修改",
  approval: "终审",
  ready_to_publish: "待发布",
  published: "已发布",
  archived: "已归档",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`status status-${status}`} data-status={status}>
      {label ?? statusLabel(status)}
    </span>
  );
}

export function LoadingState({ children = "正在加载…" }: { children?: ReactNode }) {
  return (
    <div className="state-panel" aria-live="polite" aria-busy="true">
      <span className="spinner" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state-panel state-empty">
      <strong>{title}</strong>
      {children ? <div>{children}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const apiError = error instanceof LiveClipApiError ? error : null;
  return (
    <div className="state-panel state-error" role="alert">
      <strong>{errorMessage(error)}</strong>
      {apiError ? (
        <p className="error-meta">
          错误码：{apiError.code}
          {apiError.correlationId ? ` · 请求 ID：${apiError.correlationId}` : ""}
        </p>
      ) : null}
      {onRetry ? (
        <button type="button" className="button button-secondary" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

export function formatMs(value: number): string {
  const totalSeconds = Math.max(0, value) / 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(3).padStart(6, "0")}`;
}
