"""Internal review of imported dual-profile results (Stage 19b).

These views are for reviewers inside the console: they include internal
evidence (routing status, score, flags, risks, review reason, decision
history). Nothing here is customer-facing; customer views are built only from
``CustomerClipView`` (Stage 19c).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from liveclip.application.dual_profile_imports import (
    DualProfileImportResult,
    DualProfileImportService,
    DualProfileReviewRecord,
    ReviewClipRecord,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    HOOK_MAX_CHARS,
    PROFILE_LABELS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    ClipDecision,
    ClipDecisionAction,
    CustomerText,
    CustomerTextWarning,
    customer_text_warnings,
    effective_customer_text,
    is_deliverable,
    is_selected_for_delivery,
    latest_review_decision,
    strong_customer_text_warnings,
    unacknowledged_strong_warnings,
)

PROFILE_ORDER = (ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON)
ReviewState = Literal["pending", "approved", "rejected"]


class DualProfileImportNotFound(LookupError):
    """The project has no dual-profile import (HTTP 404)."""


class CustomerTextWarningConflict(RuntimeError):
    """Customer text that still has strong warnings would be approved, selected or
    delivered without an explicit acknowledgement (409)."""

    def __init__(
        self,
        warnings: tuple[CustomerTextWarning, ...],
        *,
        clip_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            "customer text still contains reviewer-style notes; rewrite it at approval or "
            "keep it explicitly with acknowledge_warnings"
        )
        self.warnings = warnings
        # Parallel to ``warnings`` when raised for several clips (delivery creation).
        self.clip_ids = clip_ids


class DualProfileTextWarningView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: Literal["title", "hook", "summary"]
    kind: Literal["strong", "narration"]
    start: int
    end: int
    match: str
    message: str


def _warning_views(text: CustomerText) -> tuple[DualProfileTextWarningView, ...]:
    return tuple(
        DualProfileTextWarningView(
            field=value.field,
            kind=value.kind,
            start=value.start,
            end=value.end,
            match=value.match,
            message=value.message,
        )
        for value in customer_text_warnings(text.title, text.hook, text.summary)
    )


class DualProfileDecisionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    action: ClipDecisionAction
    title_override: str | None
    hook_override: str | None
    summary_override: str | None
    actor_username: str
    actor_display_name: str
    decided_at: datetime
    acknowledge_warnings: bool


class DualProfileClipText(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    hook: str
    summary: str


class DualProfileReviewClip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    import_clip_id: str
    candidate_id: str
    profile: ClipProfile
    routed_status: Literal["selected", "manual_review"]
    review_state: ReviewState
    variant_group_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    original: DualProfileClipText
    effective: DualProfileClipText
    has_override: bool
    text_warnings: tuple[DualProfileTextWarningView, ...]
    score: float
    review_reason: str
    quality_flags: tuple[str, ...]
    risk_tags: tuple[str, ...]
    video_asset_id: str
    subtitle_asset_id: str
    deliverable: bool
    selected_for_delivery: bool
    decisions: tuple[DualProfileDecisionView, ...]


class DualProfileReviewGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: ClipProfile
    label: Literal["短片", "小课"]
    clips: tuple[DualProfileReviewClip, ...]


class DualProfileReviewView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    import_id: str
    source_filename: str
    snapshot: str
    algorithm_version: str
    routing_policy_version: str
    clip_count: int
    imported_at: datetime
    imported_by: str
    deliverable_count: int
    selected_count: int
    text_limits: dict[str, int]
    groups: tuple[DualProfileReviewGroup, ...]


class DualProfileReviewRepository(Protocol):
    def load_review(self, *, project_id: str) -> DualProfileReviewRecord | None: ...

    def append_decision(
        self,
        *,
        project_id: str,
        import_clip_id: str,
        acting_user_id: str,
        action: ClipDecisionAction,
        title_override: str | None = None,
        hook_override: str | None = None,
        summary_override: str | None = None,
        require_deliverable: bool = False,
        acknowledge_warnings: bool = False,
        now: datetime,
    ) -> ClipDecision: ...


def decision_permission(action: ClipDecisionAction) -> Literal["review_clip", "deliver"]:
    """approve/reject need ``review_clip``; select/deselect need ``deliver``."""

    if action in {ClipDecisionAction.APPROVE, ClipDecisionAction.REJECT}:
        return "review_clip"
    return "deliver"


class DualProfileReviewService:
    def __init__(
        self,
        repository: DualProfileReviewRepository,
        importer: DualProfileImportService,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._importer = importer
        self._now = now or (lambda: datetime.now(UTC))

    def import_run(
        self,
        *,
        acting_user_id: str,
        run_dir: Path,
        transcript_path: Path,
        project_name: str | None = None,
    ) -> DualProfileImportResult:
        return self._importer.import_run(
            acting_user_id=acting_user_id,
            run_dir=run_dir,
            transcript_path=transcript_path,
            project_name=project_name,
        )

    def get_review(self, project_id: str) -> DualProfileReviewView:
        record = self._repository.load_review(project_id=project_id)
        if record is None:
            raise DualProfileImportNotFound("project has no dual-profile import")
        return _review_view(record)

    def decide(
        self,
        project_id: str,
        import_clip_id: str,
        *,
        acting_user_id: str,
        action: ClipDecisionAction,
        title_override: str | None = None,
        hook_override: str | None = None,
        summary_override: str | None = None,
        acknowledge_warnings: bool = False,
    ) -> DualProfileReviewView:
        record = self._repository.load_review(project_id=project_id)
        if record is None:
            raise DualProfileImportNotFound("project has no dual-profile import")
        clip = next(
            (value for value in record.clips if value.import_clip_id == import_clip_id), None
        )
        if (
            action is ClipDecisionAction.SELECT
            and clip is not None
            and not acknowledge_warnings
            and is_deliverable(clip.routed_status, clip.decisions)
        ):
            pending = unacknowledged_strong_warnings(clip.original_text, clip.decisions)
            if pending:
                raise CustomerTextWarningConflict(pending)
        if action is ClipDecisionAction.APPROVE and clip is not None:
            proposed = CustomerText(
                title=title_override if title_override is not None else clip.original_text.title,
                hook=hook_override if hook_override is not None else clip.original_text.hook,
                summary=(
                    summary_override if summary_override is not None else clip.original_text.summary
                ),
            )
            strong = strong_customer_text_warnings(proposed)
            if strong and not acknowledge_warnings:
                raise CustomerTextWarningConflict(strong)
        self._repository.append_decision(
            project_id=project_id,
            import_clip_id=import_clip_id,
            acting_user_id=acting_user_id,
            action=action,
            title_override=title_override,
            hook_override=hook_override,
            summary_override=summary_override,
            require_deliverable=action is ClipDecisionAction.SELECT,
            acknowledge_warnings=acknowledge_warnings
            and action in {ClipDecisionAction.APPROVE, ClipDecisionAction.SELECT},
            now=self._now(),
        )
        return self.get_review(project_id)


def _review_state(clip: ReviewClipRecord) -> ReviewState:
    latest = latest_review_decision(clip.decisions)
    if latest is None:
        return "pending"
    return "approved" if latest.action is ClipDecisionAction.APPROVE else "rejected"


def _clip_view(clip: ReviewClipRecord) -> DualProfileReviewClip:
    decisions = clip.decisions
    effective = effective_customer_text(clip.original_text, decisions)
    return DualProfileReviewClip(
        import_clip_id=clip.import_clip_id,
        candidate_id=clip.candidate_id,
        profile=clip.profile,
        routed_status=clip.routed_status.value,
        review_state=_review_state(clip),
        variant_group_id=clip.variant_group_id,
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
        duration_ms=clip.duration_ms,
        original=DualProfileClipText(
            title=clip.original_text.title,
            hook=clip.original_text.hook,
            summary=clip.original_text.summary,
        ),
        effective=DualProfileClipText(
            title=effective.title, hook=effective.hook, summary=effective.summary
        ),
        has_override=effective != clip.original_text,
        text_warnings=_warning_views(effective),
        score=clip.score,
        review_reason=clip.review_reason,
        quality_flags=clip.quality_flags,
        risk_tags=clip.risk_tags,
        video_asset_id=clip.video_asset_id,
        subtitle_asset_id=clip.subtitle_asset_id,
        deliverable=is_deliverable(clip.routed_status, decisions),
        selected_for_delivery=is_selected_for_delivery(clip.routed_status, decisions),
        decisions=tuple(
            DualProfileDecisionView(
                sequence=value.decision.sequence,
                action=value.decision.action,
                title_override=value.decision.title_override,
                hook_override=value.decision.hook_override,
                summary_override=value.decision.summary_override,
                actor_username=value.actor_username,
                actor_display_name=value.actor_display_name,
                decided_at=value.decided_at,
                acknowledge_warnings=value.acknowledge_warnings,
            )
            for value in clip.history
        ),
    )


def _review_view(record: DualProfileReviewRecord) -> DualProfileReviewView:
    clips = tuple(
        _clip_view(clip)
        for clip in sorted(
            record.clips,
            key=lambda value: (
                PROFILE_ORDER.index(value.profile),
                value.start_ms,
                value.candidate_id,
            ),
        )
    )
    return DualProfileReviewView(
        project_id=record.project_id,
        import_id=record.import_id,
        source_filename=record.source_filename,
        snapshot=record.snapshot_fingerprint[:20],
        algorithm_version=record.algorithm_version,
        routing_policy_version=record.routing_policy_version,
        clip_count=record.clip_count,
        imported_at=record.imported_at,
        imported_by=record.imported_by,
        deliverable_count=sum(clip.deliverable for clip in clips),
        selected_count=sum(clip.selected_for_delivery for clip in clips),
        text_limits={
            "title": TITLE_MAX_CHARS,
            "hook": HOOK_MAX_CHARS,
            "summary": SUMMARY_MAX_CHARS,
        },
        groups=tuple(
            DualProfileReviewGroup(
                profile=profile,
                label=PROFILE_LABELS[profile],
                clips=tuple(clip for clip in clips if clip.profile is profile),
            )
            for profile in PROFILE_ORDER
        ),
    )


__all__ = [
    "CustomerTextWarningConflict",
    "DualProfileClipText",
    "DualProfileDecisionView",
    "DualProfileImportNotFound",
    "DualProfileReviewClip",
    "DualProfileReviewGroup",
    "DualProfileReviewRepository",
    "DualProfileReviewService",
    "DualProfileReviewView",
    "DualProfileTextWarningView",
    "decision_permission",
]
