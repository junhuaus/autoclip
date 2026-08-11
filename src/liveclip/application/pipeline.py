from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.idempotency import IdempotencyContext
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    StageRunStatus,
    TaskStatus,
)


class StageLeaseLost(RuntimeError):
    """The caller no longer owns the durable stage task fence."""


class PipelineResourceNotFound(LookupError):
    """The requested project or pipeline run does not exist."""


class PipelineConflict(RuntimeError):
    """The requested pipeline mutation conflicts with persisted state."""


class DeterministicRetryRejected(PipelineConflict):
    """An unchanged deterministic pipeline failure cannot be retried."""


class PipelineConfigInvalid(PipelineConflict):
    """A persisted pipeline snapshot is legacy, incomplete, or fingerprint-invalid."""


class PipelineRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["2"] = "2"
    run_scope: Literal["full", "import"] = "full"
    provider: str = Field(pattern=r"^(mock|openai|mock-codex|openai-codex|openrouter-codex)$")
    top_n: int = Field(ge=1, le=100)
    minimum_clip_ms: int = Field(ge=1_000, le=600_000)
    maximum_clip_ms: int = Field(ge=1_000, le=1_800_000)
    chunk_duration_ms: int = Field(ge=10_000, le=3_600_000)
    chunk_overlap_ms: int = Field(ge=0, le=60_000)
    max_chunk_bytes: int = Field(ge=1_000_000, le=25_000_000)
    transcription_model: str = Field(min_length=1, max_length=100)
    llm_model: str = Field(min_length=1, max_length=100)
    preview_width: int = Field(ge=180, le=2_160)
    preview_height: int = Field(ge=320, le=3_840)
    video_encoder: str = Field(pattern=r"^(auto|h264_videotoolbox|libx264)$")
    asr_concurrency: int = Field(default=1, ge=1, le=8)
    asr_vocabulary_prompt: str = Field(
        default="LiveClip、直播、高光、切片",
        max_length=1_000,
    )
    openai_request_timeout_seconds: float = Field(default=120.0, ge=5, le=600)
    openai_max_request_retries: int = Field(default=2, ge=0, le=8)
    openai_retry_base_seconds: float = Field(default=1.0, gt=0, le=60)
    openai_retry_max_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_input_price_per_million: Decimal | None = Field(default=None, ge=0)
    llm_output_price_per_million: Decimal | None = Field(default=None, ge=0)
    asr_contract_version: str = Field(
        default="mock-asr-contract-v1",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    llm_contract_version: str = Field(
        default="mock-llm-contract-v2.no-blur",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    editing_prompt_version: str = Field(
        default="editing_v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    editing_prompt_sha256: str = Field(
        default="75a507f34c3e2bebb0f8c9b4668f5c4a6c57a8544aa8cc869d2e7284d6ad9c68",
        pattern=r"^[a-f0-9]{64}$",
    )
    editorial_schema_version: str = Field(
        default="editorial-suggestion-v2.no-layout",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    edit_plan_schema_version: str = Field(
        default="edit-plan-v1.caption-v2.clean-proxy-v2.no-blur-v1",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> PipelineRunConfig:
        if self.minimum_clip_ms > self.maximum_clip_ms:
            raise ValueError("minimum clip duration cannot exceed maximum")
        if self.chunk_overlap_ms >= self.chunk_duration_ms:
            raise ValueError("audio overlap must be shorter than a chunk")
        if self.chunk_overlap_ms * 2 > self.chunk_duration_ms:
            raise ValueError("audio overlap must not exceed half of a chunk")
        if self.preview_width >= self.preview_height:
            raise ValueError("preview render dimensions must be portrait")
        if self.preview_width % 2 or self.preview_height % 2:
            raise ValueError("preview render dimensions must be even")
        if self.openai_retry_base_seconds > self.openai_retry_max_seconds:
            raise ValueError("OpenAI retry base delay cannot exceed its maximum")
        if (self.llm_input_price_per_million is None) != (
            self.llm_output_price_per_million is None
        ):
            raise ValueError("both optional OpenAI LLM prices must be configured together")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_persisted_pipeline_config(
    payload: Mapping[str, object] | object,
    stored_fingerprint: str,
) -> PipelineRunConfig:
    """Load one immutable v2 snapshot and prove its database fingerprint."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") != "2":
        raise PipelineConfigInvalid("legacy pipeline config cannot be resumed safely")
    required_fields = frozenset(PipelineRunConfig.model_fields)
    if set(payload) != required_fields:
        raise PipelineConfigInvalid("pipeline config snapshot is incomplete or has unknown fields")
    try:
        # Pydantic's strict JSON contract intentionally accepts JSON strings for
        # Decimal, matching the exact representation emitted by ``mode='json'``.
        config = PipelineRunConfig.model_validate_json(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    except Exception as exc:
        raise PipelineConfigInvalid("pipeline config snapshot is invalid") from exc
    if config.fingerprint != stored_fingerprint:
        raise PipelineConfigInvalid("pipeline config fingerprint does not match its snapshot")
    return config


class CreatedPipeline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    run_id: str


class StageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: str
    status: StageRunStatus
    progress: int = Field(ge=0, le=100)
    retry_count: int = Field(ge=0)
    error_code: str | None = None
    safe_error_message: str | None = None


class RunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    project_id: str
    status: PipelineRunStatus
    progress: int = Field(ge=0, le=100)
    cancellation_requested: bool
    error_code: str | None = None
    safe_error_message: str | None = None
    stages: tuple[StageSnapshot, ...]


class ProjectSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    name: str
    source_filename: str
    status: ProjectStatus
    current_run_id: str
    generation: int = Field(ge=1)


class LeaseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    worker_id: str
    lease_token: str


class StageWork(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    stage_run_id: str
    run_id: str
    project_id: str
    stage: PipelineStage
    source_path: Path
    config: PipelineRunConfig
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    generation: int = Field(ge=1)
    revision_epoch: int = Field(ge=0)
    already_succeeded: bool
    output_fingerprint: str | None = None
    checkpoint: dict[str, object] | None = None
    cancellation_requested: bool


class StageExecutionRepository(Protocol):
    def start_or_resume_stage(self, lease: LeaseIdentity) -> StageWork: ...

    def complete_stage(
        self,
        lease: LeaseIdentity,
        *,
        output_fingerprint: str,
        checkpoint: dict[str, object],
        diagnostic_relative_path: str | None = None,
    ) -> bool: ...

    def fail_stage(
        self,
        lease: LeaseIdentity,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        retry_delay_ms: int,
        diagnostic_relative_path: str | None = None,
    ) -> TaskStatus | None: ...

    def cancel_stage(self, lease: LeaseIdentity) -> bool: ...


class PipelineRepository(Protocol):
    def replay_pipeline(
        self,
        idempotency: IdempotencyContext | None,
        *,
        expected_project_id: str | None = None,
    ) -> CreatedPipeline | None: ...

    def create_project_and_run(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline: ...

    def get_run(self, run_id: str) -> RunSnapshot: ...

    def get_project(self, project_id: str) -> ProjectSnapshot: ...

    def list_projects(self) -> tuple[ProjectSnapshot, ...]: ...

    def create_run(
        self,
        *,
        project_id: str,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline: ...

    def request_run_cancel(self, run_id: str) -> RunSnapshot: ...

    def retry_failed_run(self, run_id: str) -> RunSnapshot: ...


class PipelineService:
    def __init__(self, repository: PipelineRepository) -> None:
        self._repository = repository

    def create_project_and_run(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError("source path must be absolute and cannot contain '..'")
        if max_stage_retries < 0:
            raise ValueError("max stage retries must be nonnegative")
        return self._repository.create_project_and_run(
            source_path=source_path,
            config=config,
            max_stage_retries=max_stage_retries,
            idempotency=idempotency,
        )

    def replay_pipeline(
        self,
        idempotency: IdempotencyContext | None,
        *,
        expected_project_id: str | None = None,
    ) -> CreatedPipeline | None:
        """Replay a completed create before provider readiness is evaluated."""

        return self._repository.replay_pipeline(
            idempotency,
            expected_project_id=expected_project_id,
        )

    def import_project(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        payload = config.model_dump(mode="python")
        payload["run_scope"] = "import"
        import_config = PipelineRunConfig.model_validate(payload)
        return self.create_project_and_run(
            source_path=source_path,
            config=import_config,
            max_stage_retries=max_stage_retries,
            idempotency=idempotency,
        )

    def get_run(self, run_id: str) -> RunSnapshot:
        return self._repository.get_run(run_id)

    def get_project(self, project_id: str) -> ProjectSnapshot:
        return self._repository.get_project(project_id)

    def list_projects(self) -> tuple[ProjectSnapshot, ...]:
        return self._repository.list_projects()

    def create_run(
        self,
        *,
        project_id: str,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        if max_stage_retries < 0:
            raise ValueError("max stage retries must be nonnegative")
        return self._repository.create_run(
            project_id=project_id,
            config=config,
            max_stage_retries=max_stage_retries,
            idempotency=idempotency,
        )

    def cancel(self, run_id: str) -> RunSnapshot:
        return self._repository.request_run_cancel(run_id)

    def retry(self, run_id: str) -> RunSnapshot:
        return self._repository.retry_failed_run(run_id)
