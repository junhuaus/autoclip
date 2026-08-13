from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

SystemRole = Literal["administrator", "member"]
WorkspaceRole = Literal["owner", "editor", "reviewer", "viewer"]


class WorkspaceUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str
    system_role: SystemRole = "member"


class WorkspaceMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str
    role: WorkspaceRole


class WorkspaceRepository(Protocol):
    def get_user_by_username(self, username: str) -> WorkspaceUser: ...

    def ensure_user(self, *, username: str, display_name: str) -> WorkspaceUser: ...

    def list_project_members(self, project_id: str) -> tuple[WorkspaceMembership, ...]: ...

    def get_project_membership(self, project_id: str, user_id: str) -> WorkspaceMembership: ...

    def add_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        username: str,
        display_name: str,
        role: Literal["editor", "reviewer", "viewer"],
        correlation_id: str | None = None,
    ) -> WorkspaceMembership: ...

    def remove_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        member_user_id: str,
        correlation_id: str | None = None,
    ) -> None: ...

    def transfer_project_ownership(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        new_owner_user_id: str,
        correlation_id: str | None = None,
    ) -> tuple[WorkspaceMembership, ...]: ...


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository

    def get_user_by_username(self, username: str) -> WorkspaceUser:
        return self._repository.get_user_by_username(username)

    def list_project_members(self, project_id: str) -> tuple[WorkspaceMembership, ...]:
        return self._repository.list_project_members(project_id)

    def get_project_membership(self, project_id: str, user_id: str) -> WorkspaceMembership:
        return self._repository.get_project_membership(project_id, user_id)

    def add_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        username: str,
        display_name: str,
        role: Literal["editor", "reviewer", "viewer"],
        correlation_id: str | None = None,
    ) -> WorkspaceMembership:
        return self._repository.add_project_member(
            project_id=project_id,
            acting_user_id=acting_user_id,
            username=username,
            display_name=display_name,
            role=role,
            correlation_id=correlation_id,
        )

    def remove_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        member_user_id: str,
        correlation_id: str | None = None,
    ) -> None:
        self._repository.remove_project_member(
            project_id=project_id,
            acting_user_id=acting_user_id,
            member_user_id=member_user_id,
            correlation_id=correlation_id,
        )

    def transfer_project_ownership(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        new_owner_user_id: str,
        correlation_id: str | None = None,
    ) -> tuple[WorkspaceMembership, ...]:
        return self._repository.transfer_project_ownership(
            project_id=project_id,
            acting_user_id=acting_user_id,
            new_owner_user_id=new_owner_user_id,
            correlation_id=correlation_id,
        )

    def ensure_configured_users(self, usernames: tuple[str, ...]) -> None:
        for username in usernames:
            self._repository.ensure_user(username=username, display_name=username)
