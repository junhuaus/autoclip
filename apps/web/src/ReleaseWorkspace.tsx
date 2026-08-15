import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LiveClipApiClient, errorMessage, signedUrlRefreshInterval } from "./api";
import type {
  ClipSummaryResponse,
  PlatformPreset,
  ProjectSnapshot,
  ReleaseApprovalStatus,
  ReleaseCaptionMode,
  ReleaseChecklist,
  ReleaseItemSnapshot,
  ReleaseItemStatus,
  ReleaseMetricRequest,
  ReleasePlatform,
} from "./types";
import { EmptyState, ErrorState, LoadingState, StatusBadge, formatMs } from "./ui";

type ReleaseView = "queue" | "calendar";

const PLATFORM_LABELS: Record<ReleasePlatform, string> = {
  douyin: "抖音",
  xiaohongshu: "小红书",
  bilibili_vertical: "哔哩哔哩竖屏",
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  generic_vertical: "通用竖屏",
};

const RELEASE_STATUS_LABELS: Record<ReleaseItemStatus, string> = {
  draft: "准备中",
  ready: "可发布",
  scheduled_external: "外部已排期",
  published: "已发布",
  failed: "发布失败",
  withdrawn: "已撤回",
};

const APPROVAL_LABELS: Record<ReleaseApprovalStatus, string> = {
  draft: "文案草稿",
  pending_review: "待发布审核",
  approved: "发布审核通过",
  changes_requested: "需修改",
};

const CHECKLIST_LABELS: Record<keyof ReleaseChecklist, string> = {
  hook_confirmed: "Hook 与高光语句已确认",
  first_frame_confirmed: "首帧与封面已确认",
  subtitles_confirmed: "字幕已校对",
  music_rights_confirmed: "音乐版权已确认",
  likeness_confirmed: "肖像使用已确认",
  personal_data_confirmed: "个人信息已检查",
  claims_confirmed: "事实与宣称已复核",
  sponsorship_confirmed: "商业合作标识已确认",
  platform_policy_confirmed: "目标平台规则已确认",
};

