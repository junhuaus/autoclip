"""Version-one transport-neutral observation contract for Delivery work."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeliveryProgressPhase(StrEnum):
    QUEUED = "queued"
    COPYING_HASHING = "copying_hashing"
    WRITING_METADATA = "writing_metadata"
    WRITING_ZIP = "writing_zip"
    VERIFYING_PACKAGE = "verifying_package"
    COMMITTING_ASSETS = "committing_assets"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryProgressUnit(StrEnum):
    BYTES = "bytes"
    FILES = "files"
    MEMBERS = "members"
    ASSETS = "assets"


WORK_PHASES = (
    DeliveryProgressPhase.COPYING_HASHING,
    DeliveryProgressPhase.WRITING_METADATA,
    DeliveryProgressPhase.WRITING_ZIP,
    DeliveryProgressPhase.VERIFYING_PACKAGE,
    DeliveryProgressPhase.COMMITTING_ASSETS,
)

PHASE_UNITS = {
    DeliveryProgressPhase.COPYING_HASHING: DeliveryProgressUnit.BYTES,
    DeliveryProgressPhase.WRITING_METADATA: DeliveryProgressUnit.FILES,
    DeliveryProgressPhase.WRITING_ZIP: DeliveryProgressUnit.BYTES,
    DeliveryProgressPhase.VERIFYING_PACKAGE: DeliveryProgressUnit.MEMBERS,
    DeliveryProgressPhase.COMMITTING_ASSETS: DeliveryProgressUnit.ASSETS,
}


class DeliveryProgressEvent(BaseModel):
    """Absolute, phase-local count from a completed producer operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    phase: DeliveryProgressPhase
    unit: DeliveryProgressUnit
    completed: int = Field(ge=0)
    total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_work(self) -> DeliveryProgressEvent:
        if self.phase not in WORK_PHASES:
            raise ValueError("progress events require a work phase")
        if self.unit != PHASE_UNITS[self.phase]:
            raise ValueError("progress unit does not match producer phase")
        if self.total is not None and self.completed > self.total:
            raise ValueError("completed work exceeds known total")
        return self


class DeliveryProgressSnapshot(BaseModel):
    """Authorized read projection; queued and terminal states have no work count."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    phase: DeliveryProgressPhase
    unit: DeliveryProgressUnit | None
    completed: int | None = Field(ge=0)
    total: int | None = Field(ge=0)
    attempt_id: str | None = Field(pattern=r"^[0-9a-f]{32}$")
    business_advanced_at: datetime | None
    worker_heartbeat_at: datetime | None
    lease_fresh: bool

    @model_validator(mode="after")
    def validate_projection(self) -> DeliveryProgressSnapshot:
        if self.phase in WORK_PHASES:
            if self.unit is None or self.completed is None or self.attempt_id is None:
                raise ValueError("active progress requires a unit, count and attempt")
            if self.unit != PHASE_UNITS[self.phase]:
                raise ValueError("progress unit does not match producer phase")
        elif self.unit is not None or self.completed is not None or self.total is not None:
            raise ValueError("queued and terminal progress have no work counter")
        if self.total is not None and self.completed is not None and self.completed > self.total:
            raise ValueError("completed work exceeds known total")
        if self.lease_fresh and (self.attempt_id is None or self.worker_heartbeat_at is None):
            raise ValueError("fresh lease requires the current attempt and heartbeat")
        return self


class DeliveryProgressLostLease(RuntimeError):
    """The event no longer belongs to the current live Delivery attempt."""


class DeliveryProgressWriteFailed(RuntimeError):
    """The current attempt could not durably record required work."""


class DeliveryProgressSink(Protocol):
    """A fenced, short-transaction sink; never receives paths or model output."""

    def advance(self, event: DeliveryProgressEvent) -> None: ...
