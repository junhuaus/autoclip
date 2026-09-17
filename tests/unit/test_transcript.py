from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier, Lock

import pytest

from liveclip.domain.transcript import WordTimingStatus
from liveclip.pipeline.transcript import (
    merge_chunk_results,
    transcribe_chunks,
    transcribe_chunks_detailed,
)
from liveclip.providers.asr.base import ASRChunkResult, LocalASRSegment, audio_path_for_chunk
from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment


@dataclass(frozen=True)
class StubChunk:
    chunk_id: str
    source_start_ms: int
    source_end_ms: int
    path: Path
    cache_key: str | None = None
    sha256: str | None = None


def _result(
    chunk: StubChunk,
    *segments: tuple[str, int, int, str],
) -> ASRChunkResult:
    return ASRChunkResult(
        chunk_id=chunk.chunk_id,
        chunk_duration_ms=chunk.source_end_ms - chunk.source_start_ms,
        language="zh",
        provider="mock",
        model="mock-asr-v1",
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            LocalASRSegment(
                segment_id=segment_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                words=None,
            )
            for segment_id, start_ms, end_ms, text in segments
        ),
    )


def test_local_times_become_absolute_and_exact_overlap_is_deduplicated(tmp_path: Path) -> None:
    first = StubChunk("chunk_001", 0, 6_000, tmp_path / "one.m4a")
    second = StubChunk("chunk_002", 5_000, 11_000, tmp_path / "two.m4a")
    document = merge_chunk_results(
        (first, second),
        (
            _result(
                first,
                ("local_1", 1_000, 3_000, "开场先讲清楚价值。"),
                ("local_2", 5_000, 6_000, "接下来介绍三个方法。"),
            ),
            _result(
                second,
                ("local_3", 0, 1_000, "接下来介绍三个方法。"),
                ("local_4", 1_000, 3_000, "第一个方法是先给结论。"),
            ),
        ),
        source_duration_ms=11_000,
    )

    assert [(segment.start_ms, segment.end_ms) for segment in document.segments] == [
        (1_000, 3_000),
        (5_000, 6_000),
        (6_000, 8_000),
    ]
    assert document.segments[1].source_chunk_ids == ("chunk_001", "chunk_002")
    assert document.word_timing_status == WordTimingStatus.UNAVAILABLE
    assert all(segment.words is None for segment in document.segments)


def test_temporal_suffix_prefix_overlap_merges_text_and_evidence(tmp_path: Path) -> None:
    first = StubChunk("chunk_001", 0, 6_000, tmp_path / "one.m4a")
    second = StubChunk("chunk_002", 5_000, 10_000, tmp_path / "two.m4a")
    document = merge_chunk_results(
        (first, second),
        (
            _result(first, ("local_1", 4_000, 6_000, "今天介绍三个方法")),
            _result(second, ("local_2", 500, 3_000, "三个方法马上开始。")),
        ),
        source_duration_ms=10_000,
    )

    assert len(document.segments) == 1
    assert document.segments[0].text == "今天介绍三个方法马上开始。"
    assert document.segments[0].source_chunk_ids == ("chunk_001", "chunk_002")
    assert (document.segments[0].start_ms, document.segments[0].end_ms) == (4_000, 8_000)


def test_mock_provider_returns_chunk_local_duplicates_without_word_timing(tmp_path: Path) -> None:
    script = (
        MockScriptSegment(
            script_id="script_1",
            source_start_ms=4_500,
            source_end_ms=6_500,
            text="相邻音频块会重复这句话。",
        ),
    )
    provider = MockASRProvider(script)
    first = StubChunk("chunk_001", 0, 6_000, tmp_path / "one.m4a")
    second = StubChunk("chunk_002", 5_000, 10_000, tmp_path / "two.m4a")

    first_result = provider.transcribe(first)
    second_result = provider.transcribe(second)

    assert (first_result.segments[0].start_ms, first_result.segments[0].end_ms) == (
        4_500,
        6_000,
    )
    assert (second_result.segments[0].start_ms, second_result.segments[0].end_ms) == (
        0,
        1_500,
    )
    assert first_result.word_timing_status == WordTimingStatus.UNAVAILABLE
    assert second_result.segments[0].words is None


