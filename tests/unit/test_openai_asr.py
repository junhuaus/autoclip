from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import OpenAI

from liveclip.domain.transcript import WordTimingStatus
from liveclip.media.models import AudioChunk
from liveclip.providers.asr.openai import OpenAIASRProvider
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import (
    ProviderCallStatus,
    ProviderConfigurationError,
    ProviderTransientError,
)


@dataclass(frozen=True)
class _HTTPReply:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _CapturedRequest:
    headers: httpx.Headers
    body: bytes


@dataclass
class _Clock:
    now: float = 20.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _ForbiddenTranscriptions:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, **_kwargs: object) -> object:
        self.call_count += 1
        raise AssertionError("invalid local audio must not reach OpenAI")


def _forbidden_client() -> tuple[SimpleNamespace, _ForbiddenTranscriptions]:
    transcriptions = _ForbiddenTranscriptions()
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    return client, transcriptions


def _write_audio(path: Path, content: bytes = b"fake-m4a-audio") -> bytes:
    path.write_bytes(content)
    return content


def _chunk(
    path: Path,
    *,
    content: bytes | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    duration_ms: int = 2_000,
) -> AudioChunk:
    actual = path.read_bytes() if content is None else content
    return AudioChunk(
        index=0,
        chunk_id="chunk_000000",
        source_start_ms=10_000,
        source_end_ms=10_000 + duration_ms,
        duration_ms=duration_ms,
        overlap_before_ms=0,
        overlap_after_ms=0,
        path=path.absolute(),
        size_bytes=len(actual) if size_bytes is None else size_bytes,
        sha256=hashlib.sha256(actual).hexdigest() if sha256 is None else sha256,
        cache_key="c" * 64,
    )


def _verbose_payload(
    *,
    text: str = "你好世界",
    segments: list[dict[str, Any]] | None = None,
    words: list[dict[str, Any]] | None = None,
    include_segments: bool = True,
    include_words: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "duration": 2.0,
        "language": "chinese",
        "text": text,
        "usage": {"type": "duration", "seconds": 2.0},
    }
    if include_segments:
        payload["segments"] = (
            segments
            if segments is not None
            else [
                {
                    "id": 0,
                    "seek": 0,
                    "start": 0.125,
                    "end": 1.875,
                    "text": "你好世界",
                    "tokens": [1, 2],
                    "temperature": 0.0,
                    "avg_logprob": -0.1,
                    "compression_ratio": 1.0,
                    "no_speech_prob": 0.0,
                }
            ]
        )
    if include_words:
        payload["words"] = (
            words
            if words is not None
            else [
                {"word": "你好", "start": 0.125, "end": 0.9},
                {"word": "世界", "start": 0.95, "end": 1.875},
            ]
        )
    return payload


