from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.domain.state_transitions import DeliveryStatus


class DeliveryConflict(RuntimeError):
    """The current approved render set is not eligible for delivery."""


class DeliveryResourceNotFound(LookupError):
    """The requested delivery does not exist."""


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    include_zip: bool = True


class DeliverySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delivery_id: str
    project_id: str
    task_id: str
    version: int = Field(ge=1)
    delivery_version: str
    status: DeliveryStatus
    clip_count: int = Field(ge=0)
    manifest_asset_id: str | None
    zip_asset_id: str | None
    include_zip: bool
    error_code: str | None
    safe_error_message: str | None


@dataclass(frozen=True, slots=True)
class DeliveryWorkClip:
    clip_id: str
    edit_plan_revision_id: str
    render_job_id: str
    edit_plan_revision: int
    title: str
    source_start_ms: int
    source_end_ms: int
    score: float
    video_relative_path: str
    video_sha256: str
    subtitle_relative_path: str
    subtitle_sha256: str


@dataclass(frozen=True, slots=True)
class DeliveryWork:
    delivery_id: str
    task_id: str
    project_id: str
    run_id: str
    generation: int
    revision_epoch: int
    version: int
    include_zip: bool
    snapshot_fingerprint: str
    package_fingerprint: str
    created_at: datetime
    source_filename: str
    source_fingerprint: str
    clips: tuple[DeliveryWorkClip, ...]


@dataclass(frozen=True, slots=True)
class DeliveryManifestClip:
    clip_id: str
    edit_plan_revision: int
    title: str
    video_filename: str
    subtitle_filename: str
    source_start_ms: int
    source_end_ms: int
    duration_ms: int
    score: float
    review_status: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DeliveryPersistence:
    manifest_asset_id: str
    zip_asset_id: str | None
    manifest_clips: tuple[DeliveryManifestClip, ...]


class DeliveryRepository(Protocol):
    def enqueue_delivery(
        self,
        project_id: str,
        request: DeliveryRequest,
        *,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> DeliverySnapshot: ...

    def get_delivery(self, delivery_id: str) -> DeliverySnapshot: ...

    def list_deliveries(self, project_id: str) -> tuple[DeliverySnapshot, ...]: ...

    def start_delivery(self, lease: LeaseIdentity) -> DeliveryWork: ...

    def complete_delivery(
        self,
        lease: LeaseIdentity,
        work: DeliveryWork,
        persistence: DeliveryPersistence,
    ) -> bool: ...


class DeliveryService:
    def __init__(self, repository: DeliveryRepository, *, max_retries: int) -> None:
        self._repository = repository
        self._max_retries = max_retries

    def enqueue(
        self,
        project_id: str,
        request: DeliveryRequest,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> DeliverySnapshot:
        return self._repository.enqueue_delivery(
            project_id,
            request,
            max_retries=self._max_retries,
            idempotency=idempotency,
        )

    def get(self, delivery_id: str) -> DeliverySnapshot:
        return self._repository.get_delivery(delivery_id)

    def list(self, project_id: str) -> tuple[DeliverySnapshot, ...]:
        return self._repository.list_deliveries(project_id)
