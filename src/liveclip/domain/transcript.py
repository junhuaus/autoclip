from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WordTimingStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class TranscriptWord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: NonEmptyText = Field(max_length=100)

    @model_validator(mode="after")
    def validate_interval(self) -> TranscriptWord:
        if self.end_ms <= self.start_ms:
            raise ValueError("word end_ms must be greater than start_ms")
        return self


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    segment_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: NonEmptyText = Field(max_length=4_000)
    source_chunk_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    words: tuple[TranscriptWord, ...] | None = None

    @model_validator(mode="after")
    def validate_interval_and_words(self) -> TranscriptSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("segment end_ms must be greater than start_ms")
        if self.words is not None:
            previous_start = -1
            for word in self.words:
                if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                    raise ValueError("word timing must stay inside its segment")
                if word.start_ms < previous_start:
                    raise ValueError("words must be ordered")
                previous_start = word.start_ms
        return self


class TranscriptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    language: str = Field(default="zh", min_length=2, max_length=16)
    source_duration_ms: int = Field(gt=0)
    word_timing_status: WordTimingStatus
    segments: tuple[TranscriptSegment, ...]

    @model_validator(mode="after")
    def validate_segment_timeline(self) -> TranscriptDocument:
        previous_start = -1
        identifiers: set[str] = set()
        for segment in self.segments:
            if segment.segment_id in identifiers:
                raise ValueError("transcript segment IDs must be unique")
            identifiers.add(segment.segment_id)
            if segment.start_ms < previous_start:
                raise ValueError("transcript segments must be ordered")
            if segment.end_ms > self.source_duration_ms:
                raise ValueError("transcript segment exceeds source duration")
            previous_start = segment.start_ms
        if self.word_timing_status == WordTimingStatus.UNAVAILABLE and any(
            segment.words is not None for segment in self.segments
        ):
            raise ValueError("word timing cannot be populated when marked unavailable")
        return self