function localDateTimeValue(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function toIsoOrNull(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function commaValues(value: string): string[] {
  return value
    .split(/[，,\n]/)
    .map((item) => item.trim().replace(/^#/, ""))
    .filter(Boolean);
}

function calendarLabel(value: string | null): string {
  if (!value) return "待排期";
  return new Date(value).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}

function platformPreset(
  presets: PlatformPreset[],
  platform: ReleasePlatform,
  version: string | undefined,
): PlatformPreset | undefined {
  if (!version) return undefined;
  return presets.find((item) => item.platform === platform && item.version === version);
}

function ReleaseCreatePanel({
  api,
  project,
  clips,
  presets,
  currentVersions,
  onCreated,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  clips: ClipSummaryResponse[];
  presets: PlatformPreset[];
  currentVersions: Partial<Record<ReleasePlatform, string>>;
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState<ReleasePlatform>("douyin");
  const canManage = project.allowed_actions.includes("manage_release");
  const eligibleClips = clips.filter(({ clip }) => clip.review_status !== "rejected");
  const releaseAssignees = project.members.filter((member) =>
    ["owner", "editor"].includes(member.role),
  );
  const currentPresets = (Object.keys(PLATFORM_LABELS) as ReleasePlatform[])
    .map((value) => platformPreset(presets, value, currentVersions[value]))
    .filter((value): value is PlatformPreset => value !== undefined);
  const preset = platformPreset(presets, platform, currentVersions[platform]);
  const mutation = useMutation({
    mutationFn: (body: {
      clip_id: string;
      expected_revision: number;
      platform: ReleasePlatform;
      account_label: string;
      caption_mode: ReleaseCaptionMode;
      assignee_user_id: string | null;
      planned_publish_at: string | null;
    }) => api.createReleaseItem(project.project_id, body),
    onSuccess: () => {
      setOpen(false);
      onCreated();
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!preset) return;
    const data = new FormData(event.currentTarget);
    const clipId = String(data.get("clip_id") ?? "");
    const selected = eligibleClips.find(({ clip }) => clip.clip_id === clipId);
    if (!selected) return;
    mutation.mutate({
      clip_id: clipId,
      expected_revision: selected.clip.edit_plan_revision,
      platform,
      account_label: String(data.get("account_label") ?? ""),
      caption_mode: String(data.get("caption_mode")) as ReleaseCaptionMode,
      assignee_user_id: String(data.get("assignee_user_id") ?? "") || null,
      planned_publish_at: toIsoOrNull(String(data.get("planned_publish_at") ?? "")),
    });
  };

  return (
    <section className="release-create">
      <button
        type="button"
        className="button button-primary"
        disabled={!canManage || eligibleClips.length === 0 || !preset}
        onClick={() => setOpen((value) => !value)}
      >
        ＋ 建立发布任务
      </button>
      {!canManage ? <span className="hint">当前角色只能查看或审核发布任务。</span> : null}
      {canManage && eligibleClips.length === 0 ? (
        <span className="hint">需要至少一个未拒绝的高光时刻。</span>
      ) : null}
      {canManage && eligibleClips.length > 0 && !preset ? (
        <span className="hint">当前平台预设不可用，请刷新后重试。</span>
      ) : null}
      {open ? (
        <form className="release-create-form" onSubmit={submit}>
          <label>
            高光时刻
            <select name="clip_id" required defaultValue="">
              <option value="" disabled>选择高光</option>
              {eligibleClips.map(({ clip }) => (
                <option key={clip.clip_id} value={clip.clip_id}>
                  {clip.title} · {clip.review_status === "approved" ? "已批准" : "待内容审核"} · r{clip.edit_plan_revision} · {formatMs(clip.source_end_ms - clip.source_start_ms)}
                </option>
              ))}
            </select>
          </label>
          <label>
            目标平台
            <select
              name="platform"
              value={platform}
              onChange={(event) => setPlatform(event.currentTarget.value as ReleasePlatform)}
            >
              {currentPresets.map((item) => (
                <option key={item.platform} value={item.platform}>{item.label}</option>
              ))}
            </select>
          </label>
          <label>
            发布账号
            <input name="account_label" required maxLength={120} placeholder="例如：官方主账号" />
          </label>
          <label>
            视频与字幕
            <select name="caption_mode" defaultValue="clean_separate">
              <option value="clean_separate">干净视频 + 独立 SRT（推荐编辑）</option>
              <option value="burned">已烧录字幕的最终视频</option>
            </select>
          </label>
          <label>
            发布执行人
            <select name="assignee_user_id" defaultValue="">
              <option value="">暂不分配</option>
              {releaseAssignees.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.display_name} · {member.role === "owner" ? "负责人" : "编辑"}
                </option>
              ))}
            </select>
          </label>
          <label>
            计划发布时间
            <input name="planned_publish_at" type="datetime-local" />
          </label>
          {preset ? (
            <p className="release-preset-note">
              {preset.recommended_width}×{preset.recommended_height} · 规则核对于 {preset.checked_at}
            </p>
          ) : null}
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={mutation.isPending || !preset}>
              {mutation.isPending ? "正在建立…" : "建立发布任务"}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setOpen(false)}>
              取消
            </button>
          </div>
          {mutation.isError ? <p className="form-error" role="alert">{errorMessage(mutation.error)}</p> : null}
        </form>
      ) : null}
    </section>
  );
}

function ReleaseCard({
  api,
  project,
  release,
  preset,
  previewMediaUrl,
  onChanged,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  release: ReleaseItemSnapshot;
  preset: PlatformPreset | undefined;
  previewMediaUrl: string | undefined;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const coverVideoRef = useRef<HTMLVideoElement>(null);
  const [title, setTitle] = useState(release.title);
  const [titleVariants, setTitleVariants] = useState(release.title_variants.join("，"));
  const [description, setDescription] = useState(release.description);
  const [hashtags, setHashtags] = useState(release.hashtags.join("，"));
  const [cta, setCta] = useState(release.cta);
  const [captionMode, setCaptionMode] = useState(release.caption_mode);
  const [coverSeconds, setCoverSeconds] = useState(String(release.cover_time_ms / 1_000));
  const [assigneeId, setAssigneeId] = useState(release.assignee?.user_id ?? "");
  const [plannedAt, setPlannedAt] = useState(localDateTimeValue(release.planned_publish_at));
  const [checklist, setChecklist] = useState(release.checklist);
  const [approvalReason, setApprovalReason] = useState("");
  const [externalUrl, setExternalUrl] = useState(release.external_url ?? "");
  const [externalId, setExternalId] = useState(release.external_id ?? "");
  const [publishedAt, setPublishedAt] = useState(() =>
    localDateTimeValue(release.published_at ?? new Date().toISOString()),
  );
  const [resultNotes, setResultNotes] = useState(release.result_notes ?? "");
  const [activePackageId, setActivePackageId] = useState<string | null>(null);
  const [publicationPackageId, setPublicationPackageId] = useState(
    release.publication_evidence?.release_package_id ?? "",
  );
  const canManage = project.allowed_actions.includes("manage_release");
  const canApprove = project.allowed_actions.includes("approve_release");
  const mutable = !["published", "withdrawn"].includes(release.status);
  const canSyncStale =
    mutable && release.stale && release.stale_reason === "revision_changed";
  const canUpdate = mutable && release.stale_reason !== "project_run_changed";
  const currentSucceededPackages = release.packages.filter(
    (item) => item.status === "succeeded" && item.current,
  );
  const hasActiveStoredPackage = release.packages.some(
    (item) => item.status === "queued" || item.status === "creating",
  );

  useEffect(() => {
    setTitle(release.title);
    setTitleVariants(release.title_variants.join("，"));
    setDescription(release.description);
    setHashtags(release.hashtags.join("，"));
    setCta(release.cta);
    setCaptionMode(release.caption_mode);
    setCoverSeconds(String(release.cover_time_ms / 1_000));
    setAssigneeId(release.assignee?.user_id ?? "");
    setPlannedAt(localDateTimeValue(release.planned_publish_at));
    setChecklist(release.checklist);
    setExternalUrl(release.external_url ?? "");
    setExternalId(release.external_id ?? "");
    setPublishedAt(
      localDateTimeValue(release.published_at ?? new Date().toISOString()),
    );
    setResultNotes(release.result_notes ?? "");
    const eligiblePackage = release.packages.find(
      (item) => item.status === "succeeded" && item.current,
    );
    setPublicationPackageId(
      release.publication_evidence?.release_package_id ??
        eligiblePackage?.release_package_id ??
        "",
    );
  }, [release]);

  const packageQuery = useQuery({
    queryKey: ["release-package", activePackageId],
    queryFn: () => api.getReleasePackage(activePackageId as string),
    enabled: activePackageId !== null,
    refetchInterval: (query) => {
      const item = query.state.data;
      const status = item?.release_package.status;
      return status === "queued" || status === "creating"
        ? 800
        : signedUrlRefreshInterval([item?.download_url]);
    },
  });
  useEffect(() => {
    const status = packageQuery.data?.release_package.status;
    if (status === "succeeded" || status === "failed") onChanged();
  }, [onChanged, packageQuery.data?.release_package.status]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateReleaseItem(release.release_item_id, {
        expected_management_version: release.management_version,
        edit_plan_revision: release.current_edit_plan_revision,
        title,
        title_variants: commaValues(titleVariants),
        description,
        hashtags: commaValues(hashtags),
        cta,
        caption_mode: captionMode,
        cover_time_ms: Math.round(Number(coverSeconds || "0") * 1_000),
        assignee_user_id: assigneeId || null,
        planned_publish_at: toIsoOrNull(plannedAt),
        checklist,
      }),
    onSuccess: onChanged,
  });
  const approvalMutation = useMutation({
    mutationFn: (target: ReleaseApprovalStatus) =>
      api.transitionReleaseApproval(release.release_item_id, {
        expected_management_version: release.management_version,
        target,
        reason: approvalReason.trim(),
      }),
    onSuccess: () => {
      setApprovalReason("");
      onChanged();
    },
  });
  const statusMutation = useMutation({
    mutationFn: (target: ReleaseItemStatus) =>
      api.transitionReleaseStatus(release.release_item_id, {
        expected_management_version: release.management_version,
        target,
        ...(target === "published"
          ? {
              external_url: externalUrl.trim() || undefined,
              external_id: externalId.trim() || undefined,
              published_at: toIsoOrNull(publishedAt) ?? undefined,
              release_package_id: publicationPackageId,
            }
          : {}),
        ...(resultNotes.trim() ? { result_notes: resultNotes.trim() } : {}),
      }),
    onSuccess: onChanged,
  });
  const packageMutation = useMutation({
    mutationFn: () =>
      api.createReleasePackage(release.release_item_id, release.management_version, true),
    onSuccess: (accepted) => {
      setActivePackageId(accepted.resource_id);
      void queryClient.invalidateQueries({ queryKey: ["releases", project.project_id] });
    },
  });
  const packageInFlight =
    hasActiveStoredPackage ||
    packageMutation.isPending ||
    (activePackageId !== null &&
      (packageQuery.isPending ||
        ["queued", "creating"].includes(packageQuery.data?.release_package.status ?? "")));
  const metricMutation = useMutation({
    mutationFn: (body: ReleaseMetricRequest) =>
      api.addReleaseMetric(release.release_item_id, body),
    onSuccess: onChanged,
  });
  const submitMetric = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const number = (name: string) => Number.parseInt(String(data.get(name) ?? "0"), 10) || 0;
    metricMutation.mutate({
      captured_at: new Date().toISOString(),
      views: number("views"),
      likes: number("likes"),
      comments: number("comments"),
      shares: number("shares"),
      saves: number("saves"),
      followers_gained: number("followers_gained"),
      notes: String(data.get("notes") ?? "").trim() || null,
    });
  };
  const errors = [
    saveMutation.error,
    approvalMutation.error,
    statusMutation.error,
    packageMutation.error,
    packageQuery.error,
    metricMutation.error,
  ].filter(Boolean);

  return (
    <article className={`release-card ${release.stale ? "release-card-stale" : ""}`}>
      <header className="release-card-header">
        <div>
          <p className="eyebrow">{PLATFORM_LABELS[release.platform]} · {release.account_label}</p>
          <h3>{release.title}</h3>
          <p>{release.high_impact_sentence}</p>
        </div>
        <div className="release-card-statuses">
          <StatusBadge status={release.status} label={RELEASE_STATUS_LABELS[release.status]} />
          <StatusBadge status={release.approval_status} label={APPROVAL_LABELS[release.approval_status]} />
        </div>
      </header>
      <div className="release-facts">
        <span>计划 {release.planned_publish_at ? new Date(release.planned_publish_at).toLocaleString("zh-CN") : "未排期"}</span>
        <span>执行人 {release.assignee?.display_name ?? "未分配"}</span>
        <span>剪辑 r{release.edit_plan_revision}</span>
        <span>{release.caption_mode === "clean_separate" ? "干净视频 + SRT" : "烧录字幕视频"}</span>
        <span>预设 {release.preset_version}</span>
      </div>
      {release.stale ? <p className="notice notice-error">{release.stale_reason === "project_run_changed" ? "项目已开始新的处理批次；旧发布任务不能同步，请从当前批次的高光时刻建立新任务。" : canSyncStale ? `剪辑已从 r${release.edit_plan_revision} 更新到 r${release.current_edit_plan_revision}；请先同步当前版本，发布审核会重置，旧平台包保留为历史版本。` : `此历史发布记录绑定剪辑 r${release.edit_plan_revision}；如需发布当前 r${release.current_edit_plan_revision}，请建立新任务。`}</p> : null}
      {release.publication_evidence ? <p className="notice">已发布使用 {release.publication_evidence.package_version} · 视频校验 {release.publication_evidence.video_sha256.slice(0, 12)}… · {release.publication_evidence.artifact_kind === "zip" ? "ZIP" : "Manifest"} {release.publication_evidence.artifact_sha256.slice(0, 12)}…</p> : null}
      {release.published_at || release.external_url || release.external_id || release.result_notes ? (
        <section className="release-publication-record" aria-label="外部发布记录">
          <strong>外部发布记录</strong>
          <span>实际发布时间 {release.published_at ? new Date(release.published_at).toLocaleString("zh-CN") : "未记录"}</span>
          {release.external_url ? <a href={release.external_url} target="_blank" rel="noreferrer">打开发布页面</a> : null}
          {release.external_id ? <span>平台内容 ID {release.external_id}</span> : null}
          {release.result_notes ? <p>{release.result_notes}</p> : null}
        </section>
      ) : null}

      <details className="release-editor" open={release.status === "draft" || release.stale}>
        <summary>发布文案、封面与合规清单</summary>
        <div className="release-editor-grid">
          <label>主标题<input value={title} maxLength={100} disabled={!canManage || !canUpdate} onChange={(event) => setTitle(event.target.value)} /></label>
          <label>备选标题（逗号分隔，最多 3 个）<input value={titleVariants} disabled={!canManage || !canUpdate} onChange={(event) => setTitleVariants(event.target.value)} /></label>
          <label className="release-wide">发布正文<textarea value={description} maxLength={5_000} disabled={!canManage || !canUpdate} onChange={(event) => setDescription(event.target.value)} /></label>
          <label>话题标签<input value={hashtags} disabled={!canManage || !canUpdate} placeholder="直播，高光" onChange={(event) => setHashtags(event.target.value)} /></label>
          <label>行动引导<input value={cta} maxLength={200} disabled={!canManage || !canUpdate} onChange={(event) => setCta(event.target.value)} /></label>
          <label>视频与字幕<select value={captionMode} disabled={!canManage || !canUpdate} onChange={(event) => setCaptionMode(event.target.value as ReleaseCaptionMode)}><option value="clean_separate">干净视频 + 独立 SRT</option><option value="burned">烧录字幕最终视频</option></select></label>
          <label>封面时间（片段内秒）<input type="number" min="0" step="0.1" value={coverSeconds} disabled={!canManage || !canUpdate} onChange={(event) => setCoverSeconds(event.target.value)} /></label>
          <label>执行人<select value={assigneeId} disabled={!canManage || !canUpdate} onChange={(event) => setAssigneeId(event.target.value)}><option value="">未分配</option>{project.members.filter((member) => ["owner", "editor"].includes(member.role)).map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name} · {member.role === "owner" ? "负责人" : "编辑"}</option>)}</select></label>
          <label>计划发布时间<input type="datetime-local" value={plannedAt} disabled={!canManage || !canUpdate} onChange={(event) => setPlannedAt(event.target.value)} /></label>
        </div>
        {previewMediaUrl && preset ? (
          <section className="release-cover-preview" aria-label="封面和平台安全区预览">
            <div className="release-cover-frame">
              <video
                ref={coverVideoRef}
                src={previewMediaUrl}
                preload="metadata"
                muted
                playsInline
                controls
              />
              <div
                className="release-safe-zone"
                style={{
                  inset: `${preset.safe_zone.top * 100}% ${preset.safe_zone.right * 100}% ${preset.safe_zone.bottom * 100}% ${preset.safe_zone.left * 100}%`,
                }}
              >
                <span>平台安全区预览</span>
              </div>
            </div>
            <div>
              <strong>{release.caption_mode === "burned" ? "最终成片" : "干净代理"}封面帧与平台遮挡检查</strong>
              <p>拖动视频复核画面；“定位封面帧”会跳到当前设置的片段内时间。安全区是保守编辑参考，发布前仍需在目标账号确认。</p>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  const video = coverVideoRef.current;
                  if (!video) return;
                  const requested = Number(coverSeconds || "0");
                  video.currentTime = Math.max(
                    0,
                    Math.min(
                      Number.isFinite(requested) ? requested : 0,
                      video.duration || requested,
                    ),
                  );
                }}
              >
                定位封面帧（{coverSeconds || "0"} 秒）
              </button>
            </div>
          </section>
        ) : <p className="notice notice-error">当前字幕模式没有可验证的成片预览；生成对应渲染后才能确认首帧和封面。</p>}
        <fieldset className="release-checklist" disabled={!canManage || !canUpdate}>
          <legend>发布前人工确认</legend>
          {Object.entries(CHECKLIST_LABELS).map(([name, label]) => (
            <label key={name}><input type="checkbox" checked={checklist[name as keyof ReleaseChecklist]} disabled={name === "first_frame_confirmed" && !previewMediaUrl} onChange={(event) => setChecklist((value) => ({ ...value, [name]: event.target.checked }))} />{label}</label>
          ))}
        </fieldset>
        {canManage && canUpdate ? <button type="button" className="button button-primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? "保存中…" : canSyncStale ? "同步到当前剪辑版本" : "保存发布设置"}</button> : null}
      </details>

      <section className={`release-preflight ${release.preflight.passed ? "release-preflight-pass" : "release-preflight-blocked"}`}>
        <div><strong>{release.preflight.passed ? "发布预检通过" : `${release.preflight.blocker_count} 项阻塞`}</strong><span>{release.preflight.warning_count} 项提醒</span></div>
        <ul>{release.preflight.checks.filter((check) => check.outcome !== "passed").map((check) => <li key={check.code} data-outcome={check.outcome}>{check.message}</li>)}</ul>
        {preset ? <p>推荐 {preset.recommended_width}×{preset.recommended_height} · 安全区：上 {Math.round(preset.safe_zone.top * 100)}% / 下 {Math.round(preset.safe_zone.bottom * 100)}%</p> : null}
      </section>

      {mutable ? (
        <section className="release-approval-actions">
          <label>审核或状态说明<input value={approvalReason} maxLength={1_000} onChange={(event) => setApprovalReason(event.target.value)} placeholder="提交、批准或退回时必填" /></label>
          <div className="button-row">
            {canManage && ["draft", "changes_requested"].includes(release.approval_status) ? <button type="button" className="button button-secondary" disabled={!approvalReason.trim() || approvalMutation.isPending || release.stale} onClick={() => approvalMutation.mutate("pending_review")}>提交发布审核</button> : null}
            {canManage && release.approval_status === "pending_review" ? <button type="button" className="button button-ghost" disabled={!approvalReason.trim() || approvalMutation.isPending || release.stale} onClick={() => approvalMutation.mutate("draft")}>撤回审核</button> : null}
            {canApprove && release.approval_status === "pending_review" ? <><button type="button" className="button button-primary" disabled={!approvalReason.trim() || approvalMutation.isPending || release.stale} onClick={() => approvalMutation.mutate("approved")}>批准发布</button><button type="button" className="button button-danger-ghost" disabled={!approvalReason.trim() || approvalMutation.isPending || release.stale} onClick={() => approvalMutation.mutate("changes_requested")}>退回修改</button></> : null}
            {canApprove && release.approval_status === "approved" ? <button type="button" className="button button-danger-ghost" disabled={!approvalReason.trim() || approvalMutation.isPending || release.stale} onClick={() => approvalMutation.mutate("changes_requested")}>撤销批准并退回修改</button> : null}
            {canManage && release.approval_status === "approved" && release.status === "draft" ? <button type="button" className="button button-primary" disabled={!release.preflight.passed || statusMutation.isPending || release.stale} onClick={() => statusMutation.mutate("ready")}>标记可发布</button> : null}
            {canManage && release.status === "ready" && release.planned_publish_at ? <button type="button" className="button button-secondary" disabled={statusMutation.isPending || release.stale} onClick={() => statusMutation.mutate("scheduled_external")}>记录外部排期</button> : null}
          </div>
        </section>
      ) : null}

      {["ready", "scheduled_external"].includes(release.status) ? (
        <section className="release-package-actions">
          <div><strong>平台交付包</strong><p>始终生成可完整下载的 ZIP，包含平台视频、封面、发布文案、清单和校验信息。</p></div>
          <button type="button" className="button button-primary" disabled={!canManage || !release.preflight.passed || packageInFlight || release.stale} onClick={() => packageMutation.mutate()}>{packageInFlight ? "正在生成…" : "生成平台包"}</button>
        </section>
      ) : null}
      {packageQuery.data ? <div className={`notice ${packageQuery.data.release_package.status === "failed" ? "notice-error" : ""}`}><StatusBadge status={packageQuery.data.release_package.status} /><span>{packageQuery.data.release_package.package_version}</span>{packageQuery.data.release_package.safe_error_message ? <span>{packageQuery.data.release_package.safe_error_message}</span> : null}{packageQuery.data.download_url ? <a className="button button-primary" href={packageQuery.data.download_url} download>{packageQuery.data.download_kind === "zip" ? "下载平台 ZIP" : "下载 Manifest"}</a> : null}{packageQuery.data.release_package.status === "failed" && canManage && ["ready", "scheduled_external"].includes(release.status) && !release.stale ? <button type="button" className="button button-secondary" disabled={packageInFlight} onClick={() => packageMutation.mutate()}>重试生成新版本</button> : null}</div> : null}
      {release.packages.length > 0 ? <ul className="release-package-history">{release.packages.map((item) => <li key={item.release_package_id}><span>{item.package_version}</span><StatusBadge status={item.status} /><span>{item.published_artifact ? "已发布使用" : item.current ? "当前版本" : "历史版本"}</span>{item.safe_error_message ? <span className="form-error">{item.safe_error_message}</span> : null}{item.status === "succeeded" ? <button type="button" className="button button-ghost" onClick={() => setActivePackageId(item.release_package_id)}>查看下载</button> : null}{item.status === "failed" && canManage && ["ready", "scheduled_external"].includes(release.status) && !release.stale ? <button type="button" className="button button-ghost" disabled={packageInFlight} onClick={() => packageMutation.mutate()}>重试生成新版本</button> : null}{item.release_package_id === packageQuery.data?.release_package.release_package_id && packageQuery.data.download_url ? <a href={packageQuery.data.download_url} download>下载</a> : null}</li>)}</ul> : null}

      {["ready", "scheduled_external"].includes(release.status) && canManage ? (
        <details className="release-publish-evidence">
          <summary>记录外部发布结果</summary>
          <div className="release-editor-grid"><label>实际发布包<select aria-label="实际发布包" value={publicationPackageId} onChange={(event) => setPublicationPackageId(event.target.value)}><option value="">请选择当前成功包</option>{currentSucceededPackages.map((item) => <option key={item.release_package_id} value={item.release_package_id}>{item.package_version} · 视频 {item.video_sha256.slice(0, 12)}…</option>)}</select></label><label>实际发布时间<input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} /></label><label>发布链接<input type="url" value={externalUrl} placeholder="https://…" onChange={(event) => setExternalUrl(event.target.value)} /></label><label>平台内容 ID<input value={externalId} onChange={(event) => setExternalId(event.target.value)} /></label><label className="release-wide">结果说明<textarea value={resultNotes} onChange={(event) => setResultNotes(event.target.value)} /></label></div>
          <button type="button" className="button button-primary" disabled={statusMutation.isPending || !publicationPackageId || !publishedAt || (!externalUrl.trim() && !externalId.trim()) || !["ready_to_publish", "published"].includes(project.lifecycle)} onClick={() => statusMutation.mutate("published")}>确认已在外部发布</button>
          {currentSucceededPackages.length === 0 ? <p className="hint">先生成并完成当前版本的平台 ZIP，才能记录发布。</p> : null}
          {!['ready_to_publish', 'published'].includes(project.lifecycle) ? <p className="hint">先在“任务与生命周期”中将项目推进到“待发布”。</p> : null}
        </details>
      ) : null}

      {release.status === "published" ? (
        <details className="release-metrics">
          <summary>记录发布效果</summary>
          <form onSubmit={submitMetric}><label>播放<input name="views" type="number" min="0" defaultValue="0" /></label><label>点赞<input name="likes" type="number" min="0" defaultValue="0" /></label><label>评论<input name="comments" type="number" min="0" defaultValue="0" /></label><label>分享<input name="shares" type="number" min="0" defaultValue="0" /></label><label>收藏<input name="saves" type="number" min="0" defaultValue="0" /></label><label>新增关注<input name="followers_gained" type="number" min="0" defaultValue="0" /></label><label className="release-wide">备注<input name="notes" /></label><button className="button button-secondary" type="submit" disabled={!canManage || metricMutation.isPending}>保存效果快照</button></form>
          {release.metrics.length > 0 ? <table><thead><tr><th>采集时间</th><th>播放</th><th>点赞</th><th>评论</th><th>分享</th><th>收藏</th><th>新增关注</th></tr></thead><tbody>{release.metrics.map((metric) => <tr key={metric.metric_id}><td>{new Date(metric.captured_at).toLocaleString("zh-CN")}</td><td>{metric.views.toLocaleString()}</td><td>{metric.likes.toLocaleString()}</td><td>{metric.comments.toLocaleString()}</td><td>{metric.shares.toLocaleString()}</td><td>{metric.saves.toLocaleString()}</td><td>{metric.followers_gained.toLocaleString()}</td></tr>)}</tbody></table> : <p className="hint">尚未记录发布效果。</p>}
        </details>
      ) : null}
      {canManage && release.status !== "withdrawn" ? (
        <details className="release-exception-actions">
          <summary>异常、重试与撤回</summary>
          <label>
            操作说明
            <textarea
              value={resultNotes}
              maxLength={2_000}
              placeholder="说明失败原因、重试背景或撤回原因"
              onChange={(event) => setResultNotes(event.target.value)}
            />
          </label>
          <div className="button-row">
            {["ready", "scheduled_external"].includes(release.status) ? (
              <button
                type="button"
                className="button button-danger-ghost"
                disabled={!resultNotes.trim() || statusMutation.isPending}
                onClick={() => statusMutation.mutate("failed")}
              >
                记录发布失败
              </button>
            ) : null}
            {["ready", "scheduled_external", "failed"].includes(release.status) ? (
              <button
                type="button"
                className="button button-secondary"
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate("draft")}
              >
                返回准备中
              </button>
            ) : null}
            <button
              type="button"
              className="button button-danger-ghost"
              disabled={!resultNotes.trim() || statusMutation.isPending}
              onClick={() => statusMutation.mutate("withdrawn")}
            >
              撤回发布任务
            </button>
          </div>
        </details>
      ) : null}
      {errors.length > 0 ? <p className="form-error" role="alert">{errorMessage(errors[0])}</p> : null}
    </article>
  );
}

