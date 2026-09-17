from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.authorization import ProjectAction
from liveclip.application.idempotency import IdempotencyContext
from liveclip.domain.clip_profile import ClipProfile, clip_profile_spec
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_EXECUTION,
    CURRENT_SEMANTIC_LINEAGE,
    CURRENT_SEMANTIC_TRANSPORT,
    CURRENT_SEMANTIC_VALIDATION,
    LEGACY_SEMANTIC_VALIDATION,
    SemanticExecutionContract,
    SemanticLineageContract,
    SemanticTransportContract,
    SemanticValidationContract,
)
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    StageRunStatus,
    TaskStatus,
)
from liveclip.limits import (
    MAX_LLM_REQUEST_TIMEOUT_SECONDS,
    MIN_LLM_REQUEST_TIMEOUT_SECONDS,
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


class _PipelineRunConfigFields(BaseModel):
    """Fields shared by historical v2 and current v3 immutable snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_scope: Literal["full", "import"] = "full"
    provider: str = Field(
        pattern=r"^(mock|openai|mock-codex|openai-codex|openrouter-codex|mlx-codex)$"
    )
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
    asr_concurrency: int = Field(default=4, ge=1, le=8)
    asr_vocabulary_prompt: str = Field(
        default="LiveClip、直播、高光、切片",
        max_length=1_000,
    )
    openai_request_timeout_seconds: float = Field(
        default=300.0,
        ge=MIN_LLM_REQUEST_TIMEOUT_SECONDS,
        le=MAX_LLM_REQUEST_TIMEOUT_SECONDS,
    )
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
        default="edit-plan-v1.caption-v2.clean-delivery-master-v1.no-blur-v1",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> _PipelineRunConfigFields:
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


class _PipelineRunConfigV2(_PipelineRunConfigFields):
    """Exact historical snapshot contract; never use for newly-created runs."""

    schema_version: Literal["2"] = "2"


class _PipelineRunConfigV3(_PipelineRunConfigFields):
    """Exact historical Algorithm B v1 snapshot contract."""

    schema_version: Literal["3"] = "3"
    clipping_algorithm: Literal["a", "b"] = "a"
    semantic_skill_version: str = Field(
        default="semantic_window_v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )
    semantic_score_threshold: float = Field(default=75.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_semantic_config(self) -> _PipelineRunConfigV3:
        if self.clipping_algorithm == "b" and self.maximum_clip_ms > 600_000:
            raise ValueError("algorithm B maximum clip duration cannot exceed 10 minutes")
        return self


class _PipelineRunConfigV4(_PipelineRunConfigV3):
    """Exact experimental Algorithm B v2 snapshot contract."""

    schema_version: Literal["4"] = "4"  # type: ignore[assignment]
    semantic_target_clip_ms: int = Field(default=60_000, ge=1_000, le=600_000)
    semantic_continuous_merge_enabled: bool = False
    semantic_consolidation_skill_version: str = Field(
        default="semantic_continuous_v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_consolidation_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def validate_continuous_semantic_config(self) -> _PipelineRunConfigV4:
        if self.clipping_algorithm != "b":
            return self
        if self.semantic_continuous_merge_enabled and not (
            self.minimum_clip_ms <= self.semantic_target_clip_ms <= self.maximum_clip_ms
        ):
            raise ValueError("algorithm B target duration must be between minimum and maximum")
        if (
            self.semantic_continuous_merge_enabled
            and self.semantic_consolidation_skill_sha256 == "0" * 64
        ):
            raise ValueError("algorithm B continuous merge requires a Skill fingerprint")
        return self


class _PipelineRunConfigV5(_PipelineRunConfigV4):
    """Immutable v5 snapshot with Full-first semantic-global clipping."""

    schema_version: Literal["5"] = "5"  # type: ignore[assignment]
    clipping_algorithm: Literal[
        "a", "b", "b_v2_experimental", "semantic_global", "semantic_windowed"
    ] = "a"  # type: ignore[assignment]
    semantic_profile: Literal["general", "vocal_coach_live"] = "general"
    semantic_discovery_skill_version: str = Field(
        default="semantic_global_v1.discovery",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_discovery_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )
    semantic_global_review_skill_version: str = Field(
        default="semantic_global_v2.global_review",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_global_review_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )
    semantic_full_context_budget_ratio: float = Field(default=0.58, ge=0.1, le=0.8)
    semantic_model_context_tokens: int = Field(default=128_000, ge=16_000, le=2_000_000)
    semantic_tokenizer_name: str = Field(
        default="o200k_base",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_output_reserve_tokens: int = Field(default=16_000, ge=2_000, le=200_000)
    semantic_safety_margin_tokens: int = Field(default=1_000, ge=1_000, le=200_000)
    semantic_fallback_target_ms: int = Field(default=900_000, ge=60_000, le=3_600_000)
    semantic_fallback_minimum_ms: int = Field(default=600_000, ge=60_000, le=3_600_000)
    semantic_fallback_maximum_ms: int = Field(default=1_200_000, ge=60_000, le=3_600_000)
    semantic_fallback_context_guard_ms: int = Field(default=30_000, ge=0, le=300_000)
    semantic_global_context_ms: int = Field(default=90_000, ge=30_000, le=300_000)
    semantic_no_render: bool = False
    semantic_prompt_debug: bool = False

    @model_validator(mode="after")
    def validate_semantic_global_config(self) -> _PipelineRunConfigV5:
        if self.clipping_algorithm == "b" and self.semantic_continuous_merge_enabled:
            raise ValueError("algorithm B v1 cannot enable experimental continuous consolidation")
        if self.clipping_algorithm == "b_v2_experimental" and not (
            self.semantic_continuous_merge_enabled
            and self.semantic_consolidation_skill_sha256 != "0" * 64
        ):
            raise ValueError("experimental Algorithm B v2 requires its consolidation Skill")
        if self.clipping_algorithm not in {"semantic_global", "semantic_windowed"}:
            return self
        if not self.minimum_clip_ms <= self.semantic_target_clip_ms <= self.maximum_clip_ms:
            raise ValueError("semantic global duration must satisfy minimum <= target <= maximum")
        if self.maximum_clip_ms > 600_000:
            raise ValueError("semantic global maximum duration cannot exceed 10 minutes")
        if "0" * 64 in {
            self.semantic_discovery_skill_sha256,
            self.semantic_global_review_skill_sha256,
        }:
            raise ValueError("semantic global requires Discovery and Global Review Skill hashes")
        if not (
            self.semantic_fallback_minimum_ms
            <= self.semantic_fallback_target_ms
            <= self.semantic_fallback_maximum_ms
        ):
            raise ValueError("semantic fallback duration must satisfy minimum <= target <= maximum")
        budget = int(self.semantic_model_context_tokens * self.semantic_full_context_budget_ratio)
        if self.semantic_output_reserve_tokens + self.semantic_safety_margin_tokens >= budget:
            raise ValueError("semantic global reserves leave no model input budget")
        return self


class _PipelineRunConfigV6(_PipelineRunConfigV5):
    """Immutable v6 snapshot with candidate Boundary Review and Global Review v3."""

    schema_version: Literal["6"] = "6"  # type: ignore[assignment]
    semantic_global_review_skill_version: str = Field(
        default="semantic_global_v3.global_review",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_boundary_review_skill_version: str = Field(
        default="semantic_global_v3.boundary_review",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_boundary_review_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def validate_boundary_review_config(self) -> _PipelineRunConfigV6:
        if (
            self.clipping_algorithm in {"semantic_global", "semantic_windowed"}
            and self.semantic_global_review_skill_version == "semantic_global_v3.global_review"
            and self.semantic_boundary_review_skill_sha256 == "0" * 64
        ):
            raise ValueError("semantic global v3 requires a Boundary Review Skill hash")
        return self


class _PipelineRunConfigV7(_PipelineRunConfigV6):
    """Immutable v7 snapshot with an explicit mini-lesson Topic Chain Profile."""

    schema_version: Literal["7"] = "7"  # type: ignore[assignment]
    clip_profile: ClipProfile = ClipProfile.SHORT_HIGHLIGHT
    semantic_link_review_skill_version: str = Field(
        default="semantic_topic_chain_v1.link_review",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_link_review_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )
    semantic_topic_chain_skill_version: str = Field(
        default="semantic_topic_chain_v1.topic_chain",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_topic_chain_skill_sha256: str = Field(
        default="0" * 64,
        pattern=r"^[a-f0-9]{64}$",
    )
    semantic_result_schema_version: Literal["4"] = "4"

    @model_validator(mode="after")
    def validate_clip_profile_config(self) -> _PipelineRunConfigV7:
        if self.clip_profile != ClipProfile.MINI_LESSON:
            return self
        if self.clipping_algorithm != "semantic_windowed":
            raise ValueError("mini_lesson requires semantic_windowed Topic Chain processing")
        spec = clip_profile_spec(self.clip_profile)
        if (
            self.minimum_clip_ms,
            self.semantic_target_clip_ms,
            self.maximum_clip_ms,
        ) != (
            spec.minimum_duration_ms,
            spec.target_duration_ms,
            spec.maximum_duration_ms,
        ):
            raise ValueError("mini_lesson duration bounds are fixed at 90/180/300 seconds")
        if "0" * 64 in {
            self.semantic_discovery_skill_sha256,
            self.semantic_link_review_skill_sha256,
            self.semantic_topic_chain_skill_sha256,
            self.semantic_boundary_review_skill_sha256,
            self.semantic_global_review_skill_sha256,
        }:
            raise ValueError("mini_lesson requires every Topic Chain Prompt fingerprint")
        expected_versions = (
            "semantic_topic_chain_v1.discovery",
            "semantic_topic_chain_v1.link_review",
            "semantic_topic_chain_v1.topic_chain",
            "semantic_topic_chain_v1.boundary_review",
            "semantic_topic_chain_v1.global_review",
        )
        actual_versions = (
            self.semantic_discovery_skill_version,
            self.semantic_link_review_skill_version,
            self.semantic_topic_chain_skill_version,
            self.semantic_boundary_review_skill_version,
            self.semantic_global_review_skill_version,
        )
        if actual_versions != expected_versions:
            raise ValueError("mini_lesson requires the installed Topic Chain v1 contracts")
        return self


class PipelineRunConfig(_PipelineRunConfigV7):
    """Immutable v8 snapshot with an independently versioned quality validator."""

    schema_version: Literal["8"] = "8"  # type: ignore[assignment]
    semantic_validation_contract: SemanticValidationContract = CURRENT_SEMANTIC_VALIDATION


class PipelineRunConfigV9(PipelineRunConfig):
    """New mini runs preserve explicit V5 lineage and the accepted quality contract."""

    schema_version: Literal["9"] = "9"  # type: ignore[assignment]
    semantic_result_schema_version: Literal["5"] = "5"  # type: ignore[assignment]
    clip_profile: ClipProfile = ClipProfile.MINI_LESSON
    semantic_lineage_contract: SemanticLineageContract = CURRENT_SEMANTIC_LINEAGE
    semantic_validation_contract: Literal["semantic-v4-quality-v2"] = "semantic-v4-quality-v2"
    semantic_discovery_skill_version: str = Field(
        default="semantic_topic_chain_v2.discovery",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_topic_chain_skill_version: str = Field(
        default="semantic_topic_chain_v2.topic_chain",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    semantic_boundary_review_skill_version: str = Field(
        default="semantic_topic_chain_v2.boundary_review",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )

    @model_validator(mode="after")
    def validate_clip_profile_config(self) -> PipelineRunConfigV9:
        if (
            self.clip_profile != ClipProfile.MINI_LESSON
            or self.clipping_algorithm != "semantic_windowed"
        ):
            raise ValueError("v9 requires mini_lesson semantic_windowed processing")
        spec = clip_profile_spec(self.clip_profile)
        if (self.minimum_clip_ms, self.semantic_target_clip_ms, self.maximum_clip_ms) != (
            spec.minimum_duration_ms,
            spec.target_duration_ms,
            spec.maximum_duration_ms,
        ):
            raise ValueError("mini_lesson duration bounds are fixed at 90/180/300 seconds")
        stages = ("discovery", "link_review", "topic_chain", "boundary_review", "global_review")
        expected = (
            "semantic_topic_chain_v2.discovery",
            "semantic_topic_chain_v1.link_review",
            "semantic_topic_chain_v2.topic_chain",
            "semantic_topic_chain_v2.boundary_review",
            "semantic_topic_chain_v1.global_review",
        )
        if tuple(getattr(self, f"semantic_{stage}_skill_version") for stage in stages) != expected:
            raise ValueError("v9 requires the installed lineage and quality prompt contracts")
        if any(getattr(self, f"semantic_{stage}_skill_sha256") == "0" * 64 for stage in stages):
            raise ValueError("v9 requires all five prompt fingerprints")
        return self


class PipelineRunConfigV10(PipelineRunConfig):
    """New non-mini runs use measured, lossless semantic request transport."""

    schema_version: Literal["10"] = "10"  # type: ignore[assignment]
    semantic_transport_contract: SemanticTransportContract = CURRENT_SEMANTIC_TRANSPORT

    @model_validator(mode="after")
    def validate_transport_profile(self) -> PipelineRunConfigV10:
        if self.clip_profile == ClipProfile.MINI_LESSON:
            raise ValueError("new mini_lesson transport requires v11 lineage")
        return self


class PipelineRunConfigV11(PipelineRunConfigV9):
    """New mini runs bind lossless transport alongside unchanged V5 lineage."""

    schema_version: Literal["11"] = "11"  # type: ignore[assignment]
    semantic_transport_contract: SemanticTransportContract = CURRENT_SEMANTIC_TRANSPORT


class PipelineRunConfigV12(PipelineRunConfigV10):
    """Bounded semantic invocations with immutable run-scoped repair accounting."""

    schema_version: Literal["12"] = "12"  # type: ignore[assignment]
    semantic_execution_contract: SemanticExecutionContract = CURRENT_SEMANTIC_EXECUTION


class PipelineRunConfigV13(PipelineRunConfigV11):
    """Mini lineage plus bounded, durably accounted semantic invocations."""

    schema_version: Literal["13"] = "13"  # type: ignore[assignment]
    semantic_execution_contract: SemanticExecutionContract = CURRENT_SEMANTIC_EXECUTION


PipelineConfig = Annotated[
    PipelineRunConfig
    | PipelineRunConfigV9
    | PipelineRunConfigV10
    | PipelineRunConfigV11
    | PipelineRunConfigV12
    | PipelineRunConfigV13,
    Field(discriminator="schema_version"),
]


def load_persisted_pipeline_config(
    payload: Mapping[str, object] | object,
    stored_fingerprint: str,
) -> PipelineConfig:
    """Load exact v8--v13 snapshots or adapt fingerprinted historical v2--v7 in memory."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") not in {
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
    }:
        raise PipelineConfigInvalid("legacy pipeline config cannot be resumed safely")
    version = payload.get("schema_version")
    model = (
        _PipelineRunConfigV2
        if version == "2"
        else _PipelineRunConfigV3
        if version == "3"
        else _PipelineRunConfigV4
        if version == "4"
        else _PipelineRunConfigV5
        if version == "5"
        else _PipelineRunConfigV6
        if version == "6"
        else _PipelineRunConfigV7
        if version == "7"
        else PipelineRunConfigV13
        if version == "13"
        else PipelineRunConfigV12
        if version == "12"
        else PipelineRunConfigV11
        if version == "11"
        else PipelineRunConfigV10
        if version == "10"
        else PipelineRunConfigV9
        if version == "9"
        else PipelineRunConfig
    )
    required_fields = frozenset(model.model_fields)
    if set(payload) != required_fields:
        raise PipelineConfigInvalid("pipeline config snapshot is incomplete or has unknown fields")
    try:
        # Pydantic's strict JSON contract intentionally accepts JSON strings for
        # Decimal, matching the exact representation emitted by ``mode='json'``.
        persisted = model.model_validate_json(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    except Exception as exc:
        raise PipelineConfigInvalid("pipeline config snapshot is invalid") from exc
    if persisted.fingerprint != stored_fingerprint:
        raise PipelineConfigInvalid("pipeline config fingerprint does not match its snapshot")
    if isinstance(persisted, PipelineRunConfig):
        return persisted
    upgraded = persisted.model_dump(mode="python")
    upgraded["schema_version"] = "8"
    upgraded["semantic_validation_contract"] = LEGACY_SEMANTIC_VALIDATION
    if isinstance(persisted, _PipelineRunConfigV7):
        # Preserve the exact mini profile and all five frozen prompt identities.
        return PipelineRunConfig.model_validate(upgraded)
    if isinstance(persisted, _PipelineRunConfigV2):
        upgraded.update(
            clipping_algorithm="a",
            semantic_skill_version="semantic_window_v1",
            semantic_skill_sha256="0" * 64,
            semantic_score_threshold=75.0,
        )
    if isinstance(persisted, (_PipelineRunConfigV2, _PipelineRunConfigV3)):
        upgraded.update(
            semantic_target_clip_ms=int(persisted.maximum_clip_ms),
            semantic_continuous_merge_enabled=False,
            semantic_consolidation_skill_version="semantic_continuous_v1",
            semantic_consolidation_skill_sha256="0" * 64,
        )
    if (
        isinstance(persisted, _PipelineRunConfigV4)
        and persisted.clipping_algorithm == "b"
        and persisted.semantic_continuous_merge_enabled
    ):
        upgraded["clipping_algorithm"] = "b_v2_experimental"
    if not isinstance(persisted, _PipelineRunConfigV5):
        upgraded.update(
            semantic_profile="general",
            semantic_discovery_skill_version="semantic_global_v1.discovery",
            semantic_discovery_skill_sha256="0" * 64,
            semantic_global_review_skill_version="semantic_global_v1.global_review",
            semantic_global_review_skill_sha256="0" * 64,
            semantic_full_context_budget_ratio=0.58,
            semantic_model_context_tokens=128_000,
            semantic_tokenizer_name="o200k_base",
            semantic_output_reserve_tokens=16_000,
            semantic_safety_margin_tokens=1_000,
            semantic_fallback_target_ms=900_000,
            semantic_fallback_minimum_ms=600_000,
            semantic_fallback_maximum_ms=1_200_000,
            semantic_fallback_context_guard_ms=30_000,
            semantic_global_context_ms=90_000,
            semantic_no_render=False,
            semantic_prompt_debug=False,
        )
    upgraded.update(
        semantic_boundary_review_skill_version="semantic_global_v3.boundary_review",
        semantic_boundary_review_skill_sha256="0" * 64,
    )
    if isinstance(persisted, _PipelineRunConfigV6):
        upgraded["semantic_boundary_review_skill_version"] = (
            persisted.semantic_boundary_review_skill_version
        )
        upgraded["semantic_boundary_review_skill_sha256"] = (
            persisted.semantic_boundary_review_skill_sha256
        )
    upgraded.update(
        clip_profile=ClipProfile.SHORT_HIGHLIGHT,
        semantic_link_review_skill_version="semantic_topic_chain_v1.link_review",
        semantic_link_review_skill_sha256="0" * 64,
        semantic_topic_chain_skill_version="semantic_topic_chain_v1.topic_chain",
        semantic_topic_chain_skill_sha256="0" * 64,
        semantic_result_schema_version="4",
    )
    return PipelineRunConfig.model_validate(upgraded)


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
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_units: int | None = Field(default=None, ge=0)
    total_units: int | None = Field(default=None, ge=1)
    unit_label: str | None = None
    activity_count: int | None = Field(default=None, ge=1)
    activity_label: str | None = None

    @model_validator(mode="after")
    def validate_units(self) -> StageSnapshot:
        values = (self.completed_units, self.total_units, self.unit_label)
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError("stage unit progress must be complete or absent")
        if (
            self.completed_units is not None
            and self.total_units is not None
            and self.completed_units > self.total_units
        ):
            raise ValueError("completed stage units cannot exceed total units")
        if (self.activity_count is None) != (self.activity_label is None):
            raise ValueError("stage activity progress must be complete or absent")
        return self


class RunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    project_id: str
    status: PipelineRunStatus
    progress: int = Field(ge=0, le=100)
    cancellation_requested: bool
    error_code: str | None = None
    safe_error_message: str | None = None
    active_task_heartbeat_at: datetime | None = None
    active_task_lease_expires_at: datetime | None = None
    stages: tuple[StageSnapshot, ...]


class WorkspaceMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str
    role: Literal["owner", "editor", "reviewer", "viewer"]


class ProjectSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    name: str
    source_filename: str
    status: ProjectStatus
    current_run_id: str
    generation: int = Field(ge=1)
    visibility: Literal["private", "workspace"] = "private"
    lifecycle: ProjectLifecycle = ProjectLifecycle.PROCESSING
    lifecycle_before_archive: ProjectLifecycle | None = None
    management_version: int = Field(default=1, ge=1)
    assignee: WorkspaceMember | None = None
    priority: ProjectPriority = ProjectPriority.NORMAL
    due_at: datetime | None = None
    updated_at: datetime | None = None
    owner: WorkspaceMember
    members: tuple[WorkspaceMember, ...]
    current_user_role: Literal["owner", "editor", "reviewer", "viewer"]
    allowed_actions: tuple[ProjectAction, ...] = ()
    allowed_lifecycle_transitions: tuple[ProjectLifecycle, ...] = ()


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
    config: PipelineConfig
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


PipelineCapability = Literal["asr", "semantic"]


@dataclass(frozen=True, slots=True)
class ActionReadiness:
    required: tuple[PipelineCapability, ...]
    satisfied: tuple[PipelineCapability, ...]
    blocking_issues: tuple[str, ...]


class ActionNotReady(PipelineConflict):
    def __init__(self, readiness: ActionReadiness) -> None:
        self.readiness = readiness
        super().__init__("Remaining actions are blocked: " + ", ".join(readiness.blocking_issues))


@dataclass(frozen=True, slots=True)
class PipelineRecoveryActions:
    run_id: str
    config: PipelineConfig
    remaining_stages: tuple[PipelineStage, ...]
    required: tuple[PipelineCapability, ...]
    state_fingerprint: str


ActionReadinessCheck = Callable[[PipelineConfig, tuple[PipelineCapability, ...]], ActionReadiness]


def required_pipeline_capabilities(
    config: PipelineConfig,
    remaining_stages: tuple[PipelineStage, ...],
    *,
    edit_committed: bool = False,
) -> tuple[PipelineCapability, ...]:
    if config.run_scope == "import":
        return ()
    required: list[PipelineCapability] = []
    if PipelineStage.TRANSCRIBE in remaining_stages:
        required.append("asr")
    if (PipelineStage.EDIT in remaining_stages and not edit_committed) or (
        PipelineStage.CANDIDATES in remaining_stages
        and config.clipping_algorithm in {"semantic_global", "semantic_windowed"}
    ):
        required.append("semantic")
    return tuple(required)


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
        owner_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline: ...

    def get_run(self, run_id: str) -> RunSnapshot: ...

    def get_project(self, project_id: str, *, user_id: str | None = None) -> ProjectSnapshot: ...

    def list_projects(self, *, user_id: str | None = None) -> tuple[ProjectSnapshot, ...]: ...

    def create_run(
        self,
        *,
        project_id: str,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline: ...

    def request_run_cancel(self, run_id: str) -> RunSnapshot: ...

    def recovery_actions(self, run_id: str) -> PipelineRecoveryActions: ...

    def retry_failed_run(
        self, run_id: str, *, expected_actions: PipelineRecoveryActions | None = None
    ) -> RunSnapshot: ...


class PipelineService:
    def __init__(
        self,
        repository: PipelineRepository,
        *,
        forbidden_source_roots: tuple[Path, ...] = (),
        readiness_check: ActionReadinessCheck | None = None,
    ) -> None:
        self._repository = repository
        self._readiness_check = readiness_check
        self._forbidden_source_roots = tuple(
            root.expanduser().resolve(strict=False) for root in forbidden_source_roots
        )

    def create_project_and_run(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        owner_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError("source path must be absolute and cannot contain '..'")
        resolved_source = source_path.expanduser().resolve(strict=False)
        if any(
            resolved_source == root or root in resolved_source.parents
            for root in self._forbidden_source_roots
        ):
            raise ValueError("source media must be outside the LiveClip data directory")
        if max_stage_retries < 0:
            raise ValueError("max stage retries must be nonnegative")
        return self._repository.create_project_and_run(
            source_path=resolved_source,
            config=config,
            max_stage_retries=max_stage_retries,
            owner_id=owner_id,
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
        owner_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        payload = config.model_dump(mode="python")
        payload["run_scope"] = "import"
        import_config = type(config).model_validate(payload)
        return self.create_project_and_run(
            source_path=source_path,
            config=import_config,
            max_stage_retries=max_stage_retries,
            owner_id=owner_id,
            idempotency=idempotency,
        )

    def get_run(self, run_id: str) -> RunSnapshot:
        return self._repository.get_run(run_id)

    def get_project(self, project_id: str, *, user_id: str | None = None) -> ProjectSnapshot:
        return self._repository.get_project(project_id, user_id=user_id)

    def list_projects(self, *, user_id: str | None = None) -> tuple[ProjectSnapshot, ...]:
        return self._repository.list_projects(user_id=user_id)

    def list_projects_for_user(self, user_id: str) -> tuple[ProjectSnapshot, ...]:
        return self.list_projects(user_id=user_id)

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
        actions = self._repository.recovery_actions(run_id)
        if self._readiness_check is not None:
            self._readiness_check(actions.config, actions.required)
        return self._repository.retry_failed_run(run_id, expected_actions=actions)
