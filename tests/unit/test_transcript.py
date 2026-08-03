from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from liveclip.domain.transcript import WordTimingStatus
from liveclip.pipeline.transcript import merge_chunk_results, transcribe_chunks
from liveclip.providers.asr.base import ASRChunkResult, LocalASRSegment, audio_path_for_chunk
from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment


@dataclass(frozen=True)
class StubChunk:
    chunk_id: str
    source_start_ms: int
    source_end_ms: int
    path: Path


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
