"""Immutable customer deliveries of imported dual-profile clips (Stage 19c).

A customer delivery is a versioned snapshot (v001, v002, …) of the clips that
are currently selected for delivery and deliverable, with their *effective*
customer text (reviewer overrides applied). Creating a version queues one
worker Task that builds the offline package; later reviewer decisions never
change an existing version.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.state_transitions import DeliveryStatus

CUSTOMER_DELIVERY_TITLE_MAX_CHARS = 80
CUSTOMER_DELIVERY_MANIFEST_KIND = "customer_delivery_manifest"
CUSTOMER_DELIVERY_ZIP_KIND = "customer_delivery_zip"


class CustomerDeliveryConflict(RuntimeError):
    """The customer delivery cannot be created or completed in the current state (409)."""


class CustomerDeliveryNotFound(LookupError):
    """The customer delivery or its project import does not exist (404)."""


def validate_delivery_title(value: str) -> str:
    title = unicodedata.normalize("NFC", value).strip()
    if not title or len(title) > CUSTOMER_DELIVERY_TITLE_MAX_CHARS:
        raise ValueError(f"delivery title must be 1-{CUSTOMER_DELIVERY_TITLE_MAX_CHARS} characters")
    if any(unicodedata.category(character).startswith("C") for character in title):
        raise ValueError("delivery title must not contain control characters")
    return title


class CustomerDeliveryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=200)
    expected_clip_ids: tuple[str, ...] | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return validate_delivery_title(value)


class CustomerDeliverySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_id: str
    project_id: str
    task_id: str | None
    version: int
    delivery_version: str
    title: str
    status: DeliveryStatus
    clip_count: int
    short_count: int
    lesson_count: int
    created_by: str
    created_at: datetime
    completed_at: datetime | None
    zip_asset_id: str | None
    error_code: str | None
    safe_error_message: str | None


@dataclass(frozen=True, slots=True)
class CustomerDeliveryWorkClip:
    ordinal: int
    profile: ClipProfile
    title: str
    hook: str
    summary: str
    duration_ms: int
    video_relative_path: str
    video_sha256: str
    video_size_bytes: int
    subtitle_relative_path: str
    subtitle_sha256: str
    subtitle_size_bytes: int


@dataclass(frozen=True, slots=True)
class CustomerDeliveryWork:
    task_id: str
    delivery_id: str
    project_id: str
    version: int
    title: str
    created_at: datetime
    snapshot_fingerprint: str
    clips: tuple[CustomerDeliveryWorkClip, ...]

    @property
    def delivery_version(self) -> str:
        return f"v{self.version:03d}"


@dataclass(frozen=True, slots=True)
class CustomerDeliveryPersistence:
    directory_relative_path: str
    manifest_relative_path: str
    manifest_sha256: str
    manifest_size_bytes: int
    zip_relative_path: str
    zip_sha256: str
    zip_size_bytes: int


class CustomerDeliveryRepository(Protocol):
    def enqueue_customer_delivery(
        self,
        project_id: str,
        *,
        acting_user_id: str,
        request: CustomerDeliveryCreate,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CustomerDeliverySnapshot: ...

    def list_customer_deliveries(self, project_id: str) -> tuple[CustomerDeliverySnapshot, ...]: ...

    def get_customer_delivery(self, delivery_id: str) -> CustomerDeliverySnapshot: ...

    def is_customer_delivery_task(self, task_id: str, target_id: str) -> bool: ...

    def start_customer_delivery(self, lease: LeaseIdentity) -> CustomerDeliveryWork: ...

    def assert_customer_delivery_current(
        self, lease: LeaseIdentity, work: CustomerDeliveryWork
    ) -> None: ...

    def complete_customer_delivery(
        self,
        lease: LeaseIdentity,
        work: CustomerDeliveryWork,
        persistence: CustomerDeliveryPersistence,
    ) -> bool: ...


class CustomerDeliveryService:
    def __init__(self, repository: CustomerDeliveryRepository, *, max_retries: int) -> None:
        self._repository = repository
        self._max_retries = max_retries

    def create(
        self,
        project_id: str,
        *,
        acting_user_id: str,
        request: CustomerDeliveryCreate,
        idempotency: IdempotencyContext | None = None,
    ) -> CustomerDeliverySnapshot:
        return self._repository.enqueue_customer_delivery(
            project_id,
            acting_user_id=acting_user_id,
            request=request,
            max_retries=self._max_retries,
            idempotency=idempotency,
        )

    def list(self, project_id: str) -> tuple[CustomerDeliverySnapshot, ...]:
        return self._repository.list_customer_deliveries(project_id)

    def get(self, delivery_id: str) -> CustomerDeliverySnapshot:
        return self._repository.get_customer_delivery(delivery_id)


__all__ = [
    "CUSTOMER_DELIVERY_MANIFEST_KIND",
    "CUSTOMER_DELIVERY_TITLE_MAX_CHARS",
    "CUSTOMER_DELIVERY_ZIP_KIND",
    "CustomerDeliveryConflict",
    "CustomerDeliveryCreate",
    "CustomerDeliveryNotFound",
    "CustomerDeliveryPersistence",
    "CustomerDeliveryRepository",
    "CustomerDeliveryService",
    "CustomerDeliverySnapshot",
    "CustomerDeliveryWork",
    "CustomerDeliveryWorkClip",
    "validate_delivery_title",
]
