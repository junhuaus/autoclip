from __future__ import annotations

from pathlib import Path

from liveclip.agent_tools.subtitle_calibration import ASRSubtitleCalibrationBackend
from liveclip.config.settings import Settings
from liveclip.media.models import AudioChunkManifest
from liveclip.media.secure_files import ensure_directory_no_follow, read_regular_text_no_follow
from liveclip.providers.asr.base import ASRProvider
from liveclip.providers.asr.mlx import MLXASRProvider
from liveclip.providers.asr.mock import MockASRProvider
from liveclip.providers.asr.openai import OpenAIASRProvider
from liveclip.providers.asr.openrouter import OpenRouterASRProvider
from liveclip.providers.openai_retry import OpenAIRetryPolicy


def configured_subtitle_calibration_backend(
    settings: Settings,
    *,
    audio_manifest_path: Path,
) -> ASRSubtitleCalibrationBackend:
    """Bind the Agent's audio tool to verified generated chunks and configured ASR."""

    payload = read_regular_text_no_follow(audio_manifest_path, max_bytes=8 * 1024 * 1024)
    manifest = AudioChunkManifest.model_validate_json(payload)
    if not manifest.complete:
        raise ValueError("subtitle calibration requires a complete audio manifest")
    audio_root = ensure_directory_no_follow(audio_manifest_path.parent.resolve(strict=True))
    for chunk in manifest.chunks:
        try:
            resolved_chunk = chunk.path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("subtitle calibration audio chunk is missing") from exc
        if resolved_chunk.parent != audio_root or chunk.path != resolved_chunk:
            raise ValueError("subtitle calibration audio chunk escapes its manifest directory")
    provider = _configured_asr_provider(settings)
    return ASRSubtitleCalibrationBackend(
        provider=provider,
        chunks=manifest.chunks,
        source_duration_ms=manifest.source_duration_ms,
        language="zh",
        vocabulary_prompt=settings.asr_vocabulary_prompt,
        max_interval_ms=600_000,
    )


def _configured_asr_provider(settings: Settings) -> ASRProvider:
    retry_policy = OpenAIRetryPolicy(
        max_retries=settings.openai_max_request_retries,
        base_delay_seconds=settings.openai_retry_base_seconds,
        max_delay_seconds=settings.openai_retry_max_seconds,
    )
    if settings.ai_provider in {"mock", "mock-codex"}:
        return MockASRProvider(model_name=settings.transcription_model)
    if settings.ai_provider == "openrouter-codex":
        key = settings.openrouter_api_key
        return OpenRouterASRProvider(
            api_key=key.get_secret_value() if key is not None else None,
            model_name=settings.openrouter_asr_model,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.openai_request_timeout_seconds,
            retry_policy=retry_policy,
        )
    if settings.ai_provider == "mlx-codex":
        return MLXASRProvider(
            model_path=settings.resolved_mlx_asr_model_path(),
            model_name=settings.transcription_model,
        )
    key = settings.openai_api_key
    return OpenAIASRProvider(
        api_key=key.get_secret_value() if key is not None else None,
        model_name=settings.transcription_model,
        timeout_seconds=settings.openai_request_timeout_seconds,
        retry_policy=retry_policy,
    )


__all__ = ["configured_subtitle_calibration_backend"]
