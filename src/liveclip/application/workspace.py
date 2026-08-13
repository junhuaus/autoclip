from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

WorkspaceRole = Literal["owner", "editor", "reviewer"]


class WorkspaceUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str


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

    def add_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        username: str,
        display_name: str,
        role: Literal["editor", "reviewer"],
    ) -> WorkspaceMembership: ...

    def remove_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        member_user_id: str,
    ) -> None: ...


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository

    def get_user_by_username(self, username: str) -> WorkspaceUser:
        return self._repository.get_user_by_username(username)

    def list_project_members(self, project_id: str) -> tuple[WorkspaceMembership, ...]:
        return self._repository.list_project_members(project_id)

    def add_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        username: str,
        display_name: str,
        role: Literal["editor", "reviewer"],
    ) -> WorkspaceMembership:
        return self._repository.add_project_member(
            project_id=project_id,
            acting_user_id=acting_user_id,
            username=username,
            display_name=display_name,
            role=role,
        )

    def remove_project_member(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        member_user_id: str,
    ) -> None:
        self._repository.remove_project_member(
            project_id=project_id,
            acting_user_id=acting_user_id,
            member_user_id=member_user_id,
        )

    def ensure_configured_users(self, usernames: tuple[str, ...]) -> None:
        for username in usernames:
            self._repository.ensure_user(username=username, display_name=username)
