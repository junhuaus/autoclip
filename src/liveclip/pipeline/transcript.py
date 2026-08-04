# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
import os
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from liveclip.domain.time import ms_to_srt
from liveclip.domain.transcript import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
    WordTimingStatus,
)
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.providers.asr.base import ASRChunkResult, ASRProvider, AudioChunkLike
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderRequestError,
)


class _ChunkCacheRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    chunk_id: str = Field(min_length=1, max_length=128)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    chunk_cache_identity: str = Field(min_length=1, max_length=256)
    provider_contract_version: str = Field(min_length=1, max_length=80)
    vocabulary_prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: ASRChunkResult


@dataclass(frozen=True, slots=True)
class _AbsoluteDraft:
    start_ms: int
    end_ms: int
    text: str
    source_chunk_ids: tuple[str, ...]
    words: tuple[TranscriptWord, ...] | None


@dataclass(frozen=True, slots=True)
class TranscriptionRunResult:
    document: TranscriptDocument
    call_records: tuple[ProviderCallRecord, ...]


ChunkOutcomeCallback = Callable[
    [AudioChunkLike, ProviderCallRecord | None, ProviderCallStatus, bool],
    None,
]


def normalize_transcript_text(value: str) -> str:
    """Normalize Chinese text for comparison without changing displayed content."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character).startswith(("L", "N"))
    )


def merge_chunk_results(
    chunks: Sequence[AudioChunkLike],
    results: Sequence[ASRChunkResult],
    *,
    source_duration_ms: int,
    temporal_tolerance_ms: int = 1_000,
) -> TranscriptDocument:
    """Convert chunk-local times to source time and remove overlap duplicates.

    Exact normalized duplicates and sufficiently long suffix/prefix duplicates are
    merged only when their source intervals overlap or nearly touch. The resulting
    segment retains every contributing chunk ID as durable merge evidence.
    """

    if source_duration_ms <= 0:
        raise ValueError("source_duration_ms must be positive")
    if len(chunks) != len(results):
        raise ValueError("every audio chunk must have exactly one ASR result")

    ordered_pairs = sorted(
        zip(chunks, results, strict=True),
        key=lambda item: (item[0].source_start_ms, item[0].source_end_ms, item[0].chunk_id),
    )
    all_word_timings_available = bool(ordered_pairs) and all(
        result.word_timing_status == WordTimingStatus.AVAILABLE for _, result in ordered_pairs
    )

    raw_drafts: list[_AbsoluteDraft] = []
    seen_chunk_ids: set[str] = set()
    language = "zh"
    for chunk, result in ordered_pairs:
        _validate_chunk_result_pair(chunk, result, source_duration_ms=source_duration_ms)
        if chunk.chunk_id in seen_chunk_ids:
            raise ValueError("audio chunk IDs must be unique")
        seen_chunk_ids.add(chunk.chunk_id)
        language = result.language
        for local_segment in result.segments:
            absolute_start = chunk.source_start_ms + local_segment.start_ms
            absolute_end = chunk.source_start_ms + local_segment.end_ms
            words: tuple[TranscriptWord, ...] | None = None
            if all_word_timings_available and local_segment.words is not None:
                words = tuple(
                    TranscriptWord(
                        start_ms=chunk.source_start_ms + word.start_ms,
                        end_ms=chunk.source_start_ms + word.end_ms,
                        text=word.text,
                    )
                    for word in local_segment.words
                )
            raw_drafts.append(
                _AbsoluteDraft(
                    start_ms=absolute_start,
                    end_ms=absolute_end,
                    text=local_segment.text.strip(),
                    source_chunk_ids=(chunk.chunk_id,),
                    words=words,
                )
            )

    raw_drafts.sort(key=lambda item: (item.start_ms, item.end_ms, item.text))
    merged: list[_AbsoluteDraft] = []
    for incoming in raw_drafts:
        exact_index = _find_exact_duplicate(
            merged,
            incoming,
            temporal_tolerance_ms=temporal_tolerance_ms,
        )
        if exact_index is not None:
            merged[exact_index] = _merge_exact(merged[exact_index], incoming)
            continue

        if merged and _temporally_related(
            merged[-1], incoming, temporal_tolerance_ms=temporal_tolerance_ms
        ):
            overlap = _longest_suffix_prefix(
                normalize_transcript_text(merged[-1].text),
                normalize_transcript_text(incoming.text),
            )
            shorter_length = min(
                len(normalize_transcript_text(merged[-1].text)),
                len(normalize_transcript_text(incoming.text)),
            )
            if overlap >= 3 and shorter_length > 0 and overlap / shorter_length >= 0.3:
                merged[-1] = _merge_suffix_prefix(merged[-1], incoming, overlap)
                continue
        merged.append(incoming)

    merged.sort(key=lambda item: (item.start_ms, item.end_ms, item.text))
    status = (
        WordTimingStatus.AVAILABLE if all_word_timings_available else WordTimingStatus.UNAVAILABLE
    )
    segments = tuple(
        TranscriptSegment(
            segment_id=f"segment_{index:06d}",
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            text=item.text,
            source_chunk_ids=item.source_chunk_ids,
            words=item.words if status == WordTimingStatus.AVAILABLE else None,
        )
        for index, item in enumerate(merged, start=1)
    )
    return TranscriptDocument(
        language=language,
        source_duration_ms=source_duration_ms,
        word_timing_status=status,
        segments=segments,
    )


def transcribe_chunks(
    provider: ASRProvider,
    chunks: Sequence[AudioChunkLike],
    *,
    source_duration_ms: int,
    output_dir: Path,
    cache_dir: Path | None = None,
    language: str = "zh",
    vocabulary_prompt: str | None = None,
    concurrency: int = 1,
    cancel_requested: Callable[[], bool] = lambda: False,
    on_chunk_outcome: ChunkOutcomeCallback | None = None,
) -> TranscriptDocument:
    """Resume cached successful chunks, merge them, and atomically emit artifacts."""

    return transcribe_chunks_detailed(
        provider,
        chunks,
        source_duration_ms=source_duration_ms,
        output_dir=output_dir,
        cache_dir=cache_dir,
        language=language,
        vocabulary_prompt=vocabulary_prompt,
        concurrency=concurrency,
        cancel_requested=cancel_requested,
        on_chunk_outcome=on_chunk_outcome,
    ).document


def transcribe_chunks_detailed(
    provider: ASRProvider,
    chunks: Sequence[AudioChunkLike],
    *,
    source_duration_ms: int,
    output_dir: Path,
    cache_dir: Path | None = None,
    language: str = "zh",
    vocabulary_prompt: str | None = None,
    concurrency: int = 1,
    cancel_requested: Callable[[], bool] = lambda: False,
    on_chunk_outcome: ChunkOutcomeCallback | None = None,
) -> TranscriptionRunResult:
    """Run/cache per-chunk ASR with deterministic ordering and durable call evidence."""

    if not 1 <= concurrency <= 8:
        raise ValueError("ASR concurrency must be between one and eight")

    destination = Path(output_dir)
    cache_root = Path(cache_dir) if cache_dir is not None else destination / "asr-cache"
    ordered_chunks = tuple(
        sorted(
            chunks,
            key=lambda chunk: (
                chunk.source_start_ms,
                chunk.source_end_ms,
                chunk.chunk_id,
            ),
        )
    )
    results_by_chunk: dict[str, ASRChunkResult] = {}
    calls_by_id: dict[str, ProviderCallRecord] = {}
    missing: list[tuple[AudioChunkLike, Path, str]] = []
    vocabulary_prompt_sha256 = hashlib.sha256((vocabulary_prompt or "").encode()).hexdigest()
    contract_version = _provider_contract_version(provider)
    for chunk in ordered_chunks:
        if cancel_requested():
            raise ProviderCancelled()
        chunk_cache_identity = _chunk_cache_identity(chunk)
        cache_path = cache_root / _chunk_cache_filename(
            chunk.chunk_id,
            chunk_cache_identity,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            contract_version=contract_version,
            language=language,
            vocabulary_prompt_sha256=vocabulary_prompt_sha256,
        )
        cached = _load_cached_result(
            cache_path,
            chunk,
            chunk_cache_identity=chunk_cache_identity,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            provider_contract_version=contract_version,
            language=language,
            vocabulary_prompt_sha256=vocabulary_prompt_sha256,
        )
        if cached is not None:
            results_by_chunk[chunk.chunk_id] = cached
            if cached.call_record is not None:
                calls_by_id[cached.call_record.call_id] = cached.call_record
            if on_chunk_outcome is not None:
                on_chunk_outcome(
                    chunk,
                    cached.call_record,
                    ProviderCallStatus.SUCCEEDED,
                    True,
                )
            continue
        missing.append((chunk, cache_path, chunk_cache_identity))

    if missing:
        failures: list[Exception] = []
        if concurrency == 1:
            for item in missing:
                try:
                    result = _transcribe_and_cache(
                        provider,
                        item,
                        source_duration_ms=source_duration_ms,
                        language=language,
                        vocabulary_prompt=vocabulary_prompt,
                        vocabulary_prompt_sha256=vocabulary_prompt_sha256,
                        provider_contract_version=contract_version,
                        cancel_requested=cancel_requested,
                    )
                except Exception as exc:
                    _report_chunk_failure(item[0], exc, on_chunk_outcome=on_chunk_outcome)
                    raise
                _accept_chunk_success(
                    item[0],
                    result,
                    results_by_chunk=results_by_chunk,
                    calls_by_id=calls_by_id,
                    on_chunk_outcome=on_chunk_outcome,
                )
        else:
            with ThreadPoolExecutor(
                max_workers=concurrency,
                thread_name_prefix="liveclip-asr",
            ) as pool:
                # Submit at most one bounded batch. A failed batch therefore cannot
                # leave the rest of a multi-hour recording queued for paid calls.
                for batch_start in range(0, len(missing), concurrency):
                    if failures or cancel_requested():
                        break
                    batch = missing[batch_start : batch_start + concurrency]
                    futures: dict[
                        Future[ASRChunkResult],
                        tuple[AudioChunkLike, Path, str],
                    ] = {
                        pool.submit(
                            _transcribe_and_cache,
                            provider,
                            item,
                            source_duration_ms=source_duration_ms,
                            language=language,
                            vocabulary_prompt=vocabulary_prompt,
                            vocabulary_prompt_sha256=vocabulary_prompt_sha256,
                            provider_contract_version=contract_version,
                            cancel_requested=cancel_requested,
                        ): item
                        for item in batch
                    }
                    for future in as_completed(futures):
                        item = futures[future]
                        try:
                            result = future.result()
                        except Exception as exc:
                            _report_chunk_failure(
                                item[0],
                                exc,
                                on_chunk_outcome=on_chunk_outcome,
                            )
                            failures.append(exc)
                        else:
                            _accept_chunk_success(
                                item[0],
                                result,
                                results_by_chunk=results_by_chunk,
                                calls_by_id=calls_by_id,
                                on_chunk_outcome=on_chunk_outcome,
                            )
            if failures:
                raise failures[0]
            if cancel_requested():
                raise ProviderCancelled()

    results = [results_by_chunk[chunk.chunk_id] for chunk in ordered_chunks]

    document = merge_chunk_results(
        ordered_chunks,
        tuple(results),
        source_duration_ms=source_duration_ms,
    )
    write_transcript_artifacts(document, destination)
    return TranscriptionRunResult(
        document=document,
        call_records=tuple(calls_by_id.values()),
    )


def _transcribe_and_cache(
    provider: ASRProvider,
    item: tuple[AudioChunkLike, Path, str],
    *,
    source_duration_ms: int,
    language: str,
    vocabulary_prompt: str | None,
    vocabulary_prompt_sha256: str,
    provider_contract_version: str,
    cancel_requested: Callable[[], bool],
) -> ASRChunkResult:
    chunk, cache_path, chunk_cache_identity = item
    result = provider.transcribe(
        chunk,
        language=language,
        vocabulary_prompt=vocabulary_prompt,
        cancel_requested=cancel_requested,
    )
    _validate_chunk_result_pair(chunk, result, source_duration_ms=source_duration_ms)
    record = _ChunkCacheRecord(
        chunk_id=chunk.chunk_id,
        source_start_ms=chunk.source_start_ms,
        source_end_ms=chunk.source_end_ms,
        chunk_cache_identity=chunk_cache_identity,
        provider_contract_version=provider_contract_version,
        vocabulary_prompt_sha256=vocabulary_prompt_sha256,
        result_sha256=_result_sha256(result),
        result=result,
    )
    _atomic_write_immutable_text(cache_path, record.model_dump_json(indent=2) + "\n")
    return result


def _accept_chunk_success(
    chunk: AudioChunkLike,
    result: ASRChunkResult,
    *,
    results_by_chunk: dict[str, ASRChunkResult],
    calls_by_id: dict[str, ProviderCallRecord],
    on_chunk_outcome: ChunkOutcomeCallback | None,
) -> None:
    results_by_chunk[chunk.chunk_id] = result
    if result.call_record is not None:
        calls_by_id[result.call_record.call_id] = result.call_record
    if on_chunk_outcome is not None:
        on_chunk_outcome(
            chunk,
            result.call_record,
            ProviderCallStatus.SUCCEEDED,
            False,
        )


def _report_chunk_failure(
    chunk: AudioChunkLike,
    error: Exception,
    *,
    on_chunk_outcome: ChunkOutcomeCallback | None,
) -> None:
    if on_chunk_outcome is None:
        return
    if isinstance(error, ProviderCancelled):
        if error.call_record is not None:
            on_chunk_outcome(
                chunk,
                error.call_record,
                ProviderCallStatus.CANCELLED,
                False,
            )
        return
    call_record: ProviderCallRecord | None = None
    if isinstance(error, ProviderRequestError):
        call_record = error.call_record
    status = call_record.status if call_record is not None else ProviderCallStatus.FAILED
    on_chunk_outcome(chunk, call_record, status, False)


def write_transcript_artifacts(document: TranscriptDocument, output_dir: Path) -> None:
    destination = Path(output_dir)
    _atomic_write_text(destination / "transcript.json", document.model_dump_json(indent=2) + "\n")
    _atomic_write_text(destination / "transcript.srt", transcript_to_srt(document))


def transcript_to_srt(document: TranscriptDocument) -> str:
    rows: list[str] = []
    for index, segment in enumerate(document.segments, start=1):
        rows.extend(
            [
                str(index),
                f"{ms_to_srt(segment.start_ms)} --> {ms_to_srt(segment.end_ms)}",
                segment.text,
                "",
            ]
        )
    return "\n".join(rows)


def _validate_chunk_result_pair(
    chunk: AudioChunkLike,
    result: ASRChunkResult,
    *,
    source_duration_ms: int,
) -> None:
    if chunk.source_start_ms < 0 or chunk.source_end_ms <= chunk.source_start_ms:
        raise ValueError("audio chunk has an invalid interval")
    if chunk.source_end_ms > source_duration_ms:
        raise ValueError("audio chunk exceeds source duration")
    if result.chunk_id != chunk.chunk_id:
        raise ValueError("ASR result chunk_id does not match requested chunk")
    if result.chunk_duration_ms != chunk.source_end_ms - chunk.source_start_ms:
        raise ValueError("ASR result duration does not match requested chunk")


def _chunk_cache_filename(
    chunk_id: str,
    cache_identity: str,
    *,
    provider_name: str,
    model_name: str,
    contract_version: str,
    language: str,
    vocabulary_prompt_sha256: str,
) -> str:
    identity = "\0".join(
        (
            chunk_id,
            cache_identity,
            provider_name,
            model_name,
            contract_version,
            language,
            vocabulary_prompt_sha256,
        )
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"chunk-{digest}.json"


def _chunk_cache_identity(chunk: AudioChunkLike) -> str:
    for attribute in ("cache_key", "sha256"):
        value = getattr(chunk, attribute, None)
        if isinstance(value, str) and value:
            return value[:256]
    return f"{chunk.chunk_id}:{chunk.source_start_ms}:{chunk.source_end_ms}"


def _load_cached_result(
    path: Path,
    chunk: AudioChunkLike,
    *,
    chunk_cache_identity: str,
    provider_name: str,
    model_name: str,
    provider_contract_version: str,
    language: str,
    vocabulary_prompt_sha256: str,
) -> ASRChunkResult | None:
    try:
        record = _ChunkCacheRecord.model_validate_json(
            read_regular_text_no_follow(path, max_bytes=8 * 1024 * 1024)
        )
    except SecureFileMissing:
        return None
    except (SecureFileError, ValidationError) as exc:
        raise ValueError("ASR cache exists but is not a trusted record") from exc
    if (
        record.chunk_id != chunk.chunk_id
        or record.source_start_ms != chunk.source_start_ms
        or record.source_end_ms != chunk.source_end_ms
        or record.chunk_cache_identity != chunk_cache_identity
        or record.provider_contract_version != provider_contract_version
        or record.vocabulary_prompt_sha256 != vocabulary_prompt_sha256
        or record.result.provider != provider_name
        or record.result.model != model_name
        or record.result.language != language
        or record.result_sha256 != _result_sha256(record.result)
    ):
        raise ValueError("ASR cache record does not match its immutable input identity")
    return record.result


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write_immutable_text(path: Path, value: str) -> None:
    write_text_immutable_no_follow(path, value, max_bytes=8 * 1024 * 1024)


def _provider_contract_version(provider: ASRProvider) -> str:
    value = getattr(provider, "contract_version", None)
    if isinstance(value, str) and value:
        return value
    return f"{provider.provider_name}-asr-contract-v1"


def _result_sha256(result: ASRChunkResult) -> str:
    return hashlib.sha256(result.model_dump_json().encode("utf-8")).hexdigest()


def _find_exact_duplicate(
    existing: Sequence[_AbsoluteDraft],
    incoming: _AbsoluteDraft,
    *,
    temporal_tolerance_ms: int,
) -> int | None:
    incoming_normalized = normalize_transcript_text(incoming.text)
    for index in range(len(existing) - 1, max(-1, len(existing) - 9), -1):
        candidate = existing[index]
        if candidate.end_ms + temporal_tolerance_ms < incoming.start_ms:
            break
        if (
            incoming_normalized
            and incoming_normalized == normalize_transcript_text(candidate.text)
            and _temporally_related(
                candidate,
                incoming,
                temporal_tolerance_ms=temporal_tolerance_ms,
            )
        ):
            return index
    return None


def _temporally_related(
    left: _AbsoluteDraft,
    right: _AbsoluteDraft,
    *,
    temporal_tolerance_ms: int,
) -> bool:
    overlap = min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms)
    if overlap > 0:
        return True
    gap = max(left.start_ms, right.start_ms) - min(left.end_ms, right.end_ms)
    return gap <= temporal_tolerance_ms


def _merge_exact(left: _AbsoluteDraft, right: _AbsoluteDraft) -> _AbsoluteDraft:
    text = left.text if len(left.text) >= len(right.text) else right.text
    return _AbsoluteDraft(
        start_ms=min(left.start_ms, right.start_ms),
        end_ms=max(left.end_ms, right.end_ms),
        text=text,
        source_chunk_ids=_merge_chunk_ids(left.source_chunk_ids, right.source_chunk_ids),
        words=_merge_words(left.words, right.words),
    )


def _merge_suffix_prefix(
    left: _AbsoluteDraft,
    right: _AbsoluteDraft,
    overlap_length: int,
) -> _AbsoluteDraft:
    _, raw_positions = _normalized_with_positions(right.text)
    cut_at = raw_positions[overlap_length - 1] + 1
    remainder = right.text[cut_at:].lstrip(" \t，,；;")
    return replace(
        left,
        end_ms=max(left.end_ms, right.end_ms),
        text=f"{left.text}{remainder}",
        source_chunk_ids=_merge_chunk_ids(left.source_chunk_ids, right.source_chunk_ids),
        words=_merge_words(left.words, right.words),
    )


def _normalized_with_positions(value: str) -> tuple[str, tuple[int, ...]]:
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(value):
        normalized_piece = unicodedata.normalize("NFKC", character).casefold()
        for normalized_character in normalized_piece:
            if unicodedata.category(normalized_character).startswith(("L", "N")):
                characters.append(normalized_character)
                positions.append(index)
    return "".join(characters), tuple(positions)


def _longest_suffix_prefix(left: str, right: str) -> int:
    maximum = min(len(left), len(right))
    for length in range(maximum, 0, -1):
        if left[-length:] == right[:length]:
            return length
    return 0


def _merge_chunk_ids(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    merged = tuple(dict.fromkeys((*left, *right)))
    if len(merged) > 8:
        raise ValueError("transcript merge evidence exceeds the eight-chunk domain limit")
    return merged


def _merge_words(
    left: tuple[TranscriptWord, ...] | None,
    right: tuple[TranscriptWord, ...] | None,
) -> tuple[TranscriptWord, ...] | None:
    if left is None and right is None:
        return None
    values = (*(() if left is None else left), *(() if right is None else right))
    unique = {
        (word.start_ms, word.end_ms, normalize_transcript_text(word.text)): word for word in values
    }
    return tuple(sorted(unique.values(), key=lambda word: (word.start_ms, word.end_ms, word.text)))
