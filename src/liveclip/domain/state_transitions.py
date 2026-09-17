from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar


class InvalidStateTransition(ValueError):
    """Raised when an application service requests an illegal state change."""


class PipelineRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineStage(StrEnum):
    INGEST = "ingest"
    PREPROCESS = "preprocess"
    TRANSCRIBE = "transcribe"
    CANDIDATES = "candidates"
    EDIT = "edit"
    PROXY_RENDER = "proxy_render"


PIPELINE_STAGE_ORDER = tuple(PipelineStage)


class StageRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


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


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    CREATING = "creating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EditPackageStatus(StrEnum):
    QUEUED = "queued"
    CREATING = "creating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    WAITING = "waiting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskKind(StrEnum):
    STAGE = "stage"
    RENDER = "render"
    DELIVERY = "delivery"
    COMPLETION = "completion"


class ResourceClass(StrEnum):
    HEAVY = "heavy"
    CHEAP = "cheap"


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    DETERMINISTIC = "deterministic"


class AttemptOutcome(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEFERRED = "deferred"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST_LEASE = "lost_lease"


class AssetStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    ORPHANED = "orphaned"
    INVALID = "invalid"


class ProjectStatus(StrEnum):
    IMPORTED = "imported"
    PROCESSING = "processing"
    PENDING_REVIEW = "pending_review"
    READY_FOR_DELIVERY = "ready_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"


_StatusT = TypeVar("_StatusT", bound=StrEnum)


_PIPELINE_TRANSITIONS = {
    PipelineRunStatus.QUEUED: frozenset({PipelineRunStatus.RUNNING, PipelineRunStatus.CANCELLED}),
    PipelineRunStatus.RUNNING: frozenset(
        {
            PipelineRunStatus.COMPLETED,
            PipelineRunStatus.FAILED,
            PipelineRunStatus.CANCELLED,
        }
    ),
    PipelineRunStatus.FAILED: frozenset({PipelineRunStatus.QUEUED}),
    PipelineRunStatus.COMPLETED: frozenset(),
    # A cancelled durable run may be explicitly resumed. Repository-level
    # resume validation keeps all completed stages immutable and requeues only
    # the first safely resumable cancelled stage plus its downstream stages.
    PipelineRunStatus.CANCELLED: frozenset({PipelineRunStatus.QUEUED}),
}

_STAGE_TRANSITIONS = {
    StageRunStatus.QUEUED: frozenset(
        {StageRunStatus.RUNNING, StageRunStatus.SKIPPED, StageRunStatus.CANCELLED}
    ),
    StageRunStatus.RUNNING: frozenset(
        {StageRunStatus.SUCCEEDED, StageRunStatus.FAILED, StageRunStatus.CANCELLED}
    ),
    StageRunStatus.FAILED: frozenset({StageRunStatus.QUEUED}),
    StageRunStatus.SUCCEEDED: frozenset(),
    StageRunStatus.SKIPPED: frozenset(),
    StageRunStatus.CANCELLED: frozenset({StageRunStatus.QUEUED}),
}

_RENDER_TRANSITIONS = {
    RenderStatus.QUEUED: frozenset({RenderStatus.RUNNING, RenderStatus.FAILED, RenderStatus.STALE}),
    RenderStatus.RUNNING: frozenset(
        {RenderStatus.SUCCEEDED, RenderStatus.FAILED, RenderStatus.STALE}
    ),
    RenderStatus.SUCCEEDED: frozenset({RenderStatus.STALE}),
    RenderStatus.FAILED: frozenset({RenderStatus.QUEUED, RenderStatus.STALE}),
    RenderStatus.STALE: frozenset(),
}

_DELIVERY_TRANSITIONS = {
    DeliveryStatus.QUEUED: frozenset({DeliveryStatus.CREATING, DeliveryStatus.FAILED}),
    DeliveryStatus.CREATING: frozenset({DeliveryStatus.SUCCEEDED, DeliveryStatus.FAILED}),
    DeliveryStatus.FAILED: frozenset({DeliveryStatus.QUEUED}),
    DeliveryStatus.SUCCEEDED: frozenset(),
}

_EDIT_PACKAGE_TRANSITIONS = {
    EditPackageStatus.QUEUED: frozenset({EditPackageStatus.CREATING, EditPackageStatus.FAILED}),
    EditPackageStatus.CREATING: frozenset({EditPackageStatus.SUCCEEDED, EditPackageStatus.FAILED}),
    EditPackageStatus.FAILED: frozenset({EditPackageStatus.QUEUED}),
    EditPackageStatus.SUCCEEDED: frozenset(),
}

_TASK_TRANSITIONS = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.WAITING: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.WAITING,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED}),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.CANCELLED: frozenset({TaskStatus.QUEUED}),
}

