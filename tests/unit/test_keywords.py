from __future__ import annotations

import pytest

from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.keywords import KeywordTimingPrecision, derive_keyword_occurrences
from liveclip.domain.transcript import TranscriptSegment, TranscriptWord


def segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    text: str,
    *,
    words: tuple[TranscriptWord, ...] | None = None,
) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        words=words,
    )


def test_keywords_are_grounded_in_caption_segment_when_words_are_unavailable() -> None:
    captions = (
        CaptionCue(start_ms=0, end_ms=3_000, text="唱歌之前需要先做快速热身"),
        CaptionCue(start_ms=3_000, end_ms=6_000, text="热身能够保护声带"),
    )

    values = derive_keyword_occurrences(
        captions,
        source_start_ms=120_000,
        source_end_ms=126_000,
        title="唱歌前的快速热身法",
        hook="保护声带",
        reason="这是一套实用的唱歌训练",
        segments=(
            segment("s1", 120_000, 123_000, captions[0].text),
            segment("s2", 123_000, 126_000, captions[1].text),
        ),
    )

    assert values
    assert {value.text for value in values}.issuperset({"唱歌", "快速热身"})
    for value in values:
        assert value.timing_precision is KeywordTimingPrecision.SEGMENT
        assert value.source_start_ms == 120_000 + value.clip_start_ms
        assert value.source_end_ms == 120_000 + value.clip_end_ms
        assert any(value.text in cue.text for cue in captions)


def test_exact_persisted_words_upgrade_keyword_precision_without_inventing_time() -> None:
    captions = (CaptionCue(start_ms=0, end_ms=4_000, text="先保护声带再开始唱歌"),)
    words = (
        TranscriptWord(start_ms=50_000, end_ms=50_100, text="先"),
        TranscriptWord(start_ms=50_100, end_ms=50_700, text="保护"),
        TranscriptWord(start_ms=50_700, end_ms=51_200, text="声带"),
        TranscriptWord(start_ms=52_000, end_ms=52_500, text="唱歌"),
    )

    values = derive_keyword_occurrences(
        captions,
        source_start_ms=50_000,
        source_end_ms=54_000,
        title="保护声带的唱歌方法",
        segments=(segment("s1", 50_000, 54_000, captions[0].text, words=words),),
    )

    protection = next(value for value in values if value.text == "保护声带")
    assert protection.timing_precision is KeywordTimingPrecision.WORD
    assert (protection.clip_start_ms, protection.clip_end_ms) == (100, 1_200)
    assert (protection.source_start_ms, protection.source_end_ms) == (50_100, 51_200)


def test_keyword_time_never_uses_out_of_clip_words() -> None:
    captions = (CaptionCue(start_ms=0, end_ms=2_000, text="快速热身"),)
    words = (TranscriptWord(start_ms=9_000, end_ms=9_500, text="快速热身"),)

    value = derive_keyword_occurrences(
        captions,
        source_start_ms=10_000,
        source_end_ms=12_000,
        title="快速热身",
        segments=(
            segment("outside", 9_000, 10_000, captions[0].text, words=words),
            segment("s1", 10_000, 12_000, captions[0].text),
        ),
        limit=1,
    )[0]

    assert value.timing_precision is KeywordTimingPrecision.SEGMENT
    assert (value.source_start_ms, value.source_end_ms) == (10_000, 12_000)


def test_keyword_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="outside the supported range"):
        derive_keyword_occurrences(
            (CaptionCue(start_ms=0, end_ms=1_000, text="有效字幕"),),
            source_start_ms=0,
            source_end_ms=1_000,
            title="有效字幕",
            segments=(segment("s1", 0, 1_000, "有效字幕"),),
            limit=7,
        )


def test_caption_display_timing_is_never_used_as_asr_keyword_timing() -> None:
    captions = (CaptionCue(start_ms=500, end_ms=1_500, text="声带保护"),)
    values = derive_keyword_occurrences(
        captions,
        source_start_ms=10_000,
        source_end_ms=12_000,
        title="声带保护",
        segments=(segment("s1", 10_200, 11_800, "声带保护很重要"),),
        limit=1,
    )

    assert (values[0].clip_start_ms, values[0].clip_end_ms) == (200, 1_800)
    assert values[0].timing_precision is KeywordTimingPrecision.SEGMENT


def test_partial_boundary_segment_is_not_claimed_as_keyword_evidence() -> None:
    values = derive_keyword_occurrences(
        (CaptionCue(start_ms=0, end_ms=1_000, text="边界关键词"),),
        source_start_ms=10_000,
        source_end_ms=11_000,
        title="边界关键词",
        segments=(segment("s1", 9_000, 10_500, "边界关键词可能在片段外"),),
    )

    assert values == ()


def test_word_precision_does_not_include_an_unrelated_preceding_word() -> None:
    captions = (CaptionCue(start_ms=0, end_ms=2_000, text="前情快速热身"),)
    values = derive_keyword_occurrences(
        captions,
        source_start_ms=10_000,
        source_end_ms=12_000,
        title="快速热身",
        segments=(
            segment(
                "s1",
                10_000,
                12_000,
                "前情快速热身",
                words=(
                    TranscriptWord(start_ms=10_100, end_ms=10_500, text="前情"),
                    TranscriptWord(start_ms=10_600, end_ms=11_000, text="快速"),
                    TranscriptWord(start_ms=11_000, end_ms=11_500, text="热身"),
                ),
            ),
        ),
        limit=1,
    )

    assert values[0].timing_precision is KeywordTimingPrecision.WORD
    assert (values[0].source_start_ms, values[0].source_end_ms) == (10_600, 11_500)


def test_boundary_crossing_word_is_not_clamped_and_mislabeled_as_word_precision() -> None:
    captions = (CaptionCue(start_ms=0, end_ms=1_000, text="快速热身"),)
    values = derive_keyword_occurrences(
        captions,
        source_start_ms=10_000,
        source_end_ms=11_000,
        title="快速热身",
        segments=(
            segment(
                "overlap",
                9_500,
                10_500,
                "快速热身",
                words=(
                    TranscriptWord(start_ms=9_500, end_ms=10_000, text="快速"),
                    TranscriptWord(start_ms=10_000, end_ms=10_500, text="热身"),
                ),
            ),
            segment("s1", 10_000, 11_000, "快速热身"),
        ),
        limit=1,
    )

    assert values[0].timing_precision is KeywordTimingPrecision.SEGMENT
    assert (values[0].source_start_ms, values[0].source_end_ms) == (10_000, 11_000)
