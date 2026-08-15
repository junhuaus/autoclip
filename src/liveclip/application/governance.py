from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.identity import AdministrationDenied
from liveclip.application.workspace import WorkspaceUser

GovernanceAction = Literal["view", "transfer_ownership"]
GovernanceProjectRole = Literal["owner", "editor", "reviewer", "viewer"]


class AdminProjectMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str
    role: GovernanceProjectRole
    is_active: bool


class AdminProjectSnapshot(BaseModel):
    """A Project projection available only through an explicit admin route.

    It intentionally omits ordinary Project actions: system administration
    neither creates membership nor grants editorial authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    name: str
    source_filename: str
    pipeline_status: Literal["queued", "running", "completed", "failed", "cancelled"] | None
    current_run_id: str | None
    generation: int = Field(ge=0)
    visibility: Literal["private", "workspace"]
    lifecycle: Literal[
        "draft",
        "processing",
        "needs_attention",
        "editorial_review",
        "changes_requested",
        "approval",
        "ready_to_publish",
        "published",
        "archived",
    ]
    management_version: int = Field(ge=1)
    assignee: AdminProjectMember | None
    priority: Literal["low", "normal", "high", "urgent"]
    due_at: datetime | None
    updated_at: datetime | None
    owner: AdminProjectMember
    members: tuple[AdminProjectMember, ...]
    administrative_context: Literal[True] = True
    allowed_governance_actions: tuple[GovernanceAction, ...] = (
        "view",
        "transfer_ownership",
    )


class AdministrativeAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: str
    actor_username: str | None
    action: str
    target_type: str
    target_id: str | None
    project_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    correlation_id: str | None
    created_at: datetime


class ProjectGovernanceRepository(Protocol):
    def list_projects(self, actor: WorkspaceUser) -> tuple[AdminProjectSnapshot, ...]: ...

    def get_project(self, actor: WorkspaceUser, project_id: str) -> AdminProjectSnapshot: ...

    def transfer_project_ownership(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
        new_owner_user_id: str,
        correlation_id: str | None = None,
    ) -> AdminProjectSnapshot: ...

    def list_audit_events(
        self,
        *,
        actor: WorkspaceUser,
        limit: int,
        project_id: str | None,
    ) -> tuple[AdministrativeAuditEvent, ...]: ...


class ProjectGovernanceService:
    def __init__(self, repository: ProjectGovernanceRepository) -> None:
        self._repository = repository

    def list_projects(self, actor: WorkspaceUser) -> tuple[AdminProjectSnapshot, ...]:
        _require_administrator(actor)
        return self._repository.list_projects(actor)

    def get_project(self, actor: WorkspaceUser, project_id: str) -> AdminProjectSnapshot:
        _require_administrator(actor)
        return self._repository.get_project(actor, project_id)

    def transfer_project_ownership(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
        new_owner_user_id: str,
        correlation_id: str | None = None,
    ) -> AdminProjectSnapshot:
        _require_administrator(actor)
        return self._repository.transfer_project_ownership(
            actor=actor,
            project_id=project_id,
            new_owner_user_id=new_owner_user_id,
            correlation_id=correlation_id,
        )

    def list_audit_events(
        self,
        actor: WorkspaceUser,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> tuple[AdministrativeAuditEvent, ...]:
        _require_administrator(actor)
        if not 1 <= limit <= 200:
            raise ValueError("administrative audit limit must be between 1 and 200")
        return self._repository.list_audit_events(
            actor=actor,
            limit=limit,
            project_id=project_id,
        )


def _require_administrator(actor: WorkspaceUser) -> None:
    if actor.system_role != "administrator":
        raise AdministrationDenied("system administrator permission is required")
