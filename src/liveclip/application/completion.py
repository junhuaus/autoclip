"""Application contracts for one durable processing or delivery goal."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.delivery_progress import DeliveryProgressSnapshot
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import PipelineRunConfig
from liveclip.domain.completion import (
    CompletionIntentStatus,
    CompletionOutcome,
    CompletionSelectionPolicy,
    CompletionTarget,
)


class CompletionConflict(RuntimeError):
    """A request conflicts with the saved goal or its current project state."""


class CompletionResourceNotFound(LookupError):
    """The requested goal is not visible to the current actor."""


class CompletionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    target: CompletionTarget = CompletionTarget.DELIVERY
    selection_policy: CompletionSelectionPolicy = CompletionSelectionPolicy.DEFAULT
    include_zip: bool = True
    preset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def validate_target_options(self) -> CompletionOptions:
        if self.target == CompletionTarget.PROCESS_ONLY:
            if self.selection_policy != CompletionSelectionPolicy.DEFAULT:
                raise ValueError("processing-only goals cannot request clip selection")
            if self.include_zip:
                raise ValueError("processing-only goals cannot request a ZIP")
        return self


class CompletionSelectedClip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    expected_revision: int = Field(ge=1)


class CompletionCheckpointClip(BaseModel):
    """One approved current revision bound to its exact review decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    edit_plan_revision_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    edit_plan_revision: int = Field(ge=1)
    decision_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class CompletionSelectionCheckpoint(BaseModel):
    """Version-one durable selection projection, including an intentionally empty set."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    intent_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    generation: int = Field(ge=1)
    mode: CompletionSelectionPolicy
    action_key: str = Field(min_length=1, max_length=160)
    selected: tuple[CompletionCheckpointClip, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def require_unique_clips(self) -> CompletionSelectionCheckpoint:
        ids = tuple(item.clip_id for item in self.selected)
        if len(ids) != len(set(ids)):
            raise ValueError("checkpoint clip IDs must be unique")
        return self


class CompletionSelectionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_version: int = Field(ge=1)
    selected: tuple[CompletionSelectedClip, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def require_unique_clips(self) -> CompletionSelectionSubmission:
        ids = tuple(item.clip_id for item in self.selected)
        if len(ids) != len(set(ids)):
            raise ValueError("selected clip IDs must be unique")
        return self


class CompletionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    intent_id: str
    project_id: str
    run_id: str
    generation: int = Field(ge=1)
    requester_user_id: str
    actor_user_id: str
    options: CompletionOptions
    status: CompletionIntentStatus
    version: int = Field(ge=1)
    selection_submitted: bool
    delivery_id: str | None
    outcome: CompletionOutcome | None
    blocking_code: str | None
    safe_error_message: str | None
    delivery_progress: DeliveryProgressSnapshot | None = None


class CompletionRepository(Protocol):
    def create_for_existing_run(
        self,
        *,
        project_id: str,
        run_id: str,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
    ) -> CompletionSnapshot: ...

    def create_project_and_run_with_goal(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
        fresh_source_guard: Callable[[Path], Path] | None = None,
    ) -> CompletionSnapshot: ...

    def get(self, intent_id: str, *, actor_user_id: str) -> CompletionSnapshot: ...

    def list_for_project(
        self, project_id: str, *, actor_user_id: str
    ) -> tuple[CompletionSnapshot, ...]: ...

    def resume(
        self, intent_id: str, *, actor_user_id: str, expected_version: int
    ) -> CompletionSnapshot: ...

    def submit_selection(
        self,
        intent_id: str,
        submission: CompletionSelectionSubmission,
        *,
        actor_user_id: str,
    ) -> CompletionSnapshot: ...

    def cancel(
        self, intent_id: str, *, actor_user_id: str, expected_version: int
    ) -> CompletionSnapshot: ...
