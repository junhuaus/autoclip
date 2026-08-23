from __future__ import annotations

import re
from pathlib import Path

from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.media.secure_files import read_regular_text_no_follow

_SRT_BLOCK = re.compile(
    r"(?ms)^(?P<cue>[1-9][0-9]*)\r?\n"
    r"(?P<start>[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}) --> "
    r"(?P<end>[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3})\r?\n"
    r"(?P<text>.*?)(?=\r?\n\r?\n[1-9][0-9]*\r?\n|\Z)"
)


def load_srt_transcript(path: Path) -> TranscriptDocument:
    """Load bounded, timestamped SRT evidence without fuzzy text cleanup."""

    raw = read_regular_text_no_follow(path, max_bytes=16 * 1024 * 1024)
    matches = tuple(_SRT_BLOCK.finditer(raw.strip()))
    if not matches:
        raise ValueError("timestamped transcript is not valid SRT")
    segments: list[TranscriptSegment] = []
    expected_cue = 1
    for match in matches:
        cue_id = int(match.group("cue"))
        if cue_id != expected_cue:
            raise ValueError("SRT cue IDs must be stable and sequential")
        start_ms = _timestamp_ms(match.group("start"))
        end_ms = _timestamp_ms(match.group("end"))
        text = "\n".join(line.rstrip() for line in match.group("text").strip().splitlines())
        if not text:
            raise ValueError("SRT cue text cannot be empty")
        segments.append(
            TranscriptSegment(
                segment_id=f"cue_{cue_id:06d}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            )
        )
        expected_cue += 1
    consumed = "\n\n".join(match.group(0).strip() for match in matches)
    normalized = raw.strip().replace("\r\n", "\n")
    if consumed.replace("\r\n", "\n") != normalized:
        raise ValueError("SRT transcript contains unparsed or malformed content")
    return TranscriptDocument(
        source_duration_ms=max(segment.end_ms for segment in segments),
        language="zh",
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(segments),
    )


def _timestamp_ms(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise ValueError("SRT timestamp is out of range")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(milliseconds)


__all__ = ["load_srt_transcript"]
