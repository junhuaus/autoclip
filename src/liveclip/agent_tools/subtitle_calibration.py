from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.media.models import AudioChunk
from liveclip.pipeline.transcript import merge_chunk_results
from liveclip.providers.asr.base import ASRProvider
from liveclip.providers.telemetry import (
    ProviderCancelled,
    ProviderConfigurationError,
    ProviderRequestError,
)


class SubtitleCalibrationError(RuntimeError):
    """Safe failure from bounded second-pass subtitle transcription."""


class CalibrationChunkEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chunk_id: str = Field(min_length=1, max_length=128)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_interval(self) -> CalibrationChunkEvidence:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("calibration chunk interval is reversed")
        return self


class CalibrationTranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    segment_id: str = Field(min_length=1, max_length=64)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4_000)
    source_chunk_ids: tuple[str, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_interval(self) -> CalibrationTranscriptSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("calibration transcript interval is reversed")
        return self


class SubtitleCalibrationEvidence(BaseModel):
    """Bounded ASR observation. It is evidence, not an editorial correction."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    evidence_kind: Literal["verified_audio_asr", "mock_fixture"]
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=100)
    contract_version: str = Field(min_length=1, max_length=128)
    requested_start_ms: int = Field(ge=0)
    requested_end_ms: int = Field(gt=0)
    language: str = Field(min_length=2, max_length=16)
    chunks: tuple[CalibrationChunkEvidence, ...] = Field(min_length=1, max_length=32)
    segments: tuple[CalibrationTranscriptSegment, ...] = Field(max_length=2_000)
    provider_calls: tuple[dict[str, object], ...] = Field(default_factory=tuple, max_length=32)
    cache_hit: bool = False

    @model_validator(mode="after")
    def validate_interval(self) -> SubtitleCalibrationEvidence:
        if self.requested_end_ms <= self.requested_start_ms:
            raise ValueError("subtitle calibration interval is reversed")
        return self


class SubtitleCalibrationBackend(Protocol):
    def inspect_interval(
        self,
        *,
        start_ms: int,
        end_ms: int,
        cancel_requested: Callable[[], bool],
    ) -> SubtitleCalibrationEvidence: ...


class ASRSubtitleCalibrationBackend:
    """Run a second ASR pass over verified preprocessed chunks for one interval."""

    def __init__(
        self,
        *,
        provider: ASRProvider,
        chunks: Sequence[AudioChunk],
        source_duration_ms: int,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        max_interval_ms: int = 600_000,
    ) -> None:
        if source_duration_ms <= 0:
            raise ValueError("calibration source duration must be positive")
        if max_interval_ms <= 0:
            raise ValueError("calibration interval limit must be positive")
        ordered = tuple(
            sorted(
                chunks,
                key=lambda item: (item.source_start_ms, item.source_end_ms, item.chunk_id),
            )
        )
        if not ordered:
            raise ValueError("subtitle calibration requires audio chunks")
        if len({item.chunk_id for item in ordered}) != len(ordered):
            raise ValueError("subtitle calibration chunk IDs must be unique")
        if any(item.source_end_ms > source_duration_ms for item in ordered):
            raise ValueError("subtitle calibration chunk exceeds source duration")
        self._provider = provider
        self._chunks = ordered
        self._source_duration_ms = source_duration_ms
        self._language = language
        self._vocabulary_prompt = vocabulary_prompt
        self._max_interval_ms = max_interval_ms
        self._cache: dict[tuple[int, int], SubtitleCalibrationEvidence] = {}

    def inspect_interval(
        self,
        *,
        start_ms: int,
        end_ms: int,
        cancel_requested: Callable[[], bool],
    ) -> SubtitleCalibrationEvidence:
        if start_ms < 0 or end_ms <= start_ms or end_ms > self._source_duration_ms:
            raise SubtitleCalibrationError("subtitle calibration interval is invalid")
        if end_ms - start_ms > self._max_interval_ms:
            raise SubtitleCalibrationError("subtitle calibration interval exceeds its limit")
        cache_key = (start_ms, end_ms)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        selected = tuple(
            chunk
            for chunk in self._chunks
            if chunk.source_end_ms > start_ms and chunk.source_start_ms < end_ms
        )
        self._require_complete_coverage(selected, start_ms=start_ms, end_ms=end_ms)
        try:
            results = tuple(
                self._provider.transcribe(
                    chunk,
                    language=self._language,
                    vocabulary_prompt=self._vocabulary_prompt,
                    cancel_requested=cancel_requested,
                )
                for chunk in selected
            )
            document = merge_chunk_results(
                selected,
                results,
                source_duration_ms=self._source_duration_ms,
            )
        except ProviderCancelled:
            raise
        except (ProviderConfigurationError, ProviderRequestError, ValueError) as exc:
            raise SubtitleCalibrationError("subtitle calibration ASR failed safely") from exc
        calls = tuple(
            result.call_record.model_dump(mode="json")
            for result in results
            if result.call_record is not None
        )
        evidence = SubtitleCalibrationEvidence(
            evidence_kind=(
                "mock_fixture" if self._provider.provider_name == "mock" else "verified_audio_asr"
            ),
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            contract_version=self._provider.contract_version,
            requested_start_ms=start_ms,
            requested_end_ms=end_ms,
            language=document.language,
            chunks=tuple(
                CalibrationChunkEvidence(
                    chunk_id=chunk.chunk_id,
                    source_start_ms=chunk.source_start_ms,
                    source_end_ms=chunk.source_end_ms,
                    size_bytes=chunk.size_bytes,
                    sha256=chunk.sha256,
                )
                for chunk in selected
            ),
            segments=tuple(
                CalibrationTranscriptSegment(
                    segment_id=segment.segment_id,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    source_chunk_ids=segment.source_chunk_ids,
                )
                for segment in document.segments
                if segment.end_ms > start_ms and segment.start_ms < end_ms
            ),
            provider_calls=calls,
        )
        self._cache[cache_key] = evidence
        return evidence

    @staticmethod
    def _require_complete_coverage(
        chunks: Sequence[AudioChunk],
        *,
        start_ms: int,
        end_ms: int,
    ) -> None:
        cursor = start_ms
        for chunk in chunks:
            if chunk.source_end_ms <= cursor:
                continue
            if chunk.source_start_ms > cursor:
                raise SubtitleCalibrationError("audio chunks do not cover the requested interval")
            cursor = max(cursor, chunk.source_end_ms)
            if cursor >= end_ms:
                return
        raise SubtitleCalibrationError("audio chunks do not cover the requested interval")


__all__ = [
    "ASRSubtitleCalibrationBackend",
    "CalibrationChunkEvidence",
    "CalibrationTranscriptSegment",
    "SubtitleCalibrationBackend",
    "SubtitleCalibrationError",
    "SubtitleCalibrationEvidence",
]
