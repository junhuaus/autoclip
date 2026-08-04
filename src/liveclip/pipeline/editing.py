from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from liveclip.domain.candidate import CandidateClip
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.providers.llm.base import (
    LLMDisposition,
    LLMProvider,
    LLMProviderResult,
    deterministic_edit_plan,
)
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCancelled


class _CandidateEditCacheRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    candidate_id: str = Field(min_length=1, max_length=64)
    candidate_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=64)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_contract_version: str = Field(min_length=1, max_length=80)
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: LLMProviderResult


@dataclass(frozen=True, slots=True)
class EditedCandidate:
    candidate: CandidateClip
    result: LLMProviderResult
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class EditingRunResult:
    all_results: tuple[EditedCandidate, ...]
    selected: tuple[EditedCandidate, ...]
    call_records: tuple[ProviderCallRecord, ...]


CallRecordsCallback = Callable[[tuple[ProviderCallRecord, ...], bool], None]


def edit_and_rank_candidates(
    provider: LLMProvider,
    candidates: Sequence[CandidateClip],
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
    top_n: int,
    cache_dir: Path,
    cancel_requested: Callable[[], bool] = lambda: False,
    on_call_records: CallRecordsCallback | None = None,
) -> EditingRunResult:
    """Edit every rough candidate, cache each completed call, then rank stably."""

    if not candidates:
        raise ValueError("editing requires at least one rough candidate")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise ValueError("rough candidate IDs must be unique")

    all_results: list[EditedCandidate] = []
    calls_by_id: dict[str, ProviderCallRecord] = {}
    provider_circuit_open = False
    for candidate in candidates:
        if cancel_requested():
            raise ProviderCancelled()
        fingerprint = _candidate_fingerprint(
            candidate,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
        )
        cache_path = Path(cache_dir) / _cache_filename(
            candidate.candidate_id,
            fingerprint,
            provider=provider,
        )
        cached = _load_cache(
            cache_path,
            candidate=candidate,
            fingerprint=fingerprint,
            provider=provider,
        )
        if cached is not None:
            item = EditedCandidate(candidate=candidate, result=cached, cache_hit=True)
            all_results.append(item)
            _accept_call_records(
                cached.call_records,
                cache_hit=True,
                calls_by_id=calls_by_id,
                callback=on_call_records,
            )
            if cached.disposition == LLMDisposition.PROVIDER_ERROR:
                provider_circuit_open = True
            continue

        if provider_circuit_open:
            result = _circuit_open_result(
                provider,
                candidate,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
            )
            all_results.append(EditedCandidate(candidate, result, False))
            continue

        result = provider.edit_candidate(
            candidate,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            cancel_requested=cancel_requested,
        )
        if result.plan.candidate_id != candidate.candidate_id:
            raise ValueError("editor returned a plan for a different candidate")

        # Transport/provider failures are not cached: a later stage retry must be able
        # to recover. All completed Responses outcomes are immutable call evidence.
        if result.disposition != LLMDisposition.PROVIDER_ERROR:
            record = _CandidateEditCacheRecord(
                candidate_id=candidate.candidate_id,
                candidate_fingerprint=fingerprint,
                provider=provider.provider_name,
                model=provider.model_name,
                prompt_version=provider.prompt_version,
                prompt_sha256=provider.prompt_sha256,
                provider_contract_version=provider.contract_version,
                result_sha256=_result_sha256(result),
                result=result,
            )
            _write_immutable(cache_path, record.model_dump_json(indent=2) + "\n")
        else:
            provider_circuit_open = True

        all_results.append(EditedCandidate(candidate, result, False))
        _accept_call_records(
            result.call_records,
            cache_hit=False,
            calls_by_id=calls_by_id,
            callback=on_call_records,
        )

    ranked = sorted(
        all_results,
        key=lambda item: (
            -item.result.plan.score,
            -item.candidate.rule_score,
            item.result.plan.source_start_ms,
            item.candidate.candidate_id,
        ),
    )
    selected = tuple(ranked[: min(top_n, len(ranked))])
    return EditingRunResult(
        all_results=tuple(all_results),
        selected=selected,
        call_records=tuple(calls_by_id.values()),
    )


def _circuit_open_result(
    provider: LLMProvider,
    candidate: CandidateClip,
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
) -> LLMProviderResult:
    return LLMProviderResult(
        plan=deterministic_edit_plan(
            candidate,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            model=provider.model_name,
            prompt_version=provider.prompt_version,
            degraded=True,
            risk_flags=("ai_provider_circuit_open",),
        ),
        disposition=LLMDisposition.PROVIDER_ERROR,
    )


def _candidate_fingerprint(
    candidate: CandidateClip,
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
) -> str:
    payload = json.dumps(
        {
            "candidate": candidate.model_dump(mode="json"),
            "maximum_duration_ms": maximum_duration_ms,
            "minimum_duration_ms": minimum_duration_ms,
            "source_duration_ms": source_duration_ms,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_filename(
    candidate_id: str,
    fingerprint: str,
    *,
    provider: LLMProvider,
) -> str:
    identity = "\0".join(
        (
            candidate_id,
            fingerprint,
            provider.provider_name,
            provider.model_name,
            provider.prompt_version,
            provider.prompt_sha256,
            provider.contract_version,
        )
    )
    return f"candidate-{hashlib.sha256(identity.encode()).hexdigest()}.json"


def _load_cache(
    path: Path,
    *,
    candidate: CandidateClip,
    fingerprint: str,
    provider: LLMProvider,
) -> LLMProviderResult | None:
    try:
        record = _CandidateEditCacheRecord.model_validate_json(
            read_regular_text_no_follow(path, max_bytes=8 * 1024 * 1024)
        )
    except SecureFileMissing:
        return None
    except (SecureFileError, ValidationError) as exc:
        raise ValueError("editing cache exists but is not a trusted record") from exc
    if (
        record.candidate_id != candidate.candidate_id
        or record.candidate_fingerprint != fingerprint
        or record.provider != provider.provider_name
        or record.model != provider.model_name
        or record.prompt_version != provider.prompt_version
        or record.prompt_sha256 != provider.prompt_sha256
        or record.provider_contract_version != provider.contract_version
        or record.result.plan.candidate_id != candidate.candidate_id
        or record.result_sha256 != _result_sha256(record.result)
    ):
        raise ValueError("editing cache record does not match its immutable input identity")
    return record.result


def _accept_call_records(
    records: tuple[ProviderCallRecord, ...],
    *,
    cache_hit: bool,
    calls_by_id: dict[str, ProviderCallRecord],
    callback: CallRecordsCallback | None,
) -> None:
    for record in records:
        existing = calls_by_id.get(record.call_id)
        if existing is not None and existing != record:
            raise ValueError("provider call ID maps to conflicting metadata")
        calls_by_id[record.call_id] = record
    if records and callback is not None:
        callback(records, cache_hit)


def _write_immutable(path: Path, value: str) -> None:
    write_text_immutable_no_follow(path, value, max_bytes=8 * 1024 * 1024)


def _result_sha256(result: LLMProviderResult) -> str:
    return hashlib.sha256(result.model_dump_json().encode("utf-8")).hexdigest()