def test_successful_chunk_cache_and_transcript_artifacts_are_reused(tmp_path: Path) -> None:
    chunk = StubChunk("chunk_001", 5_000, 9_000, tmp_path / "one.m4a")
    script = (
        MockScriptSegment(
            script_id="script_1",
            source_start_ms=5_000,
            source_end_ms=9_000,
            text="缓存成功后不再调用提供方。",
        ),
    )
    output_dir = tmp_path / "transcript"
    first_document = transcribe_chunks(
        MockASRProvider(script),
        (chunk,),
        source_duration_ms=10_000,
        output_dir=output_dir,
    )

    class NeverCalledProvider:
        provider_name = "mock"
        model_name = "mock-asr-v1"

        def transcribe(self, *_args: object, **_kwargs: object) -> ASRChunkResult:
            raise AssertionError("a validated successful cache should be reused")

    second_document = transcribe_chunks(
        NeverCalledProvider(),
        (chunk,),
        source_duration_ms=10_000,
        output_dir=output_dir,
    )

    assert second_document == first_document
    assert (output_dir / "transcript.json").is_file()
    srt = (output_dir / "transcript.srt").read_text(encoding="utf-8")
    assert "00:00:05,000 --> 00:00:09,000" in srt
    assert "缓存成功后不再调用提供方。" in srt
    assert len(tuple((output_dir / "asr-cache").glob("chunk-*.json"))) == 1


class _CountingMockASR:
    provider_name = "mock"
    model_name = "mock-asr-v1"
    contract_version = "mock-asr-contract-v1"

    def __init__(self, script: tuple[MockScriptSegment, ...]) -> None:
        self.calls = 0
        self._delegate = MockASRProvider(script)

    def transcribe(self, chunk: StubChunk, **kwargs: object) -> ASRChunkResult:
        self.calls += 1
        return self._delegate.transcribe(chunk, **kwargs)  # type: ignore[arg-type]


def test_verified_asr_cache_can_be_reused_by_a_later_project_generation(
    tmp_path: Path,
) -> None:
    chunk = StubChunk(
        "chunk_001",
        0,
        4_000,
        tmp_path / "one.m4a",
        cache_key="a" * 64,
        sha256="b" * 64,
    )
    script = (
        MockScriptSegment(
            script_id="s1",
            source_start_ms=0,
            source_end_ms=4_000,
            text="跨代缓存避免重复调用。",
        ),
    )
    first_dir = tmp_path / "g001" / "transcript"
    expected = transcribe_chunks(
        MockASRProvider(script),
        (chunk,),
        source_duration_ms=4_000,
        output_dir=first_dir,
    )
    provider = _CountingMockASR(script)
    cache_events: list[bool] = []

    actual = transcribe_chunks_detailed(
        provider,
        (chunk,),
        source_duration_ms=4_000,
        output_dir=tmp_path / "g002" / "attempt",
        cache_dir=tmp_path / "g002" / "transcript" / "asr-cache",
        fallback_cache_dirs=(first_dir / "asr-cache",),
        on_chunk_outcome=lambda _chunk, _record, _status, cache_hit: cache_events.append(cache_hit),
    ).document

    assert actual == expected
    assert provider.calls == 0
    assert cache_events == [True]


def test_cross_generation_cache_rejects_same_key_with_different_audio_sha(
    tmp_path: Path,
) -> None:
    first_chunk = StubChunk(
        "chunk_001",
        0,
        4_000,
        tmp_path / "first.m4a",
        cache_key="a" * 64,
        sha256="b" * 64,
    )
    changed_chunk = StubChunk(
        "chunk_001",
        0,
        4_000,
        tmp_path / "changed.m4a",
        cache_key="a" * 64,
        sha256="c" * 64,
    )
    script = (
        MockScriptSegment(
            script_id="s1",
            source_start_ms=0,
            source_end_ms=4_000,
            text="内容哈希不同必须重新调用。",
        ),
    )
    first_dir = tmp_path / "g001" / "transcript"
    transcribe_chunks(
        MockASRProvider(script),
        (first_chunk,),
        source_duration_ms=4_000,
        output_dir=first_dir,
    )
    provider = _CountingMockASR(script)
    cache_events: list[bool] = []

    transcribe_chunks_detailed(
        provider,
        (changed_chunk,),
        source_duration_ms=4_000,
        output_dir=tmp_path / "g002" / "attempt",
        cache_dir=tmp_path / "g002" / "transcript" / "asr-cache",
        fallback_cache_dirs=(first_dir / "asr-cache",),
        on_chunk_outcome=lambda _chunk, _record, _status, cache_hit: cache_events.append(cache_hit),
    )

    assert provider.calls == 1
    assert cache_events == [False]


