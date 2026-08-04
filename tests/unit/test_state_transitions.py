import pytest

from liveclip.domain.state_transitions import (
    AssetStatus,
    DeliveryStatus,
    InvalidStateTransition,
    PipelineRunStatus,
    ProjectStateFacts,
    ProjectStatus,
    RenderStatus,
    ReviewStatus,
    StageRunStatus,
    TaskStatus,
    derive_project_status,
    record_review_status,
    transition_asset,
    transition_delivery,
    transition_pipeline_run,
    transition_render,
    transition_stage_run,
    transition_task,
)


@pytest.mark.parametrize(
    ("transition", "current", "target"),
    [
        (transition_pipeline_run, PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING),
        (transition_pipeline_run, PipelineRunStatus.RUNNING, PipelineRunStatus.COMPLETED),
        (transition_pipeline_run, PipelineRunStatus.RUNNING, PipelineRunStatus.FAILED),
        (transition_pipeline_run, PipelineRunStatus.FAILED, PipelineRunStatus.QUEUED),
        (transition_stage_run, StageRunStatus.QUEUED, StageRunStatus.RUNNING),
        (transition_stage_run, StageRunStatus.QUEUED, StageRunStatus.SKIPPED),
        (transition_stage_run, StageRunStatus.RUNNING, StageRunStatus.SUCCEEDED),
        (transition_stage_run, StageRunStatus.FAILED, StageRunStatus.QUEUED),
        (transition_render, RenderStatus.QUEUED, RenderStatus.RUNNING),
        (transition_render, RenderStatus.RUNNING, RenderStatus.SUCCEEDED),
        (transition_render, RenderStatus.SUCCEEDED, RenderStatus.STALE),
        (transition_render, RenderStatus.FAILED, RenderStatus.QUEUED),
        (transition_render, RenderStatus.FAILED, RenderStatus.STALE),
        (transition_delivery, DeliveryStatus.QUEUED, DeliveryStatus.CREATING),
        (transition_delivery, DeliveryStatus.CREATING, DeliveryStatus.SUCCEEDED),
        (transition_delivery, DeliveryStatus.FAILED, DeliveryStatus.QUEUED),
        (transition_task, TaskStatus.QUEUED, TaskStatus.RUNNING),
        (transition_task, TaskStatus.RUNNING, TaskStatus.QUEUED),
        (transition_task, TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (transition_asset, AssetStatus.PENDING, AssetStatus.COMMITTED),
        (transition_asset, AssetStatus.PENDING, AssetStatus.ORPHANED),
        (transition_asset, AssetStatus.COMMITTED, AssetStatus.INVALID),
    ],
)
def test_legal_and_idempotent_transitions(
    transition: object, current: object, target: object
) -> None:
    assert callable(transition)
    assert transition(current, target) == target  # type: ignore[operator]
    assert transition(target, target) == target  # type: ignore[operator]


@pytest.mark.parametrize(
    ("transition", "current", "target"),
    [
        (transition_pipeline_run, PipelineRunStatus.QUEUED, PipelineRunStatus.COMPLETED),
        (transition_pipeline_run, PipelineRunStatus.COMPLETED, PipelineRunStatus.RUNNING),
        (transition_pipeline_run, PipelineRunStatus.CANCELLED, PipelineRunStatus.QUEUED),
        (transition_stage_run, StageRunStatus.QUEUED, StageRunStatus.SUCCEEDED),
        (transition_stage_run, StageRunStatus.SUCCEEDED, StageRunStatus.QUEUED),
        (transition_render, RenderStatus.QUEUED, RenderStatus.SUCCEEDED),
        (transition_render, RenderStatus.STALE, RenderStatus.QUEUED),
        (transition_delivery, DeliveryStatus.QUEUED, DeliveryStatus.SUCCEEDED),
        (transition_delivery, DeliveryStatus.SUCCEEDED, DeliveryStatus.QUEUED),
        (transition_task, TaskStatus.QUEUED, TaskStatus.SUCCEEDED),
        (transition_task, TaskStatus.SUCCEEDED, TaskStatus.QUEUED),
        (transition_asset, AssetStatus.COMMITTED, AssetStatus.PENDING),
        (transition_asset, AssetStatus.ORPHANED, AssetStatus.COMMITTED),
    ],
)
def test_illegal_transitions_fail_closed(
    transition: object, current: object, target: object
) -> None:
    assert callable(transition)
    with pytest.raises(InvalidStateTransition, match="illegal"):
        transition(current, target)  # type: ignore[operator]


def test_review_decision_cannot_manufacture_pending_status() -> None:
    assert (
        record_review_status(ReviewStatus.PENDING_REVIEW, ReviewStatus.APPROVED)
        == ReviewStatus.APPROVED
    )
    assert (
        record_review_status(ReviewStatus.APPROVED, ReviewStatus.REJECTED) == ReviewStatus.REJECTED
    )
    with pytest.raises(InvalidStateTransition, match="derived"):
        record_review_status(ReviewStatus.APPROVED, ReviewStatus.PENDING_REVIEW)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (ProjectStateFacts(source_imported=True), ProjectStatus.IMPORTED),
        (
            ProjectStateFacts(
                source_imported=True,
                pipeline_status=PipelineRunStatus.QUEUED,
            ),
            ProjectStatus.PROCESSING,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                review_statuses=(ReviewStatus.PENDING_REVIEW,),
            ),
            ProjectStatus.PENDING_REVIEW,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                review_statuses=(ReviewStatus.REJECTED,),
            ),
            ProjectStatus.PENDING_REVIEW,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                review_statuses=(ReviewStatus.APPROVED,),
                approved_current_final_count=1,
            ),
            ProjectStatus.READY_FOR_DELIVERY,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                review_statuses=(ReviewStatus.APPROVED,),
                approved_current_final_count=1,
                delivery_status=DeliveryStatus.SUCCEEDED,
                latest_delivery_matches_current=True,
            ),
            ProjectStatus.DELIVERED,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                has_unrecovered_failure=True,
            ),
            ProjectStatus.FAILED,
        ),
        (
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=True,
                has_unrecovered_failure=True,
                render_statuses=(RenderStatus.RUNNING,),
            ),
            ProjectStatus.PROCESSING,
        ),
    ],
)
def test_project_status_is_derived_from_current_facts(
    facts: ProjectStateFacts, expected: ProjectStatus
) -> None:
    assert derive_project_status(facts) == expected


def test_project_state_facts_reject_impossible_delivery_counts() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ProjectStateFacts(
            source_imported=True,
            review_statuses=(ReviewStatus.APPROVED,),
            approved_current_final_count=2,
        )


def test_current_successful_delivery_survives_a_newer_failed_attempt() -> None:
    facts = ProjectStateFacts(
        source_imported=True,
        has_completed_pipeline=True,
        delivery_status=DeliveryStatus.FAILED,
        latest_delivery_matches_current=True,
    )

    assert derive_project_status(facts) == ProjectStatus.DELIVERED
