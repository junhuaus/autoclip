from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import case, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.governance import (
    AdministrativeAuditEvent,
    AdminProjectMember,
    AdminProjectSnapshot,
)
from liveclip.application.identity import AdministrationDenied, IdentityConflict
from liveclip.application.workspace import WorkspaceUser
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AuditEventRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    SourceMediaRow,
    WorkspaceUserRow,
)

_PROJECT_ROLES = {"owner", "editor", "reviewer", "viewer"}
_VISIBILITIES = {"private", "workspace"}
_LIFECYCLES = {
    "draft",
    "processing",
    "needs_attention",
    "editorial_review",
    "changes_requested",
    "approval",
    "ready_to_publish",
    "published",
    "archived",
}
_PRIORITIES = {"low", "normal", "high", "urgent"}
_PIPELINE_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}


class SqlAlchemyProjectGovernanceRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_projects(self, actor: WorkspaceUser) -> tuple[AdminProjectSnapshot, ...]:
        # BEGIN IMMEDIATE linearizes the explicit administrative read with a
        # concurrent role revocation. No filesystem or network work occurs.
        with begin_immediate(self._engine) as connection:
            _require_current_administrator(connection, actor.user_id)
            project_ids = tuple(
                str(value)
                for value in connection.scalars(
                    select(ProjectRow.id).order_by(ProjectRow.updated_at.desc(), ProjectRow.id)
                )
            )
            return tuple(_project_snapshot(connection, project_id) for project_id in project_ids)

    def get_project(self, actor: WorkspaceUser, project_id: str) -> AdminProjectSnapshot:
        with begin_immediate(self._engine) as connection:
            _require_current_administrator(connection, actor.user_id)
            return _project_snapshot(connection, project_id)

    def transfer_project_ownership(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
        new_owner_user_id: str,
        correlation_id: str | None = None,
    ) -> AdminProjectSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            _require_current_administrator(connection, actor.user_id)
            project = connection.execute(
                select(ProjectRow.owner_id, ProjectRow.management_version).where(
                    ProjectRow.id == project_id
                )
            ).one_or_none()
            if project is None:
                raise LookupError("project does not exist")
            old_owner_user_id = str(project.owner_id)
            if old_owner_user_id == new_owner_user_id:
                raise IdentityConflict("new owner must differ from the current project owner")

            target = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.is_active,
                ).where(WorkspaceUserRow.id == new_owner_user_id)
            ).one_or_none()
            if target is None or not bool(target.is_active):
                raise IdentityConflict("new owner must be an active workspace user")

            old_owner_membership = connection.execute(
                select(ProjectMemberRow.id, ProjectMemberRow.role).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == old_owner_user_id,
                )
            ).one_or_none()
            if old_owner_membership is None or str(old_owner_membership.role) != "owner":
                raise IdentityConflict("project owner membership is inconsistent")

            new_owner_membership = connection.execute(
                select(ProjectMemberRow.id).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == new_owner_user_id,
                )
            ).one_or_none()
            connection.execute(
                update(ProjectMemberRow)
                .where(ProjectMemberRow.id == old_owner_membership.id)
                .values(role="editor")
            )
            if new_owner_membership is None:
                connection.execute(
                    insert(ProjectMemberRow).values(
                        id=new_id(),
                        project_id=project_id,
                        user_id=new_owner_user_id,
                        role="owner",
                        created_at=now,
                    )
                )
            else:
                connection.execute(
                    update(ProjectMemberRow)
                    .where(ProjectMemberRow.id == new_owner_membership.id)
                    .values(role="owner")
                )

            project_update = connection.execute(
                update(ProjectRow)
                .where(
                    ProjectRow.id == project_id,
                    ProjectRow.owner_id == old_owner_user_id,
                    ProjectRow.management_version == int(project.management_version),
                )
                .values(
                    owner_id=new_owner_user_id,
                    management_version=ProjectRow.management_version + 1,
                    updated_at=now,
                )
            )
            if project_update.rowcount != 1:
                raise IdentityConflict("project ownership changed concurrently")

            connection.execute(
                insert(AuditEventRow).values(
                    id=new_id(),
                    actor_user_id=actor.user_id,
                    actor_username=actor.username,
                    action="project.ownership_transferred_by_administrator",
                    target_type="project",
                    target_id=project_id,
                    project_id=project_id,
                    before_json={
                        "owner_user_id": old_owner_user_id,
                        "management_version": int(project.management_version),
                    },
                    after_json={
                        "owner_user_id": new_owner_user_id,
                        "management_version": int(project.management_version) + 1,
                        "administrative_context": True,
                    },
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            return _project_snapshot(connection, project_id)

    def list_audit_events(
        self,
        *,
        actor: WorkspaceUser,
        limit: int,
        project_id: str | None,
    ) -> tuple[AdministrativeAuditEvent, ...]:
        with begin_immediate(self._engine) as connection:
            _require_current_administrator(connection, actor.user_id)
            query = select(
                AuditEventRow.id,
                AuditEventRow.actor_username,
                AuditEventRow.action,
                AuditEventRow.target_type,
                AuditEventRow.target_id,
                AuditEventRow.project_id,
                AuditEventRow.before_json,
                AuditEventRow.after_json,
                AuditEventRow.correlation_id,
                AuditEventRow.created_at,
            )
            if project_id is not None:
                query = query.where(AuditEventRow.project_id == project_id)
            rows = tuple(
                connection.execute(
                    query.order_by(AuditEventRow.created_at.desc(), AuditEventRow.id.desc()).limit(
                        limit
                    )
                )
            )
            return tuple(_audit_event(row) for row in rows)


def _project_snapshot(connection: Connection, project_id: str) -> AdminProjectSnapshot:
    project = connection.execute(
        select(
            ProjectRow.id,
            ProjectRow.name,
            ProjectRow.source_request_path,
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectRow.visibility,
            ProjectRow.lifecycle,
            ProjectRow.management_version,
            ProjectRow.assignee_user_id,
            ProjectRow.priority,
            ProjectRow.due_at,
            ProjectRow.updated_at,
            ProjectRow.owner_id,
        ).where(ProjectRow.id == project_id)
    ).one_or_none()
    if project is None:
        raise LookupError("project does not exist")

    member_rows = tuple(
        connection.execute(
            select(
                WorkspaceUserRow.id,
                WorkspaceUserRow.username,
                WorkspaceUserRow.display_name,
                WorkspaceUserRow.is_active,
                ProjectMemberRow.role,
            )
            .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
            .where(ProjectMemberRow.project_id == project_id)
            .order_by(
                case((ProjectMemberRow.role == "owner", 0), else_=1),
                WorkspaceUserRow.display_name,
                WorkspaceUserRow.id,
            )
        )
    )
    members = tuple(_project_member(row) for row in member_rows)
    owner = next(
        (
            member
            for member in members
            if member.user_id == str(project.owner_id) and member.role == "owner"
        ),
        None,
    )
    if owner is None:
        raise IdentityConflict("project owner membership is inconsistent")
    assignee = next(
        (
            member
            for member in members
            if member.user_id == _optional_string(project.assignee_user_id)
        ),
        None,
    )

    pipeline_status_value = None
    if project.current_pipeline_run_id is not None:
        pipeline_status_value = connection.scalar(
            select(PipelineRunRow.status).where(
                PipelineRunRow.id == project.current_pipeline_run_id
            )
        )
        if pipeline_status_value is None:
            raise IdentityConflict("project current pipeline run is missing")
    source_filename = (
        connection.scalar(
            select(SourceMediaRow.filename).where(SourceMediaRow.project_id == project_id)
        )
        or Path(str(project.source_request_path)).name
    )

    visibility = str(project.visibility)
    lifecycle = str(project.lifecycle)
    priority = str(project.priority)
    pipeline_status = str(pipeline_status_value) if pipeline_status_value is not None else None
    if visibility not in _VISIBILITIES:
        raise IdentityConflict("project visibility is invalid")
    if lifecycle not in _LIFECYCLES:
        raise IdentityConflict("project lifecycle is invalid")
    if priority not in _PRIORITIES:
        raise IdentityConflict("project priority is invalid")
    if pipeline_status is not None and pipeline_status not in _PIPELINE_STATUSES:
        raise IdentityConflict("project pipeline status is invalid")
    return AdminProjectSnapshot(
        project_id=str(project.id),
        name=str(project.name),
        source_filename=str(source_filename),
        pipeline_status=cast(Any, pipeline_status),
        current_run_id=_optional_string(project.current_pipeline_run_id),
        generation=int(project.current_generation),
        visibility=cast(Any, visibility),
        lifecycle=cast(Any, lifecycle),
        management_version=int(project.management_version),
        assignee=assignee,
        priority=cast(Any, priority),
        due_at=project.due_at,
        updated_at=project.updated_at,
        owner=owner,
        members=members,
    )


def _project_member(row: Any) -> AdminProjectMember:
    role = str(row.role)
    if role not in _PROJECT_ROLES:
        raise IdentityConflict("project membership role is invalid")
    return AdminProjectMember(
        user_id=str(row.id),
        username=str(row.username),
        display_name=str(row.display_name),
        role=cast(Any, role),
        is_active=bool(row.is_active),
    )


def _audit_event(row: Any) -> AdministrativeAuditEvent:
    return AdministrativeAuditEvent(
        event_id=str(row.id),
        actor_username=_optional_string(row.actor_username),
        action=str(row.action),
        target_type=str(row.target_type),
        target_id=_optional_string(row.target_id),
        project_id=_optional_string(row.project_id),
        before=_json_object(row.before_json),
        after=_json_object(row.after_json),
        correlation_id=_optional_string(row.correlation_id),
        created_at=row.created_at,
    )


def _require_current_administrator(connection: Connection, user_id: str) -> None:
    row = connection.execute(
        select(WorkspaceUserRow.system_role, WorkspaceUserRow.is_active).where(
            WorkspaceUserRow.id == user_id
        )
    ).one_or_none()
    if row is None or not bool(row.is_active) or str(row.system_role) != "administrator":
        raise AdministrationDenied("system administrator permission is required")


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _json_object(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
