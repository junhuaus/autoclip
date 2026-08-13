from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from liveclip.application.clips import ClipSummary
from liveclip.application.deliveries import DeliverySnapshot
from liveclip.application.identity import ManagedUser
from liveclip.application.reviewing import BatchReviewCommand, BatchReviewItem, ClipDetail
from liveclip.application.workspace import WorkspaceMembership, WorkspaceUser
from liveclip.domain.edit_plan import MAX_CAPTION_CUES, CaptionCue
from liveclip.domain.state_transitions import ReviewStatus


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


class BatchReviewItemRequest(ApiRequestModel):
    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)
    status: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=1_000)


class BatchReviewRequest(ApiRequestModel):
    items: tuple[BatchReviewItemRequest, ...] = Field(min_length=1, max_length=100)

    def to_command(self) -> BatchReviewCommand:
        return BatchReviewCommand(
            items=tuple(
                BatchReviewItem(
                    clip_id=item.clip_id,
                    expected_revision=item.expected_revision,
                    status=ReviewStatus(item.status),
                    reason=item.reason,
                )
                for item in self.items
            )
        )


class RenderCreateRequest(ApiRequestModel):
    expected_revision: int = Field(ge=1)
    kind: Literal["proxy", "final"] = "final"


class DeliveryCreateRequest(ApiRequestModel):
    include_zip: bool = True


class ProjectMemberCreateRequest(ApiRequestModel):
    username: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["editor", "reviewer", "viewer"]


class LoginRequest(ApiRequestModel):
    username: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    password: SecretStr = Field(min_length=1, max_length=128)


class AdminUserCreateRequest(ApiRequestModel):
    username: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    system_role: Literal["administrator", "member"] = "member"
    password: SecretStr = Field(min_length=12, max_length=128)


class AdminUserPatchRequest(ApiRequestModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    system_role: Literal["administrator", "member"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> AdminUserPatchRequest:
        if self.display_name is None and self.system_role is None and self.is_active is None:
            raise ValueError("at least one user field must change")
        return self


class AdminPasswordResetRequest(ApiRequestModel):
    password: SecretStr = Field(min_length=12, max_length=128)


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


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    user: WorkspaceUser
    credential_kind: Literal["session", "legacy"] = "legacy"
    csrf_token: str | None = None
    expires_at: str | None = None


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    user: WorkspaceUser
    csrf_token: str
    expires_at: str


class AdminUsersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    users: tuple[ManagedUser, ...]


class ProjectMembersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    members: tuple[WorkspaceMembership, ...]


class ClipSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clip: ClipSummary
    proxy_media_url: str | None


class ClipDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clip: ClipDetail
    asset_urls: dict[str, str]


class BatchReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    clips: tuple[ClipDetailResponse, ...]


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
