from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.releases import (
    PlatformPreset,
    ReleaseApprovalStatus,
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleaseItemStatus,
    ReleasePackageStatus,
    ReleasePlatform,
    ReleasePreflight,
    current_platform_preset_versions,
    get_platform_preset,
    list_platform_presets,
)


class ReleaseConflict(RuntimeError):
    """A release mutation or package no longer matches current trusted state."""


class ReleaseResourceNotFound(LookupError):
    """The requested release item or package does not exist."""


class ReleaseItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)
    platform: ReleasePlatform
    account_label: str = Field(min_length=1, max_length=120)
    caption_mode: ReleaseCaptionMode = ReleaseCaptionMode.CLEAN_SEPARATE
    assignee_user_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    planned_publish_at: datetime | None = None

    @field_validator("account_label")
    @classmethod
    def strip_account_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("release account label cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self) -> ReleaseItemCreate:
        _validate_optional_aware(self.planned_publish_at, "planned publish time")
        return self


class ReleaseItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_management_version: int = Field(ge=1)
    edit_plan_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=100)
    title_variants: tuple[str, ...] = Field(default=(), max_length=3)
    description: str = Field(default="", max_length=5_000)
    hashtags: tuple[str, ...] = Field(default=(), max_length=20)
    cta: str = Field(default="", max_length=200)
    caption_mode: ReleaseCaptionMode
    cover_time_ms: int = Field(ge=0)
    assignee_user_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    planned_publish_at: datetime | None
    checklist: ReleaseChecklist

    @field_validator("title", "description", "cta")
    @classmethod
    def strip_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        if info.field_name == "title" and not normalized:
            raise ValueError("release title cannot be blank")
        return normalized

    @field_validator("title_variants")
    @classmethod
    def validate_title_variants(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 100 for item in normalized):
            raise ValueError("release title variants must contain 1-100 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("release title variants must be unique")
        return normalized

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lstrip("#").strip() for item in value)
        if any(not item or len(item) > 50 for item in normalized):
            raise ValueError("release hashtags must contain 1-50 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("release hashtags must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self) -> ReleaseItemUpdate:
        _validate_optional_aware(self.planned_publish_at, "planned publish time")
        return self


class ReleaseApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_management_version: int = Field(ge=1)
    target: ReleaseApprovalStatus
    reason: str = Field(min_length=1, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("release approval reason cannot be blank")
        return normalized


class ReleaseStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_management_version: int = Field(ge=1)
    target: ReleaseItemStatus
    release_package_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    external_url: str | None = Field(default=None, max_length=1_000)
    external_id: str | None = Field(default=None, max_length=200)
    published_at: datetime | None = None
    result_notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("external_url")
    @classmethod
    def validate_external_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("release external URL must be an HTTPS public URL")
        return normalized

    @field_validator("external_id", "result_notes")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_outcome(self) -> ReleaseStatusCommand:
        _validate_optional_aware(self.published_at, "published time")
        if self.target is ReleaseItemStatus.PUBLISHED:
            if self.release_package_id is None:
                raise ValueError("published release requires the exact platform package")
            if self.external_url is None and self.external_id is None:
                raise ValueError("published release requires an external URL or ID")
            if self.published_at is None:
                raise ValueError("published release requires a published time")
        elif any(
            value is not None
            for value in (
                self.release_package_id,
                self.external_url,
                self.external_id,
                self.published_at,
            )
        ):
            raise ValueError("publication evidence is only accepted for published releases")
        if self.target is ReleaseItemStatus.FAILED and self.result_notes is None:
            raise ValueError("failed release requires result notes")
        return self


class ReleaseMetricCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    captured_at: datetime
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    saves: int = Field(default=0, ge=0)
    followers_gained: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_capture(self) -> ReleaseMetricCreate:
        _validate_optional_aware(self.captured_at, "metric capture time")
        return self


class ReleasePackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_release_item_version: int = Field(ge=1)
    include_zip: Literal[True] = True


class ReleaseAssignee(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str


class ReleaseMetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    metric_id: str
    captured_at: datetime
    views: int = Field(ge=0)
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    shares: int = Field(ge=0)
    saves: int = Field(ge=0)
    followers_gained: int = Field(ge=0)
    notes: str | None
    recorded_by_username: str
    created_at: datetime


class ReleasePackageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    release_package_id: str
    release_item_id: str
    project_id: str
    task_id: str
    requested_by_user_id: str
    version: int = Field(ge=1)
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    release_item_version: int = Field(ge=1)
    current: bool
    published_artifact: bool
    status: ReleasePackageStatus
    preset_version: str
    caption_mode: ReleaseCaptionMode
    manifest_asset_id: str | None
    zip_asset_id: str | None
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    include_zip: bool
    error_code: str | None
    safe_error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class ReleasePublicationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["liveclip.release-publication-evidence.v1"] = (
        "liveclip.release-publication-evidence.v1"
    )
    release_package_id: str
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    release_item_version: int = Field(ge=1)
    preset_version: str
    caption_mode: ReleaseCaptionMode
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_kind: Literal["zip", "manifest"]
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    recorded_at: datetime


class ReleaseItemSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    release_item_id: str
    project_id: str
    clip_id: str
    edit_plan_revision: int = Field(ge=1)
    current_edit_plan_revision: int = Field(ge=1)
    stale: bool
    stale_reason: Literal["revision_changed", "project_run_changed"] | None
    platform: ReleasePlatform
    preset_version: str
    account_label: str
    title: str
    title_variants: tuple[str, ...]
    description: str
    hashtags: tuple[str, ...]
    cta: str
    caption_mode: ReleaseCaptionMode
    cover_time_ms: int = Field(ge=0)
    clip_duration_ms: int = Field(gt=0)
    high_impact_sentence: str
    risk_flags: tuple[str, ...]
    preview_asset_id: str | None
    assignee: ReleaseAssignee | None
    planned_publish_at: datetime | None
    approval_status: ReleaseApprovalStatus
    status: ReleaseItemStatus
    checklist: ReleaseChecklist
    preflight: ReleasePreflight
    management_version: int = Field(ge=1)
    external_url: str | None
    external_id: str | None
    published_at: datetime | None
    result_notes: str | None
    publication_evidence: ReleasePublicationEvidence | None
    metrics: tuple[ReleaseMetricSnapshot, ...]
    packages: tuple[ReleasePackageSnapshot, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReleasePackageWork:
    release_package_id: str
    release_item_id: str
    task_id: str
    project_id: str
    project_name: str
    requested_by_user_id: str
    requested_by_username: str
    run_id: str
    generation: int
    revision_epoch: int
    release_item_version: int
    version: int
    preset: PlatformPreset
    caption_mode: ReleaseCaptionMode
    include_zip: bool
    snapshot_fingerprint: str
    package_fingerprint: str
    snapshot: dict[str, object]
    created_at: datetime
    source_filename: str
    source_fingerprint: str
    source_render_job_id: str
    source_video_asset_id: str
    source_video_relative_path: str
    source_video_sha256: str
    source_video_size_bytes: int
    clip_id: str
    edit_plan_revision: int
    source_start_ms: int
    source_end_ms: int
    score: float
    high_impact_sentence: str
    risk_flags: tuple[str, ...]
    account_label: str
    planned_publish_at: datetime | None
    title: str
    description: str
    title_variants: tuple[str, ...]
    hashtags: tuple[str, ...]
    cta: str
    cover_time_ms: int
    captions: tuple[CaptionCue, ...]
    preflight: ReleasePreflight
    checklist: ReleaseChecklist


@dataclass(frozen=True, slots=True)
class ReleasePackagePersistence:
    manifest_asset_id: str
    zip_asset_id: str | None
    manifest_sha256: str
    zip_sha256: str | None


class ReleaseRepository(Protocol):
    def create_item(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        command: ReleaseItemCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot: ...

    def update_item(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseItemUpdate,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot: ...

    def transition_approval(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseApprovalCommand,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot: ...

    def transition_status(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseStatusCommand,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot: ...

    def add_metric(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseMetricCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot: ...

    def get_item(self, release_item_id: str) -> ReleaseItemSnapshot: ...

    def list_items(self, project_id: str) -> tuple[ReleaseItemSnapshot, ...]: ...

    def enqueue_package(
        self,
        release_item_id: str,
        *,
        requested_by_user_id: str,
        request: ReleasePackageRequest,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleasePackageSnapshot: ...

    def get_package(self, release_package_id: str) -> ReleasePackageSnapshot: ...

    def is_release_package_task(self, task_id: str, target_id: str) -> bool: ...

    def start_release_package(self, lease: LeaseIdentity) -> ReleasePackageWork: ...

    def assert_release_package_current(
        self,
        lease: LeaseIdentity,
        work: ReleasePackageWork,
    ) -> None: ...

    def complete_release_package(
        self,
        lease: LeaseIdentity,
        work: ReleasePackageWork,
        persistence: ReleasePackagePersistence,
    ) -> bool: ...


class ReleaseService:
    def __init__(self, repository: ReleaseRepository, *, max_retries: int) -> None:
        self._repository = repository
        self._max_retries = max_retries

    def presets(self, *, include_historical: bool = False) -> tuple[PlatformPreset, ...]:
        return list_platform_presets(include_historical=include_historical)

    def current_preset_versions(self) -> dict[ReleasePlatform, str]:
        return current_platform_preset_versions()

    def create_item(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        command: ReleaseItemCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot:
        get_platform_preset(command.platform)
        return self._repository.create_item(
            project_id=project_id,
            acting_user_id=acting_user_id,
            command=command,
            correlation_id=correlation_id,
            idempotency=idempotency,
        )

    def update_item(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseItemUpdate,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        return self._repository.update_item(
            release_item_id,
            acting_user_id=acting_user_id,
            command=command,
            correlation_id=correlation_id,
        )

    def transition_approval(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseApprovalCommand,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        return self._repository.transition_approval(
            release_item_id,
            acting_user_id=acting_user_id,
            command=command,
            correlation_id=correlation_id,
        )

    def transition_status(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseStatusCommand,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        return self._repository.transition_status(
            release_item_id,
            acting_user_id=acting_user_id,
            command=command,
            correlation_id=correlation_id,
        )

    def add_metric(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseMetricCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot:
        return self._repository.add_metric(
            release_item_id,
            acting_user_id=acting_user_id,
            command=command,
            correlation_id=correlation_id,
            idempotency=idempotency,
        )

    def get_item(self, release_item_id: str) -> ReleaseItemSnapshot:
        return self._repository.get_item(release_item_id)

    def list_items(self, project_id: str) -> tuple[ReleaseItemSnapshot, ...]:
        return self._repository.list_items(project_id)

    def enqueue_package(
        self,
        release_item_id: str,
        *,
        requested_by_user_id: str,
        request: ReleasePackageRequest,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleasePackageSnapshot:
        return self._repository.enqueue_package(
            release_item_id,
            requested_by_user_id=requested_by_user_id,
            request=request,
            max_retries=self._max_retries,
            idempotency=idempotency,
        )

    def get_package(self, release_package_id: str) -> ReleasePackageSnapshot:
        return self._repository.get_package(release_package_id)


def release_package_path(work: ReleasePackageWork, project_dir: Path) -> Path:
    return project_dir / "release-packages" / work.release_item_id / f"v{work.version:03d}"


def _validate_optional_aware(value: datetime | None, label: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"release {label} must include a timezone")


__all__ = [
    "ReleaseApprovalCommand",
    "ReleaseAssignee",
    "ReleaseConflict",
    "ReleaseItemCreate",
    "ReleaseItemSnapshot",
    "ReleaseItemUpdate",
    "ReleaseMetricCreate",
    "ReleaseMetricSnapshot",
    "ReleasePackagePersistence",
    "ReleasePackageRequest",
    "ReleasePackageSnapshot",
    "ReleasePackageWork",
    "ReleaseRepository",
    "ReleaseResourceNotFound",
    "ReleaseService",
    "release_package_path",
]
