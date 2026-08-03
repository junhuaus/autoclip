from __future__ import annotations

from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.transcript import TranscriptSegment


def captions_for_clip(
    segments: tuple[TranscriptSegment, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[CaptionCue, ...]:
    if source_start_ms < 0 or source_end_ms <= source_start_ms:
        raise ValueError("clip interval is invalid")
    cues: list[CaptionCue] = []
    for segment in segments:
        absolute_start = max(segment.start_ms, source_start_ms)
        absolute_end = min(segment.end_ms, source_end_ms)
        if absolute_end <= absolute_start:
            continue
        cues.append(
            CaptionCue(
                start_ms=absolute_start - source_start_ms,
                end_ms=absolute_end - source_start_ms,
                text=segment.text,
            )
        )
    if not cues:
        raise ValueError("clip has no transcript segments for captions")
    return tuple(cues)
