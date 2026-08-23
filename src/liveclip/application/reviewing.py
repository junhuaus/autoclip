from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.idempotency import IdempotencyContext
from liveclip.domain.edit_plan import MAX_CAPTION_CUES, CaptionCue, EditPlan
from liveclip.domain.keywords import KeywordOccurrence
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus


class ReviewConflict(RuntimeError):
    """The requested review mutation conflicts with current persisted state."""


class ReviewResourceNotFound(LookupError):
    """The requested clip, render, transcript, or delivery does not exist."""


class ClipPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_revision: int = Field(ge=1)
    source_start_ms: int | None = Field(default=None, ge=0)
    source_end_ms: int | None = Field(default=None, gt=0)
    score: float | None = Field(default=None, ge=0, le=100)
    title: str | None = Field(default=None, min_length=1, max_length=40)
    layout: Literal["center_crop"] | None = None
    captions: tuple[CaptionCue, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_CAPTION_CUES
    )

    @model_validator(mode="after")
    def require_change(self) -> ClipPatch:
        if all(
            value is None
            for value in (
                self.source_start_ms,
                self.source_end_ms,
                self.score,
                self.title,
                self.layout,
                self.captions,
            )
        ):
            raise ValueError(
                "clip patch must include a score, title, boundary, layout, or caption change"
            )
        if (
            self.source_start_ms is not None
            and self.source_end_ms is not None
            and self.source_end_ms <= self.source_start_ms
        ):
            raise ValueError("clip patch end must be greater than start")
        return self


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_revision: int = Field(ge=1)
    status: ReviewStatus
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_decision(self) -> ReviewCommand:
        if self.status == ReviewStatus.PENDING_REVIEW:
            raise ValueError("pending_review is derived and cannot be recorded")
        if self.status == ReviewStatus.REJECTED and not (self.reason and self.reason.strip()):
            raise ValueError("rejection requires a reason")
        if self.status == ReviewStatus.APPROVED and self.reason is not None:
            raise ValueError("approval does not accept a rejection reason")
        return self


class BatchReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)
    status: ReviewStatus
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_decision(self) -> BatchReviewItem:
        ReviewCommand(
            expected_revision=self.expected_revision,
            status=self.status,
            reason=self.reason,
        )
        return self

    def command(self) -> ReviewCommand:
        return ReviewCommand(
            expected_revision=self.expected_revision,
            status=self.status,
            reason=self.reason,
        )


class BatchReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[BatchReviewItem, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_clips(self) -> BatchReviewCommand:
        clip_ids = tuple(item.clip_id for item in self.items)
        if len(set(clip_ids)) != len(clip_ids):
            raise ValueError("batch review clip IDs must be unique")
        return self


class RenderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    render_id: str
    task_id: str | None
    kind: str = Field(pattern=r"^(proxy|final)$")
    status: RenderStatus
    edit_plan_revision: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    video_asset_id: str | None
    subtitle_asset_id: str | None
    quality_report_asset_id: str | None
    contact_sheet_asset_id: str | None
    error_code: str | None
    safe_error_message: str | None
    created_at: datetime
    updated_at: datetime


class ReviewSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: ReviewStatus
    reason: str | None = None
    decided_at: datetime | None = None


class ClipDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str
    project_id: str
    run_id: str
    generation: int = Field(ge=1)
    revision_epoch: int = Field(ge=0)
    candidate_key: str
    allowed_start_ms: int = Field(ge=0)
    allowed_end_ms: int = Field(gt=0)
    transcript_text: str
    context_before: str
    context_after: str
    rule_score: float = Field(ge=0, le=100)
    reasons: tuple[str, ...]
    rank: int | None
    current_revision: int = Field(ge=1)
    plan: EditPlan
    captions: tuple[CaptionCue, ...]
    keywords: tuple[KeywordOccurrence, ...]
    revision_created_at: datetime
    review: ReviewSnapshot
    renders: tuple[RenderSnapshot, ...]
    allowed_actions: tuple[str, ...]


class TranscriptSegmentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    segment_id: str
    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str


class TranscriptSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    run_id: str
    language: str
    provider: str
    model: str
    word_timing_status: str
    segments: tuple[TranscriptSegmentSnapshot, ...]


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_revision: int = Field(ge=1)
    kind: str = Field(default="final", pattern=r"^(proxy|final)$")


class ReviewRepository(Protocol):
    def get_clip(self, clip_id: str) -> ClipDetail: ...

    def revise_clip(self, clip_id: str, patch: ClipPatch) -> ClipDetail: ...

    def revise_and_review(
        self,
        clip_id: str,
        patch: ClipPatch,
        command: ReviewCommand,
    ) -> ClipDetail: ...

    def review_clip(self, clip_id: str, command: ReviewCommand) -> ClipDetail: ...

    def review_clips_batch(
        self,
        project_id: str,
        command: BatchReviewCommand,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> tuple[ClipDetail, ...]: ...

    def get_transcript(self, project_id: str) -> TranscriptSnapshot: ...


class ReviewService:
    def __init__(self, repository: ReviewRepository) -> None:
        self._repository = repository

    def get_clip(self, clip_id: str) -> ClipDetail:
        return self._repository.get_clip(clip_id)

    def revise_clip(self, clip_id: str, patch: ClipPatch) -> ClipDetail:
        return self._repository.revise_clip(clip_id, patch)

    def revise_and_review(
        self,
        clip_id: str,
        patch: ClipPatch,
        command: ReviewCommand,
    ) -> ClipDetail:
        """Create a human revision and decide that exact revision atomically."""

        if patch.expected_revision != command.expected_revision:
            raise ReviewConflict("clip patch and review must expect the same current revision")
        return self._repository.revise_and_review(clip_id, patch, command)

    def review_clip(self, clip_id: str, command: ReviewCommand) -> ClipDetail:
        return self._repository.review_clip(clip_id, command)

    def review_clips_batch(
        self,
        project_id: str,
        command: BatchReviewCommand,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> tuple[ClipDetail, ...]:
        return self._repository.review_clips_batch(
            project_id,
            command,
            idempotency=idempotency,
        )

    def get_transcript(self, project_id: str) -> TranscriptSnapshot:
        return self._repository.get_transcript(project_id)
