from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated local settings.

    Secrets remain ``SecretStr`` values and are never included in ``public_summary``.
    Paths are resolved by the service that owns their security boundary.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LIVECLIP_",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    data_dir: Path = Path("data/projects")
    allowed_media_roots_raw: str = Field(
        default="", validation_alias="LIVECLIP_ALLOWED_MEDIA_ROOTS"
    )
    api_token: SecretStr | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=1, le=65535)
    media_url_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
    cors_origins_raw: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        validation_alias="LIVECLIP_CORS_ORIGINS",
    )

    ai_provider: str = "mock"
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    transcription_model: str = Field(
        default="whisper-1", validation_alias="OPENAI_TRANSCRIPTION_MODEL"
    )
    llm_model: str = Field(default="gpt-5.6-terra", validation_alias="OPENAI_LLM_MODEL")

    asr_chunk_seconds: int = Field(
        default=600, ge=10, le=3600, validation_alias="ASR_CHUNK_SECONDS"
    )
    asr_chunk_overlap_seconds: int = Field(
        default=5, ge=0, le=60, validation_alias="ASR_CHUNK_OVERLAP_SECONDS"
    )
    asr_max_chunk_bytes: int = Field(
        default=24_000_000,
        ge=1_000_000,
        le=25_000_000,
        validation_alias="ASR_MAX_CHUNK_BYTES",
    )
    asr_concurrency: int = Field(default=1, ge=1, le=8, validation_alias="ASR_CONCURRENCY")

    default_top_n: int = Field(default=15, ge=1, le=100, validation_alias="DEFAULT_TOP_N")
    min_clip_seconds: int = Field(default=30, ge=1, le=600, validation_alias="MIN_CLIP_SECONDS")
    max_clip_seconds: int = Field(default=90, ge=1, le=1800, validation_alias="MAX_CLIP_SECONDS")

    preview_render_width: int = Field(
        default=540, ge=180, le=2160, validation_alias="PREVIEW_RENDER_WIDTH"
    )
    preview_render_height: int = Field(
        default=960, ge=320, le=3840, validation_alias="PREVIEW_RENDER_HEIGHT"
    )
    final_render_width: int = Field(
        default=1080, ge=360, le=4320, validation_alias="FINAL_RENDER_WIDTH"
    )
    final_render_height: int = Field(
        default=1920, ge=640, le=7680, validation_alias="FINAL_RENDER_HEIGHT"
    )
    video_encoder: str = "auto"

    worker_lease_seconds: int = Field(
        default=120, ge=15, le=3600, validation_alias="WORKER_LEASE_SECONDS"
    )
    worker_heartbeat_seconds: int = Field(
        default=30, ge=5, le=1800, validation_alias="WORKER_HEARTBEAT_SECONDS"
    )
    max_stage_retries: int = Field(default=3, ge=0, le=20, validation_alias="MAX_STAGE_RETRIES")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    llm_input_price_per_million: Decimal | None = Field(
        default=None, validation_alias="OPENAI_LLM_INPUT_PRICE_PER_MILLION"
    )
    llm_output_price_per_million: Decimal | None = Field(
        default=None, validation_alias="OPENAI_LLM_OUTPUT_PRICE_PER_MILLION"
    )

    @field_validator("ai_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mock", "openai"}:
            raise ValueError("LIVECLIP_AI_PROVIDER must be 'mock' or 'openai'")
        return normalized

    @field_validator("video_encoder")
    @classmethod
    def validate_encoder(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "h264_videotoolbox", "libx264"}:
            raise ValueError("LIVECLIP_VIDEO_ENCODER must be auto, h264_videotoolbox, or libx264")
        return normalized

    @model_validator(mode="after")
    def validate_cross_field_invariants(self) -> Settings:
        if self.asr_chunk_overlap_seconds >= self.asr_chunk_seconds:
            raise ValueError("ASR_CHUNK_OVERLAP_SECONDS must be shorter than ASR_CHUNK_SECONDS")
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("MIN_CLIP_SECONDS must not exceed MAX_CLIP_SECONDS")
        if self.worker_heartbeat_seconds * 2 >= self.worker_lease_seconds:
            raise ValueError("WORKER_LEASE_SECONDS must exceed twice WORKER_HEARTBEAT_SECONDS")
        return self

    @property
    def allowed_media_roots(self) -> tuple[Path, ...]:
        return tuple(Path(item).expanduser() for item in _split_list(self.allowed_media_roots_raw))

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(_split_list(self.cors_origins_raw, include_path_separator=False))

    def resolved_data_dir(self, base_dir: Path | None = None) -> Path:
        value = self.data_dir.expanduser()
        if not value.is_absolute():
            value = (base_dir or Path.cwd()) / value
        return value.resolve(strict=False)

    def public_summary(self, base_dir: Path | None = None) -> dict[str, object]:
        return {
            "data_dir": str(self.resolved_data_dir(base_dir)),
            "allowed_media_roots_configured": len(self.allowed_media_roots),
            "api_host": self.api_host,
            "api_port": self.api_port,
            "api_token_configured": bool(self.api_token and self.api_token.get_secret_value()),
            "ai_provider": self.ai_provider,
            "openai_configured": bool(
                self.openai_api_key and self.openai_api_key.get_secret_value()
            ),
            "transcription_model": self.transcription_model,
            "llm_model": self.llm_model,
        }


def _split_list(value: str, *, include_path_separator: bool = True) -> list[str]:
    normalized = value.replace("\n", ",")
    if include_path_separator:
        normalized = normalized.replace(os.pathsep, ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
