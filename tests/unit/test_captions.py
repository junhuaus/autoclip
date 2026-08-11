import pytest

from liveclip.domain.transcript import TranscriptSegment
from liveclip.services.captions import captions_for_clip


def test_captions_convert_absolute_segments_to_clamped_clip_relative_time() -> None:
    segments = (
        TranscriptSegment(
            segment_id="s1",
            start_ms=8_000,
            end_ms=12_000,
            text="开头被切点截断",
        ),
        TranscriptSegment(
            segment_id="s2",
            start_ms=12_000,
            end_ms=18_000,
            text="完整句子",
        ),
        TranscriptSegment(
            segment_id="s3",
            start_ms=18_000,
            end_ms=24_000,
            text="结尾被切点截断",
        ),
    )

    cues = captions_for_clip(segments, source_start_ms=10_000, source_end_ms=20_000)

    assert [(cue.start_ms, cue.end_ms) for cue in cues] == [
        (0, 2_000),
        (2_000, 8_000),
        (8_000, 10_000),
    ]


def test_captions_drop_tiny_boundary_tail_and_merge_real_short_segment() -> None:
    segments = (
        TranscriptSegment(segment_id="s1", start_ms=0, end_ms=8_000, text="边界残片"),
        TranscriptSegment(segment_id="s2", start_ms=8_000, end_ms=8_100, text="短句"),
        TranscriptSegment(segment_id="s3", start_ms=8_100, end_ms=12_000, text="完整句"),
    )

    cues = captions_for_clip(segments, source_start_ms=7_900, source_end_ms=12_000)

    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [(100, 4_100, "短句完整句")]


def test_caption_density_is_coalesced_without_losing_text() -> None:
    segments = tuple(
        TranscriptSegment(
            segment_id=f"s{index}",
            start_ms=index * 1_000,
            end_ms=(index + 1) * 1_000,
            text=str(index),
        )
        for index in range(10)
    )

    cues = captions_for_clip(segments, source_start_ms=0, source_end_ms=10_000)

    assert len(cues) <= 7
    assert "".join(cue.text.replace(" ", "") for cue in cues) == "0123456789"


def test_long_openrouter_segment_is_time_split_without_losing_text() -> None:
    text = "强混声需要正确训练而不是用嗓子硬喊" * 12
    segments = (
        TranscriptSegment(
            segment_id="openrouter_000001",
            start_ms=188,
            end_ms=30_188,
            text=text,
        ),
    )

    cues = captions_for_clip(segments, source_start_ms=188, source_end_ms=30_188)

    assert len(cues) > 1
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms == 30_000
    assert all(len(cue.text) <= 120 for cue in cues)
    assert all(cue.end_ms - cue.start_ms >= 250 for cue in cues)
    assert "".join(cue.text for cue in cues) == text


def test_transcript_caption_preserves_chinese_full_width_punctuation() -> None:
    text = "很多人先介绍自己，观众却不知道为什么要留下。"  # noqa: RUF001
    segments = (TranscriptSegment(segment_id="punctuation", start_ms=0, end_ms=4_000, text=text),)

    cues = captions_for_clip(segments, source_start_ms=0, source_end_ms=4_000)

    assert [cue.text for cue in cues] == [text]


def test_dense_provider_sentence_at_clip_boundary_is_omitted() -> None:
    segments = (
        TranscriptSegment(
            segment_id="complete",
            start_ms=0,
            end_ms=30_000,
            text="候选主体内容完整保留",
        ),
        TranscriptSegment(
            segment_id="uncertain_boundary_tail",
            start_ms=30_000,
            end_ms=60_000,
            text="边界长句" * 30,
        ),
    )

    cues = captions_for_clip(segments, source_start_ms=0, source_end_ms=30_500)

    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [
        (0, 30_000, "候选主体内容完整保留")
    ]


def test_dense_provider_sentence_inside_clip_remains_invalid() -> None:
    segments = (
        TranscriptSegment(
            segment_id="dense_complete_segment",
            start_ms=0,
            end_ms=500,
            text="完整但过密的字幕" * 20,
        ),
    )

    with pytest.raises(ValueError, match="too dense"):
        captions_for_clip(segments, source_start_ms=0, source_end_ms=500)