export function ReleaseWorkspace({
  api,
  project,
  clips,
  onProjectChanged,
}: {
  api: LiveClipApiClient;
  project: ProjectSnapshot;
  clips: ClipSummaryResponse[];
  onProjectChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [view, setView] = useState<ReleaseView>("queue");
  const presetsQuery = useQuery({
    queryKey: ["release-presets"],
    queryFn: () => api.listReleasePresets(),
    staleTime: 24 * 60 * 60_000,
  });
  const releasesQuery = useQuery({
    queryKey: ["releases", project.project_id],
    queryFn: () => api.listReleaseItems(project.project_id),
    refetchInterval: (query) => {
      const releases = query.state.data?.releases ?? [];
      const active = releases.some((release) => release.packages.some((item) => item.status === "queued" || item.status === "creating"));
      return active
        ? 1_000
        : signedUrlRefreshInterval(
            Object.values(query.state.data?.preview_media_urls ?? {}),
          );
    },
  });
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["releases", project.project_id] });
    onProjectChanged();
  }, [onProjectChanged, project.project_id, queryClient]);
  const releases = releasesQuery.data?.releases ?? [];
  const groups = useMemo(() => {
    if (view === "calendar") {
      const values = new Map<string, ReleaseItemSnapshot[]>();
      for (const release of releases) {
        const label = calendarLabel(release.planned_publish_at);
        values.set(label, [...(values.get(label) ?? []), release]);
      }
      return [...values.entries()];
    }
    const order: ReleaseItemStatus[] = ["draft", "ready", "scheduled_external", "failed", "published", "withdrawn"];
    return order.map((status) => [RELEASE_STATUS_LABELS[status], releases.filter((item) => item.status === status)] as const).filter(([, values]) => values.length > 0);
  }, [releases, view]);
  const counts = {
    pending: releases.filter((item) => item.approval_status === "pending_review").length,
    ready: releases.filter((item) => item.status === "ready").length,
    scheduled: releases.filter((item) => item.status === "scheduled_external").length,
    published: releases.filter((item) => item.status === "published").length,
  };

  return (
    <section className="panel release-workspace" aria-labelledby="release-workspace-title">
      <div className="section-heading release-workspace-heading">
        <div><p className="eyebrow">短视频发布运营</p><h2 id="release-workspace-title">发布队列</h2><p>同一高光可面向不同平台和账号建立独立任务；LiveClip 只记录外部发布结果，不代替平台上传。</p></div>
        <ReleaseCreatePanel api={api} project={project} clips={clips} presets={presetsQuery.data?.presets ?? []} currentVersions={presetsQuery.data?.current_versions ?? {}} onCreated={refresh} />
      </div>
      <div className="release-stats"><span><strong>{counts.pending}</strong> 待发布审核</span><span><strong>{counts.ready}</strong> 可发布</span><span><strong>{counts.scheduled}</strong> 已排期</span><span><strong>{counts.published}</strong> 已发布</span></div>
      <div className="release-view-switch" role="group" aria-label="发布任务视图"><button type="button" aria-pressed={view === "queue"} onClick={() => setView("queue")}>队列</button><button type="button" aria-pressed={view === "calendar"} onClick={() => setView("calendar")}>日历</button><button type="button" className="button button-ghost" onClick={() => void releasesQuery.refetch()}>刷新</button></div>
      {presetsQuery.isPending || releasesQuery.isPending ? <LoadingState>正在加载发布计划…</LoadingState> : null}
      {presetsQuery.isError ? <ErrorState error={presetsQuery.error} onRetry={() => void presetsQuery.refetch()} /> : null}
      {releasesQuery.isError ? <ErrorState error={releasesQuery.error} onRetry={() => void releasesQuery.refetch()} /> : null}
      {releasesQuery.data?.releases.length === 0 ? <EmptyState title="还没有发布任务">从未拒绝的高光时刻建立第一个平台发布任务。</EmptyState> : null}
      {groups.map(([label, values]) => <section className="release-group" key={label}><h3>{label}<span>{values.length}</span></h3><div className="release-card-list">{values.map((release) => <ReleaseCard key={release.release_item_id} api={api} project={project} release={release} preset={platformPreset(presetsQuery.data?.presets ?? [], release.platform, release.preset_version)} previewMediaUrl={releasesQuery.data?.preview_media_urls?.[release.release_item_id]} onChanged={refresh} />)}</div></section>)}
    </section>
  );
}
