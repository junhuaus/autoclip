from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.edit_plan import CaptionCue, EditPlan, validate_caption_cues


class RevisionOrigin(StrEnum):
    AI = "ai"
    DETERMINISTIC = "deterministic"
    HUMAN = "human"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class RenderStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"


class RenderKind(StrEnum):
    PROXY = "proxy"
    FINAL = "final"


class EditPlanRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    origin: RevisionOrigin
    plan: EditPlan
    captions: tuple[CaptionCue, ...]
    created_at: datetime

    @model_validator(mode="after")
    def validate_revision(self) -> EditPlanRevision:
        if self.revision == 1 and self.parent_revision is not None:
            raise ValueError("initial revision cannot have a parent")
        if self.revision > 1 and self.parent_revision != self.revision - 1:
            raise ValueError("revision parent must be the preceding revision")
        validate_caption_cues(self.captions, clip_duration_ms=self.plan.duration_ms)
        return self


class RenderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    render_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    revision: int = Field(ge=1)
    kind: RenderKind
    status: RenderStatus
    path: Path | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_artifact(self) -> RenderRecord:
        if self.status == RenderStatus.SUCCEEDED and (self.path is None or self.sha256 is None):
            raise ValueError("succeeded render requires a path and SHA-256")
        return self


class ReviewDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    revision: int = Field(ge=1)
    status: ReviewStatus
    reason: str | None = Field(default=None, max_length=500)
    decided_at: datetime

    @model_validator(mode="after")
    def validate_decision(self) -> ReviewDecisionRecord:
        if self.status == ReviewStatus.PENDING_REVIEW:
            raise ValueError("pending_review is derived and cannot be recorded as a decision")
        if self.status == ReviewStatus.REJECTED and not (self.reason and self.reason.strip()):
            raise ValueError("rejection requires a reason")
        return self


class ClipLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    current_revision: int = Field(ge=1)
    revisions: tuple[EditPlanRevision, ...]
    renders: tuple[RenderRecord, ...] = ()
    decisions: tuple[ReviewDecisionRecord, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> ClipLifecycle:
        expected = list(range(1, self.current_revision + 1))
        if [revision.revision for revision in self.revisions] != expected:
            raise ValueError("revision history must be contiguous through current revision")
        if any(revision.clip_id != self.clip_id for revision in self.revisions):
            raise ValueError("revision belongs to a different clip")
        if any(render.revision > self.current_revision for render in self.renders):
            raise ValueError("render references a future revision")
        if any(decision.revision > self.current_revision for decision in self.decisions):
            raise ValueError("decision references a future revision")
        return self

    @property
    def current(self) -> EditPlanRevision:
        return self.revisions[-1]

    @property
    def review_status(self) -> ReviewStatus:
        current_decisions = [
            decision for decision in self.decisions if decision.revision == self.current_revision
        ]
        return current_decisions[-1].status if current_decisions else ReviewStatus.PENDING_REVIEW


def start_clip_lifecycle(revision: EditPlanRevision) -> ClipLifecycle:
    if revision.revision != 1:
        raise ValueError("clip lifecycle must begin at revision 1")
    return ClipLifecycle(
        clip_id=revision.clip_id,
        current_revision=1,
        revisions=(revision,),
    )


def add_render(lifecycle: ClipLifecycle, render: RenderRecord) -> ClipLifecycle:
    if render.revision != lifecycle.current_revision:
        raise ValueError("new render must target the current revision")
    if any(existing.render_id == render.render_id for existing in lifecycle.renders):
        raise ValueError("render ID already exists")
    return lifecycle.model_copy(update={"renders": (*lifecycle.renders, render)})


def decide_clip(
    lifecycle: ClipLifecycle,
    *,
    status: ReviewStatus,
    reason: str | None = None,
    decided_at: datetime | None = None,
) -> ClipLifecycle:
    decision = ReviewDecisionRecord(
        revision=lifecycle.current_revision,
        status=status,
        reason=reason,
        decided_at=decided_at or datetime.now(UTC),
    )
    return lifecycle.model_copy(update={"decisions": (*lifecycle.decisions, decision)})


def revise_clip(
    lifecycle: ClipLifecycle,
    *,
    plan: EditPlan,
    captions: tuple[CaptionCue, ...],
    origin: RevisionOrigin = RevisionOrigin.HUMAN,
    created_at: datetime | None = None,
) -> ClipLifecycle:
    next_revision_number = lifecycle.current_revision + 1
    revision = EditPlanRevision(
        clip_id=lifecycle.clip_id,
        revision=next_revision_number,
        parent_revision=lifecycle.current_revision,
        origin=origin,
        plan=plan,
        captions=captions,
        created_at=created_at or datetime.now(UTC),
    )
    stale_renders = tuple(
        render.model_copy(update={"status": RenderStatus.STALE})
        if render.revision < next_revision_number
        and render.status in {RenderStatus.QUEUED, RenderStatus.RUNNING, RenderStatus.SUCCEEDED}
        else render
        for render in lifecycle.renders
    )
    return ClipLifecycle(
        clip_id=lifecycle.clip_id,
        current_revision=next_revision_number,
        revisions=(*lifecycle.revisions, revision),
        renders=stale_renders,
        decisions=lifecycle.decisions,
    )


def current_final_render(lifecycle: ClipLifecycle) -> RenderRecord | None:
    matches = [
        render
        for render in lifecycle.renders
        if render.revision == lifecycle.current_revision
        and render.kind == RenderKind.FINAL
        and render.status == RenderStatus.SUCCEEDED
    ]
    return matches[-1] if matches else None
