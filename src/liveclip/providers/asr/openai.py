from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import traceback
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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
    open_validated_audio_chunk,
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

_TIMELINE_START_TOLERANCE_MS = 250
# Whisper-compatible backends can report optional word timing slightly beyond
# the exact AAC chunk boundary. Keep word timing strict; segment intervals use
# source intersection because their text can still overlap verified audio.
_TIMELINE_END_TOLERANCE_MS = 1_000
OPENAI_ASR_CONTRACT_VERSION = "openai-asr-whisper-timestamps-v4"
_OPENAI_RAW_RESPONSE_HEADER = "X-Stainless-Raw-Response"


@dataclass(frozen=True, slots=True)
class _TranscriptionEnvelope:
    response: object
    request_id: str | None
    requires_parse: bool = False


class _TimestampASRProvider:
    """Shared, validated timestamp-ASR implementation for OpenAI-compatible APIs."""

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
        provider_name: str,
        contract_version: str,
        required_model: str,
        credential_name: str,
        failure_prefix: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        request_id_header: str | None = None,
        json_audio_input: bool = False,
        vocabulary_provider_slug: str | None = None,
    ) -> None:
        if model_name != required_model:
            raise ProviderConfigurationError(
                "configured transcription model lacks the required timestamp contract"
            )
        if client is None and not (api_key and api_key.strip()):
            raise ProviderConfigurationError(f"{credential_name} is not configured")
        self._model_name = model_name
        self._provider_name = provider_name
        self._contract_version = contract_version
        self._failure_prefix = failure_prefix
        self._request_id_header = request_id_header
        self._request_headers = default_headers
        self._json_audio_input = json_audio_input
        self._vocabulary_provider_slug = vocabulary_provider_slug
        self._retry_policy = retry_policy or OpenAIRetryPolicy()
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "max_retries": 0,
            "timeout": timeout_seconds,
        }
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        if default_headers is not None:
            client_kwargs["default_headers"] = default_headers
        self._client: Any = client or OpenAI(**client_kwargs)
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def contract_version(self) -> str:
        return self._contract_version

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
        with open_validated_audio_chunk(chunk) as handle:
            request_fields: dict[str, Any] = {
                "model": self.model_name,
                "language": language,
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment", "word"],
            }
            if self._json_audio_input:
                request_fields["input_audio"] = {
                    # Each verified chunk is capped at 25 MB. Encoding one bounded
                    # chunk never reads the multi-hour source into memory.
                    "data": base64.b64encode(handle.read()).decode("ascii"),
                    "format": "m4a",
                }
                if vocabulary_prompt and self._vocabulary_provider_slug:
                    request_fields["provider"] = {
                        "options": {
                            self._vocabulary_provider_slug: {
                                "prompt": vocabulary_prompt,
                            }
                        }
                    }
            else:
                request_fields["file"] = (
                    audio_path_for_chunk(chunk).name,
                    handle,
                    "audio/mp4",
                )
                if vocabulary_prompt:
                    request_fields["prompt"] = vocabulary_prompt
                if self._request_headers is not None:
                    request_fields["extra_headers"] = self._request_headers

            def request() -> object:
                handle.seek(0)
                if self._request_id_header is None:
                    response = self._client.audio.transcriptions.create(**request_fields)
                    return _TranscriptionEnvelope(
                        response=response,
                        request_id=_request_id(response),
                    )
                if self._json_audio_input:
                    headers = {
                        _OPENAI_RAW_RESPONSE_HEADER: "raw",
                        **(self._request_headers or {}),
                    }
                    raw_response = self._client.post(
                        "/audio/transcriptions",
                        cast_to=TranscriptionVerbose,
                        body=request_fields,
                        options={"headers": headers},
                    )
                else:
                    raw_response = self._client.audio.transcriptions.with_raw_response.create(
                        **request_fields
                    )
                header_value = raw_response.headers.get(self._request_id_header)
                return _TranscriptionEnvelope(
                    response=raw_response,
                    # OpenRouter's generation ID has distinct provenance from an
                    # ordinary x-request-id and must never fall back to it.
                    request_id=_safe_request_id(header_value),
                    requires_parse=True,
                )

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
                        provider=self.provider_name,
                        failure_code=f"{self._failure_prefix}_CANCELLED",
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
                    provider=self.provider_name,
                    failure_code=_provider_failure_code(
                        exc.failure_code,
                        prefix=self._failure_prefix,
                    ),
                    request_id=exc.request_id,
                )
                error_type = ProviderTransientError if exc.transient else ProviderDeterministicError
                raise error_type(record) from exc

        envelope = execution.value
        if not isinstance(envelope, _TranscriptionEnvelope):
            raise ProviderConfigurationError("transcription adapter returned an invalid envelope")
        response = envelope.response
        request_id = envelope.request_id
        if envelope.requires_parse:
            try:
                parser = getattr(response, "parse", None)
                if not callable(parser):
                    raise TypeError("raw transcription response cannot be parsed")
                response = parser()
            except Exception as exc:
                invalid = _call_record(
                    call_id=call_id,
                    operation_key=operation_key,
                    chunk=chunk,
                    model=self.model_name,
                    called_at=called_at,
                    request_count=execution.request_count,
                    retry_count=execution.retry_count,
                    latency_ms=execution.latency_ms,
                    status=ProviderCallStatus.INVALID,
                    provider=self.provider_name,
                    failure_code=f"{self._failure_prefix}_ASR_RESPONSE_INVALID",
                    request_id=request_id,
                )
                # A syntactically successful provider response can still be
                # truncated or malformed by an upstream serving path. The
                # request itself was valid, so let the durable stage retry use
                # already committed per-chunk caches instead of misreporting a
                # local configuration error.
                raise ProviderTransientError(invalid) from exc
            if self._request_id_header is None:
                request_id = request_id or _request_id(response)
        success_record: ProviderCallRecord | None = None
        try:
            if self._request_id_header is not None and request_id is None:
                raise ValueError("transcription response omitted its required generation ID")
            usage = _usage_payload(response, provider=self.provider_name)
            audio_seconds = _audio_seconds(usage, duration_ms=duration_ms)
            success_record = _call_record(
                call_id=call_id,
                operation_key=operation_key,
                chunk=chunk,
                model=self.model_name,
                called_at=called_at,
                request_count=execution.request_count,
                retry_count=execution.retry_count,
                latency_ms=execution.latency_ms,
                status=ProviderCallStatus.SUCCEEDED,
                provider=self.provider_name,
                request_id=request_id,
                usage_json=usage,
                audio_seconds=audio_seconds,
            )
            return _map_verbose_response(
                response,
                chunk=chunk,
                language=language,
                request_id=request_id,
                call_record=success_record,
                provider=self.provider_name,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            invalid = (
                success_record.model_copy(
                    update={
                        "status": ProviderCallStatus.INVALID,
                        "failure_code": f"{self._failure_prefix}_ASR_RESPONSE_INVALID",
                        "usage_json": {
                            **(success_record.usage_json or {}),
                            "validation_shape": _response_validation_shape(response, exc),
                        },
                    }
                )
                if success_record is not None
                else _call_record(
                    call_id=call_id,
                    operation_key=operation_key,
                    chunk=chunk,
                    model=self.model_name,
                    called_at=called_at,
                    request_count=execution.request_count,
                    retry_count=execution.retry_count,
                    latency_ms=execution.latency_ms,
                    status=ProviderCallStatus.INVALID,
                    provider=self.provider_name,
                    failure_code=f"{self._failure_prefix}_ASR_RESPONSE_INVALID",
                    request_id=request_id,
                )
            )
            raise ProviderTransientError(invalid) from exc


class OpenAIASRProvider(_TimestampASRProvider):
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
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            client=client,
            monotonic=monotonic,
            sleep=sleep,
            jitter=jitter,
            provider_name="openai",
            contract_version=OPENAI_ASR_CONTRACT_VERSION,
            required_model="whisper-1",
            credential_name="OPENAI_API_KEY",
            failure_prefix="OPENAI",
        )


