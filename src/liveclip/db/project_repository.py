from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy import update as sql_update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.projects import (
    ProjectActivity,
    ProjectLifecycleUpdate,
    ProjectManagementConflict,
    ProjectManagementUpdate,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AuditEventRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.db.workspace_repository import WorkspacePermissionDenied
from liveclip.domain.project_lifecycle import (
    ProjectLifecycle,
    transition_project_lifecycle,
)
from liveclip.domain.state_transitions import PipelineRunStatus


class SqlAlchemyProjectManagementRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def update_management(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectManagementUpdate,
        correlation_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            project = _project_for_owner(connection, project_id, acting_user_id)
            if int(project.management_version) != update.expected_management_version:
                raise ProjectManagementConflict("project management version changed")
            if update.assignee_user_id is not None:
                assignee_exists = connection.scalar(
                    select(ProjectMemberRow.id)
                    .join(WorkspaceUserRow, WorkspaceUserRow.id == ProjectMemberRow.user_id)
                    .where(
                        ProjectMemberRow.project_id == project_id,
                        ProjectMemberRow.user_id == update.assignee_user_id,
                        WorkspaceUserRow.is_active.is_(True),
                    )
                )
                if assignee_exists is None:
                    raise ProjectManagementConflict(
                        "project assignee must be an active project member"
                    )
            before = {
                "visibility": str(project.visibility),
                "assignee_user_id": _optional_string(project.assignee_user_id),
                "priority": str(project.priority),
                "due_at": _timestamp(project.due_at),
                "management_version": int(project.management_version),
            }
            after = {
                "visibility": update.visibility,
                "assignee_user_id": update.assignee_user_id,
                "priority": update.priority.value,
                "due_at": _timestamp(update.due_at),
                "management_version": update.expected_management_version + 1,
            }
            changed = any(
                before[key] != after[key] for key in before if key != "management_version"
            )
            if not changed:
                raise ProjectManagementConflict("project management fields did not change")
            result = connection.execute(
                sql_update(ProjectRow)
                .where(
                    ProjectRow.id == project_id,
                    ProjectRow.owner_id == acting_user_id,
                    ProjectRow.management_version == update.expected_management_version,
                )
                .values(
                    visibility=update.visibility,
                    assignee_user_id=update.assignee_user_id,
                    priority=update.priority.value,
                    due_at=update.due_at,
                    management_version=ProjectRow.management_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ProjectManagementConflict("project management version changed")
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="project.management_updated",
                project_id=project_id,
                before=before,
                after=after,
                correlation_id=correlation_id,
                now=now,
            )

    def transition_lifecycle(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectLifecycleUpdate,
        correlation_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            project = _project_for_owner(connection, project_id, acting_user_id)
            if int(project.management_version) != update.expected_management_version:
                raise ProjectManagementConflict("project management version changed")
            current = ProjectLifecycle(str(project.lifecycle))
            restore = (
                ProjectLifecycle(str(project.lifecycle_before_archive))
                if project.lifecycle_before_archive is not None
                else None
            )
            transition_project_lifecycle(current, update.target, restore_target=restore)
            target_is_archive = update.target is ProjectLifecycle.ARCHIVED
            restoring = current is ProjectLifecycle.ARCHIVED
            if target_is_archive and project.current_pipeline_run_id is not None:
                run_status = connection.scalar(
                    select(PipelineRunRow.status).where(
                        PipelineRunRow.id == project.current_pipeline_run_id
                    )
                )
                if run_status in {
                    PipelineRunStatus.QUEUED.value,
                    PipelineRunStatus.RUNNING.value,
                }:
                    raise ProjectManagementConflict(
                        "active project processing must finish or be cancelled before archiving"
                    )
            result = connection.execute(
                sql_update(ProjectRow)
                .where(
                    ProjectRow.id == project_id,
                    ProjectRow.owner_id == acting_user_id,
                    ProjectRow.management_version == update.expected_management_version,
                )
                .values(
                    lifecycle=update.target.value,
                    lifecycle_before_archive=(
                        current.value
                        if target_is_archive
                        else None
                        if restoring
                        else project.lifecycle_before_archive
                    ),
                    archived_at=(
                        now if target_is_archive else None if restoring else project.archived_at
                    ),
                    management_version=ProjectRow.management_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ProjectManagementConflict("project management version changed")
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action=("project.restored" if restoring else "project.lifecycle_changed"),
                project_id=project_id,
                before={
                    "lifecycle": current.value,
                    "management_version": update.expected_management_version,
                },
                after={
                    "lifecycle": update.target.value,
                    "reason": update.reason,
                    "management_version": update.expected_management_version + 1,
                },
                correlation_id=correlation_id,
                now=now,
            )

    def list_activity(self, project_id: str, *, limit: int) -> tuple[ProjectActivity, ...]:
        with self._engine.connect() as connection:
            project_exists = connection.scalar(
                select(ProjectRow.id).where(ProjectRow.id == project_id)
            )
            if project_exists is None:
                raise LookupError("project does not exist")
            rows = connection.execute(
                select(
                    AuditEventRow.id,
                    AuditEventRow.actor_username,
                    AuditEventRow.action,
                    AuditEventRow.target_type,
                    AuditEventRow.target_id,
                    AuditEventRow.before_json,
                    AuditEventRow.after_json,
                    AuditEventRow.created_at,
                )
                .where(AuditEventRow.project_id == project_id)
                .order_by(AuditEventRow.created_at.desc(), AuditEventRow.id.desc())
                .limit(limit)
            )
            return tuple(
                ProjectActivity(
                    event_id=str(row.id),
                    actor_username=_optional_string(row.actor_username),
                    action=str(row.action),
                    target_type=str(row.target_type),
                    target_id=_optional_string(row.target_id),
                    before=_json_object(row.before_json),
                    after=_json_object(row.after_json),
                    created_at=row.created_at,
                )
                for row in rows
            )


def _project_for_owner(connection: Connection, project_id: str, acting_user_id: str):  # type: ignore[no-untyped-def]
    project = connection.execute(
        select(
            ProjectRow.owner_id,
            ProjectRow.visibility,
            ProjectRow.lifecycle,
            ProjectRow.lifecycle_before_archive,
            ProjectRow.management_version,
            ProjectRow.assignee_user_id,
            ProjectRow.priority,
            ProjectRow.due_at,
            ProjectRow.archived_at,
            ProjectRow.current_pipeline_run_id,
        ).where(ProjectRow.id == project_id)
    ).one_or_none()
    if project is None:
        raise LookupError("project does not exist")
    if str(project.owner_id) != acting_user_id:
        raise WorkspacePermissionDenied("only the project owner can manage the project")
    return project


def _audit(
    connection: Connection,
    *,
    actor_user_id: str,
    action: str,
    project_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    correlation_id: str | None,
    now: datetime,
) -> None:
    username = connection.scalar(
        select(WorkspaceUserRow.username).where(WorkspaceUserRow.id == actor_user_id)
    )
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor_user_id,
            actor_username=str(username) if username is not None else None,
            action=action,
            target_type="project",
            target_id=project_id,
            project_id=project_id,
            before_json=before,
            after_json=after,
            correlation_id=correlation_id,
            created_at=now,
        )
    )


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _json_object(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
