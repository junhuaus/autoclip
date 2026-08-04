from __future__ import annotations

from liveclip.domain.edit_plan import CaptionCue, caption_cues_from_transcript_segments
from liveclip.domain.transcript import TranscriptSegment


def captions_for_clip(
    segments: tuple[TranscriptSegment, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[CaptionCue, ...]:
    return caption_cues_from_transcript_segments(
        segments,
        source_start_ms=source_start_ms,
        source_end_ms=source_end_ms,
    )
