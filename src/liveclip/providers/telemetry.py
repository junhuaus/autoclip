from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    CANCELLED = "cancelled"


class ProviderCallRecord(BaseModel):
    """Secret-free durable evidence for one logical provider call and its retries."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    call_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    operation_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    subject_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.:-]+$")
    operation: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    response_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    request_count: int = Field(ge=1)
    retry_count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    audio_seconds: float = Field(default=0.0, ge=0)
    usage_json: dict[str, Any] | None = None
    estimated_cost: str | None = Field(default=None, pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
    status: ProviderCallStatus
    failure_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Z0-9_]+$",
    )
    prompt_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    prompt_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    called_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> ProviderCallRecord:
        if self.retry_count >= self.request_count:
            raise ValueError("retry_count must be lower than request_count")
        if self.called_at.tzinfo is None or self.called_at.utcoffset() is None:
            raise ValueError("provider called_at must be timezone-aware")
        if (self.prompt_version is None) != (self.prompt_sha256 is None):
            raise ValueError("prompt version and hash must be stored together")
        if self.status == ProviderCallStatus.SUCCEEDED and self.failure_code is not None:
            raise ValueError("successful provider calls cannot carry a failure code")
        return self

    def durable_metadata(self) -> dict[str, Any]:
        """Return bounded non-secret metadata for ``ApiUsageRow.usage_json``."""

        return {
            "schema_version": self.schema_version,
            "call_id": self.call_id,
            "operation_key": self.operation_key,
            "subject_id": self.subject_id,
            "response_model": self.response_model,
            "failure_code": self.failure_code,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "provider_usage": self.usage_json,
        }


class ProviderRequestError(RuntimeError):
    """Safe base exception whose message never contains provider response content."""

    def __init__(self, call_record: ProviderCallRecord) -> None:
        super().__init__("cloud provider request failed")
        self.call_record = call_record


class ProviderTransientError(ProviderRequestError):
    pass


class ProviderDeterministicError(ProviderRequestError):
    pass


class ProviderCancelled(RuntimeError):
    def __init__(
        self,
        call_record: ProviderCallRecord | None = None,
        *,
        call_records: Sequence[ProviderCallRecord] = (),
    ) -> None:
        super().__init__("cloud provider request was cancelled")
        combined = tuple(call_records) + ((call_record,) if call_record is not None else ())
        by_id: dict[str, ProviderCallRecord] = {}
        for record in combined:
            existing = by_id.get(record.call_id)
            if existing is not None and existing != record:
                raise ValueError("provider cancellation contains conflicting call evidence")
            by_id[record.call_id] = record
        self.call_records = tuple(by_id.values())
        self.call_record = self.call_records[-1] if self.call_records else None


class ProviderConfigurationError(RuntimeError):
    """A local provider setting or generated input cannot produce a valid request."""
