from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.clips import ClipQueryService, ClipSummary
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.domain.edit_plan import CaptionCue, captions_to_srt
from liveclip.domain.keywords import KeywordOccurrence
from liveclip.domain.state_transitions import EditPackageStatus, RenderStatus, ReviewStatus

EditPackagePreset = Literal["clean_editing"]
EditPackageContent = Literal["full", "metadata_only"]


class EditPackageConflict(RuntimeError):
    """The selected current clip set cannot produce a trustworthy editor package."""


class EditPackageResourceNotFound(LookupError):
    """The requested editor package does not exist."""


class EditPackageItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)


class EditPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[EditPackageItem, ...] = Field(min_length=1, max_length=100)
    preset: EditPackagePreset = "clean_editing"
    content: EditPackageContent = "full"
    include_zip: bool = True

    @model_validator(mode="after")
    def validate_unique_selection(self) -> EditPackageRequest:
        identifiers = tuple(item.clip_id for item in self.items)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("edit package clip IDs must be unique")
        return self


class EditPackageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    edit_package_id: str
    project_id: str
    task_id: str
    requested_by_user_id: str
    version: int = Field(ge=1)
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    status: EditPackageStatus
    clip_count: int = Field(ge=0)
    preset: EditPackagePreset
    content: EditPackageContent
    manifest_asset_id: str | None
    zip_asset_id: str | None
    include_zip: bool
    error_code: str | None
    safe_error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class EditPackageClipMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    candidate_key: str = Field(min_length=1, max_length=64)
    edit_plan_revision: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    title: str = Field(min_length=1, max_length=40)
    high_impact_sentence: str = Field(min_length=1, max_length=80)
    recommendation_reason: str = Field(min_length=1, max_length=240)
    risk_flags: tuple[str, ...] = Field(max_length=8)
    captions: tuple[CaptionCue, ...] = Field(min_length=1)
    keywords: tuple[KeywordOccurrence, ...]
    review_status: ReviewStatus

    @model_validator(mode="after")
    def validate_timeline(self) -> EditPackageClipMetadata:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("edit package clip interval must be positive")
        duration_ms = self.source_end_ms - self.source_start_ms
        if any(cue.end_ms > duration_ms for cue in self.captions):
            raise ValueError("edit package subtitle exceeds its clip duration")
        return self


@dataclass(frozen=True, slots=True)
class EditPackageWorkClip:
    ordinal: int
    edit_plan_revision_id: str
    render_job_id: str
    metadata: EditPackageClipMetadata
    video_asset_id: str
    video_relative_path: str
    video_sha256: str
    video_size_bytes: int
    contact_sheet_asset_id: str
    contact_sheet_relative_path: str
    contact_sheet_sha256: str
    contact_sheet_size_bytes: int


@dataclass(frozen=True, slots=True)
class EditPackageWork:
    edit_package_id: str
    task_id: str
    project_id: str
    project_name: str
    owner_username: str
    requested_by_user_id: str
    requested_by_username: str
    run_id: str
    generation: int
    revision_epoch: int
    version: int
    preset: EditPackagePreset
    content: EditPackageContent
    include_zip: bool
    snapshot_fingerprint: str
    package_fingerprint: str
    created_at: datetime
    source_filename: str
    source_fingerprint: str
    clips: tuple[EditPackageWorkClip, ...]


@dataclass(frozen=True, slots=True)
class EditPackageManifestClip:
    clip_id: str
    ordinal: int
    edit_plan_revision: int
    title: str
    video_filename: str | None
    subtitle_filename: str | None
    thumbnail_filename: str
    video_sha256: str | None
    subtitle_sha256: str | None
    thumbnail_sha256: str


@dataclass(frozen=True, slots=True)
class EditPackagePersistence:
    manifest_asset_id: str
    zip_asset_id: str | None
    manifest_clips: tuple[EditPackageManifestClip, ...]
    directory_identity: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class ClipHandoffDownload:
    project_id: str
    clip_id: str
    edit_plan_revision: int
    title: str
    video_asset_id: str
    subtitle_srt: str


class EditPackageRepository(Protocol):
    def enqueue_edit_package(
        self,
        project_id: str,
        requested_by_user_id: str,
        request: EditPackageRequest,
        selections: tuple[ClipSummary, ...],
        *,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> EditPackageSnapshot: ...

    def get_edit_package(self, edit_package_id: str) -> EditPackageSnapshot: ...

    def list_edit_packages(self, project_id: str) -> tuple[EditPackageSnapshot, ...]: ...

    def is_edit_package_task(self, task_id: str, target_id: str) -> bool: ...

    def start_edit_package(self, lease: LeaseIdentity) -> EditPackageWork: ...

    def assert_edit_package_current(
        self,
        lease: LeaseIdentity,
        work: EditPackageWork,
    ) -> None: ...

    def complete_edit_package(
        self,
        lease: LeaseIdentity,
        work: EditPackageWork,
        persistence: EditPackagePersistence,
    ) -> bool: ...

    def get_clip_handoff_download(self, clip_id: str) -> ClipHandoffDownload: ...


class EditPackageService:
    def __init__(
        self,
        repository: EditPackageRepository,
        clips: ClipQueryService,
        *,
        max_retries: int,
    ) -> None:
        self._repository = repository
        self._clips = clips
        self._max_retries = max_retries

    def enqueue(
        self,
        project_id: str,
        requested_by_user_id: str,
        request: EditPackageRequest,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> EditPackageSnapshot:
        current = {clip.clip_id: clip for clip in self._clips.list_project_clips(project_id)}
        selected: list[ClipSummary] = []
        for item in request.items:
            clip = current.get(item.clip_id)
            if clip is None:
                raise EditPackageConflict("selected clip is not current for this project")
            if clip.edit_plan_revision != item.expected_revision:
                raise EditPackageConflict("selected clip revision changed")
            if clip.proxy_asset_id is None or clip.proxy_status != RenderStatus.SUCCEEDED:
                raise EditPackageConflict("selected clip has no current clean review video")
            selected.append(clip)
        return self._repository.enqueue_edit_package(
            project_id,
            requested_by_user_id,
            request,
            tuple(selected),
            max_retries=self._max_retries,
            idempotency=idempotency,
        )

    def get(self, edit_package_id: str) -> EditPackageSnapshot:
        return self._repository.get_edit_package(edit_package_id)

    def list(self, project_id: str) -> tuple[EditPackageSnapshot, ...]:
        return self._repository.list_edit_packages(project_id)

    def clip_download(self, clip_id: str) -> ClipHandoffDownload:
        return self._repository.get_clip_handoff_download(clip_id)


def subtitle_for_metadata(metadata: EditPackageClipMetadata) -> str:
    return captions_to_srt(metadata.captions)
