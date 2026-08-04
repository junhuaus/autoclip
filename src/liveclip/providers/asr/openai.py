from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, BinaryIO

from openai import OpenAI
from openai.types.audio.transcription_verbose import TranscriptionVerbose

from liveclip.domain.time import seconds_to_ms
from liveclip.domain.transcript import WordTimingStatus
from liveclip.providers.asr.base import (
    ASRChunkResult,
    AudioChunkLike,
    LocalASRSegment,
    LocalASRWord,
    audio_path_for_chunk,
)
from liveclip.providers.openai_retry import (
    OpenAIRetryCancelled,
    OpenAIRetryFailure,
    OpenAIRetryPolicy,
    call_openai_with_retry,
)
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderConfigurationError,
    ProviderDeterministicError,
    ProviderTransientError,
)

_MAX_OPENAI_AUDIO_BYTES = 25_000_000
_TIMELINE_TOLERANCE_MS = 250
OPENAI_ASR_CONTRACT_VERSION = "openai-asr-whisper-timestamps-v1"


class OpenAIASRProvider:
    """Timestamp-capable OpenAI transcription adapter for generated audio chunks."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = "whisper-1",
        timeout_seconds: float = 120.0,
        retry_policy: OpenAIRetryPolicy | None = None,
        client: Any | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if model_name != "whisper-1":
            raise ProviderConfigurationError(
                "configured OpenAI transcription model lacks the required timestamp contract"
            )
        if client is None and not api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured")
        self._model_name = model_name
        self._retry_policy = retry_policy or OpenAIRetryPolicy()
        self._client: Any = client or OpenAI(
            api_key=api_key,
            max_retries=0,
            timeout=timeout_seconds,
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def contract_version(self) -> str:
        return OPENAI_ASR_CONTRACT_VERSION

    def transcribe(
        self,
        chunk: AudioChunkLike,
        *,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> ASRChunkResult:
        if language != "zh":
            raise ProviderConfigurationError("OpenAI ASR v1 expects the Chinese language hint")
        if cancel_requested():
            raise ProviderCancelled()

        called_at = datetime.now(UTC)
        call_id = uuid.uuid4().hex
        operation_key = _operation_key(
            chunk,
            model=self.model_name,
            language=language,
            vocabulary_prompt=vocabulary_prompt,
            contract_version=self.contract_version,
        )
        duration_ms = chunk.source_end_ms - chunk.source_start_ms
        with _validated_audio_handle(chunk) as handle:
            kwargs: dict[str, Any] = {
                "model": self.model_name,
                "file": (audio_path_for_chunk(chunk).name, handle, "audio/mp4"),
                "language": language,
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment", "word"],
            }
            if vocabulary_prompt:
                kwargs["prompt"] = vocabulary_prompt

            def request() -> object:
                handle.seek(0)
                return self._client.audio.transcriptions.create(**kwargs)

            retry_kwargs: dict[str, Any] = {}
            if self._monotonic is not None:
                retry_kwargs["monotonic"] = self._monotonic
            if self._sleep is not None:
                retry_kwargs["sleep"] = self._sleep
            if self._jitter is not None:
                retry_kwargs["jitter"] = self._jitter
            try:
                execution = call_openai_with_retry(
                    request,
                    policy=self._retry_policy,
                    cancel_requested=cancel_requested,
                    **retry_kwargs,
                )
            except OpenAIRetryCancelled as exc:
                record = (
                    _call_record(
                        call_id=call_id,
                        operation_key=operation_key,
                        chunk=chunk,
                        model=self.model_name,
                        called_at=called_at,
                        request_count=exc.request_count,
                        retry_count=exc.retry_count,
                        latency_ms=exc.latency_ms,
                        status=ProviderCallStatus.CANCELLED,
                        failure_code="OPENAI_CANCELLED",
                    )
                    if exc.request_count > 0
                    else None
                )
                raise ProviderCancelled(record) from exc
            except OpenAIRetryFailure as exc:
                record = _call_record(
                    call_id=call_id,
                    operation_key=operation_key,
                    chunk=chunk,
                    model=self.model_name,
                    called_at=called_at,
                    request_count=exc.request_count,
                    retry_count=exc.retry_count,
                    latency_ms=exc.latency_ms,
                    status=ProviderCallStatus.FAILED,
                    failure_code=exc.failure_code,
                    request_id=exc.request_id,
                )
                error_type = ProviderTransientError if exc.transient else ProviderDeterministicError
                raise error_type(record) from exc

        response = execution.value
        request_id = _request_id(response)
        usage = _usage_payload(response)
        audio_seconds = _audio_seconds(usage, duration_ms=duration_ms)
        record = _call_record(
            call_id=call_id,
            operation_key=operation_key,
            chunk=chunk,
            model=self.model_name,
            called_at=called_at,
            request_count=execution.request_count,
            retry_count=execution.retry_count,
            latency_ms=execution.latency_ms,
            status=ProviderCallStatus.SUCCEEDED,
            request_id=request_id,
            usage_json=usage,
            audio_seconds=audio_seconds,
        )
        try:
            return _map_verbose_response(
                response,
                chunk=chunk,
                language=language,
                request_id=request_id,
                call_record=record,
            )
        except (TypeError, ValueError) as exc:
            invalid = record.model_copy(
                update={
                    "status": ProviderCallStatus.INVALID,
                    "failure_code": "OPENAI_ASR_RESPONSE_INVALID",
                }
            )
            raise ProviderDeterministicError(invalid) from exc


@contextmanager
def _validated_audio_handle(chunk: AudioChunkLike) -> Iterator[BinaryIO]:
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
    if metadata.st_size != expected_size or metadata.st_size > _MAX_OPENAI_AUDIO_BYTES:
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


def _map_verbose_response(
    response: object,
    *,
    chunk: AudioChunkLike,
    language: str,
    request_id: str | None,
    call_record: ProviderCallRecord,
) -> ASRChunkResult:
    if not isinstance(response, TranscriptionVerbose):
        raise TypeError("timestamp transcription did not return verbose JSON")
    if response.segments is None:
        raise ValueError("timestamp transcription omitted segments")
    if response.text.strip() and not response.segments:
        raise ValueError("nonempty transcription omitted segment alignment")

    chunk_duration_ms = chunk.source_end_ms - chunk.source_start_ms
    raw_words: list[LocalASRWord] | None = None
    if response.words:
        parsed_words: list[LocalASRWord] = []
        for word in response.words:
            text = word.word.strip()
            if not text:
                continue
            start_ms, end_ms = _bounded_interval(
                word.start,
                word.end,
                duration_ms=chunk_duration_ms,
            )
            parsed_words.append(LocalASRWord(start_ms=start_ms, end_ms=end_ms, text=text))
        if parsed_words:
            parsed_words.sort(key=lambda item: (item.start_ms, item.end_ms, item.text))
            raw_words = parsed_words

    segments: list[LocalASRSegment] = []
    assigned_word_indexes: set[int] = set()
    for index, segment in enumerate(response.segments, start=1):
        text = segment.text.strip()
        if not text:
            continue
        start_ms, end_ms = _bounded_interval(
            segment.start,
            segment.end,
            duration_ms=chunk_duration_ms,
        )
        segment_words: tuple[LocalASRWord, ...] | None = None
        if raw_words is not None:
            current_word_indexes = tuple(
                word_index
                for word_index, word in enumerate(raw_words)
                if word.start_ms >= start_ms and word.end_ms <= end_ms
            )
            if assigned_word_indexes.intersection(current_word_indexes):
                raise ValueError("provider word timing belongs to overlapping segments")
            assigned_word_indexes.update(current_word_indexes)
            segment_words = tuple(raw_words[index] for index in current_word_indexes)
        segments.append(
            LocalASRSegment(
                segment_id=f"openai_{index:06d}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                words=segment_words,
            )
        )

    if raw_words is not None and assigned_word_indexes != set(range(len(raw_words))):
        raise ValueError("provider word timing is not aligned to a segment")

    return ASRChunkResult(
        chunk_id=chunk.chunk_id,
        chunk_duration_ms=chunk_duration_ms,
        language=language,
        provider="openai",
        model=call_record.model,
        word_timing_status=(
            WordTimingStatus.AVAILABLE if raw_words is not None else WordTimingStatus.UNAVAILABLE
        ),
        segments=tuple(segments),
        request_id=request_id,
        call_record=call_record,
    )


def _bounded_interval(start: float, end: float, *, duration_ms: int) -> tuple[int, int]:
    start_ms = seconds_to_ms(start)
    end_ms = seconds_to_ms(end)
    if start_ms < -_TIMELINE_TOLERANCE_MS or end_ms > duration_ms + _TIMELINE_TOLERANCE_MS:
        raise ValueError("provider timestamp exceeds the audio chunk")
    start_ms = max(0, start_ms)
    end_ms = min(duration_ms, end_ms)
    if end_ms <= start_ms:
        raise ValueError("provider timestamp interval is empty")
    return start_ms, end_ms


def _operation_key(
    chunk: AudioChunkLike,
    *,
    model: str,
    language: str,
    vocabulary_prompt: str | None,
    contract_version: str,
) -> str:
    payload = {
        "cache_key": getattr(chunk, "cache_key", None),
        "chunk_id": chunk.chunk_id,
        "contract_version": contract_version,
        "language": language,
        "model": model,
        "prompt_sha256": hashlib.sha256((vocabulary_prompt or "").encode()).hexdigest(),
        "source_end_ms": chunk.source_end_ms,
        "source_start_ms": chunk.source_start_ms,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _call_record(
    *,
    call_id: str,
    operation_key: str,
    chunk: AudioChunkLike,
    model: str,
    called_at: datetime,
    request_count: int,
    retry_count: int,
    latency_ms: int,
    status: ProviderCallStatus,
    failure_code: str | None = None,
    request_id: str | None = None,
    usage_json: dict[str, Any] | None = None,
    audio_seconds: float = 0.0,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id=call_id,
        operation_key=operation_key,
        subject_id=chunk.chunk_id,
        provider="openai",
        operation="audio.transcriptions",
        model=model,
        request_id=request_id,
        request_count=request_count,
        retry_count=retry_count,
        latency_ms=latency_ms,
        audio_seconds=audio_seconds,
        usage_json=usage_json,
        status=status,
        failure_code=failure_code,
        called_at=called_at,
    )


def _request_id(response: object) -> str | None:
    value = getattr(response, "_request_id", None)
    return str(value)[:160] if value else None


def _usage_payload(response: object) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    model_dump = getattr(usage, "model_dump", None)
    if not callable(model_dump):
        return None
    payload = model_dump(mode="json", exclude_none=True)
    if not isinstance(payload, dict):
        return None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > 16_384:
        return None
    return payload


def _audio_seconds(usage: dict[str, Any] | None, *, duration_ms: int) -> float:
    if usage is not None:
        seconds = usage.get("seconds")
        if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= 0:
            return float(seconds)
    return duration_ms / 1_000
