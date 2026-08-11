import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage, signedUrlRefreshInterval } from "./api";
import type {
  CaptionCue,
  ClipDetailResponse,
  ClipPatchRequest,
  RenderKind,
  RenderSnapshot,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, formatMs } from "./ui";

interface ClipEditorProps {
  api: LiveClipApiClient;
  clipId: string;
  onClose: () => void;
  onChanged: () => void;
}

interface CaptionDraft {
  startMs: string;
  endMs: string;
  text: string;
}

interface EditorDraft {
  revision: number;
  title: string;
  sourceStartMs: string;
  sourceEndMs: string;
  captions: CaptionDraft[];
}

function draftFromResponse(response: ClipDetailResponse): EditorDraft {
  return {
    revision: response.clip.current_revision,
    title: response.clip.plan.title,
    sourceStartMs: String(response.clip.plan.source_start_ms),
    sourceEndMs: String(response.clip.plan.source_end_ms),
    captions: response.clip.captions.map((cue) => ({
      startMs: String(cue.start_ms),
      endMs: String(cue.end_ms),
      text: cue.text,
    })),
  };
}

function patchFromDraft(draft: EditorDraft, original: EditorDraft): ClipPatchRequest | null {
  const sourceStartMs = Number(draft.sourceStartMs);
  const sourceEndMs = Number(draft.sourceEndMs);
  if (
    !draft.title.trim() ||
    draft.captions.length === 0 ||
    !Number.isSafeInteger(sourceStartMs) ||
    !Number.isSafeInteger(sourceEndMs)
  ) {
    return null;
  }
  const captions: CaptionCue[] = [];
  for (const cue of draft.captions) {
    const startMs = Number(cue.startMs);
    const endMs = Number(cue.endMs);
    if (!cue.text.trim() || !Number.isSafeInteger(startMs) || !Number.isSafeInteger(endMs)) {
      return null;
    }
    captions.push({ start_ms: startMs, end_ms: endMs, text: cue.text });
  }
  const patch: ClipPatchRequest = { expected_revision: draft.revision };
  if (draft.sourceStartMs !== original.sourceStartMs) {
    patch.source_start_ms = sourceStartMs;
  }
  if (draft.sourceEndMs !== original.sourceEndMs) {
    patch.source_end_ms = sourceEndMs;
  }
  if (draft.title !== original.title) {
    patch.title = draft.title;
  }
  if (JSON.stringify(draft.captions) !== JSON.stringify(original.captions)) {
    patch.captions = captions;
  }
  return Object.keys(patch).length > 1 ? patch : null;
}

function currentVideo(
  response: ClipDetailResponse,
): { render: RenderSnapshot; url: string } | null {
  const render = response.clip.renders.find(
    (item) =>
      item.edit_plan_revision === response.clip.current_revision &&
      item.status === "succeeded" &&
      item.video_asset_id !== null,
  );
  if (!render?.video_asset_id) {
    return null;
  }
  const url = response.asset_urls[render.video_asset_id];
  return url ? { render, url } : null;
}