@contextmanager
def _sdk_provider(
    replies: Sequence[_HTTPReply],
    *,
    retry_policy: OpenAIRetryPolicy | None = None,
    clock: _Clock | None = None,
) -> Iterator[tuple[OpenAIASRProvider, list[_CapturedRequest], OpenAI]]:
    remaining = list(replies)
    captured: list[_CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_CapturedRequest(headers=request.headers, body=request.read()))
        if not remaining:
            raise AssertionError("unexpected additional SDK request")
        reply = remaining.pop(0)
        return httpx.Response(
            reply.status_code,
            json=reply.payload,
            headers=reply.headers,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    sdk = OpenAI(
        api_key="unit-test-token",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=http_client,
    )
    retry_kwargs: dict[str, object] = {}
    if clock is not None:
        retry_kwargs = {
            "monotonic": clock.monotonic,
            "sleep": clock.sleep,
            "jitter": lambda: 0.0,
        }
    provider = OpenAIASRProvider(
        client=sdk,
        retry_policy=retry_policy,
        **retry_kwargs,
    )
    try:
        yield provider, captured, sdk
        assert remaining == []
    finally:
        sdk.close()


def _multipart_parts(captured: _CapturedRequest) -> dict[str, list[Any]]:
    content_type = captured.headers["content-type"]
    envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + captured.body
    message = BytesParser(policy=default).parsebytes(envelope)
    assert message.is_multipart()
    parts: dict[str, list[Any]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        assert isinstance(name, str)
        parts.setdefault(name, []).append(part)
    return parts


def _part_bytes(part: Any) -> bytes:
    value = part.get_payload(decode=True)
    assert isinstance(value, bytes)
    return value


def test_timestamp_chinese_request_uses_official_sdk_multipart_and_maps_result(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "chunk-0000.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    reply = _HTTPReply(
        200,
        _verbose_payload(),
        headers={"x-request-id": "req_asr_success"},
    )

    with _sdk_provider([reply]) as (provider, captured, sdk):
        assert sdk.max_retries == 0
        result = provider.transcribe(chunk, vocabulary_prompt="专有词: 量子芯片")

    assert len(captured) == 1
    assert captured[0].headers["authorization"].startswith("Bearer ")
    parts = _multipart_parts(captured[0])
    assert _part_bytes(parts["model"][0]) == b"whisper-1"
    assert _part_bytes(parts["language"][0]) == b"zh"
    assert _part_bytes(parts["prompt"][0]).decode() == "专有词: 量子芯片"
    assert _part_bytes(parts["response_format"][0]) == b"verbose_json"
    assert [_part_bytes(part) for part in parts["timestamp_granularities[]"]] == [
        b"segment",
        b"word",
    ]
    file_part = parts["file"][0]
    assert file_part.get_filename() == audio_path.name
    assert file_part.get_content_type() == "audio/mp4"
    assert _part_bytes(file_part) == content
    assert str(tmp_path).encode() not in captured[0].body

    assert result.request_id == "req_asr_success"
    assert result.word_timing_status == WordTimingStatus.AVAILABLE
    assert result.segments[0].start_ms == 125
    assert result.segments[0].end_ms == 1_875
    assert [(word.start_ms, word.end_ms, word.text) for word in result.segments[0].words or ()] == [
        (125, 900, "你好"),
        (950, 1_875, "世界"),
    ]
    assert result.call_record is not None
    assert result.call_record.request_id == "req_asr_success"
    assert result.call_record.usage_json == {"seconds": 2.0, "type": "duration"}
    assert result.call_record.audio_seconds == 2.0
    assert result.call_record.status == ProviderCallStatus.SUCCEEDED
    assert (result.call_record.request_count, result.call_record.retry_count) == (1, 0)


def test_application_retry_is_the_only_retry_layer_for_official_sdk(tmp_path: Path) -> None:
    audio_path = tmp_path / "chunk-retry.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    clock = _Clock()
    replies = [
        _HTTPReply(
            500,
            {"error": {"message": "temporary", "type": "server_error"}},
            headers={"x-request-id": "req_first_failure"},
        ),
        _HTTPReply(200, _verbose_payload(), headers={"x-request-id": "req_retry_success"}),
    ]

    with _sdk_provider(
        replies,
        retry_policy=OpenAIRetryPolicy(
            max_retries=1,
            base_delay_seconds=0.2,
            max_delay_seconds=1.0,
        ),
        clock=clock,
    ) as (provider, captured, sdk):
        assert sdk.max_retries == 0
        result = provider.transcribe(chunk)

    assert len(captured) == 2
    assert result.call_record is not None
    assert result.request_id == "req_retry_success"
    assert (result.call_record.request_count, result.call_record.retry_count) == (2, 1)
    assert result.call_record.latency_ms == 100


def test_provider_created_sdk_disables_builtin_retries() -> None:
    provider = OpenAIASRProvider(api_key="unit-test-token")
    try:
        assert provider._client.max_retries == 0
    finally:
        provider._client.close()


def test_absent_word_timestamps_are_unavailable_and_not_fabricated(tmp_path: Path) -> None:
    audio_path = tmp_path / "chunk-no-words.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    reply = _HTTPReply(
        200,
        _verbose_payload(include_words=False),
        headers={"x-request-id": "req_no_words"},
    )

    with _sdk_provider([reply]) as (provider, _captured, _sdk):
        result = provider.transcribe(chunk)

    assert result.word_timing_status == WordTimingStatus.UNAVAILABLE
    assert result.segments[0].words is None


def test_empty_word_timestamp_array_is_unavailable_not_available(tmp_path: Path) -> None:
    audio_path = tmp_path / "chunk-empty-words.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    reply = _HTTPReply(
        200,
        _verbose_payload(words=[]),
        headers={"x-request-id": "req_empty_words"},
    )

    with _sdk_provider([reply]) as (provider, _captured, _sdk):
        result = provider.transcribe(chunk)

    assert result.word_timing_status == WordTimingStatus.UNAVAILABLE
    assert result.segments[0].words is None


def test_partial_word_timestamp_text_is_unavailable_not_available(tmp_path: Path) -> None:
    audio_path = tmp_path / "chunk-partial-words.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    reply = _HTTPReply(
        200,
        _verbose_payload(words=[{"word": "你", "start": 0.125, "end": 0.9}]),
        headers={"x-request-id": "req_partial_words"},
    )

    with _sdk_provider([reply]) as (provider, _captured, _sdk):
        result = provider.transcribe(chunk)

    assert result.word_timing_status == WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None


