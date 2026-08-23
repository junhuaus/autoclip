import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage, signedUrlRefreshInterval } from "./api";
import { ClipComments } from "./ClipComments";
import type {
  CaptionCue,
  ClipDetailResponse,
  ClipPatchRequest,
  RenderKind,
  RenderSnapshot,
  WorkspaceMember,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, formatMs } from "./ui";

interface ClipEditorProps {
  api: LiveClipApiClient;
  clipId: string;
  canEdit?: boolean;
  canRender?: boolean;
  canComment?: boolean;
  members?: WorkspaceMember[];
  onClose: () => void;
  onChanged: () => void;
  onDirtyChange?: (clipId: string, dirty: boolean) => void;
  externalBusy?: boolean;
}

interface CaptionDraft {
  startMs: string;
  endMs: string;
  text: string;
}

interface EditorDraft {
  revision: number;
  score: string;
  title: string;
  sourceStartMs: string;
  sourceEndMs: string;
  captions: CaptionDraft[];
}

function draftFromResponse(response: ClipDetailResponse): EditorDraft {
  return {
    revision: response.clip.current_revision,
    score: String(response.clip.plan.score),
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
  const score = Number(draft.score);
  if (
    !draft.title.trim() ||
    draft.captions.length === 0 ||
    !Number.isFinite(score) ||
    score < 0 ||
    score > 100 ||
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
  if (draft.score !== original.score) {
    patch.score = score;
  }
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

export function ClipEditor({
  api,
  clipId,
  canEdit = true,
  canRender = true,
  canComment = true,
  members = [],
  onClose,
  onChanged,
  onDirtyChange = () => undefined,
  externalBusy = false,
}: ClipEditorProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EditorDraft | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [activeRenderId, setActiveRenderId] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingSeekMs = useRef<number | null>(null);

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

  const editorDirty = Boolean(
    draft &&
      clipQuery.data &&
      JSON.stringify(draft) !== JSON.stringify(draftFromResponse(clipQuery.data)),
  );

  useEffect(() => {
    onDirtyChange(clipId, editorDirty);
  }, [clipId, editorDirty, onDirtyChange]);

  useEffect(
    () => () => {
      onDirtyChange(clipId, false);
    },
    [clipId, onDirtyChange],
  );

  const refreshRelated = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["clip", clipId] }),
      queryClient.invalidateQueries({ queryKey: ["clips"] }),
      queryClient.invalidateQueries({ queryKey: ["project"] }),
      queryClient.invalidateQueries({ queryKey: ["deliveries"] }),
    ]);
    onChanged();
  };

  const seekTo = (startMs: number) => {
    const element = videoRef.current;
    if (!element || !video) return;
    if (element.readyState < 1) {
      pendingSeekMs.current = startMs;
      return;
    }
    const requestedSeconds = startMs / 1_000;
    element.currentTime = Number.isFinite(element.duration)
      ? Math.min(Math.max(0, requestedSeconds), element.duration)
      : Math.max(0, requestedSeconds);
  };

  const currentVideoTimeMs = () => {
    const element = videoRef.current;
    if (!element || !video || !Number.isFinite(element.currentTime)) return null;
    return Math.max(0, Math.round(element.currentTime * 1_000));
  };

  const saveMutation = useMutation({
    mutationFn: (body: ClipPatchRequest) => api.patchClip(clipId, body),
    onSuccess: (response) => {
      queryClient.setQueryData(["clip", clipId], response);
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
    return <LoadingState>正在加载高光详情…</LoadingState>;
  }
  if (clipQuery.isError) {
    return <ErrorState error={clipQuery.error} onRetry={() => void clipQuery.refetch()} />;
  }
  if (!draft) {
    return <EmptyState title="高光详情不可用" />;
  }

  const response = clipQuery.data;
  const clip = response.clip;
  const originalDraft = draftFromResponse(response);
  const dirty = editorDirty;
  const allowed = new Set(clip.allowed_actions);
  const staleRenders = clip.renders.filter((render) => render.status === "stale");
  const video = currentVideo(response);
  const busy =
    externalBusy ||
    saveMutation.isPending ||
    renderMutation.isPending;
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
      setInputError("请填写 0–100 的评分，并为标题、毫秒时间和至少一条字幕填写有效值。");
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
          <p className="eyebrow">高光 #{clip.rank ?? "—"} · revision {clip.current_revision}</p>
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
          <span>旧 revision 的 {staleRenders.length} 个渲染已失效，不能用于当前预览或交付。</span>
        </div>
      ) : null}

      {activeRenderQuery.data ? (
        <div className="notice" aria-live="polite">
          <StatusBadge status={activeRenderQuery.data.status} />
          <span>
            {activeRenderQuery.data.kind === "final" ? "烧录版视频" : "预览/交付母版"}
            {renderPolling ? "正在渲染，页面会自动刷新。" : "渲染状态已更新。"}
          </span>
        </div>
      ) : null}
      {activeRenderQuery.isError ? <ErrorState error={activeRenderQuery.error} /> : null}

      <div className="editor-grid">
        <div>
          {video ? (
            <figure className="video-frame">
              <video
                ref={videoRef}
                controls
                preload="metadata"
                src={video.url}
                onLoadedMetadata={() => {
                  if (pendingSeekMs.current === null) return;
                  const startMs = pendingSeekMs.current;
                  pendingSeekMs.current = null;
                  seekTo(startMs);
                }}
              >
                浏览器不支持 HTML5 视频播放。
              </video>
              <figcaption>
                当前 revision {video.render.edit_plan_revision} · {video.render.kind === "final"
                  ? "烧录版视频（标题与字幕已写入画面）"
                  : "干净预览/交付母版（标题与字幕作为独立元数据）"}
              </figcaption>
            </figure>
          ) : (
            <EmptyState title="当前 revision 尚无可播放视频">
              {allowed.has("render_proxy") ? "可生成当前 revision 的预览/交付母版。" : "等待渲染完成或刷新详情。"}
            </EmptyState>
          )}

          <div className="clip-timed-metadata editor-timed-metadata">
            <section className="clip-keywords" aria-labelledby={`editor-keywords-${clip.clip_id}`}>
              <h4 id={`editor-keywords-${clip.clip_id}`}>编辑关键词</h4>
              {clip.keywords.length > 0 ? (
                <ul aria-label="当前切片详情编辑关键词">
                  {clip.keywords.map((keyword, index) => (
                    <li key={`${keyword.text}-${keyword.clip_start_ms}-${index}`}>
                      <button
                        type="button"
                        disabled={!video}
                        onClick={() => seekTo(keyword.clip_start_ms)}
                        aria-label={`定位到详情编辑关键词 ${keyword.text}，${formatMs(keyword.clip_start_ms)}`}
                      >
                        <strong>{keyword.text}</strong>
                        <time>{formatMs(keyword.clip_start_ms)}–{formatMs(keyword.clip_end_ms)}</time>
                        <span>
                          {keyword.timing_precision === "word" ? "词级时间" : "转写段时间窗"}
                        </span>
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
          </div>

          <div className="transcript-card">
            <h3>高光描述（独立元数据）</h3>
            <p><strong>标题：</strong>{clip.plan.title}</p>
            <p><strong>高光语句：</strong>{clip.plan.hook}</p>
            <p><strong>推荐理由：</strong>{clip.plan.reason}</p>
            <p className="hint">标题、描述和字幕不写入母版画面；回到高光列表勾选即可加入交付。</p>
            {clip.plan.risk_flags.length > 0 ? (
              <ul className="risk-list" aria-label="当前方案风险标签">
                {clip.plan.risk_flags.map((flag) => <li key={flag}>{flag}</li>)}
              </ul>
            ) : null}
          </div>

          <div className="transcript-card">
            <h3>高光原文</h3>
            <p>{clip.transcript_text}</p>
            <details>
              <summary>查看前后文与生成原因</summary>
              <p><strong>前文：</strong>{clip.context_before || "无"}</p>
              <p><strong>后文：</strong>{clip.context_after || "无"}</p>
              <ul>{clip.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </details>
          </div>

          <ClipComments
            api={api}
            clipId={clip.clip_id}
            currentRevision={clip.current_revision}
            durationMs={clip.plan.source_end_ms - clip.plan.source_start_ms}
            members={members}
            canCreate={canComment && !dirty}
            createDisabledReason={
              dirty
                ? "请先保存当前编辑草稿；新批注必须绑定一个已保存的 revision。"
                : null
            }
            getCurrentTimeMs={currentVideoTimeMs}
            onSeek={seekTo}
          />

          <section
            className="clip-captions editor-captions-final"
            aria-labelledby={`editor-captions-${clip.clip_id}`}
          >
            <div className="metadata-heading">
              <h4 id={`editor-captions-${clip.clip_id}`}>字幕</h4>
              <span>当前 revision · 点击跳转</span>
            </div>
            <ol aria-label="当前切片详情字幕">
              {clip.captions.map((cue, index) => (
                <li key={`${cue.start_ms}-${cue.end_ms}-${index}`}>
                  <button
                    type="button"
                    disabled={!video}
                    onClick={() => seekTo(cue.start_ms)}
                    aria-label={`定位到详情字幕 ${formatMs(cue.start_ms)}：${cue.text}`}
                  >
                    <time>{formatMs(cue.start_ms)}–{formatMs(cue.end_ms)}</time>
                    <span>{cue.text}</span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <form className="editor-form" onSubmit={(event) => { event.preventDefault(); save(); }}>
          <h3>编辑当前方案</h3>
          <p className="hint">
            评分范围为 0–100；源边界使用绝对毫秒；字幕使用片段相对毫秒。允许窗口：
            {clip.allowed_start_ms}–{clip.allowed_end_ms} ms。最终校验由后端完成。
          </p>

          <label>
            评分
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={draft.score}
              required
              disabled={busy || !canEdit}
              onChange={(event) => setDraft({ ...draft, score: event.currentTarget.value })}
            />
          </label>

          <label>
            标题
            <input
              value={draft.title}
              maxLength={40}
              required
              disabled={busy || !canEdit}
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
                disabled={busy || !canEdit}
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
                disabled={busy || !canEdit}
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
            <button type="button" className="button button-ghost" onClick={addCaption} disabled={busy || !canEdit}>
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
                      disabled={busy || !canEdit}
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
                      disabled={busy || !canEdit}
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
                    disabled={busy || !canEdit}
                    value={cue.text}
                    onChange={(event) => updateCaption(index, { text: event.currentTarget.value })}
                  />
                </label>
                <button
                  type="button"
                  className="button button-danger-ghost"
                  disabled={busy || !canEdit || draft.captions.length <= 1}
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
            disabled={busy || !canEdit || !dirty || draft.captions.length === 0 || !allowed.has("edit")}
          >
            {saveMutation.isPending ? "保存中…" : "保存为新 revision"}
          </button>
          {!dirty ? <span className="hint">没有尚未保存的修改</span> : null}
        </form>
      </div>

      <div className="action-grid action-grid-single">
        <section className="action-card">
          <h3>渲染</h3>
          <p className="hint">切片初版会自动生成母版；只有修改当前 revision 后才需在这里重新渲染。</p>
          <div className="button-row">
            <button
              type="button"
              className="button button-secondary"
              disabled={busy || !canRender || renderPolling || !allowed.has("render_proxy")}
              onClick={() => renderMutation.mutate("proxy")}
            >
              渲染预览/交付母版
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || !canRender || renderPolling || !allowed.has("render_final")}
              onClick={() => renderMutation.mutate("final")}
            >
              生成可选烧录版
            </button>
          </div>
          {renderMutation.isError ? <p className="form-error" role="alert">{errorMessage(renderMutation.error)}</p> : null}
          {!allowed.has("render_final") ? <p className="hint">选入交付不影响母版；选中后才可按需另生成标题/字幕烧录版。</p> : null}
        </section>
      </div>

      <details className="render-history">
        <summary>渲染历史（{clip.renders.length}）</summary>
        {clip.renders.length === 0 ? <p>暂无渲染记录。</p> : (
          <ul>
            {clip.renders.map((render) => (
              <li key={render.render_id}>
                <span>{render.kind === "final" ? "烧录版" : "预览/交付母版"} r{render.edit_plan_revision}</span>
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
