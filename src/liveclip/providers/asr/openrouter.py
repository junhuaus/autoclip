from __future__ import annotations

from collections.abc import Callable
from typing import Any

from liveclip.providers.asr.openai import _TimestampASRProvider
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import ProviderConfigurationError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_ASR_MODEL = "openai/whisper-large-v3"
OPENROUTER_ASR_CONTRACT_VERSION = "openrouter-asr-whisper-large-v3-timestamps-v5"


class OpenRouterASRProvider(_TimestampASRProvider):
    """OpenRouter Whisper Large V3 adapter with segment and word timestamps."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = OPENROUTER_ASR_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_seconds: float = 120.0,
        retry_policy: OpenAIRetryPolicy | None = None,
        client: Any | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if normalized_base_url != OPENROUTER_BASE_URL:
            raise ProviderConfigurationError(
                "OPENROUTER_BASE_URL must be the official HTTPS API endpoint"
            )
        if model_name != OPENROUTER_ASR_MODEL:
            raise ProviderConfigurationError(
                "OPENROUTER_ASR_MODEL must be openai/whisper-large-v3 for the v1 contract"
            )
        client_base_url = getattr(client, "base_url", None) if client is not None else None
        if client_base_url is not None and str(client_base_url).strip().rstrip("/") != (
            OPENROUTER_BASE_URL
        ):
            raise ProviderConfigurationError(
                "injected OpenRouter client must use the official HTTPS API endpoint"
            )
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            client=client,
            monotonic=monotonic,
            sleep=sleep,
            jitter=jitter,
            provider_name="openrouter",
            contract_version=OPENROUTER_ASR_CONTRACT_VERSION,
            required_model=OPENROUTER_ASR_MODEL,
            credential_name="OPENROUTER_API_KEY",
            failure_prefix="OPENROUTER",
            base_url=normalized_base_url,
            default_headers={
                "HTTP-Referer": "http://localhost",
                "X-OpenRouter-Title": "LiveClip",
            },
            request_id_header="X-Generation-Id",
            json_audio_input=True,
            vocabulary_provider_slug="groq",
        )