@pytest.mark.parametrize(
    ("cache_key", "sha256"),
    (("a" * 64, None), (None, "b" * 64), ("not-a-sha", "b" * 64)),
)
def test_partial_or_invalid_real_chunk_cache_identity_fails_closed(
    tmp_path: Path,
    cache_key: str | None,
    sha256: str | None,
) -> None:
    chunk = StubChunk(
        "chunk_001",
        0,
        4_000,
        tmp_path / "one.m4a",
        cache_key=cache_key,
        sha256=sha256,
    )
    provider = _CountingMockASR(())

    with pytest.raises(ValueError, match="requires both cache_key and content sha256"):
        transcribe_chunks(
            provider,
            (chunk,),
            source_duration_ms=4_000,
            output_dir=tmp_path / "transcript",
        )

    assert provider.calls == 0


def test_tampered_asr_cache_fails_before_provider_call(tmp_path: Path) -> None:
    chunk = StubChunk("chunk_001", 0, 4_000, tmp_path / "one.m4a")
    script = (
        MockScriptSegment(script_id="s1", source_start_ms=0, source_end_ms=4_000, text="原文。"),
    )
    output_dir = tmp_path / "transcript"
    transcribe_chunks(
        MockASRProvider(script),
        (chunk,),
        source_duration_ms=4_000,
        output_dir=output_dir,
    )
    cache_path = next((output_dir / "asr-cache").glob("chunk-*.json"))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["result"]["segments"][0]["text"] = "被篡改。"
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    provider = _CountingMockASR(script)

    with pytest.raises(ValueError, match="immutable input identity"):
        transcribe_chunks(
            provider,
            (chunk,),
            source_duration_ms=4_000,
            output_dir=output_dir,
        )

    assert provider.calls == 0


def test_asr_cache_rejects_final_and_ancestor_symlinks_before_provider_call(
    tmp_path: Path,
) -> None:
    chunk = StubChunk("chunk_001", 0, 4_000, tmp_path / "one.m4a")
    script = (
        MockScriptSegment(script_id="s1", source_start_ms=0, source_end_ms=4_000, text="原文。"),
    )
    output_dir = tmp_path / "first"
    transcribe_chunks(
        MockASRProvider(script),
        (chunk,),
        source_duration_ms=4_000,
        output_dir=output_dir,
    )
    cache_path = next((output_dir / "asr-cache").glob("chunk-*.json"))
    outside = tmp_path / "outside-cache.json"
    outside.write_bytes(cache_path.read_bytes())
    cache_path.unlink()
    cache_path.symlink_to(outside)
    provider = _CountingMockASR(script)

    with pytest.raises(ValueError, match="trusted record"):
        transcribe_chunks(
            provider,
            (chunk,),
            source_duration_ms=4_000,
            output_dir=output_dir,
        )
    assert provider.calls == 0

    linked_output = tmp_path / "linked"
    linked_output.symlink_to(output_dir, target_is_directory=True)
    provider = _CountingMockASR(script)
    with pytest.raises(ValueError, match="trusted record"):
        transcribe_chunks(
            provider,
            (chunk,),
            source_duration_ms=4_000,
            output_dir=linked_output,
        )
    assert provider.calls == 0


def test_audio_chunk_path_supports_path_and_rejects_missing(tmp_path: Path) -> None:
    chunk = StubChunk("chunk_001", 0, 1_000, tmp_path / "one.m4a")
    assert audio_path_for_chunk(chunk) == tmp_path / "one.m4a"

    @dataclass(frozen=True)
    class MissingPath:
        chunk_id: str = "chunk_002"
        source_start_ms: int = 0
        source_end_ms: int = 1_000

    with pytest.raises(TypeError, match="path or audio_path"):
        audio_path_for_chunk(MissingPath())


