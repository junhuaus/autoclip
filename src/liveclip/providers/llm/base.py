# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    validate_edit_plan_bounds,
)
from liveclip.providers.telemetry import ProviderCallRecord

EDITORIAL_SUGGESTION_SCHEMA_VERSION = "editorial-suggestion-v2.no-layout"
MOCK_LLM_CONTRACT_VERSION = "mock-llm-contract-v2.no-blur"


class EditorialSuggestionWire(BaseModel):
    """Strict model-owned fields; system identity/provenance is intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    title: str = Field(min_length=1, max_length=40)
    hook: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=240)
    caption_template: CaptionTemplate
    effect: Effect
    risk_flags: tuple[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
        ],
        ...,
    ] = Field(max_length=8)


class LLMDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    REPAIRED = "repaired"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    PROVIDER_ERROR = "provider_error"


class LLMProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    plan: EditPlan
    disposition: LLMDisposition
    call_records: tuple[ProviderCallRecord, ...] = ()


class LLMProvider(Protocol):
    """Editorial provider port. Implementations receive data, never executable hooks."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    @property
    def prompt_sha256(self) -> str: ...

    @property
    def contract_version(self) -> str: ...

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult: ...


def deterministic_edit_plan(
    candidate: CandidateClip,
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
    model: str,
    prompt_version: str,
    degraded: bool,
    risk_flags: tuple[str, ...],
) -> EditPlan:
    title, hook = editorial_labels(candidate.text)
    plan = EditPlan(
        candidate_id=candidate.candidate_id,
        source_start_ms=candidate.source_start_ms,
        source_end_ms=candidate.source_end_ms,
        score=round(candidate.rule_score, 3),
        title=title,
        hook=hook,
        reason=(
            "云端编辑不可用，已依据完整表达边界和规则分数生成可审核降级方案。"
            if degraded
            else "规则候选边界完整、表达紧凑，适合作为本地演示高光。"
        ),
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.FADE_IN_OUT,
        risk_flags=risk_flags,
        prompt_version=prompt_version,
        model=model,
        degraded=degraded,
    )
    validate_edit_plan_bounds(
        plan,
        source_duration_ms=source_duration_ms,
        minimum_duration_ms=minimum_duration_ms,
        maximum_duration_ms=maximum_duration_ms,
        allowed_start_ms=candidate.allowed_start_ms,
        allowed_end_ms=candidate.allowed_end_ms,
    )
    return plan


def editorial_labels(untrusted_transcript: str) -> tuple[str, str]:
    """Classify bounded content without treating transcript text as instructions."""

    if "误区" in untrusted_transcript or "很多人" in untrusted_transcript:
        return "常见表达误区", "这个常见误区，可能正在悄悄赶走你的观众。"
    if "方法" in untrusted_transcript or "步骤" in untrusted_transcript:
        return "三个实用表达方法", "掌握这几个方法，直播表达会立刻更清楚。"
    if "为什么" in untrusted_transcript or "？" in untrusted_transcript:
        return "关键问题解析", "先看清关键问题，再决定怎样行动。"
    return "直播核心观点", "用一个完整片段讲清这场直播的核心观点。"


def mock_prompt_sha256(prompt_version: str) -> str:
    return hashlib.sha256(f"mock\0{prompt_version}".encode()).hexdigest()
