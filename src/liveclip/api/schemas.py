from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.clips import ClipSummary
from liveclip.application.deliveries import DeliverySnapshot
from liveclip.application.reviewing import ClipDetail
from liveclip.domain.edit_plan import MAX_CAPTION_CUES, CaptionCue


class ApiRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobCreateRequest(ApiRequestModel):
    input_path: str = Field(min_length=1, max_length=4_096)
    top_n: int | None = Field(default=None, ge=1, le=100)
    minimum_clip_seconds: int | None = Field(default=None, ge=1, le=600)
    maximum_clip_seconds: int | None = Field(default=None, ge=1, le=1_800)

    @model_validator(mode="after")
    def validate_duration_bounds(self) -> JobCreateRequest:
        if (
            self.minimum_clip_seconds is not None
            and self.maximum_clip_seconds is not None
            and self.minimum_clip_seconds > self.maximum_clip_seconds
        ):
            raise ValueError("minimum clip duration cannot exceed maximum")
        return self


class RunCreateRequest(ApiRequestModel):
    top_n: int | None = Field(default=None, ge=1, le=100)
    minimum_clip_seconds: int | None = Field(default=None, ge=1, le=600)
    maximum_clip_seconds: int | None = Field(default=None, ge=1, le=1_800)

    @model_validator(mode="after")
    def validate_duration_bounds(self) -> RunCreateRequest:
        if (
            self.minimum_clip_seconds is not None
            and self.maximum_clip_seconds is not None
            and self.minimum_clip_seconds > self.maximum_clip_seconds
        ):
            raise ValueError("minimum clip duration cannot exceed maximum")
        return self


class CaptionCueRequest(ApiRequestModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_interval(self) -> CaptionCueRequest:
        if self.end_ms <= self.start_ms:
            raise ValueError("caption cue end must be greater than start")
        return self

    def to_domain(self) -> CaptionCue:
        return CaptionCue(start_ms=self.start_ms, end_ms=self.end_ms, text=self.text)


class ClipPatchRequest(ApiRequestModel):
    expected_revision: int = Field(ge=1)
    source_start_ms: int | None = Field(default=None, ge=0)
    source_end_ms: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=40)
    layout: Literal["center_crop"] | None = None
    captions: tuple[CaptionCueRequest, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_CAPTION_CUES
    )


class ReviewActionRequest(ApiRequestModel):
    expected_revision: int = Field(ge=1)
    status: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=1_000)
    source_start_ms: int | None = Field(default=None, ge=0)
    source_end_ms: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=40)
    layout: Literal["center_crop"] | None = None
    captions: tuple[CaptionCueRequest, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_CAPTION_CUES
    )


class RenderCreateRequest(ApiRequestModel):
    expected_revision: int = Field(ge=1)
    kind: Literal["proxy", "final"] = "final"


class DeliveryCreateRequest(ApiRequestModel):
    include_zip: bool = True


class AcceptedPipelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    run_id: str
    status: str
    status_url: str


class AcceptedTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    resource_type: Literal["render", "delivery"]
    resource_id: str
    task_id: str
    status: str
    status_url: str


class ProviderHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["mock", "openai", "mock-codex", "openai-codex", "openrouter-codex"]
    asr_provider: Literal["mock", "openai", "openrouter"]
    llm_provider: Literal["mock", "openai", "codex_cli"]
    asr_ready: bool
    llm_ready: bool
    processing_ready: bool
    blocking_issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    status: Literal["ok"] = "ok"
    version: str
    database: Literal["ok"] = "ok"
    providers: ProviderHealthResponse


class ClipSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clip: ClipSummary
    proxy_media_url: str | None


class ClipDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clip: ClipDetail
    asset_urls: dict[str, str]


class DeliveryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery: DeliverySnapshot
    download_url: str | None


class ApiErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    location: tuple[str | int, ...] = ()
    type: str


class ApiErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    code: str
    message: str
    retryable: bool = False
    resource_id: str | None = None
    correlation_id: str
    details: tuple[ApiErrorItem, ...] = ()


class ApiErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ApiErrorDetail
