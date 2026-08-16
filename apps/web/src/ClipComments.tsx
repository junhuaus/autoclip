import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  LiveClipApiClient,
  createIdempotencyKey,
  errorMessage,
} from "./api";
import type {
  ClipCommentReplyRequest,
  ClipCommentStatusRequest,
  ClipCommentThread,
  ClipCommentThreadCreateRequest,
  WorkspaceMember,
} from "./types";
import { EmptyState, ErrorState, LoadingState, formatMs } from "./ui";

interface ClipCommentsProps {
  api: LiveClipApiClient;
  clipId: string;
  currentRevision: number;
  durationMs: number;
  members: WorkspaceMember[];
  canCreate: boolean;
  createDisabledReason?: string | null;
  getCurrentTimeMs: () => number | null;
  onSeek: (clipTimeMs: number) => void;
}

interface PendingCreate {
  body: ClipCommentThreadCreateRequest;
  requestKey: string;
}

interface PendingReply {
  body: ClipCommentReplyRequest;
  requestKey: string;
}

interface PendingStatus {
  body: ClipCommentStatusRequest;
  requestKey: string;
}

function selectedValues(element: HTMLSelectElement): string[] {
  return Array.from(element.selectedOptions, (option) => option.value);
}

function displayTimestamp(value: string): string {
  const instant = new Date(value);
  if (Number.isNaN(instant.valueOf())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(instant);
}

function ThreadCard({
  api,
  thread,
  members,
  onUpdated,
  onSeek,
}: {
  api: LiveClipApiClient;
  thread: ClipCommentThread;
  members: WorkspaceMember[];
  onUpdated: () => void;
  onSeek: (clipTimeMs: number) => void;
}) {
  const [replyBody, setReplyBody] = useState("");
  const [mentionIds, setMentionIds] = useState<string[]>([]);
  const [failedReply, setFailedReply] = useState<PendingReply | null>(null);
  const [failedStatus, setFailedStatus] = useState<PendingStatus | null>(null);
  const replyMutation = useMutation({
    mutationFn: (pending: PendingReply) =>
      api.replyToClipCommentThread(thread.thread_id, pending.body, pending.requestKey),
    onSuccess: () => {
      setReplyBody("");
      setMentionIds([]);
      setFailedReply(null);
      onUpdated();
    },
    onError: (_error, pending) => {
      setFailedReply(pending);
      onUpdated();
    },
  });
  const statusMutation = useMutation({
    mutationFn: (pending: PendingStatus) =>
      api.updateClipCommentThreadStatus(
        thread.thread_id,
        pending.body,
        pending.requestKey,
      ),
    onSuccess: () => {
      setFailedStatus(null);
      onUpdated();
    },
    onError: (_error, pending) => {
      setFailedStatus(pending);
      onUpdated();
    },
  });
  const busy = replyMutation.isPending || statusMutation.isPending;
  const canReply = thread.allowed_actions.includes("reply");
  const canResolve = thread.allowed_actions.includes("resolve");
  const canReopen = thread.allowed_actions.includes("reopen");

  const submitReply = (pending?: PendingReply) => {
    const operation = pending ?? {
      body: { body: replyBody.trim(), mentioned_user_ids: mentionIds },
      requestKey: createIdempotencyKey("comment-reply"),
    };
    if (!operation.body.body) return;
    setFailedReply(operation);
    replyMutation.mutate(operation);
  };

  const submitStatus = (status: "open" | "resolved", pending?: PendingStatus) => {
    statusMutation.mutate(
      pending ?? {
        body: { expected_thread_version: thread.version, status },
        requestKey: createIdempotencyKey(`comment-${status}`),
      },
    );
  };

  return (
    <article className={`comment-thread comment-thread-${thread.status}`}>
      <header>
        <div className="comment-thread-time">
          <button
            type="button"
            className="timecode-button"
            disabled={thread.current_clip_time_ms === null}
            onClick={() => {
              if (thread.current_clip_time_ms !== null) onSeek(thread.current_clip_time_ms);
            }}
          >
            {formatMs(thread.clip_time_ms)}
          </button>
          <span className={thread.is_current_revision ? "revision-current" : "revision-history"}>
            {thread.is_current_revision
              ? `当前 r${thread.edit_plan_revision}`
              : `历史 r${thread.edit_plan_revision}`}
          </span>
          <span className={`comment-status comment-status-${thread.status}`}>
            {thread.status === "open" ? "待处理" : "已解决"}
          </span>
        </div>
        <span className="hint">源视频 {formatMs(thread.source_time_ms)}</span>
      </header>
      {!thread.is_current_revision ? (
        <p className="hint revision-note">
          此批注保留在创建时的 revision；
          {thread.current_clip_time_ms === null
            ? "当前切片已不包含这个源时间点。"
            : `当前切片中的位置为 ${formatMs(thread.current_clip_time_ms)}。`}
        </p>
      ) : null}
      <ol className="comment-message-list" aria-label={`时间点 ${formatMs(thread.clip_time_ms)} 的讨论`}>
        {thread.comments.map((comment) => (
          <li key={comment.comment_id}>
            <div className="comment-author-row">
              <strong>{comment.author.display_name}</strong>
              <span>@{comment.author.username}</span>
              <time dateTime={comment.created_at}>{displayTimestamp(comment.created_at)}</time>
            </div>
            <p>{comment.body}</p>
            {comment.mentions.length > 0 ? (
              <div className="comment-mentions" aria-label="提醒成员">
                {comment.mentions.map((mention) => (
                  <span key={`${comment.comment_id}-${mention.username}`}>
                    @{mention.display_name}
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      {canReply ? (
        <form
          className="comment-reply-form"
          onSubmit={(event) => {
            event.preventDefault();
            submitReply();
          }}
        >
          <label>
            回复
            <textarea
              rows={2}
              maxLength={2_000}
              required
              disabled={busy}
              value={replyBody}
              onChange={(event) => setReplyBody(event.currentTarget.value)}
              placeholder="说明需要怎样调整"
            />
          </label>
          <label>
            提醒项目成员（可多选）
            <select
              multiple
              disabled={busy}
              value={mentionIds}
              onChange={(event) => setMentionIds(selectedValues(event.currentTarget))}
            >
              {members.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.display_name}（@{member.username}）
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              type="submit"
              className="button button-secondary"
              disabled={busy || !replyBody.trim()}
            >
              {replyMutation.isPending ? "回复中…" : "回复"}
            </button>
            {replyMutation.isError && failedReply ? (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={() => submitReply(failedReply)}
              >
                重试同一回复
              </button>
            ) : null}
          </div>
        </form>
      ) : null}
      <div className="comment-thread-actions">
        {canResolve ? (
          <button
            type="button"
            className="button button-success"
            disabled={busy}
            onClick={() => submitStatus("resolved")}
          >
            标记已解决
          </button>
        ) : null}
        {canReopen ? (
          <button
            type="button"
            className="button button-secondary"
            disabled={busy}
            onClick={() => submitStatus("open")}
          >
            重新打开
          </button>
        ) : null}
        {!canReply && !canResolve && !canReopen ? (
          <span className="hint">当前权限或项目状态仅允许查看。</span>
        ) : null}
        {statusMutation.isError && failedStatus ? (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => submitStatus(failedStatus.body.status, failedStatus)}
          >
            重试状态操作
          </button>
        ) : null}
      </div>
      {replyMutation.isError ? (
        <p className="form-error" role="alert">{errorMessage(replyMutation.error)}</p>
      ) : null}
      {statusMutation.isError ? (
        <p className="form-error" role="alert">{errorMessage(statusMutation.error)}</p>
      ) : null}
    </article>
  );
}

export function ClipComments({
  api,
  clipId,
  currentRevision,
  durationMs,
  members,
  canCreate,
  createDisabledReason = null,
  getCurrentTimeMs,
  onSeek,
}: ClipCommentsProps) {
  const queryClient = useQueryClient();
  const [showHistorical, setShowHistorical] = useState(true);
  const [showResolved, setShowResolved] = useState(true);
  const [body, setBody] = useState("");
  const [timeSeconds, setTimeSeconds] = useState("0.000");
  const [mentionIds, setMentionIds] = useState<string[]>([]);
  const [inputError, setInputError] = useState<string | null>(null);
  const [failedCreate, setFailedCreate] = useState<PendingCreate | null>(null);
  const draftTarget = useRef({ clipId, revision: currentRevision });
  const commentsQuery = useInfiniteQuery({
    queryKey: [
      "clip-comments",
      clipId,
      currentRevision,
      showHistorical ? "all" : "current",
      showResolved ? "all" : "open",
    ],
    queryFn: ({ pageParam }) =>
      api.listClipCommentThreads(clipId, {
        revision: showHistorical ? "all" : "current",
        status: showResolved ? "all" : "open",
        limit: 100,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
  });
  const invalidate = () => {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["clip-comments", clipId] }),
      queryClient.invalidateQueries({ queryKey: ["project-activity"] }),
    ]);
  };
  const createMutation = useMutation({
    mutationFn: (pending: PendingCreate) =>
      api.createClipCommentThread(clipId, pending.body, pending.requestKey),
    onSuccess: () => {
      setBody("");
      setTimeSeconds("0.000");
      setMentionIds([]);
      setInputError(null);
      setFailedCreate(null);
      invalidate();
    },
    onError: (_error, pending) => {
      setFailedCreate(pending);
      invalidate();
    },
  });
  useEffect(() => {
    if (
      draftTarget.current.clipId === clipId &&
      draftTarget.current.revision === currentRevision
    ) return;
    const hadDraft = Boolean(
      body.trim() ||
      mentionIds.length > 0 ||
      failedCreate,
    );
    const clipChanged = draftTarget.current.clipId !== clipId;
    draftTarget.current = { clipId, revision: currentRevision };
    setBody("");
    setTimeSeconds("0.000");
    setMentionIds([]);
    setFailedCreate(null);
    createMutation.reset();
    setInputError(
      hadDraft
        ? clipChanged
          ? "已切换高光时刻；上一条高光的批注草稿已清除，请重新选择时间点。"
          : `切片已更新为 revision ${currentRevision}；旧 revision 的批注草稿已清除，请重新选择时间点。`
        : null,
    );
    // The target transition is the only trigger; the captured values describe the old draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId, currentRevision]);
  const threads = useMemo(() => {
    const seen = new Set<string>();
    return (commentsQuery.data?.pages ?? []).flatMap((page) =>
      page.threads.filter((thread) => {
        if (seen.has(thread.thread_id)) return false;
        seen.add(thread.thread_id);
        return true;
      }),
    );
  }, [commentsQuery.data]);
  const openCount = useMemo(
    () => threads.filter((thread) => thread.status === "open").length,
    [threads],
  );
  const totalCount = commentsQuery.data?.pages[0]?.total_count ?? 0;

  const submitCreate = (pending?: PendingCreate) => {
    if (pending) {
      createMutation.mutate(pending);
      return;
    }
    const seconds = Number(timeSeconds);
    const clipTimeMs = Math.round(seconds * 1_000);
    if (
      !body.trim() ||
      !Number.isFinite(seconds) ||
      !Number.isSafeInteger(clipTimeMs) ||
      clipTimeMs < 0 ||
      clipTimeMs > durationMs
    ) {
      setInputError("请填写有效批注，并确保时间点位于当前切片内。");
      return;
    }
    setInputError(null);
    const operation: PendingCreate = {
      body: {
        expected_revision: currentRevision,
        clip_time_ms: clipTimeMs,
        body: body.trim(),
        mentioned_user_ids: mentionIds,
      },
      requestKey: createIdempotencyKey("comment-thread"),
    };
    setFailedCreate(operation);
    createMutation.mutate(operation);
  };

  return (
    <section className="clip-comments" aria-labelledby={`clip-comments-${clipId}`}>
      <div className="metadata-heading">
        <div>
          <h3 id={`clip-comments-${clipId}`}>协作批注</h3>
          <p className="hint">批注固定在已保存 revision 和视频时间点，不会改动审核状态。</p>
        </div>
        <span>{openCount} 条待处理</span>
      </div>
      <div className="comment-filters" aria-label="批注筛选">
        <label>
          <input
            type="checkbox"
            checked={showHistorical}
            onChange={(event) => setShowHistorical(event.currentTarget.checked)}
          />
          显示历史 revision
        </label>
        <label>
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(event) => setShowResolved(event.currentTarget.checked)}
          />
          显示已解决
        </label>
      </div>

      {canCreate ? (
        <form
          className="comment-create-form"
          onSubmit={(event) => {
            event.preventDefault();
            submitCreate();
          }}
        >
          <div className="comment-time-entry">
            <label>
              片段时间（秒）
              <input
                type="number"
                min="0"
                max={(durationMs / 1_000).toFixed(3)}
                step="0.001"
                required
                disabled={createMutation.isPending}
                value={timeSeconds}
                onChange={(event) => setTimeSeconds(event.currentTarget.value)}
              />
            </label>
            <button
              type="button"
              className="button button-secondary"
              disabled={createMutation.isPending}
              onClick={() => {
                const current = getCurrentTimeMs();
                if (current === null) {
                  setInputError("当前没有可读取时间点的视频。");
                  return;
                }
                setInputError(null);
                setTimeSeconds((current / 1_000).toFixed(3));
              }}
            >
              使用播放器当前时间
            </button>
          </div>
          <label>
            批注内容
            <textarea
              rows={3}
              maxLength={2_000}
              required
              disabled={createMutation.isPending}
              value={body}
              onChange={(event) => setBody(event.currentTarget.value)}
              placeholder="例如：这里字幕太长，请压缩成两行"
            />
          </label>
          <label>
            提醒项目成员（可多选）
            <select
              multiple
              disabled={createMutation.isPending}
              value={mentionIds}
              onChange={(event) => setMentionIds(selectedValues(event.currentTarget))}
            >
              {members.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.display_name}（@{member.username}）
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              type="submit"
              className="button button-primary"
              disabled={createMutation.isPending || !body.trim()}
            >
              {createMutation.isPending ? "提交中…" : "添加时间点批注"}
            </button>
            {createMutation.isError && failedCreate ? (
              <button
                type="button"
                className="button button-ghost"
                disabled={createMutation.isPending}
                onClick={() => submitCreate(failedCreate)}
              >
                重试同一批注
              </button>
            ) : null}
          </div>
        </form>
      ) : (
        <p className="hint disabled-reason">
          {createDisabledReason ?? "当前权限或项目状态仅允许查看批注。"}
        </p>
      )}
      {inputError ? <p className="form-error" role="alert">{inputError}</p> : null}
      {createMutation.isError ? (
        <p className="form-error" role="alert">{errorMessage(createMutation.error)}</p>
      ) : null}

      {commentsQuery.isPending ? <LoadingState>正在加载协作批注…</LoadingState> : null}
      {commentsQuery.isError ? (
        <ErrorState error={commentsQuery.error} onRetry={() => void commentsQuery.refetch()} />
      ) : null}
      {commentsQuery.data && threads.length === 0 ? (
        <EmptyState title="当前筛选下还没有批注">
          播放到需要讨论的位置，使用上方时间点创建第一条批注。
        </EmptyState>
      ) : null}
      {threads.length > 0 ? (
        <div className="comment-thread-list">
          {threads.map((thread) => (
            <ThreadCard
              key={thread.thread_id}
              api={api}
              thread={thread}
              members={members}
              onUpdated={invalidate}
              onSeek={onSeek}
            />
          ))}
        </div>
      ) : null}
      {commentsQuery.hasNextPage ? (
        <div className="comment-pagination">
          <span className="hint">已显示 {threads.length}/{totalCount} 条批注</span>
          <button
            type="button"
            className="button button-secondary"
            disabled={commentsQuery.isFetchingNextPage}
            onClick={() => void commentsQuery.fetchNextPage()}
          >
            {commentsQuery.isFetchingNextPage ? "加载中…" : "加载更多批注"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
