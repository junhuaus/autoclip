from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CandidateClip(BaseModel):
    """A deterministic rough candidate; transcript fields remain untrusted data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    allowed_start_ms: int = Field(ge=0)
    allowed_end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=24_000)
    context_before: str = Field(default="", max_length=4_000)
    context_after: str = Field(default="", max_length=4_000)
    rule_score: float = Field(ge=0, le=100)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=12)
    segment_ids: tuple[str, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_boundaries(self) -> CandidateClip:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("candidate end must be greater than start")
        if self.allowed_end_ms <= self.allowed_start_ms:
            raise ValueError("candidate adjustment window is invalid")
        if self.source_start_ms < self.allowed_start_ms:
            raise ValueError("candidate starts before its adjustment window")
        if self.source_end_ms > self.allowed_end_ms:
            raise ValueError("candidate ends after its adjustment window")
        return self

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms
