from __future__ import annotations

from enum import StrEnum


class ProjectLifecycle(StrEnum):
    DRAFT = "draft"
    PROCESSING = "processing"
    NEEDS_ATTENTION = "needs_attention"
    EDITORIAL_REVIEW = "editorial_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVAL = "approval"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ProjectPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ProjectLifecycleConflict(RuntimeError):
    """A requested editorial lifecycle transition is not legal."""


_MANUAL_TRANSITIONS: dict[ProjectLifecycle, frozenset[ProjectLifecycle]] = {
    ProjectLifecycle.DRAFT: frozenset({ProjectLifecycle.ARCHIVED}),
    ProjectLifecycle.PROCESSING: frozenset({ProjectLifecycle.ARCHIVED}),
    ProjectLifecycle.NEEDS_ATTENTION: frozenset(
        {ProjectLifecycle.EDITORIAL_REVIEW, ProjectLifecycle.ARCHIVED}
    ),
    ProjectLifecycle.EDITORIAL_REVIEW: frozenset(
        {
            ProjectLifecycle.CHANGES_REQUESTED,
            ProjectLifecycle.APPROVAL,
            ProjectLifecycle.ARCHIVED,
        }
    ),
    ProjectLifecycle.CHANGES_REQUESTED: frozenset(
        {ProjectLifecycle.EDITORIAL_REVIEW, ProjectLifecycle.ARCHIVED}
    ),
    ProjectLifecycle.APPROVAL: frozenset(
        {
            ProjectLifecycle.CHANGES_REQUESTED,
            ProjectLifecycle.READY_TO_PUBLISH,
            ProjectLifecycle.ARCHIVED,
        }
    ),
    ProjectLifecycle.READY_TO_PUBLISH: frozenset(
        {
            ProjectLifecycle.CHANGES_REQUESTED,
            ProjectLifecycle.PUBLISHED,
            ProjectLifecycle.ARCHIVED,
        }
    ),
    ProjectLifecycle.PUBLISHED: frozenset({ProjectLifecycle.ARCHIVED}),
    ProjectLifecycle.ARCHIVED: frozenset(),
}

_DISPLAY_ORDER = tuple(ProjectLifecycle)


def allowed_project_lifecycle_transitions(
    current: ProjectLifecycle,
    *,
    restore_target: ProjectLifecycle | None = None,
) -> tuple[ProjectLifecycle, ...]:
    if current is ProjectLifecycle.ARCHIVED:
        if restore_target is None or restore_target is ProjectLifecycle.ARCHIVED:
            return ()
        return (restore_target,)
    targets = _MANUAL_TRANSITIONS[current]
    return tuple(value for value in _DISPLAY_ORDER if value in targets)


def transition_project_lifecycle(
    current: ProjectLifecycle,
    target: ProjectLifecycle,
    *,
    restore_target: ProjectLifecycle | None = None,
) -> None:
    if target not in allowed_project_lifecycle_transitions(
        current,
        restore_target=restore_target,
    ):
        raise ProjectLifecycleConflict(
            f"project lifecycle cannot transition from {current.value} to {target.value}"
        )
