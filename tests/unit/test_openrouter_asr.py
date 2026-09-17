from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import OpenAI

from liveclip.domain.transcript import WordTimingStatus
from liveclip.media.models import AudioChunk
from liveclip.providers.asr.openrouter import (
    OPENROUTER_ASR_CONTRACT_VERSION,
    OPENROUTER_ASR_MODEL,
    OpenRouterASRProvider,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import (
    ProviderCallStatus,
    ProviderConfigurationError,
    ProviderDeterministicError,
    ProviderTransientError,
)


def _chunk(path: Path, *, duration_ms: int = 2_000) -> AudioChunk:
    content = b"openrouter-audio"
    path.write_bytes(content)
    return AudioChunk(
        index=0,
        chunk_id="chunk_000000",
        source_start_ms=10_000,
        source_end_ms=10_000 + duration_ms,
        duration_ms=duration_ms,
        overlap_before_ms=0,
        overlap_after_ms=0,
        path=path.absolute(),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        cache_key="c" * 64,
    )


def _payload(**updates: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "duration": 2.0,
        "language": "chinese",
        "text": "你好世界",
        "segments": [{"id": 0, "start": 0.1, "end": 1.9, "text": "你好世界"}],
        "words": [
            {"word": "你好", "start": 0.1, "end": 0.9},
            {"word": "世界", "start": 1.0, "end": 1.9},
        ],
        "usage": {
            "type": "duration",
            "seconds": 2.0,
            "cost": 0.00005,
            "provider": "openrouter",
        },
    }
    payload.update(updates)
    return payload


@contextmanager
def _provider(
    handler: Any,
    *,
    retry_policy: OpenAIRetryPolicy | None = None,
) -> Iterator[OpenRouterASRProvider]:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    sdk = OpenAI(
        api_key="unit-test-openrouter-token",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=http_client,
    )
    provider = OpenRouterASRProvider(client=sdk, retry_policy=retry_policy)
    try:
        yield provider
    finally:
        sdk.close()


def test_openrouter_timestamp_request_maps_generation_id_and_cost(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_payload(),
            headers={"X-Generation-Id": "gen_whisper_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "chunk.m4a"), vocabulary_prompt="专有词")

    assert provider.provider_name == "openrouter"
    assert provider.model_name == OPENROUTER_ASR_MODEL
    assert provider.contract_version == OPENROUTER_ASR_CONTRACT_VERSION
    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert request.headers["http-referer"] == "http://localhost"
    assert request.headers["x-openrouter-title"] == "LiveClip"
    assert request.headers["authorization"].startswith("Bearer ")
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.read())
    assert body["model"] == "openai/whisper-large-v3"
    assert body["response_format"] == "verbose_json"
    assert body["timestamp_granularities"] == ["segment", "word"]
    assert base64.b64decode(body["input_audio"]["data"]) == b"openrouter-audio"
    assert body["input_audio"]["format"] == "m4a"
    assert body["provider"] == {
        "options": {"groq": {"prompt": "专有词"}},
    }
    assert result.provider == "openrouter"
    assert result.model == OPENROUTER_ASR_MODEL
    assert result.request_id == "gen_whisper_001"
    assert result.segments[0].segment_id == "openrouter_000001"
    assert result.call_record is not None
    assert result.call_record.provider == "openrouter"
    assert result.call_record.usage_json == {
        "cost": 0.00005,
        "provider": "openrouter",
        "seconds": 2.0,
        "type": "duration",
    }


def test_openrouter_sentence_sized_word_downgrades_optional_word_timing(
    tmp_path: Path,
) -> None:
    sentence_sized_word = "这是上游按整句返回而不是按词返回的中文时间戳" * 5

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                words=[
                    {
                        "word": sentence_sized_word,
                        "start": 0.1,
                        "end": 1.9,
                    }
                ]
            ),
            headers={"X-Generation-Id": "gen_sentence_word_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "sentence-word.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None
    assert result.request_id == "gen_sentence_word_001"


def test_openrouter_segment_mirrors_in_words_are_not_claimed_as_word_timing(
    tmp_path: Path,
) -> None:
    first = "这个上游字段其实是一整句而不是一个词"
    second = "第二句也被错误地放进了可选词级数组"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                duration=2.0,
                segments=[
                    {"id": 0, "start": 0.0, "end": 1.0, "text": first},
                    {"id": 1, "start": 1.0, "end": 2.0, "text": second},
                ],
                words=[
                    {"word": first, "start": 0.0, "end": 1.0},
                    {"word": second, "start": 1.0, "end": 2.0},
                ],
            ),
            headers={"X-Generation-Id": "gen_segment_words_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "segment-words.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert [segment.text for segment in result.segments] == [first, second]
    assert all(segment.words is None for segment in result.segments)


def test_openrouter_short_segment_mirrors_are_not_claimed_as_word_timing(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                duration=2.0,
                segments=[
                    {"id": 0, "start": 0.0, "end": 1.0, "text": "你好"},
                    {"id": 1, "start": 1.0, "end": 2.0, "text": "世界"},
                ],
                words=[
                    {"word": "你好", "start": 0.0, "end": 1.0},
                    {"word": "世界", "start": 1.0, "end": 2.0},
                ],
            ),
            headers={"X-Generation-Id": "gen_short_segment_words_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "short-segment-words.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert [segment.text for segment in result.segments] == ["你好", "世界"]
    assert all(segment.words is None for segment in result.segments)


def test_openrouter_interval_offset_segment_mirror_is_not_word_timing(
    tmp_path: Path,
) -> None:
    sentence = "这仍然是完整句子"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                duration=2.0,
                segments=[{"id": 0, "start": 0.0, "end": 2.0, "text": sentence}],
                words=[{"word": sentence, "start": 0.1, "end": 1.9}],
            ),
            headers={"X-Generation-Id": "gen_offset_segment_word_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "offset-segment-word.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == sentence
    assert result.segments[0].words is None


def test_openrouter_unaligned_optional_words_do_not_erase_valid_segments(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                words=[{"word": "你好", "start": 0.0, "end": 2.1}],
            ),
            headers={"X-Generation-Id": "gen_unaligned_word_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "unaligned-word.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None


def test_openrouter_partial_optional_words_do_not_claim_complete_word_timing(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(words=[{"word": "你", "start": 0.1, "end": 0.5}]),
            headers={"X-Generation-Id": "gen_partial_word_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "partial-word.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None


@pytest.mark.parametrize(
    "word",
    (
        {"word": "你好", "start": 0.5, "end": 0.5},
        {"word": None, "start": 0.1, "end": 0.5},
        {"word": "你好", "start": 0.1, "end": 120.0},
    ),
)
def test_openrouter_invalid_optional_word_keeps_valid_segments(
    tmp_path: Path,
    word: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(words=[word]),
            headers={"X-Generation-Id": "gen_invalid_word_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "invalid-word.m4a"))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None
    assert result.request_id == "gen_invalid_word_001"


@pytest.mark.parametrize(
    ("start", "end", "expected_start_ms", "expected_end_ms"),
    ((0.1, 120.0, 100, 2_000), (-120.0, 0.5, 0, 500)),
)
def test_openrouter_intersects_segments_with_verified_audio(
    tmp_path: Path,
    start: float,
    end: float,
    expected_start_ms: int,
    expected_end_ms: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                segments=[{"id": 0, "start": start, "end": end, "text": "你好世界"}],
            ),
            headers={"X-Generation-Id": "gen_tail_drift_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / f"timeline-{start}-{end}.m4a"))

    assert result.segments[0].start_ms == expected_start_ms
    assert result.segments[0].end_ms == expected_end_ms


def test_openrouter_discards_segments_entirely_outside_verified_audio(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                segments=[
                    {"id": 0, "start": 0.1, "end": 1.9, "text": "你好世界"},
                    {"id": 1, "start": 90.0, "end": 120.0, "text": "音频外文本"},
                ],
            ),
            headers={"X-Generation-Id": "gen_outside_segment_001"},
        )

    with _provider(handler) as provider:
        result = provider.transcribe(_chunk(tmp_path / "outside-segment.m4a"))

    assert [segment.text for segment in result.segments] == ["你好世界"]


def test_openrouter_never_treats_x_request_id_as_generation_id(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"x-request-id": "req_not_a_generation"},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderTransientError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "no-generation.m4a"))

    assert raised.value.call_record.status is ProviderCallStatus.INVALID
    assert raised.value.call_record.request_id is None
    assert raised.value.call_record.failure_code == "OPENROUTER_ASR_RESPONSE_INVALID"


def test_openrouter_rejects_overlong_generation_id_instead_of_truncating(tmp_path: Path) -> None:
    overlong = "g" * 161

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"X-Generation-Id": overlong},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderTransientError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "overlong-generation.m4a"))

    assert raised.value.call_record.status is ProviderCallStatus.INVALID
    assert raised.value.call_record.request_id is None


@pytest.mark.parametrize(
    "base_url",
    (
        "http://openrouter.ai/api/v1",
        "https://user:secret@openrouter.ai/api/v1",
        "https://openrouter.ai.evil.invalid/api/v1",
        "https://openrouter.ai:444/api/v1",
        "https://openrouter.ai/api/v1?redirect=evil",
        "https://openrouter.ai/api/v1/extra",
    ),
)
def test_openrouter_rejects_noncanonical_base_urls(base_url: str) -> None:
    with pytest.raises(ProviderConfigurationError, match="official HTTPS"):
        OpenRouterASRProvider(api_key="unit-test-token", base_url=base_url)


def test_openrouter_rejects_uncontracted_model() -> None:
    with pytest.raises(ProviderConfigurationError, match="whisper-large-v3"):
        OpenRouterASRProvider(
            api_key="unit-test-token",
            model_name="openai/whisper-large-v3-turbo",
        )


def test_openrouter_retries_529_once_and_never_falls_back_to_mock(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                529,
                json={"error": {"message": "overloaded"}},
                headers={"X-Generation-Id": "gen_failed_001"},
            )
        return httpx.Response(
            200,
            json=_payload(),
            headers={"X-Generation-Id": "gen_retry_002"},
        )

    with _provider(
        handler,
        retry_policy=OpenAIRetryPolicy(
            max_retries=1,
            base_delay_seconds=0.001,
            max_delay_seconds=0.001,
        ),
    ) as provider:
        result = provider.transcribe(_chunk(tmp_path / "retry.m4a"))

    assert calls == 2
    assert result.provider == "openrouter"
    assert result.request_id == "gen_retry_002"
    assert result.call_record is not None
    assert result.call_record.request_count == 2
    assert result.call_record.retry_count == 1


def test_openrouter_auth_failure_keeps_safe_generation_id_without_retry(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"error": {"message": "secret body must not persist"}},
            headers={"X-Generation-Id": "gen_auth_001"},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderDeterministicError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "auth.m4a"))

    assert calls == 1
    assert raised.value.call_record.provider == "openrouter"
    assert raised.value.call_record.failure_code == "OPENROUTER_AUTH"
    assert raised.value.call_record.request_id == "gen_auth_001"
    assert "secret body" not in str(raised.value)


def test_openrouter_200_invalid_json_is_durable_and_stage_retryable(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b"not-json",
            headers={
                "content-type": "application/json",
                "X-Generation-Id": "gen_invalid_001",
            },
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderTransientError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "invalid-json.m4a"))

    assert calls == 1
    assert raised.value.call_record.status == ProviderCallStatus.INVALID
    assert raised.value.call_record.failure_code == "OPENROUTER_ASR_RESPONSE_INVALID"
    assert raised.value.call_record.request_id == "gen_invalid_001"


