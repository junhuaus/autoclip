"""Frozen SD-5 A preset identities and transport-neutral values."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.completion import CompletionSelectionPolicy


class CompletionPresetId(StrEnum):
    SHORT_HIGHLIGHT_V1 = "short_highlight_v1"
    MINI_LESSON_V1 = "mini_lesson_v1"


class CompletionPresetValues(BaseModel):
    """Versioned application values; provider settings are resolved separately."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    preset_id: CompletionPresetId
    clip_profile: ClipProfile
    minimum_clip_seconds: int = Field(ge=1, le=600)
    target_clip_seconds: int = Field(ge=1, le=600)
    maximum_clip_seconds: int = Field(ge=1, le=1_800)
    top_n: int = Field(ge=1, le=100)
    clipping_algorithm: Literal["semantic_windowed"] = "semantic_windowed"
    semantic_profile: Literal["general"] = "general"
    semantic_score_threshold: float = Field(ge=0, le=100)
    semantic_full_context_budget_ratio: float = Field(ge=0.1, le=0.8)
    semantic_model_context_tokens: int = Field(ge=16_000, le=2_000_000)
    default_selection_policy: CompletionSelectionPolicy = CompletionSelectionPolicy.DEFAULT
    include_zip: Literal[True] = True

    @model_validator(mode="after")
    def validate_duration_order(self) -> CompletionPresetValues:
        if not (self.minimum_clip_seconds <= self.target_clip_seconds <= self.maximum_clip_seconds):
            raise ValueError("preset duration bounds are out of order")
        return self


class CompletionPresetSummary(BaseModel):
    """Safe small descriptor for clients; no model or credential details."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    preset_id: CompletionPresetId
    display_name_zh: str = Field(min_length=1, max_length=40)
    clip_profile: ClipProfile
    minimum_clip_seconds: int = Field(ge=1, le=600)
    target_clip_seconds: int = Field(ge=1, le=600)
    maximum_clip_seconds: int = Field(ge=1, le=1_800)
    default_selection_policy: CompletionSelectionPolicy = CompletionSelectionPolicy.DEFAULT
    acceptance_status: Literal["experimental"] = "experimental"

    @model_validator(mode="after")
    def validate_duration_order(self) -> CompletionPresetSummary:
        if not (self.minimum_clip_seconds <= self.target_clip_seconds <= self.maximum_clip_seconds):
            raise ValueError("preset duration bounds are out of order")
        return self