def _map_verbose_response(
    response: object,
    *,
    chunk: AudioChunkLike,
    language: str,
    request_id: str | None,
    call_record: ProviderCallRecord,
    provider: str,
) -> ASRChunkResult:
    if not isinstance(response, TranscriptionVerbose):
        raise TypeError("timestamp transcription did not return verbose JSON")
    if not isinstance(response.text, str) or not isinstance(response.language, str):
        raise TypeError("timestamp transcription root fields are invalid")
    if _finite_seconds(response.duration) < 0:
        raise ValueError("timestamp transcription duration must be nonnegative")
    if response.segments is None:
        raise ValueError("timestamp transcription omitted segments")
    if response.text.strip() and not response.segments:
        raise ValueError("nonempty transcription omitted segment alignment")

    chunk_duration_ms = chunk.source_end_ms - chunk.source_start_ms
    raw_words = _optional_word_timings(
        response.words,
        chunk_duration_ms=chunk_duration_ms,
    )

    segments: list[LocalASRSegment] = []
    for index, segment in enumerate(response.segments, start=1):
        if not isinstance(segment.text, str):
            raise TypeError("provider segment text is invalid")
        text = segment.text.strip()
        if not text:
            continue
        interval = _source_interval_intersection(
            _finite_seconds(segment.start),
            _finite_seconds(segment.end),
            duration_ms=chunk_duration_ms,
        )
        if interval is None:
            continue
        start_ms, end_ms = interval
        segments.append(
            LocalASRSegment(
                segment_id=f"{provider}_{index:06d}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            )
        )

    if response.text.strip() and not segments:
        raise ValueError("nonempty transcription has no source-overlapping segments")

    assigned_words = _assign_optional_words(raw_words, segments)
    if assigned_words is not None:
        segments = [
            segment.model_copy(update={"words": assigned_words[index]})
            for index, segment in enumerate(segments)
        ]

    return ASRChunkResult(
        chunk_id=chunk.chunk_id,
        chunk_duration_ms=chunk_duration_ms,
        language=language,
        provider=provider,
        model=call_record.model,
        word_timing_status=(
            WordTimingStatus.AVAILABLE
            if assigned_words is not None
            else WordTimingStatus.UNAVAILABLE
        ),
        segments=tuple(segments),
        request_id=request_id,
        call_record=call_record,
    )


def _optional_word_timings(
    words: object,
    *,
    chunk_duration_ms: int,
) -> list[LocalASRWord] | None:
    """Validate optional words as a unit; invalid words never erase valid segments."""

    if not words or not isinstance(words, Iterable):
        return None
    parsed: list[LocalASRWord] = []
    try:
        for word in words:
            if not isinstance(word.word, str):
                return None
            text = word.word.strip()
            if not text:
                continue
            # Some OpenRouter backends return a sentence-sized Chinese token in
            # the optional ``words`` array. It is not honest word granularity.
            if len(text) > 100:
                return None
            start_ms, end_ms = _bounded_interval(
                _finite_seconds(word.start),
                _finite_seconds(word.end),
                duration_ms=chunk_duration_ms,
            )
            parsed.append(LocalASRWord(start_ms=start_ms, end_ms=end_ms, text=text))
    except (AttributeError, TypeError, ValueError):
        return None
    if not parsed:
        return None
    parsed.sort(key=lambda item: (item.start_ms, item.end_ms, item.text))
    return parsed


def _assign_optional_words(
    words: list[LocalASRWord] | None,
    segments: list[LocalASRSegment],
) -> tuple[tuple[LocalASRWord, ...], ...] | None:
    """Accept optional word timing only when it is complete and truly word-level."""

    if words is None or not segments:
        return None
    if len(words) == len(segments) and all(
        word.text.strip() == segment.text.strip()
        for word, segment in zip(words, segments, strict=True)
    ):
        # Some OpenRouter backends mirror each segment into ``words``. Those are
        # sentence-level intervals, not word timestamps, so report unavailable.
        # Conservatively apply this even to short segments: a genuine one-word
        # segment loses no transcript/timing truth when the redundant optional
        # word claim is omitted.
        return None

    buckets: list[list[LocalASRWord]] = [[] for _ in segments]
    for word in words:
        matching = [
            index
            for index, segment in enumerate(segments)
            if word.start_ms >= segment.start_ms and word.end_ms <= segment.end_ms
        ]
        if len(matching) != 1:
            return None
        buckets[matching[0]].append(word)
    if any(not bucket for bucket in buckets):
        return None
    if any(
        _alignment_text("".join(word.text for word in bucket)) != _alignment_text(segment.text)
        for bucket, segment in zip(buckets, segments, strict=True)
    ):
        # A partial word list is not a trustworthy word-level representation of
        # the segment. Preserve the strict segment transcript while declining
        # the optional timing claim for the entire chunk.
        return None
    return tuple(tuple(bucket) for bucket in buckets)


def _alignment_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character).startswith(("L", "N"))
    )


