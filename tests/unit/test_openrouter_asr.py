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


def test_openrouter_never_treats_x_request_id_as_generation_id(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"x-request-id": "req_not_a_generation"},
        )

    with (
        _provider(handler) as provider,
        pytest.raises(ProviderDeterministicError) as raised,
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
        pytest.raises(ProviderDeterministicError) as raised,
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


def test_openrouter_200_invalid_json_is_durable_invalid_not_retried(tmp_path: Path) -> None:
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
        pytest.raises(ProviderDeterministicError) as raised,
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
        _payload(words=[{"word": None, "start": 0.1, "end": 0.5}]),
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
        pytest.raises(ProviderDeterministicError) as raised,
    ):
        provider.transcribe(_chunk(tmp_path / "shape.m4a"))

    assert raised.value.call_record.failure_code == "OPENROUTER_ASR_RESPONSE_INVALID"