@pytest.mark.parametrize(
    "payload",
    (
        _payload(duration=None),
        _payload(duration=-1.0),
        _payload(segments=[{"id": 0, "start": None, "end": 1.0, "text": "坏时间"}]),
        _payload(
            usage={
                "type": "duration",
                "seconds": -5.0,
                "cost": 0.1,
            }
        ),
        _payload(
            usage={
                "type": "duration",
                "seconds": 2.0,
                "cost": "not-a-number",
            }
        ),
    ),
)
def test_openrouter_rejects_sdk_permissive_malformed_verbose_json(
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
            headers={"X-Generation-Id": "gen_shape_001"},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderTransientError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "shape.m4a"))

    assert raised.value.call_record.failure_code == "OPENROUTER_ASR_RESPONSE_INVALID"


def test_invalid_segment_records_only_bounded_shape_metadata(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(segments=[{"id": 0, "start": None, "end": 1.0, "text": "坏时间"}]),
            headers={"X-Generation-Id": "gen_shape_safe_001"},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderTransientError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "shape-safe.m4a"))

    validation_shape = (raised.value.call_record.usage_json or {})["validation_shape"]
    assert isinstance(validation_shape, dict)
    assert validation_shape["response_type"] == "TranscriptionVerbose"
    assert "你好世界" not in repr(validation_shape)
    assert "坏时间" not in repr(validation_shape)