def _response_validation_shape(response: object, error: BaseException) -> dict[str, object]:
    """Describe only bounded response structure; never retain transcript text."""

    frames = traceback.extract_tb(error.__traceback__)
    error_site = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "unavailable"
    return {
        "error_class": type(error).__name__,
        "error_site": error_site[:120],
        "response_type": type(response).__name__[:80],
        "root_text_chars": _safe_text_length(getattr(response, "text", None)),
        "segments": _timed_items_shape(getattr(response, "segments", None), text_field="text"),
        "words": _timed_items_shape(getattr(response, "words", None), text_field="word"),
    }


def _timed_items_shape(items: object, *, text_field: str) -> dict[str, int | None]:
    if not isinstance(items, list | tuple):
        return {
            "count": None,
            "inspected": 0,
            "invalid_interval_count": 0,
            "invalid_text_count": 0,
            "maximum_text_chars": None,
        }
    inspected_items = items[:512]
    lengths: list[int] = []
    invalid_intervals = 0
    invalid_texts = 0
    for item in inspected_items:
        text = getattr(item, text_field, None)
        if isinstance(text, str):
            lengths.append(len(text))
        else:
            invalid_texts += 1
        start = getattr(item, "start", None)
        end = getattr(item, "end", None)
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int | float)
            or not isinstance(end, int | float)
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or float(end) <= float(start)
        ):
            invalid_intervals += 1
    return {
        "count": len(items),
        "inspected": len(inspected_items),
        "invalid_interval_count": invalid_intervals,
        "invalid_text_count": invalid_texts,
        "maximum_text_chars": max(lengths) if lengths else None,
    }