export function ClipEditor({ api, clipId, onClose, onChanged }: ClipEditorProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EditorDraft | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const [activeRenderId, setActiveRenderId] = useState<string | null>(null);

  const clipQuery = useQuery({
    queryKey: ["clip", clipId],
    queryFn: () => api.getClip(clipId),
    refetchInterval: (query) =>
      signedUrlRefreshInterval(Object.values(query.state.data?.asset_urls ?? {})),
  });

  useEffect(() => {
    if (clipQuery.data) {
      setDraft(draftFromResponse(clipQuery.data));
      setInputError(null);
    }
  }, [clipQuery.data]);

  const refreshRelated = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["clip", clipId] }),
      queryClient.invalidateQueries({ queryKey: ["clips"] }),
      queryClient.invalidateQueries({ queryKey: ["project"] }),
      queryClient.invalidateQueries({ queryKey: ["deliveries"] }),
    ]);
    onChanged();
  };

  const saveMutation = useMutation({
    mutationFn: (body: ClipPatchRequest) => api.patchClip(clipId, body),
    onSuccess: (response) => {
      queryClient.setQueryData(["clip", clipId], response);
      void refreshRelated();
    },
  });

  const reviewMutation = useMutation({
    mutationFn: (variables: { status: "approved" | "rejected"; reason?: string }) => {
      if (!clipQuery.data) {
        throw new Error("clip unavailable");
      }
      return api.reviewClip(clipId, {
        expected_revision: clipQuery.data.clip.current_revision,
        status: variables.status,
        ...(variables.reason ? { reason: variables.reason } : {}),
      });
    },
    onSuccess: (response) => {
      queryClient.setQueryData(["clip", clipId], response);
      setRejectionReason("");
      void refreshRelated();
    },
  });

  const renderMutation = useMutation({
    mutationFn: (kind: RenderKind) => {
      if (!clipQuery.data) {
        throw new Error("clip unavailable");
      }
      return api.createRender(clipId, clipQuery.data.clip.current_revision, kind);
    },
    onSuccess: (accepted) => {
      setActiveRenderId(accepted.resource_id);
      void refreshRelated();
    },
  });

  const activeRenderQuery = useQuery({
    queryKey: ["render", activeRenderId],
    queryFn: () => api.getRender(activeRenderId as string),
    enabled: activeRenderId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 800 : false;
    },
  });

  useEffect(() => {
    const status = activeRenderQuery.data?.status;
    if (status === "succeeded" || status === "failed" || status === "stale") {
      void refreshRelated();
    }
    // refreshRelated is intentionally tied to the terminal status transition only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRenderQuery.data?.status]);

  if (clipQuery.isPending) {
    return <LoadingState>正在加载候选详情…</LoadingState>;
  }
  if (clipQuery.isError) {
    return <ErrorState error={clipQuery.error} onRetry={() => void clipQuery.refetch()} />;
  }
  if (!draft) {
    return <EmptyState title="候选详情不可用" />;
  }

  const response = clipQuery.data;
  const clip = response.clip;
  const originalDraft = draftFromResponse(response);
  const dirty = JSON.stringify(draft) !== JSON.stringify(originalDraft);
  const allowed = new Set(clip.allowed_actions);
  const staleRenders = clip.renders.filter((render) => render.status === "stale");
  const video = currentVideo(response);
  const busy = saveMutation.isPending || reviewMutation.isPending || renderMutation.isPending;
  const renderPolling =
    activeRenderQuery.data?.status === "queued" || activeRenderQuery.data?.status === "running";

  const updateCaption = (index: number, patch: Partial<CaptionDraft>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            captions: current.captions.map((cue, cueIndex) =>
              cueIndex === index ? { ...cue, ...patch } : cue,
            ),
          }
        : current,
    );
  };

  const save = () => {
    const patch = patchFromDraft(draft, originalDraft);
    if (!patch) {
      setInputError("请保留至少一条字幕，并为标题、毫秒时间和字幕填写有效值。");
      return;
    }
    setInputError(null);
    saveMutation.mutate(patch);
  };

  const addCaption = () => {
    const duration = Math.max(1, Number(draft.sourceEndMs) - Number(draft.sourceStartMs));
    const previousEnd = Number(draft.captions.at(-1)?.endMs ?? 0);
    const startMs = Number.isFinite(previousEnd) ? Math.min(previousEnd, duration - 1) : 0;
    const endMs = Math.min(duration, startMs + 2_000);
    setDraft({
      ...draft,
      captions: [
        ...draft.captions,
        { startMs: String(Math.max(0, startMs)), endMs: String(Math.max(startMs + 1, endMs)), text: "新字幕" },
      ],
    });
  };

  return (
    <section className="clip-editor panel" aria-labelledby="clip-editor-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">候选 #{clip.rank ?? "—"} · revision {clip.current_revision}</p>
          <h2 id="clip-editor-title">{clip.plan.title}</h2>
        </div>
        <button type="button" className="button button-ghost" onClick={onClose}>
          关闭详情
        </button>
      </div>

      <div className="badge-row">
        <StatusBadge status={clip.review.status} />
        {clip.plan.degraded ? <StatusBadge status="failed" label="降级 EditPlan" /> : null}
        <span className="metric">AI 分数 {clip.plan.score.toFixed(1)}</span>
        <span className="metric">规则分数 {clip.rule_score.toFixed(1)}</span>
      </div>

      {staleRenders.length > 0 ? (
        <div className="notice notice-stale" role="status">
          <StatusBadge status="stale" />
          <span>旧 revision 的 {staleRenders.length} 个渲染已失效，不能用于当前审核或交付。</span>
        </div>
      ) : null}

      {activeRenderQuery.data ? (
        <div className="notice" aria-live="polite">
          <StatusBadge status={activeRenderQuery.data.status} />
          <span>
            {activeRenderQuery.data.kind === "final" ? "最终视频" : "审核代理"}
            {renderPolling ? "正在渲染，页面会自动刷新。" : "渲染状态已更新。"}
          </span>
        </div>
      ) : null}
      {activeRenderQuery.isError ? <ErrorState error={activeRenderQuery.error} /> : null}

      <div className="editor-grid">
        <div>
          {video ? (
            <figure className="video-frame">
              <video controls preload="metadata" src={video.url}>
                浏览器不支持 HTML5 视频播放。
              </video>
              <figcaption>
                当前 revision {video.render.edit_plan_revision} · {video.render.kind === "final"
                  ? "最终视频（标题与字幕已烧录）"
                  : "干净审核切片（未烧录标题或字幕）"}
              </figcaption>
            </figure>
          ) : (
            <EmptyState title="当前 revision 尚无可播放视频">
              {allowed.has("render_proxy") ? "可先生成审核代理。" : "等待渲染完成或刷新详情。"}
            </EmptyState>
          )}

          <div className="transcript-card">
            <h3>高光描述（独立元数据）</h3>
            <p><strong>标题：</strong>{clip.plan.title}</p>
            <p><strong>Hook：</strong>{clip.plan.hook}</p>
            <p><strong>推荐理由：</strong>{clip.plan.reason}</p>
            <p className="hint">标题、描述和字幕不会写入审核切片画面；审核修改后再生成最终视频。</p>
            {clip.plan.risk_flags.length > 0 ? (
              <ul className="risk-list" aria-label="当前方案风险标签">
                {clip.plan.risk_flags.map((flag) => <li key={flag}>{flag}</li>)}
              </ul>
            ) : null}
          </div>

          <div className="transcript-card">
            <h3>候选转写</h3>
            <p>{clip.transcript_text}</p>
            <details>
              <summary>查看前后文与生成原因</summary>
              <p><strong>前文：</strong>{clip.context_before || "无"}</p>
              <p><strong>后文：</strong>{clip.context_after || "无"}</p>
              <ul>{clip.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </details>
          </div>
        </div>

        <form className="editor-form" onSubmit={(event) => { event.preventDefault(); save(); }}>
          <h3>编辑当前方案</h3>
          <p className="hint">
            源边界使用绝对毫秒；字幕使用片段相对毫秒。允许窗口：
            {clip.allowed_start_ms}–{clip.allowed_end_ms} ms。最终校验由后端完成。
          </p>

          <label>
            标题
            <input
              value={draft.title}
              maxLength={40}
              required
              onChange={(event) => setDraft({ ...draft, title: event.currentTarget.value })}
            />
          </label>
          <div className="field-pair">
            <label>
              源开始（ms）
              <input
                type="number"
                step="1"
                min="0"
                required
                value={draft.sourceStartMs}
                onChange={(event) => setDraft({ ...draft, sourceStartMs: event.currentTarget.value })}
              />
            </label>
            <label>
              源结束（ms）
              <input
                type="number"
                step="1"
                min="1"
                required
                value={draft.sourceEndMs}
                onChange={(event) => setDraft({ ...draft, sourceEndMs: event.currentTarget.value })}
              />
            </label>
          </div>
          <p className="hint">
            当前区间：{formatMs(Number(draft.sourceStartMs))}–{formatMs(Number(draft.sourceEndMs))}
          </p>

          <div className="caption-heading">
            <h4>逐 cue 字幕</h4>
            <button type="button" className="button button-ghost" onClick={addCaption} disabled={busy}>
              添加字幕
            </button>
          </div>
          <div className="caption-list">
            <p className="hint">每个 revision 至少保留 1 条字幕 cue。</p>
            {draft.captions.map((cue, index) => (
              <fieldset className="caption-cue" key={`${index}-${clip.current_revision}`}>
                <legend>字幕 {index + 1}</legend>
                <div className="field-pair">
                  <label>
                    开始（ms）
                    <input
                      type="number"
                      step="1"
                      min="0"
                      required
                      value={cue.startMs}
                      onChange={(event) => updateCaption(index, { startMs: event.currentTarget.value })}
                    />
                  </label>
                  <label>
                    结束（ms）
                    <input
                      type="number"
                      step="1"
                      min="1"
                      required
                      value={cue.endMs}
                      onChange={(event) => updateCaption(index, { endMs: event.currentTarget.value })}
                    />
                  </label>
                </div>
                <label>
                  文本
                  <textarea
                    rows={2}
                    maxLength={120}
                    required
                    value={cue.text}
                    onChange={(event) => updateCaption(index, { text: event.currentTarget.value })}
                  />
                </label>
                <button
                  type="button"
                  className="button button-danger-ghost"
                  disabled={busy || draft.captions.length <= 1}
                  onClick={() => setDraft({ ...draft, captions: draft.captions.filter((_, cueIndex) => cueIndex !== index) })}
                >
                  删除此 cue
                </button>
              </fieldset>
            ))}
          </div>

          {inputError ? <p className="form-error" role="alert">{inputError}</p> : null}
          {saveMutation.isError ? <p className="form-error" role="alert">{errorMessage(saveMutation.error)}</p> : null}
          <button
            type="submit"
            className="button button-primary"
            disabled={busy || !dirty || draft.captions.length === 0 || !allowed.has("edit")}
          >
            {saveMutation.isPending ? "保存中…" : "保存为新 revision"}
          </button>
          {!dirty ? <span className="hint">没有尚未保存的修改</span> : null}
        </form>
      </div>

      <div className="action-grid">
        <section className="action-card">
          <h3>人工审核</h3>
          <p className="hint">有未保存修改时请先创建新 revision，再审核该 revision。</p>
          <div className="button-row">
            <button
              type="button"
              className="button button-success"
              disabled={busy || dirty || !allowed.has("approve")}
              onClick={() => reviewMutation.mutate({ status: "approved" })}
            >
              {reviewMutation.isPending ? "提交中…" : "批准"}
            </button>
          </div>
          <label>
            拒绝理由
            <textarea
              rows={2}
              maxLength={1_000}
              value={rejectionReason}
              onChange={(event) => setRejectionReason(event.currentTarget.value)}
              placeholder="说明内容不完整等原因"
            />
          </label>
          <button
            type="button"
            className="button button-danger"
            disabled={busy || dirty || !allowed.has("reject") || !rejectionReason.trim()}
            onClick={() => reviewMutation.mutate({ status: "rejected", reason: rejectionReason.trim() })}
          >
            拒绝此 revision
          </button>
          {reviewMutation.isError ? <p className="form-error" role="alert">{errorMessage(reviewMutation.error)}</p> : null}
          {clip.review.reason ? <p className="hint">最近拒绝理由：{clip.review.reason}</p> : null}
        </section>

        <section className="action-card">
          <h3>重新渲染</h3>
          <p className="hint">渲染任务由独立 Worker 执行；本页只提交并轮询状态。</p>
          <div className="button-row">
            <button
              type="button"
              className="button button-secondary"
              disabled={busy || renderPolling || !allowed.has("render_proxy")}
              onClick={() => renderMutation.mutate("proxy")}
            >
              渲染审核代理
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || renderPolling || !allowed.has("render_final")}
              onClick={() => renderMutation.mutate("final")}
            >
              渲染最终视频
            </button>
          </div>
          {renderMutation.isError ? <p className="form-error" role="alert">{errorMessage(renderMutation.error)}</p> : null}
          {!allowed.has("render_final") ? <p className="hint">最终渲染仅在后端允许时启用，通常需先批准当前 revision。</p> : null}
        </section>
      </div>

      <details className="render-history">
        <summary>渲染历史（{clip.renders.length}）</summary>
        {clip.renders.length === 0 ? <p>暂无渲染记录。</p> : (
          <ul>
            {clip.renders.map((render) => (
              <li key={render.render_id}>
                <span>{render.kind === "final" ? "最终" : "代理"} r{render.edit_plan_revision}</span>
                <StatusBadge status={render.status} />
                {render.safe_error_message ? <span className="form-error">{render.safe_error_message}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
