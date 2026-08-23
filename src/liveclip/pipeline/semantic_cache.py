from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class SemanticCacheProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def contract_version(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    @property
    def prompt_sha256(self) -> str: ...


class SemanticStageCacheRecord(BaseModel):
    """Immutable, transcript-free evidence for one validated Agent stage output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    algorithm: str = Field(default="semantic_global", pattern=r"^semantic_global$")
    stage: str = Field(pattern=r"^(discovery|global_review)$")
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=100)
    model_settings_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_version: str = Field(min_length=1, max_length=80)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_contract_version: str = Field(min_length=1, max_length=160)
    output_schema: str = Field(pattern=r"^(DiscoveryOutput|GlobalReviewOutput)$")
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output: dict[str, object]


def semantic_stage_cache_key(
    *,
    stage: str,
    payload: dict[str, object],
    provider: SemanticCacheProvider,
    model_settings: dict[str, object],
    output_model: type[BaseModel],
) -> str:
    input_sha256 = _canonical_sha256(payload)
    settings_sha256 = _canonical_sha256(model_settings)
    identity = "\0".join(
        (
            "semantic-global-stage-cache-v1",
            "semantic_global",
            stage,
            input_sha256,
            provider.provider_name,
            provider.model_name,
            settings_sha256,
            provider.prompt_version,
            provider.prompt_sha256,
            provider.contract_version,
            output_model.__name__,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def load_semantic_stage_cache(
    *,
    cache_dirs: Sequence[Path],
    cache_key: str,
    stage: str,
    payload: dict[str, object],
    provider: SemanticCacheProvider,
    model_settings: dict[str, object],
    output_model: type[StructuredOutput],
) -> StructuredOutput | None:
    for cache_dir in cache_dirs:
        path = cache_dir / f"{cache_key}.json"
        try:
            record = SemanticStageCacheRecord.model_validate_json(
                read_regular_text_no_follow(path, max_bytes=16 * 1024 * 1024)
            )
        except SecureFileMissing:
            continue
        except (SecureFileError, ValidationError) as exc:
            raise ValueError("semantic stage cache exists but is not trusted") from exc
        output = output_model.model_validate_json(
            json.dumps(record.output, ensure_ascii=False, separators=(",", ":"))
        )
        expected_input = _canonical_sha256(payload)
        expected_settings = _canonical_sha256(model_settings)
        if (
            record.stage != stage
            or record.input_sha256 != expected_input
            or record.provider != provider.provider_name
            or record.model != provider.model_name
            or record.model_settings_sha256 != expected_settings
            or record.prompt_version != provider.prompt_version
            or record.prompt_sha256 != provider.prompt_sha256
            or record.provider_contract_version != provider.contract_version
            or record.output_schema != output_model.__name__
            or record.output_sha256 != _canonical_sha256(record.output)
        ):
            raise ValueError("semantic stage cache identity does not match its input")
        return output
    return None


def write_semantic_stage_cache(
    *,
    cache_dir: Path,
    cache_key: str,
    stage: str,
    payload: dict[str, object],
    provider: SemanticCacheProvider,
    model_settings: dict[str, object],
    output: BaseModel,
) -> None:
    output_payload = output.model_dump(mode="json")
    record = SemanticStageCacheRecord(
        stage=stage,
        input_sha256=_canonical_sha256(payload),
        provider=provider.provider_name,
        model=provider.model_name,
        model_settings_sha256=_canonical_sha256(model_settings),
        prompt_version=provider.prompt_version,
        prompt_sha256=provider.prompt_sha256,
        provider_contract_version=provider.contract_version,
        output_schema=type(output).__name__,
        output_sha256=_canonical_sha256(output_payload),
        output=output_payload,
    )
    write_text_immutable_no_follow(
        cache_dir / f"{cache_key}.json",
        record.model_dump_json(indent=2) + "\n",
        max_bytes=16 * 1024 * 1024,
    )


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "load_semantic_stage_cache",
    "semantic_stage_cache_key",
    "write_semantic_stage_cache",
]