def _safe_text_length(value: object) -> int | None:
    return len(value) if isinstance(value, str) else None


def _bounded_interval(
    start: float,
    end: float,
    *,
    duration_ms: int,
) -> tuple[int, int]:
    start_ms = seconds_to_ms(start)
    end_ms = seconds_to_ms(end)
    if (
        start_ms < -_TIMELINE_START_TOLERANCE_MS
        or end_ms > duration_ms + _TIMELINE_END_TOLERANCE_MS
    ):
        raise ValueError("provider timestamp exceeds the audio chunk")
    start_ms = max(0, start_ms)
    end_ms = min(duration_ms, end_ms)
    if end_ms <= start_ms:
        raise ValueError("provider timestamp interval is empty")
    return start_ms, end_ms


def _source_interval_intersection(
    start: float,
    end: float,
    *,
    duration_ms: int,
) -> tuple[int, int] | None:
    start_ms = max(0, seconds_to_ms(start))
    end_ms = min(duration_ms, seconds_to_ms(end))
    return (start_ms, end_ms) if end_ms > start_ms else None


def _finite_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("provider timestamp must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("provider timestamp must be finite")
    return normalized


def _provider_failure_code(code: str, *, prefix: str) -> str:
    if prefix == "OPENAI" or not code.startswith("OPENAI_"):
        return code
    return f"{prefix}_{code.removeprefix('OPENAI_')}"


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
    provider: str,
    failure_code: str | None = None,
    request_id: str | None = None,
    usage_json: dict[str, Any] | None = None,
    audio_seconds: float = 0.0,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id=call_id,
        operation_key=operation_key,
        subject_id=chunk.chunk_id,
        provider=provider,
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
    return _safe_request_id(value)


def _safe_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) else None


def _usage_payload(response: object, *, provider: str) -> dict[str, Any] | None:
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
    if provider == "openrouter":
        for field in ("seconds", "cost"):
            if field not in payload:
                continue
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"OpenRouter usage.{field} must be numeric")
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"OpenRouter usage.{field} must be finite and nonnegative")
    return payload


def _audio_seconds(usage: dict[str, Any] | None, *, duration_ms: int) -> float:
    if usage is not None:
        seconds = usage.get("seconds")
        if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= 0:
            return float(seconds)
    return duration_ms / 1_000