@pytest.mark.parametrize(
    "payload",
    [
        _verbose_payload(include_segments=False),
        _verbose_payload(segments=[]),
        _verbose_payload(
            segments=[
                {
                    "id": 0,
                    "seek": 0,
                    "start": 2.5,
                    "end": 3.001,
                    "text": "超出音频边界",
                    "tokens": [],
                    "temperature": 0.0,
                    "avg_logprob": -0.1,
                    "compression_ratio": 1.0,
                    "no_speech_prob": 0.0,
                }
            ]
        ),
    ],
    ids=["missing-segments", "empty-alignment", "fully-outside"],
)
def test_absent_or_out_of_bounds_segment_alignment_is_rejected(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    audio_path = tmp_path / "chunk-invalid-segments.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    reply = _HTTPReply(200, payload, headers={"x-request-id": "req_invalid_alignment"})

    with (
        _sdk_provider([reply]) as (provider, _captured, _sdk),
        pytest.raises(ProviderTransientError) as caught,
    ):
        provider.transcribe(chunk)

    record = caught.value.call_record
    assert record.status == ProviderCallStatus.INVALID
    assert record.failure_code == "OPENAI_ASR_RESPONSE_INVALID"
    assert record.request_id == "req_invalid_alignment"


def test_words_not_aligned_to_any_segment_are_marked_unavailable(tmp_path: Path) -> None:
    audio_path = tmp_path / "chunk-invalid-words.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content)
    segments = [
        {
            "id": 0,
            "seek": 0,
            "start": 0.1,
            "end": 1.0,
            "text": "你好",
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.0,
            "no_speech_prob": 0.0,
        }
    ]
    words = [{"word": "未对齐", "start": 1.2, "end": 1.5}]
    reply = _HTTPReply(
        200,
        _verbose_payload(segments=segments, words=words),
        headers={"x-request-id": "req_invalid_words"},
    )

    with _sdk_provider([reply]) as (provider, _captured, _sdk):
        result = provider.transcribe(chunk)

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好"
    assert result.segments[0].words is None


def test_symlink_audio_is_rejected_before_any_cloud_request(tmp_path: Path) -> None:
    target = tmp_path / "target.m4a"
    content = _write_audio(target)
    symlink = tmp_path / "linked.m4a"
    symlink.symlink_to(target)
    chunk = _chunk(symlink, content=content)
    client, transcriptions = _forbidden_client()
    provider = OpenAIASRProvider(client=client)

    with pytest.raises(ProviderConfigurationError, match="non-symlink"):
        provider.transcribe(chunk)

    assert transcriptions.call_count == 0


def test_manifest_size_mismatch_is_rejected_before_any_cloud_request(tmp_path: Path) -> None:
    audio_path = tmp_path / "size-mismatch.m4a"
    content = _write_audio(audio_path)
    chunk = _chunk(audio_path, content=content, size_bytes=len(content) + 1)
    client, transcriptions = _forbidden_client()
    provider = OpenAIASRProvider(client=client)

    with pytest.raises(ProviderConfigurationError, match="size does not match"):
        provider.transcribe(chunk)

    assert transcriptions.call_count == 0


def test_chunk_larger_than_provider_limit_is_rejected_before_hashing(tmp_path: Path) -> None:
    audio_path = tmp_path / "oversized.m4a"
    with audio_path.open("wb") as handle:
        handle.truncate(25_000_001)
    chunk = _chunk(
        audio_path,
        content=b"",
        size_bytes=25_000_001,
        sha256="0" * 64,
        duration_ms=1_000,
    )
    client, transcriptions = _forbidden_client()
    provider = OpenAIASRProvider(client=client)

    with pytest.raises(ProviderConfigurationError, match="safe manifest"):
        provider.transcribe(chunk)

    assert transcriptions.call_count == 0


def test_same_size_content_tamper_is_rejected_by_manifest_hash(tmp_path: Path) -> None:
    audio_path = tmp_path / "tampered.m4a"
    original = _write_audio(audio_path, b"original-audio")
    chunk = _chunk(audio_path, content=original)
    audio_path.write_bytes(b"modified-audio")
    assert len(original) == audio_path.stat().st_size
    client, transcriptions = _forbidden_client()
    provider = OpenAIASRProvider(client=client)

    with pytest.raises(ProviderConfigurationError, match="fingerprint"):
        provider.transcribe(chunk)

    assert transcriptions.call_count == 0
