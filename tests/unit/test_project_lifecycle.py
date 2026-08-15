from __future__ import annotations

import pytest

from liveclip.domain.project_lifecycle import (
    ProjectLifecycle,
    ProjectLifecycleConflict,
    allowed_project_lifecycle_transitions,
    transition_project_lifecycle,
)


def test_editorial_lifecycle_has_explicit_forward_and_revision_paths() -> None:
    assert allowed_project_lifecycle_transitions(ProjectLifecycle.EDITORIAL_REVIEW) == (
        ProjectLifecycle.CHANGES_REQUESTED,
        ProjectLifecycle.APPROVAL,
        ProjectLifecycle.ARCHIVED,
    )
    assert allowed_project_lifecycle_transitions(ProjectLifecycle.APPROVAL) == (
        ProjectLifecycle.CHANGES_REQUESTED,
        ProjectLifecycle.READY_TO_PUBLISH,
        ProjectLifecycle.ARCHIVED,
    )


def test_archived_project_only_restores_to_its_recorded_state() -> None:
    assert allowed_project_lifecycle_transitions(
        ProjectLifecycle.ARCHIVED,
        restore_target=ProjectLifecycle.PUBLISHED,
    ) == (ProjectLifecycle.PUBLISHED,)
    transition_project_lifecycle(
        ProjectLifecycle.ARCHIVED,
        ProjectLifecycle.PUBLISHED,
        restore_target=ProjectLifecycle.PUBLISHED,
    )
    with pytest.raises(ProjectLifecycleConflict):
        transition_project_lifecycle(
            ProjectLifecycle.ARCHIVED,
            ProjectLifecycle.DRAFT,
            restore_target=ProjectLifecycle.PUBLISHED,
        )


def test_lifecycle_rejects_skipping_editorial_approval() -> None:
    with pytest.raises(ProjectLifecycleConflict):
        transition_project_lifecycle(
            ProjectLifecycle.EDITORIAL_REVIEW,
            ProjectLifecycle.PUBLISHED,
        )
