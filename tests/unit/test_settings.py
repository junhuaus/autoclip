from pathlib import Path

import pytest
from pydantic import ValidationError

from liveclip.config.settings import Settings


def test_settings_parse_path_separated_allowed_roots() -> None:
    settings = Settings(
        allowed_media_roots_raw="/tmp/media-a:/tmp/media-b",
        _env_file=None,
    )

    assert settings.allowed_media_roots == (Path("/tmp/media-a"), Path("/tmp/media-b"))


def test_public_summary_never_contains_secret_values() -> None:
    settings = Settings(
        api_token="local-token-value",
        openai_api_key="cloud-key-value",
        _env_file=None,
    )

    serialized = repr(settings.public_summary())
    assert "local-token-value" not in serialized
    assert "cloud-key-value" not in serialized
    assert settings.public_summary()["api_token_configured"] is True
    assert settings.public_summary()["openai_configured"] is True


def test_settings_reject_invalid_timing_relationships() -> None:
    with pytest.raises(ValidationError):
        Settings(asr_chunk_seconds=10, asr_chunk_overlap_seconds=10, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(asr_chunk_seconds=11, asr_chunk_overlap_seconds=6, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(worker_lease_seconds=60, worker_heartbeat_seconds=30, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(
            llm_input_price_per_million="1.25",
            llm_output_price_per_million=None,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            llm_input_price_per_million="-1",
            llm_output_price_per_million="2",
            _env_file=None,
        )


def test_settings_read_exact_unprefixed_product_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASR_CHUNK_SECONDS", "321")
    monkeypatch.setenv("DEFAULT_TOP_N", "7")
    monkeypatch.setenv("MIN_CLIP_SECONDS", "12")
    monkeypatch.setenv("MAX_CLIP_SECONDS", "48")
    monkeypatch.setenv("PREVIEW_RENDER_WIDTH", "360")
    monkeypatch.setenv("PREVIEW_RENDER_HEIGHT", "640")
    monkeypatch.setenv("WORKER_LEASE_SECONDS", "180")
    monkeypatch.setenv("WORKER_HEARTBEAT_SECONDS", "45")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.asr_chunk_seconds == 321
    assert settings.default_top_n == 7
    assert settings.min_clip_seconds == 12
    assert settings.max_clip_seconds == 48
    assert (settings.preview_render_width, settings.preview_render_height) == (360, 640)
    assert (settings.worker_lease_seconds, settings.worker_heartbeat_seconds) == (180, 45)
    assert settings.log_level == "DEBUG"
