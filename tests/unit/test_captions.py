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
