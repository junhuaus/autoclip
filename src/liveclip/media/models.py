from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
CacheKey = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]


class SourceMediaMetadata(BaseModel):
    """Immutable metadata for a read-only source-media reference.

    Media time uses integer milliseconds from the start of the original source.
    ``resolved_path`` is intentionally a local-only value and must not be exposed by
    public API DTOs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    resolved_path: Path
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: Sha256
    duration_ms: int = Field(gt=0)
    format_name: str = Field(min_length=1, max_length=128)
    video_stream_index: int = Field(ge=0)
    video_codec: str = Field(min_length=1, max_length=64)
    video_width: int = Field(gt=0)
    video_height: int = Field(gt=0)
    video_frame_rate: float = Field(gt=0)
    video_rotation_degrees: Literal[0, 90, 180, 270]
    audio_stream_index: int = Field(ge=0)
    audio_codec: str = Field(min_length=1, max_length=64)
    audio_sample_rate_hz: int = Field(gt=0)
    audio_channels: int = Field(gt=0)
    mtime_ns: int = Field(ge=0)
    inode: int | None = Field(default=None, ge=0)
    device: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_path_identity(self) -> SourceMediaMetadata:
        if not self.resolved_path.is_absolute():
            raise ValueError("resolved source path must be absolute")
        if self.filename != self.resolved_path.name:
            raise ValueError("source filename must match the resolved path")
        if self.video_stream_index == self.audio_stream_index:
            raise ValueError("selected video and audio streams must be distinct")
        return self

    @property
    def display_width(self) -> int:
        return self.video_height if self.video_rotation_degrees in {90, 270} else self.video_width

    @property
    def display_height(self) -> int:
        return self.video_width if self.video_rotation_degrees in {90, 270} else self.video_height


class AudioChunk(BaseModel):
    """A verified, successfully published ASR audio chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    index: int = Field(ge=0)
    chunk_id: str = Field(min_length=12, max_length=32, pattern=r"^chunk_[0-9]{6,}$")
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    overlap_before_ms: int = Field(ge=0)
    overlap_after_ms: int = Field(ge=0)
    path: Path
    size_bytes: int = Field(gt=0)
    sha256: Sha256
    cache_key: CacheKey
    audio_format: Literal["m4a"] = "m4a"
    audio_codec: Literal["aac"] = "aac"
    state: Literal["succeeded"] = "succeeded"

    @model_validator(mode="after")
    def validate_chunk(self) -> AudioChunk:
        if self.chunk_id != f"chunk_{self.index:06d}":
            raise ValueError("audio chunk ID must be derived from its immutable index")
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("audio chunk end must be after its start")
        if self.duration_ms != self.source_end_ms - self.source_start_ms:
            raise ValueError("audio chunk duration must match its absolute interval")
        if self.overlap_before_ms >= self.duration_ms:
            raise ValueError("leading overlap must be shorter than the audio chunk")
        if self.overlap_after_ms >= self.duration_ms:
            raise ValueError("trailing overlap must be shorter than the audio chunk")
        if not self.path.is_absolute():
            raise ValueError("audio chunk path must be absolute")
        return self


class SilenceInterval(BaseModel):
    """A silence interval in canonical source-absolute milliseconds."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> SilenceInterval:
        if self.end_ms <= self.start_ms:
            raise ValueError("silence interval end must be after its start")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class AudioChunkManifest(BaseModel):
    """Recoverable preprocessing checkpoint containing only verified chunks."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    algorithm_version: Literal["audio-preprocess-v1"] = "audio-preprocess-v1"
    source_sha256: Sha256
    source_duration_ms: int = Field(gt=0)
    source_audio_stream_index: int = Field(ge=0)
    chunk_duration_ms: int = Field(gt=0)
    chunk_overlap_ms: int = Field(ge=0)
    sample_rate_hz: int = Field(gt=0)
    bitrate: str = Field(pattern=r"^[1-9][0-9]*k$", max_length=12)
    channels: Literal[1] = 1
    silence_noise_db: int = Field(ge=-100, le=0)
    silence_min_duration_ms: int = Field(gt=0)
    max_chunk_bytes: int = Field(gt=0)
    expected_chunk_count: int = Field(gt=0)
    chunks: tuple[AudioChunk, ...] = ()
    silences: tuple[SilenceInterval, ...] = ()
    complete: bool = False

    @model_validator(mode="after")
    def validate_manifest(self) -> AudioChunkManifest:
        if self.chunk_overlap_ms >= self.chunk_duration_ms:
            raise ValueError("chunk overlap must be shorter than chunk duration")
        if self.chunk_overlap_ms * 2 > self.chunk_duration_ms:
            raise ValueError("chunk overlap must not exceed half of chunk duration")
        indexes = tuple(chunk.index for chunk in self.chunks)
        if indexes != tuple(sorted(set(indexes))):
            raise ValueError("manifest chunks must have unique ascending indexes")
        if any(index >= self.expected_chunk_count for index in indexes):
            raise ValueError("manifest chunk index exceeds the expected chunk count")
        if any(chunk.source_end_ms > self.source_duration_ms for chunk in self.chunks):
            raise ValueError("manifest chunk exceeds source duration")
        if any(interval.end_ms > self.source_duration_ms for interval in self.silences):
            raise ValueError("silence interval exceeds source duration")
        silence_starts = tuple(interval.start_ms for interval in self.silences)
        if silence_starts != tuple(sorted(silence_starts)):
            raise ValueError("silence intervals must be ordered by start time")
        if any(
            previous.end_ms > current.start_ms
            for previous, current in zip(self.silences, self.silences[1:], strict=False)
        ):
            raise ValueError("silence intervals must not overlap")
        if self.complete and len(self.chunks) != self.expected_chunk_count:
            raise ValueError("a complete manifest must contain every expected chunk")
        return self
