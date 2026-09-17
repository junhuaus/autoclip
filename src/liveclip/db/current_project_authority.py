"""Current project authority checked on the same connection as a durable effect."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.engine import Connection

from liveclip.application.authorization import (
    ProjectAction,
    ProjectActionDenied,
    require_project_action,
)
from liveclip.application.workspace import WorkspaceRole
from liveclip.db.models import ProjectMemberRow, ProjectRow, WorkspaceUserRow
from liveclip.domain.project_lifecycle import ProjectLifecycle


class CurrentProjectAccessDenied(PermissionError):
    """The actor no longer holds the action permission on this project."""


class CurrentProjectRunChanged(RuntimeError):
    """The project has advanced beyond the run bound to this effect."""


def require_current_project_action(
    connection: Connection,
    *,
    project_id: str,
    actor_user_id: str,
    action: ProjectAction,
    expected_run_id: str | None = None,
    expected_generation: int | None = None,
) -> WorkspaceRole:
    """Check fresh identity, membership, archive and optional run fence.

    The caller must invoke this inside its write transaction before *both* an
    idempotent replay and a new business mutation. No session token is stored.
    """

    row = connection.execute(
        select(
            ProjectRow.lifecycle,
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectMemberRow.role,
        )
        .join(ProjectMemberRow, ProjectMemberRow.project_id == ProjectRow.id)
        .join(WorkspaceUserRow, WorkspaceUserRow.id == ProjectMemberRow.user_id)
        .where(
            ProjectRow.id == project_id,
            ProjectMemberRow.user_id == actor_user_id,
            WorkspaceUserRow.is_active.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise CurrentProjectAccessDenied("active project membership is required")
    raw_role = str(row.role)
    if raw_role not in {"owner", "editor", "reviewer", "viewer"}:
        raise CurrentProjectAccessDenied("project membership role is invalid")
    role = cast(WorkspaceRole, raw_role)
    try:
        require_project_action(
            role,
            action,
            archived=str(row.lifecycle) == ProjectLifecycle.ARCHIVED.value,
        )
    except ProjectActionDenied as exc:
        raise CurrentProjectAccessDenied("current project action is denied") from exc
    if expected_run_id is not None and str(row.current_pipeline_run_id) != expected_run_id:
        raise CurrentProjectRunChanged("project current run changed")
    if expected_generation is not None and int(row.current_generation) != expected_generation:
        raise CurrentProjectRunChanged("project generation changed")
    return role
