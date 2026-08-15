# ruff: noqa: RUF001
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.edit_plan import CaptionCue


class ReleasePlatform(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    BILIBILI_VERTICAL = "bilibili_vertical"
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    GENERIC_VERTICAL = "generic_vertical"


class ReleaseCaptionMode(StrEnum):
    CLEAN_SEPARATE = "clean_separate"
    BURNED = "burned"


class ReleaseApprovalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class ReleaseItemStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SCHEDULED_EXTERNAL = "scheduled_external"
    PUBLISHED = "published"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"


class ReleasePackageStatus(StrEnum):
    QUEUED = "queued"
    CREATING = "creating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReleaseTransitionError(ValueError):
    """A release workflow transition is not legal."""


class ReleaseChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    hook_confirmed: bool = False
    first_frame_confirmed: bool = False
    subtitles_confirmed: bool = False
    music_rights_confirmed: bool = False
    likeness_confirmed: bool = False
    personal_data_confirmed: bool = False
    claims_confirmed: bool = False
    sponsorship_confirmed: bool = False
    platform_policy_confirmed: bool = False

    @property
    def complete(self) -> bool:
        return all(self.model_dump().values())

    @property
    def incomplete_fields(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.model_dump().items() if not value)


class ReleaseSafeZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    top: float = Field(ge=0, le=0.4)
    right: float = Field(ge=0, le=0.4)
    bottom: float = Field(ge=0, le=0.4)
    left: float = Field(ge=0, le=0.4)
    basis: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_visible_area(self) -> ReleaseSafeZone:
        if self.top + self.bottom >= 0.8 or self.left + self.right >= 0.8:
            raise ValueError("release safe zone leaves no useful visible area")
        return self


class PlatformPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    platform: ReleasePlatform
    version: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
    checked_at: date
    label: str = Field(min_length=1, max_length=80)
    recommended_width: int = Field(ge=360, le=4096)
    recommended_height: int = Field(ge=640, le=4096)
    minimum_width: int = Field(ge=2, le=4096)
    minimum_height: int = Field(ge=2, le=4096)
    maximum_dimension: int | None = Field(default=None, ge=360, le=8192)
    maximum_duration_ms: int | None = Field(default=None, gt=0)
    maximum_file_bytes: int | None = Field(default=None, gt=0)
    safe_zone: ReleaseSafeZone
    account_policy_confirmation_required: bool = True
    policy_notes: tuple[str, ...] = Field(min_length=1, max_length=12)
    official_sources: tuple[str, ...] = Field(min_length=1, max_length=8)

    @property
    def preset_id(self) -> str:
        return f"{self.platform.value}@{self.version}"


class ReleaseMediaFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    available: bool
    trusted_render_contract: bool
    container: str
    video_codec: str
    audio_codec: str
    pixel_format: str
    progressive: bool
    fast_start: bool
    full_decode: bool
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    size_bytes: int = Field(ge=0)
    separate_subtitle_available: bool
    format_evidence: Literal[
        "actual_bytes",
        "trusted_render_contract",
        "unavailable",
    ]


class ReleaseDuplicateContentMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reference_id: str = Field(min_length=1, max_length=80)
    reference_label: str = Field(min_length=1, max_length=160)
    evidence_kind: Literal[
        "release_package",
        "published",
        "edit_package",
        "delivery",
    ]
    source_overlap_ratio: float = Field(ge=0, le=1)
    text_similarity: float = Field(ge=0, le=1)


class ReleaseEditorialFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected_revision: int = Field(ge=1)
    current_revision: int = Field(ge=1)
    clip_review_approved: bool
    release_approval: ReleaseApprovalStatus
    title: str = Field(max_length=100)
    description: str = Field(max_length=5_000)
    hashtags: tuple[str, ...] = Field(max_length=20)
    cover_time_ms: int = Field(ge=0)
    caption_mode: ReleaseCaptionMode
    captions: tuple[CaptionCue, ...]
    risk_flags: tuple[str, ...] = Field(max_length=16)
    checklist: ReleaseChecklist
    current_project_run: bool
    duplicate_content_matches: tuple[ReleaseDuplicateContentMatch, ...] = ()


class ReleasePreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(pattern=r"^[a-z0-9_]{2,80}$")
    category: str = Field(pattern=r"^[a-z_]{2,40}$")
    outcome: str = Field(pattern=r"^(passed|blocked|warning|info)$")
    message: str = Field(min_length=1, max_length=500)


class ReleasePreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = "liveclip.release-preflight.v1"
    preset_id: str
    checked_at: date
    passed: bool
    blocker_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    checks: tuple[ReleasePreflightCheck, ...] = Field(min_length=1)


_ITEM_TRANSITIONS: dict[ReleaseItemStatus, frozenset[ReleaseItemStatus]] = {
    ReleaseItemStatus.DRAFT: frozenset({ReleaseItemStatus.READY, ReleaseItemStatus.WITHDRAWN}),
    ReleaseItemStatus.READY: frozenset(
        {
            ReleaseItemStatus.DRAFT,
            ReleaseItemStatus.SCHEDULED_EXTERNAL,
            ReleaseItemStatus.PUBLISHED,
            ReleaseItemStatus.FAILED,
            ReleaseItemStatus.WITHDRAWN,
        }
    ),
    ReleaseItemStatus.SCHEDULED_EXTERNAL: frozenset(
        {
            ReleaseItemStatus.DRAFT,
            ReleaseItemStatus.PUBLISHED,
            ReleaseItemStatus.FAILED,
            ReleaseItemStatus.WITHDRAWN,
        }
    ),
    ReleaseItemStatus.FAILED: frozenset({ReleaseItemStatus.DRAFT, ReleaseItemStatus.WITHDRAWN}),
    ReleaseItemStatus.PUBLISHED: frozenset({ReleaseItemStatus.WITHDRAWN}),
    ReleaseItemStatus.WITHDRAWN: frozenset(),
}

_APPROVAL_TRANSITIONS: dict[ReleaseApprovalStatus, frozenset[ReleaseApprovalStatus]] = {
    ReleaseApprovalStatus.DRAFT: frozenset({ReleaseApprovalStatus.PENDING_REVIEW}),
    ReleaseApprovalStatus.PENDING_REVIEW: frozenset(
        {
            ReleaseApprovalStatus.DRAFT,
            ReleaseApprovalStatus.APPROVED,
            ReleaseApprovalStatus.CHANGES_REQUESTED,
        }
    ),
    ReleaseApprovalStatus.CHANGES_REQUESTED: frozenset(
        {ReleaseApprovalStatus.DRAFT, ReleaseApprovalStatus.PENDING_REVIEW}
    ),
    ReleaseApprovalStatus.APPROVED: frozenset(
        {ReleaseApprovalStatus.DRAFT, ReleaseApprovalStatus.CHANGES_REQUESTED}
    ),
}

_PACKAGE_TRANSITIONS: dict[ReleasePackageStatus, frozenset[ReleasePackageStatus]] = {
    ReleasePackageStatus.QUEUED: frozenset(
        {ReleasePackageStatus.CREATING, ReleasePackageStatus.FAILED}
    ),
    ReleasePackageStatus.CREATING: frozenset(
        {ReleasePackageStatus.SUCCEEDED, ReleasePackageStatus.FAILED}
    ),
    ReleasePackageStatus.FAILED: frozenset({ReleasePackageStatus.QUEUED}),
    ReleasePackageStatus.SUCCEEDED: frozenset(),
}


def transition_release_item(current: ReleaseItemStatus, target: ReleaseItemStatus) -> None:
    _require_transition(current, target, _ITEM_TRANSITIONS, resource="ReleaseItem")


def transition_release_approval(
    current: ReleaseApprovalStatus,
    target: ReleaseApprovalStatus,
) -> None:
    _require_transition(current, target, _APPROVAL_TRANSITIONS, resource="ReleaseApproval")


def transition_release_package(
    current: ReleasePackageStatus,
    target: ReleasePackageStatus,
) -> None:
    _require_transition(current, target, _PACKAGE_TRANSITIONS, resource="ReleasePackage")


_ReleaseStatusT = TypeVar("_ReleaseStatusT", bound=StrEnum)


def _require_transition(
    current: _ReleaseStatusT,
    target: _ReleaseStatusT,
    allowed: Mapping[_ReleaseStatusT, frozenset[_ReleaseStatusT]],
    *,
    resource: str,
) -> None:
    if current == target:
        raise ReleaseTransitionError(f"{resource} is already in state {current.value}")
    if target not in allowed[current]:
        raise ReleaseTransitionError(
            f"illegal {resource} transition: {current.value} -> {target.value}"
        )


_PRESET_VERSION = "2026-08-15.1"
_CHECKED_AT = date(2026, 8, 15)
_YOUTUBE_ENCODING = "https://support.google.com/youtube/answer/1722171"
_YOUTUBE_SHORTS = "https://support.google.com/youtube/answer/15424877"
_TIKTOK_TRANSFER = "https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide"
_LIVECLIP_RESEARCH = "docs/research/editor-handoff-platforms.md"


def _safe_zone(*, top: float, right: float, bottom: float, left: float) -> ReleaseSafeZone:
    return ReleaseSafeZone(
        top=top,
        right=right,
        bottom=bottom,
        left=left,
        basis=(
            "LiveClip conservative editorial overlay; verify against the current "
            "account and platform composer before publication"
        ),
    )


_PLATFORM_PRESET_HISTORY: tuple[PlatformPreset, ...] = (
    PlatformPreset(
        platform=ReleasePlatform.DOUYIN,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="抖音竖屏",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=640,
        safe_zone=_safe_zone(top=0.08, right=0.18, bottom=0.22, left=0.06),
        policy_notes=(
            "发布前在当前抖音账号确认时长、大小、音乐和商业内容规则。",
            "本预设未把无法从公开官方资料稳定核验的账号数值写成硬限制。",
        ),
        official_sources=(_LIVECLIP_RESEARCH,),
    ),
    PlatformPreset(
        platform=ReleasePlatform.XIAOHONGSHU,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="小红书竖屏",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=640,
        safe_zone=_safe_zone(top=0.10, right=0.10, bottom=0.20, left=0.08),
        policy_notes=(
            "发布前在当前小红书账号确认时长、大小、封面和商业内容规则。",
            "标题、正文和话题均保持可编辑，不由 LiveClip 自动发布。",
        ),
        official_sources=(_LIVECLIP_RESEARCH,),
    ),
    PlatformPreset(
        platform=ReleasePlatform.BILIBILI_VERTICAL,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="哔哩哔哩竖屏",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=640,
        safe_zone=_safe_zone(top=0.08, right=0.10, bottom=0.16, left=0.08),
        policy_notes=(
            "发布前在创作中心确认当前分区、账号、时长和大小规则。",
            "本预设只硬校验通用可移植媒体合同。",
        ),
        official_sources=(_LIVECLIP_RESEARCH,),
    ),
    PlatformPreset(
        platform=ReleasePlatform.YOUTUBE_SHORTS,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="YouTube Shorts",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=640,
        maximum_duration_ms=180_000,
        safe_zone=_safe_zone(top=0.08, right=0.16, bottom=0.20, left=0.06),
        policy_notes=(
            "竖屏或方形视频最长三分钟；超过一分钟时必须重点复核音乐权利。",
            "编码基线采用 MP4/H.264/AAC、逐行、4:2:0 与 Fast Start。",
        ),
        official_sources=(_YOUTUBE_SHORTS, _YOUTUBE_ENCODING),
    ),
    PlatformPreset(
        platform=ReleasePlatform.TIKTOK,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="TikTok",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=360,
        maximum_dimension=4096,
        maximum_file_bytes=4 * 1024 * 1024 * 1024,
        safe_zone=_safe_zone(top=0.08, right=0.18, bottom=0.22, left=0.06),
        policy_notes=(
            "官方传输接口的初始化上限不代表当前账号可发布时长。",
            "LiveClip 不保存 TikTok 凭证，也不自动调用发布接口。",
        ),
        official_sources=(_TIKTOK_TRANSFER,),
    ),
    PlatformPreset(
        platform=ReleasePlatform.GENERIC_VERTICAL,
        version=_PRESET_VERSION,
        checked_at=_CHECKED_AT,
        label="通用竖屏",
        recommended_width=1080,
        recommended_height=1920,
        minimum_width=360,
        minimum_height=640,
        safe_zone=_safe_zone(top=0.08, right=0.08, bottom=0.12, left=0.08),
        policy_notes=("通用预设只证明媒体可移植性；发布前仍需核对目标平台和账号。",),
        official_sources=(_YOUTUBE_ENCODING,),
    ),
)


class PlatformPresetRegistry:
    """Append-only version registry with an explicit current version per platform."""

    def __init__(
        self,
        presets: tuple[PlatformPreset, ...],
        current_versions: Mapping[ReleasePlatform, str],
    ) -> None:
        by_id = {preset.preset_id: preset for preset in presets}
        if len(by_id) != len(presets):
            raise ValueError("release platform preset IDs must be unique")
        preset_platforms = {preset.platform for preset in presets}
        if preset_platforms != set(current_versions):
            raise ValueError("every release platform must have one declared current version")
        for platform, version in current_versions.items():
            if f"{platform.value}@{version}" not in by_id:
                raise ValueError("current release platform preset version does not exist")
        self._by_id = by_id
        self._current_versions = dict(current_versions)

    def list_current(self) -> tuple[PlatformPreset, ...]:
        return tuple(self.get(platform) for platform in self._current_versions)

    def list_all(self) -> tuple[PlatformPreset, ...]:
        return tuple(self._by_id.values())

    def current_versions(self) -> dict[ReleasePlatform, str]:
        return dict(self._current_versions)

    def get(
        self,
        platform: ReleasePlatform,
        *,
        version: str | None = None,
    ) -> PlatformPreset:
        selected_version = version or self._current_versions.get(platform)
        if selected_version is None:
            raise LookupError("release platform preset does not exist")
        preset = self._by_id.get(f"{platform.value}@{selected_version}")
        if preset is None:
            raise LookupError("release platform preset does not exist")
        return preset


_CURRENT_PRESET_VERSIONS: dict[ReleasePlatform, str] = {
    platform: _PRESET_VERSION for platform in ReleasePlatform
}
_PRESET_REGISTRY = PlatformPresetRegistry(
    _PLATFORM_PRESET_HISTORY,
    _CURRENT_PRESET_VERSIONS,
)


def list_platform_presets(*, include_historical: bool = False) -> tuple[PlatformPreset, ...]:
    return _PRESET_REGISTRY.list_all() if include_historical else _PRESET_REGISTRY.list_current()


def current_platform_preset_versions() -> dict[ReleasePlatform, str]:
    return _PRESET_REGISTRY.current_versions()


def get_platform_preset(
    platform: ReleasePlatform,
    *,
    version: str | None = None,
) -> PlatformPreset:
    return _PRESET_REGISTRY.get(platform, version=version)


def evaluate_release_preflight(
    *,
    preset: PlatformPreset,
    media: ReleaseMediaFacts,
    editorial: ReleaseEditorialFacts,
) -> ReleasePreflight:
    checks: list[ReleasePreflightCheck] = []

    def add(code: str, category: str, outcome: str, message: str) -> None:
        checks.append(
            ReleasePreflightCheck(
                code=code,
                category=category,
                outcome=outcome,
                message=message,
            )
        )

    add(
        "current_project_run",
        "revision",
        "passed" if editorial.current_project_run else "blocked",
        "剪辑属于项目当前处理代次。"
        if editorial.current_project_run
        else "项目已切换处理代次，请重新建立发布任务。",
    )
    add(
        "current_revision",
        "revision",
        "passed" if editorial.selected_revision == editorial.current_revision else "blocked",
        "发布任务绑定当前剪辑 revision。"
        if editorial.selected_revision == editorial.current_revision
        else "剪辑 revision 已变化，请更新发布任务后重新审核。",
    )
    add(
        "clip_review",
        "approval",
        "passed" if editorial.clip_review_approved else "blocked",
        "当前剪辑已通过内容审核。"
        if editorial.clip_review_approved
        else "当前剪辑尚未通过内容审核。",
    )
    add(
        "release_approval",
        "approval",
        "passed" if editorial.release_approval is ReleaseApprovalStatus.APPROVED else "blocked",
        "发布文案与设置已通过发布审核。"
        if editorial.release_approval is ReleaseApprovalStatus.APPROVED
        else "发布文案与设置尚未通过发布审核。",
    )
    add(
        "human_checklist",
        "editorial",
        "passed" if editorial.checklist.complete else "blocked",
        "Hook、首帧、字幕、权利、隐私、声明、赞助和平台规则均已人工确认。"
        if editorial.checklist.complete
        else "仍需人工确认：" + "、".join(editorial.checklist.incomplete_fields),
    )
    add(
        "trusted_media",
        "media",
        "passed" if media.available and media.trusted_render_contract else "blocked",
        "媒体来自当前受信任渲染及已提交 Asset。"
        if media.available and media.trusted_render_contract
        else "所选字幕模式没有当前受信任媒体，请先完成相应渲染。",
    )
    format_ok = (
        media.container == "mp4"
        and media.video_codec == "h264"
        and media.audio_codec == "aac"
        and media.pixel_format == "yuv420p"
        and media.progressive
        and media.fast_start
        and media.full_decode
    )
    format_message = (
        "交付媒体字节已验证 MP4/H.264/AAC、逐行、4:2:0、Fast Start 与完整解码。"
        if media.format_evidence == "actual_bytes"
        else (
            "当前媒体通过可信渲染合同及容器、编解码与完整解码检查；"
            "生成平台包时仍会重新验证实际字节。"
            if media.format_evidence == "trusted_render_contract"
            else "当前没有可验证的媒体格式证据。"
        )
    )
    add(
        "portable_media_format",
        "media",
        "passed" if format_ok else "blocked",
        format_message
        if format_ok
        else "媒体未满足 MP4/H.264/AAC、逐行、4:2:0、Fast Start 或完整解码要求。",
    )
    dimensions_ok = (
        media.width >= preset.minimum_width
        and media.height >= preset.minimum_height
        and media.height > media.width
        and (
            preset.maximum_dimension is None
            or max(media.width, media.height) <= preset.maximum_dimension
        )
    )
    add(
        "dimensions",
        "media",
        "passed" if dimensions_ok else "blocked",
        f"竖屏尺寸 {media.width}×{media.height} 满足预设硬条件。"
        if dimensions_ok
        else f"竖屏尺寸 {media.width}×{media.height} 不满足预设硬条件。",
    )
    if dimensions_ok and (
        media.width < preset.recommended_width or media.height < preset.recommended_height
    ):
        add(
            "recommended_dimensions",
            "media",
            "warning",
            f"建议使用 {preset.recommended_width}×{preset.recommended_height}；当前媒体仍可导出。",
        )
    else:
        add(
            "recommended_dimensions",
            "media",
            "passed",
            "媒体达到预设推荐尺寸。",
        )
    duration_ok = (
        preset.maximum_duration_ms is None or media.duration_ms <= preset.maximum_duration_ms
    )
    add(
        "duration",
        "media",
        "passed" if duration_ok else "blocked",
        "片段时长满足已核验的预设硬限制。" if duration_ok else "片段时长超过已核验的预设硬限制。",
    )
    size_ok = preset.maximum_file_bytes is None or media.size_bytes <= preset.maximum_file_bytes
    add(
        "file_size",
        "media",
        "passed" if size_ok else "blocked",
        "媒体大小满足已核验的预设硬限制。" if size_ok else "媒体大小超过已核验的预设硬限制。",
    )
    cover_ok = editorial.cover_time_ms < media.duration_ms
    add(
        "cover_time",
        "editorial",
        "passed" if cover_ok else "blocked",
        "封面时间位于片段范围内。" if cover_ok else "封面时间超出片段范围。",
    )
    add(
        "title",
        "editorial",
        "passed" if editorial.title.strip() else "blocked",
        "发布标题已填写。" if editorial.title.strip() else "发布标题不能为空。",
    )
    if editorial.caption_mode is ReleaseCaptionMode.CLEAN_SEPARATE:
        add(
            "separate_subtitles",
            "captions",
            "passed" if media.separate_subtitle_available else "blocked",
            "独立 UTF-8 SRT 可随包交付。"
            if media.separate_subtitle_available
            else "独立字幕模式缺少当前 SRT。",
        )
    else:
        add(
            "burned_captions",
            "captions",
            "passed" if media.available else "blocked",
            "烧录字幕媒体可用。" if media.available else "烧录字幕媒体尚未生成。",
        )
    readability_warnings = _caption_readability_warnings(editorial.captions)
    add(
        "subtitle_readability",
        "captions",
        "warning" if readability_warnings else "passed",
        "；".join(readability_warnings)
        if readability_warnings
        else "字幕时长、行数、行宽和重叠检查通过。",
    )
    if preset.platform is ReleasePlatform.YOUTUBE_SHORTS and media.duration_ms > 60_000:
        add(
            "youtube_music_rights_over_60s",
            "rights",
            "warning",
            "该 Short 超过一分钟；有有效 Content ID 声明时可能被全局屏蔽。",
        )
    if editorial.risk_flags:
        add(
            "ai_risk_flags",
            "rights",
            "warning",
            "AI 风险标签仅供人工复核：" + "、".join(editorial.risk_flags),
        )
    else:
        add("ai_risk_flags", "rights", "passed", "当前 revision 没有 AI 风险标签。")
    if editorial.duplicate_content_matches:
        strongest = max(
            editorial.duplicate_content_matches,
            key=lambda item: (item.source_overlap_ratio, item.text_similarity),
        )
        add(
            "duplicate_content",
            "editorial",
            "warning",
            (
                f"发现 {len(editorial.duplicate_content_matches)} 个已导出或已发布内容可能重复；"
                f"最强匹配：{strongest.reference_label}；"
                f"最高源区间重叠 {strongest.source_overlap_ratio:.0%}，"
                f"文本相似 {strongest.text_similarity:.0%}。"
                "跨平台复用可以继续，但发布前请确认内容排期。"
            ),
        )
    else:
        add(
            "duplicate_content",
            "editorial",
            "passed",
            "未发现与已导出或已发布片段明显重复的内容。",
        )
    add(
        "account_policy",
        "account_policy",
        "info" if editorial.checklist.platform_policy_confirmed else "warning",
        "已记录当前账号与平台规则的人工确认；平台政策仍可能变化。"
        if editorial.checklist.platform_policy_confirmed
        else "必须在目标账号的发布界面核对当前时长、大小和政策。",
    )
    blockers = sum(check.outcome == "blocked" for check in checks)
    warnings = sum(check.outcome == "warning" for check in checks)
    return ReleasePreflight(
        preset_id=preset.preset_id,
        checked_at=preset.checked_at,
        passed=blockers == 0,
        blocker_count=blockers,
        warning_count=warnings,
        checks=tuple(checks),
    )


def _caption_readability_warnings(captions: tuple[CaptionCue, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    previous_end = 0
    for cue in captions:
        duration_ms = cue.end_ms - cue.start_ms
        if cue.start_ms < previous_end:
            warnings.append("字幕存在时间重叠")
        if duration_ms < 600:
            warnings.append("存在短于 0.6 秒的字幕")
        if duration_ms > 7_000:
            warnings.append("存在长于 7 秒的字幕")
        lines = cue.text.splitlines()
        if len(lines) > 2:
            warnings.append("存在超过两行的字幕")
        if any(len(line.strip()) > 22 for line in lines):
            warnings.append("存在单行超过 22 字符的字幕")
        previous_end = max(previous_end, cue.end_ms)
    return tuple(dict.fromkeys(warnings))


__all__ = [
    "PlatformPreset",
    "ReleaseApprovalStatus",
    "ReleaseCaptionMode",
    "ReleaseChecklist",
    "ReleaseDuplicateContentMatch",
    "ReleaseEditorialFacts",
    "ReleaseItemStatus",
    "ReleaseMediaFacts",
    "ReleasePackageStatus",
    "ReleasePlatform",
    "ReleasePreflight",
    "ReleasePreflightCheck",
    "ReleaseSafeZone",
    "ReleaseTransitionError",
    "current_platform_preset_versions",
    "evaluate_release_preflight",
    "get_platform_preset",
    "list_platform_presets",
    "transition_release_approval",
    "transition_release_item",
    "transition_release_package",
]