def test_concurrent_transcription_stops_before_submitting_after_failed_batch(
    tmp_path: Path,
) -> None:
    chunks = tuple(
        StubChunk(
            f"chunk_{index:03d}",
            index * 1_000,
            (index + 1) * 1_000,
            tmp_path / f"{index}.m4a",
        )
        for index in range(4)
    )

    class BatchFailingProvider:
        provider_name = "mock"
        model_name = "mock-asr-v1"
        contract_version = "batch-failure-v1"

        def __init__(self) -> None:
            self.called: list[str] = []
            self.lock = Lock()

        def transcribe(self, chunk: StubChunk, **_kwargs: object) -> ASRChunkResult:
            with self.lock:
                self.called.append(chunk.chunk_id)
            if chunk.chunk_id == "chunk_000":
                raise ValueError("deterministic first-batch failure")
            return _result(
                chunk,
                (f"segment_{chunk.chunk_id}", 0, 1_000, f"{chunk.chunk_id}。"),
            )

    provider = BatchFailingProvider()

    with pytest.raises(ValueError, match="first-batch failure"):
        transcribe_chunks(
            provider,
            chunks,
            source_duration_ms=4_000,
            output_dir=tmp_path / "failed",
            concurrency=2,
        )

    assert set(provider.called).issubset({"chunk_000", "chunk_001"})
    assert "chunk_000" in provider.called


def test_concurrent_transcription_runs_one_bounded_batch_in_parallel_and_merges_in_order(
    tmp_path: Path,
) -> None:
    chunks = tuple(
        StubChunk(
            f"chunk_{index:03d}",
            index * 1_000,
            (index + 1) * 1_000,
            tmp_path / f"{index}.m4a",
        )
        for index in range(4)
    )

    class BarrierProvider:
        provider_name = "mock"
        model_name = "mock-asr-v1"
        contract_version = "bounded-concurrency-v1"

        def __init__(self) -> None:
            self.barrier = Barrier(4, timeout=2)

        def transcribe(self, chunk: StubChunk, **_kwargs: object) -> ASRChunkResult:
            # A serial implementation times out here. All four workers must be
            # in flight before any provider call can return.
            self.barrier.wait()
            return _result(
                chunk,
                (f"segment_{chunk.chunk_id}", 0, 1_000, f"{chunk.chunk_id}。"),
            )

    document = transcribe_chunks(
        BarrierProvider(),
        tuple(reversed(chunks)),
        source_duration_ms=4_000,
        output_dir=tmp_path / "parallel",
        concurrency=4,
    )

    assert [segment.text for segment in document.segments] == [
        "chunk_000。",
        "chunk_001。",
        "chunk_002。",
        "chunk_003。",
    ]


def test_retry_reuses_successful_chunks_and_calls_only_failed_or_pending_chunks(
    tmp_path: Path,
) -> None:
    chunks = tuple(
        StubChunk(
            f"chunk_{index:03d}",
            index * 1_000,
            (index + 1) * 1_000,
            tmp_path / f"{index}.m4a",
        )
        for index in range(3)
    )

    class FailingProvider:
        provider_name = "mock"
        model_name = "mock-asr-v1"
        contract_version = "same-run-retry-v1"

        def __init__(self, *, fail_chunk: str | None) -> None:
            self.fail_chunk = fail_chunk
            self.called: list[str] = []

        def transcribe(self, chunk: StubChunk, **_kwargs: object) -> ASRChunkResult:
            self.called.append(chunk.chunk_id)
            if chunk.chunk_id == self.fail_chunk:
                raise RuntimeError("temporary provider response failure")
            return _result(
                chunk,
                (f"segment_{chunk.chunk_id}", 0, 1_000, f"{chunk.chunk_id}。"),
            )

    output_dir = tmp_path / "transcript"
    first = FailingProvider(fail_chunk="chunk_001")
    with pytest.raises(RuntimeError, match="temporary provider response failure"):
        transcribe_chunks(
            first,
            chunks,
            source_duration_ms=3_000,
            output_dir=output_dir,
        )

    assert first.called == ["chunk_000", "chunk_001"]
    assert len(tuple((output_dir / "asr-cache").glob("chunk-*.json"))) == 1

    second = FailingProvider(fail_chunk=None)
    cache_hits: list[tuple[str, bool]] = []
    document = transcribe_chunks_detailed(
        second,
        chunks,
        source_duration_ms=3_000,
        output_dir=output_dir,
        on_chunk_outcome=lambda chunk, _record, _status, hit: cache_hits.append(
            (chunk.chunk_id, hit)
        ),
    ).document

    assert second.called == ["chunk_001", "chunk_002"]
    assert cache_hits == [
        ("chunk_000", True),
        ("chunk_001", False),
        ("chunk_002", False),
    ]
    assert len(document.segments) == 3
