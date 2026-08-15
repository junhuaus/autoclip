from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority

ProjectVisibility = Literal["private", "workspace"]


class ProjectManagementConflict(RuntimeError):
    """Project management metadata changed or violates a persisted invariant."""


class ProjectManagementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_management_version: int = Field(ge=1)
    visibility: ProjectVisibility
    assignee_user_id: str | None
    priority: ProjectPriority
    due_at: datetime | None

    @model_validator(mode="after")
    def validate_due_at(self) -> ProjectManagementUpdate:
        if self.due_at is not None and (
            self.due_at.tzinfo is None or self.due_at.utcoffset() is None
        ):
            raise ValueError("project due time must include a timezone")
        return self


class ProjectLifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_management_version: int = Field(ge=1)
    target: ProjectLifecycle
    reason: str = Field(min_length=1, max_length=500)


class ProjectActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: str
    actor_username: str | None
    action: str
    target_type: str
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class ProjectManagementRepository(Protocol):
    def update_management(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectManagementUpdate,
        correlation_id: str | None = None,
    ) -> None: ...

    def transition_lifecycle(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectLifecycleUpdate,
        correlation_id: str | None = None,
    ) -> None: ...

    def list_activity(self, project_id: str, *, limit: int) -> tuple[ProjectActivity, ...]: ...


class ProjectManagementService:
    def __init__(self, repository: ProjectManagementRepository) -> None:
        self._repository = repository

    def update_management(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectManagementUpdate,
        correlation_id: str | None = None,
    ) -> None:
        self._repository.update_management(
            project_id=project_id,
            acting_user_id=acting_user_id,
            update=update,
            correlation_id=correlation_id,
        )

    def transition_lifecycle(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        update: ProjectLifecycleUpdate,
        correlation_id: str | None = None,
    ) -> None:
        self._repository.transition_lifecycle(
            project_id=project_id,
            acting_user_id=acting_user_id,
            update=update,
            correlation_id=correlation_id,
        )

    def list_activity(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> tuple[ProjectActivity, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("project activity limit must be between 1 and 200")
        return self._repository.list_activity(project_id, limit=limit)