_ASSET_TRANSITIONS = {
    AssetStatus.PENDING: frozenset(
        {AssetStatus.COMMITTED, AssetStatus.ORPHANED, AssetStatus.INVALID}
    ),
    AssetStatus.COMMITTED: frozenset({AssetStatus.INVALID}),
    AssetStatus.ORPHANED: frozenset(),
    AssetStatus.INVALID: frozenset(),
}


def _transition(
    current: _StatusT,
    target: _StatusT,
    allowed: dict[_StatusT, frozenset[_StatusT]],
    *,
    resource: str,
) -> _StatusT:
    if current == target:
        return current
    if target not in allowed[current]:
        raise InvalidStateTransition(
            f"illegal {resource} transition: {current.value} -> {target.value}"
        )
    return target


def transition_pipeline_run(
    current: PipelineRunStatus, target: PipelineRunStatus
) -> PipelineRunStatus:
    return _transition(current, target, _PIPELINE_TRANSITIONS, resource="PipelineRun")


def transition_stage_run(current: StageRunStatus, target: StageRunStatus) -> StageRunStatus:
    return _transition(current, target, _STAGE_TRANSITIONS, resource="StageRun")


def transition_render(current: RenderStatus, target: RenderStatus) -> RenderStatus:
    return _transition(current, target, _RENDER_TRANSITIONS, resource="Render")


def transition_delivery(current: DeliveryStatus, target: DeliveryStatus) -> DeliveryStatus:
    return _transition(current, target, _DELIVERY_TRANSITIONS, resource="Delivery")


def transition_edit_package(
    current: EditPackageStatus,
    target: EditPackageStatus,
) -> EditPackageStatus:
    return _transition(current, target, _EDIT_PACKAGE_TRANSITIONS, resource="EditPackage")


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    return _transition(current, target, _TASK_TRANSITIONS, resource="Task")


def transition_asset(current: AssetStatus, target: AssetStatus) -> AssetStatus:
    return _transition(current, target, _ASSET_TRANSITIONS, resource="Asset")


def record_review_status(current: ReviewStatus, target: ReviewStatus) -> ReviewStatus:
    if target == ReviewStatus.PENDING_REVIEW:
        raise InvalidStateTransition(
            "pending_review is derived from the absence of a decision on the current revision"
        )
    return target


@dataclass(frozen=True, slots=True)
class ProjectStateFacts:
    source_imported: bool
    has_completed_pipeline: bool = False
    pipeline_status: PipelineRunStatus | None = None
    render_statuses: tuple[RenderStatus, ...] = ()
    delivery_status: DeliveryStatus | None = None
    review_statuses: tuple[ReviewStatus, ...] = ()
    approved_current_final_count: int = 0
    has_unrecovered_failure: bool = False
    latest_delivery_matches_current: bool = False

    def __post_init__(self) -> None:
        if self.approved_current_final_count < 0:
            raise ValueError("approved_current_final_count cannot be negative")
        approved_count = self.review_statuses.count(ReviewStatus.APPROVED)
        if self.approved_current_final_count > approved_count:
            raise ValueError("current final render count cannot exceed approved clip count")


def derive_project_status(facts: ProjectStateFacts) -> ProjectStatus:
    if not facts.source_imported:
        raise ValueError("Project status is undefined before successful source import")
    if (
        facts.pipeline_status in {PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING}
        or any(
            status in {RenderStatus.QUEUED, RenderStatus.RUNNING}
            for status in facts.render_statuses
        )
        or facts.delivery_status in {DeliveryStatus.QUEUED, DeliveryStatus.CREATING}
    ):
        return ProjectStatus.PROCESSING
    if facts.latest_delivery_matches_current:
        return ProjectStatus.DELIVERED
    if facts.has_unrecovered_failure:
        return ProjectStatus.FAILED
    if not facts.has_completed_pipeline:
        return ProjectStatus.IMPORTED
    approved_count = facts.review_statuses.count(ReviewStatus.APPROVED)
    if approved_count and facts.approved_current_final_count == approved_count:
        return ProjectStatus.READY_FOR_DELIVERY
    return ProjectStatus.PENDING_REVIEW
