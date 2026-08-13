from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.workspace import WorkspaceMembership, WorkspaceUser
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import ProjectMemberRow, WorkspaceUserRow


class WorkspaceUserNotFound(LookupError):
    """The authenticated workspace user does not exist or is inactive."""


class WorkspacePermissionDenied(PermissionError):
    """The authenticated workspace user cannot change this project's members."""


class SqlAlchemyWorkspaceRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_user_by_username(self, username: str) -> WorkspaceUser:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.system_role,
                ).where(
                    WorkspaceUserRow.username == username,
                    WorkspaceUserRow.is_active.is_(True),
                )
            ).one_or_none()
        if row is None:
            raise WorkspaceUserNotFound("workspace user does not exist")
        return WorkspaceUser(
            user_id=str(row.id),
            username=str(row.username),
            display_name=str(row.display_name),
            system_role=str(row.system_role),  # type: ignore[arg-type]
        )

    def ensure_user(self, *, username: str, display_name: str) -> WorkspaceUser:
        try:
            return self.get_user_by_username(username)
        except WorkspaceUserNotFound:
            pass
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.system_role,
                ).where(WorkspaceUserRow.username == username)
            ).one_or_none()
            if row is None:
                user_id = new_id()
                connection.execute(
                    insert(WorkspaceUserRow).values(
                        id=user_id,
                        username=username,
                        display_name=display_name,
                        system_role="member",
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return WorkspaceUser(
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                    system_role="member",
                )
            if not bool(
                connection.scalar(
                    select(WorkspaceUserRow.is_active).where(WorkspaceUserRow.id == row.id)
                )
            ):
                raise WorkspaceUserNotFound("workspace user does not exist")
            return WorkspaceUser(
                user_id=str(row.id),
                username=str(row.username),
                display_name=str(row.display_name),
                system_role=str(row.system_role),  # type: ignore[arg-type]
            )

    def list_project_members(self, project_id: str) -> tuple[WorkspaceMembership, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    ProjectMemberRow.role,
                )
                .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
                .where(
                    ProjectMemberRow.project_id == project_id,
                    WorkspaceUserRow.is_active.is_(True),
                )
                .order_by(
                    case((ProjectMemberRow.role == "owner", 0), else_=1),
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.id,
                )
            )
        memberships: list[WorkspaceMembership] = []
        for row in rows:
            role = str(row.role)
            if role not in {"owner", "editor", "reviewer", "viewer"}:
                raise WorkspaceUserNotFound("project membership role is invalid")
            memberships.append(
                WorkspaceMembership(
                    user_id=str(row.id),
                    username=str(row.username),
                    display_name=str(row.display_name),
                    role=role,  # type: ignore[arg-type]
                )
            )
        return tuple(memberships)

    def get_project_membership(self, project_id: str, user_id: str) -> WorkspaceMembership:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    ProjectMemberRow.role,
                )
                .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
                .where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                    WorkspaceUserRow.is_active.is_(True),
                )
            ).one_or_none()
        if row is None:
            raise WorkspaceUserNotFound("project membership does not exist")
        role = str(row.role)
        if role not in {"owner", "editor", "reviewer", "viewer"}:
            raise WorkspaceUserNotFound("project membership role is invalid")
        return WorkspaceMembership(
            user_id=str(row.id),
            username=str(row.username),
            display_name=str(row.display_name),
            role=role,  # type: ignore[arg-type]
        )

    def add_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        username: str,
        display_name: str,
        role: Literal["editor", "reviewer", "viewer"],
    ) -> WorkspaceMembership:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            _require_project_owner(connection, project_id, acting_user_id)
            user = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.is_active,
                ).where(WorkspaceUserRow.username == username)
            ).one_or_none()
            if user is None or not bool(user.is_active):
                raise WorkspaceUserNotFound("active workspace user does not exist")
            user_id = str(user.id)
            membership = connection.execute(
                select(ProjectMemberRow.id, ProjectMemberRow.role).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
            ).one_or_none()
            if membership is None:
                connection.execute(
                    insert(ProjectMemberRow).values(
                        id=new_id(),
                        project_id=project_id,
                        user_id=user_id,
                        role=role,
                        created_at=now,
                    )
                )
            elif str(membership.role) == "owner":
                raise WorkspacePermissionDenied("project owner role cannot be changed")
            else:
                connection.execute(
                    update(ProjectMemberRow)
                    .where(ProjectMemberRow.id == membership.id)
                    .values(role=role)
                )
        return WorkspaceMembership(
            user_id=str(user_id),
            username=username,
            display_name=str(user.display_name),
            role=role,
        )

    def remove_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        member_user_id: str,
    ) -> None:
        with begin_immediate(self._engine) as connection:
            _require_project_owner(connection, project_id, acting_user_id)
            membership = connection.execute(
                select(ProjectMemberRow.id, ProjectMemberRow.role).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == member_user_id,
                )
            ).one_or_none()
            if membership is None:
                raise WorkspaceUserNotFound("project member does not exist")
            if str(membership.role) == "owner":
                raise WorkspacePermissionDenied("project owner cannot be removed")
            connection.execute(delete(ProjectMemberRow).where(ProjectMemberRow.id == membership.id))


def _require_project_owner(connection: Connection, project_id: str, user_id: str) -> None:
    role = connection.scalar(
        select(ProjectMemberRow.role).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == user_id,
        )
    )
    if role != "owner":
        raise WorkspacePermissionDenied("only the project owner can manage members")
