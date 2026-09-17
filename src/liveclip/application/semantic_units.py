"""Immutable semantic invocation authority; no transcript or response in the journal."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.stage_execution import StageMutationFence
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_EXECUTION,
    SEMANTIC_UNIT_MAX_INVOCATIONS,
    SemanticExecutionContract,
)

UnitDisposition = Literal["succeeded", "transient", "exhausted", "cancelled"]


class SemanticUnitConflict(RuntimeError):
    """The immutable invocation history or active publication fence is invalid."""


class SemanticUnitIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    semantic_stage: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    subject_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    request_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    execution_contract: SemanticExecutionContract = CURRENT_SEMANTIC_EXECUTION


class SemanticInvocation(SemanticUnitIdentity):
    invocation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    task_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    generation: int = Field(ge=1)
    invocation_number: int = Field(ge=1, le=SEMANTIC_UNIT_MAX_INVOCATIONS)
    reserved_at: datetime
    completed_at: datetime | None = None
    disposition: UnitDisposition | None = None
    repair_spent: bool | None = None
    outcome_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    outcome_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    outcome_size_bytes: int | None = Field(default=None, gt=0)
    outcome_relative_path: str | None = None

    @model_validator(mode="after")
    def complete_binding(self) -> SemanticInvocation:
        fields = (
            self.completed_at,
            self.disposition,
            self.repair_spent,
            self.outcome_asset_id,
            self.outcome_sha256,
            self.outcome_size_bytes,
            self.outcome_relative_path,
        )
        if any(value is None for value in fields) != all(value is None for value in fields):
            raise ValueError("semantic invocation completion binding is partial")
        if self.reserved_at.tzinfo is None or (
            self.completed_at is not None
            and (self.completed_at.tzinfo is None or self.completed_at < self.reserved_at)
        ):
            raise ValueError("semantic invocation timestamps are invalid")
        if self.disposition == "transient" and self.repair_spent:
            raise ValueError("semantic repair cannot be replenished by transient retry")
        return self


class SemanticInvocationOrigin(BaseModel):
    """Persisted origin of an invocation, authenticated by the journal store."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    invocation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    generation: int = Field(ge=1)
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    stage_input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class SemanticInvocationStore(Protocol):
    def load_history(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
    ) -> tuple[SemanticInvocation, ...]: ...

    def load_prior_success_history(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
    ) -> tuple[SemanticInvocation, ...]: ...

    def load_origin_identity(
        self,
        fence: StageMutationFence,
        invocation: SemanticInvocation,
    ) -> SemanticInvocationOrigin:
        """Authenticate the exact invocation and its originating run/stage rows.

        The returned fingerprints come from persisted origin rows, not the requesting
        run or outcome envelope. Validate the active fence and all origin bindings
        together in one read transaction before returning this identity.
        """
        ...

    def reserve(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
        *,
        expected_history: tuple[str, ...],
    ) -> SemanticInvocation: ...

    def complete(
        self,
        fence: StageMutationFence,
        invocation: SemanticInvocation,
        *,
        outcome_asset_id: str,
        expected_sha256: str,
        expected_size_bytes: int,
        disposition: UnitDisposition,
        repair_spent: bool,
    ) -> SemanticInvocation: ...
