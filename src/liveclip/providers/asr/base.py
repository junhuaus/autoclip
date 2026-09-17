from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.transcript import WordTimingStatus
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus

MAX_ASR_CHUNK_BYTES = 25_000_000


@runtime_checkable
class AudioChunkLike(Protocol):
    """Minimum chunk contract shared by preprocessing and ASR adapters.

    Concrete chunk models may expose their generated audio as ``path`` or
    ``audio_path``. The Mock adapter intentionally needs neither attribute;
    cloud adapters can resolve either spelling with :func:`audio_path_for_chunk`.
    """

    chunk_id: str
    source_start_ms: int
    source_end_ms: int


class LocalASRWord(BaseModel):
    """A real word timestamp measured from the beginning of one audio chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_interval(self) -> LocalASRWord:
        if self.end_ms <= self.start_ms:
            raise ValueError("local ASR word end_ms must be greater than start_ms")
        return self


class LocalASRSegment(BaseModel):
    """One provider segment whose times are strictly chunk-local milliseconds."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    segment_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4_000)
    words: tuple[LocalASRWord, ...] | None = None

    @model_validator(mode="after")
    def validate_interval_and_words(self) -> LocalASRSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("local ASR segment end_ms must be greater than start_ms")
        if self.words is not None:
            previous_start = -1
            for word in self.words:
                if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                    raise ValueError("local word timing must stay inside its segment")
                if word.start_ms < previous_start:
                    raise ValueError("local word timings must be ordered")
                previous_start = word.start_ms
        return self


class ASRChunkResult(BaseModel):
    """Validated successful provider output for exactly one audio chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    chunk_id: str = Field(min_length=1, max_length=128)
    chunk_duration_ms: int = Field(gt=0)
    language: str = Field(default="zh", min_length=2, max_length=16)
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_./:-]+$")
    word_timing_status: WordTimingStatus
    segments: tuple[LocalASRSegment, ...]
    request_id: str | None = Field(
        default=None,
        max_length=160,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    call_record: ProviderCallRecord | None = None

    @model_validator(mode="after")
    def validate_local_timeline(self) -> ASRChunkResult:
        previous_start = -1
        identifiers: set[str] = set()
        for segment in self.segments:
            if segment.segment_id in identifiers:
                raise ValueError("local ASR segment IDs must be unique within a chunk")
            identifiers.add(segment.segment_id)
            if segment.start_ms < previous_start:
                raise ValueError("local ASR segments must be ordered")
            if segment.end_ms > self.chunk_duration_ms:
                raise ValueError("local ASR segment exceeds chunk duration")
            previous_start = segment.start_ms
        if self.word_timing_status == WordTimingStatus.UNAVAILABLE and any(
            segment.words is not None for segment in self.segments
        ):
            raise ValueError("word timings cannot be supplied when marked unavailable")
        if self.word_timing_status == WordTimingStatus.AVAILABLE and any(
            segment.words is None for segment in self.segments
        ):
            raise ValueError("available word timing requires a word tuple on every segment")
        if self.call_record is not None:
            if self.call_record.subject_id != self.chunk_id:
                raise ValueError("ASR call subject must match its chunk")
            if self.call_record.request_id != self.request_id:
                raise ValueError("ASR request IDs must agree")
            if self.call_record.status != ProviderCallStatus.SUCCEEDED:
                raise ValueError("successful ASR results require a successful call record")
        return self


class ASRProvider(Protocol):
    """Synchronous application port implemented by Mock and cloud ASR adapters."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def contract_version(self) -> str: ...

    def transcribe(
        self,
        chunk: AudioChunkLike,
        *,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> ASRChunkResult: ...


def audio_path_for_chunk(chunk: AudioChunkLike) -> Path:
    """Resolve the two supported generated-audio attribute spellings."""

    for attribute in ("audio_path", "path"):
        value = getattr(chunk, attribute, None)
        if isinstance(value, (str, Path)):
            return Path(value)
    raise TypeError("audio chunk must expose path or audio_path")


@contextmanager
def open_validated_audio_chunk(
    chunk: AudioChunkLike,
    *,
    maximum_bytes: int = MAX_ASR_CHUNK_BYTES,
) -> Iterator[BinaryIO]:
    """Pin and verify one generated chunk before any Provider consumes its bytes."""

    from liveclip.providers.telemetry import ProviderConfigurationError

    if maximum_bytes <= 0:
        raise ValueError("maximum ASR chunk bytes must be positive")
    path = audio_path_for_chunk(chunk)
    expected_size = getattr(chunk, "size_bytes", None)
    expected_sha256 = getattr(chunk, "sha256", None)
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
        raise ProviderConfigurationError("audio chunk size metadata is missing")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ProviderConfigurationError("audio chunk fingerprint metadata is missing")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderConfigurationError("audio chunk is not readable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ProviderConfigurationError("audio chunk must be a regular non-symlink file")
    if metadata.st_size != expected_size or metadata.st_size > maximum_bytes:
        raise ProviderConfigurationError("audio chunk size does not match the safe manifest")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProviderConfigurationError("audio chunk could not be opened safely") from exc
    handle = os.fdopen(descriptor, "rb")
    try:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
        ):
            raise ProviderConfigurationError("audio chunk changed while opening")
        digest = hashlib.sha256()
        while block := handle.read(1024 * 1024):
            digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ProviderConfigurationError("audio chunk fingerprint does not match the manifest")
        handle.seek(0)
        yield handle
    finally:
        handle.close()
