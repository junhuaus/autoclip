from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from liveclip.domain.time import ms_to_srt
from liveclip.domain.transcript import TranscriptSegment

EDIT_PLAN_SCHEMA_VERSION = "edit-plan-v1"
MAX_CAPTION_CUES = 32
MIN_CAPTION_CUE_MS = 250
MAX_CAPTION_TEXT_CHARACTERS = 120
MAX_DISPLAY_CAPTION_CHARACTERS = 36
MAX_RENDER_OVERLAYS = 64
TITLE_OVERLAY_COUNT = 1


class Layout(StrEnum):
    VERTICAL_BLUR_BACKGROUND = "vertical_blur_background"
    CENTER_CROP = "center_crop"


class CaptionTemplate(StrEnum):
    CLEAN_ZH_V1 = "clean_zh_v1"


class Effect(StrEnum):
    NONE = "none"
    FADE_IN_OUT = "fade_in_out"


SafeShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_EXECUTABLE_PATTERNS = (
    re.compile(r"```"),
    re.compile(r"(?<!\w)/(?:[^/\s]+/)*[^/\s]+"),
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"\b(?:ffmpeg|ffprobe|filter_complex|subprocess|os\.system)\b", re.IGNORECASE),
    re.compile(
        r"(?:^|\s)(?:sudo\s+)?(?:rm|mv|cp|chmod|chown|sh|bash|zsh|python3?|node|"
        r"curl|wget|make|osascript|open)\s+(?:--?[^\s]+\s*)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:scale|crop|overlay|drawtext|subtitles|boxblur|loudnorm|silencedetect|"
        r"fade|afade|setpts|asetpts|format)\s*=",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|\s)#!"),
    re.compile(
        r"\b(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+.+\b(?:FROM|INTO|TABLE|SET)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:&&|\|\||\$\(|`[^`]+`)"),
)


def normalize_display_text(value: str, *, maximum_characters: int | None = None) -> str:
    """Normalize text for raster display without silently truncating content."""

    if maximum_characters is not None and maximum_characters < 1:
        raise ValueError("maximum_characters must be positive")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.replace("\r", " ").replace("\n", " ").split())
    normalized = "".join(
        character for character in normalized if unicodedata.category(character) != "Cc"
    )
    normalized = normalized.strip()
    if maximum_characters is not None and len(normalized) > maximum_characters:
        raise ValueError("display text exceeds its character limit after normalization")
    return normalized


def split_display_caption_text(value: str) -> tuple[str, ...]:
    """Return all normalized caption text in bounded deterministic display parts."""

    normalized = normalize_display_text(
        value,
        maximum_characters=MAX_CAPTION_TEXT_CHARACTERS,
    )
    if not normalized:
        raise ValueError("caption is empty after display normalization")
    return tuple(
        normalized[index : index + MAX_DISPLAY_CAPTION_CHARACTERS]
        for index in range(0, len(normalized), MAX_DISPLAY_CAPTION_CHARACTERS)
    )


class CaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: SafeShortText = Field(max_length=MAX_CAPTION_TEXT_CHARACTERS)

    @model_validator(mode="after")
    def validate_interval_and_text(self) -> CaptionCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("caption end_ms must be greater than start_ms")
        reject_executable_text(self.text)
        split_display_caption_text(self.text)
        return self


@dataclass(slots=True)
class _CaptionInterval:
    start_ms: int
    end_ms: int
    text: str


class EditPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(default="1", pattern=r"^1$")
    candidate_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    title: SafeShortText = Field(max_length=40)
    hook: SafeShortText = Field(max_length=80)
    reason: SafeShortText = Field(max_length=240)
    layout: Layout
    caption_template: CaptionTemplate
    effect: Effect
    risk_flags: tuple[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
        ],
        ...,
    ] = Field(default_factory=tuple, max_length=8)
    prompt_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    degraded: bool

    @model_validator(mode="after")
    def validate_interval_and_content(self) -> EditPlan:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("source_end_ms must be greater than source_start_ms")
        for text in (self.title, self.hook, self.reason, *self.risk_flags):
            reject_executable_text(text)
        normalize_display_text(self.title, maximum_characters=40)
        return self

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


def edit_plan_from_json_data(value: Mapping[str, object] | str | bytes) -> EditPlan:
    """Restore a strict EditPlan through Pydantic's JSON validation mode."""

    payload = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, Mapping)
        else value
    )
    return EditPlan.model_validate_json(payload)


def reject_executable_text(value: str) -> None:
    if len(value.encode("utf-8")) > 1_024:
        raise ValueError("text exceeds the safe UTF-8 byte limit")
    for character in value:
        category = unicodedata.category(character)
        if character in {"\t", "\n"}:
            continue
        if category[0] not in {"L", "M", "N", "P", "S", "Z"}:
            raise ValueError("text contains a disallowed Unicode category")
    if any(pattern.search(value) for pattern in _EXECUTABLE_PATTERNS):
        raise ValueError("text resembles an executable path, command, script, SQL, or filter")


def validate_edit_plan_bounds(
    plan: EditPlan,
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
    allowed_start_ms: int,
    allowed_end_ms: int,
) -> None:
    if plan.source_end_ms > source_duration_ms:
        raise ValueError("EditPlan exceeds source duration")
    if not minimum_duration_ms <= plan.duration_ms <= maximum_duration_ms:
        raise ValueError("EditPlan duration is outside configured bounds")
    if plan.source_start_ms < allowed_start_ms or plan.source_end_ms > allowed_end_ms:
        raise ValueError("EditPlan adjustment exceeds the candidate context window")


def validate_caption_cues(cues: tuple[CaptionCue, ...], *, clip_duration_ms: int) -> None:
    if not cues:
        raise ValueError("at least one caption cue is required")
    density_limit = max(1, (clip_duration_ms + 1_499) // 1_500)
    if len(cues) > min(MAX_CAPTION_CUES, density_limit):
        raise ValueError("caption cue count exceeds the clip duration resource budget")
    previous_end = 0
    display_overlay_count = TITLE_OVERLAY_COUNT
    for cue in cues:
        if cue.start_ms < previous_end:
            raise ValueError("caption cues must be ordered and non-overlapping")
        if cue.end_ms - cue.start_ms < MIN_CAPTION_CUE_MS:
            raise ValueError("caption cue duration is too short")
        if cue.end_ms > clip_duration_ms:
            raise ValueError("caption cue exceeds clip duration")
        display_parts = split_display_caption_text(cue.text)
        if cue.end_ms - cue.start_ms < len(display_parts) * MIN_CAPTION_CUE_MS:
            raise ValueError("caption text is too dense for its display interval")
        display_overlay_count += len(display_parts)
        previous_end = cue.end_ms
    if display_overlay_count > MAX_RENDER_OVERLAYS:
        raise ValueError("caption display fanout exceeds the render overlay resource budget")


def expand_caption_cues_for_display(cues: tuple[CaptionCue, ...]) -> tuple[CaptionCue, ...]:
    """Expand already validated cues into the exact intervals consumed by the renderer."""

    result: list[CaptionCue] = []
    for cue in cues:
        parts = split_display_caption_text(cue.text)
        duration_ms = cue.end_ms - cue.start_ms
        if duration_ms < len(parts) * MIN_CAPTION_CUE_MS:
            raise ValueError("caption text is too dense for its display interval")
        for index, part in enumerate(parts):
            start_ms = cue.start_ms + (duration_ms * index) // len(parts)
            end_ms = cue.start_ms + (duration_ms * (index + 1)) // len(parts)
            result.append(CaptionCue(start_ms=start_ms, end_ms=end_ms, text=part))
    return tuple(result)


def caption_cues_from_transcript_segments(
    segments: tuple[TranscriptSegment, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[CaptionCue, ...]:
    """Build bounded clip-relative cues without retaining tiny clipped sentence tails."""

    if source_start_ms < 0 or source_end_ms <= source_start_ms:
        raise ValueError("clip interval is invalid")
    clip_duration_ms = source_end_ms - source_start_ms
    intervals: list[_CaptionInterval] = []
    for segment in segments:
        absolute_start = max(segment.start_ms, source_start_ms)
        absolute_end = min(segment.end_ms, source_end_ms)
        if absolute_end <= absolute_start:
            continue
        was_boundary_clipped = segment.start_ms < source_start_ms or segment.end_ms > source_end_ms
        if absolute_end - absolute_start < MIN_CAPTION_CUE_MS and was_boundary_clipped:
            continue
        relative_start = absolute_start - source_start_ms
        relative_end = absolute_end - source_start_ms
        if intervals:
            relative_start = max(relative_start, intervals[-1].end_ms)
        if relative_end <= relative_start:
            continue
        intervals.append(
            _CaptionInterval(
                start_ms=relative_start,
                end_ms=relative_end,
                text=segment.text,
            )
        )
    if not intervals:
        raise ValueError("clip has no usable transcript segments for captions")

    _coalesce_short_caption_intervals(intervals, clip_duration_ms=clip_duration_ms)
    density_limit = min(MAX_CAPTION_CUES, max(1, (clip_duration_ms + 1_499) // 1_500))
    while len(intervals) > density_limit:
        candidates = [
            (right.end_ms - left.start_ms, index)
            for index, (left, right) in enumerate(pairwise(intervals))
            if len(_join_caption_text(left.text, right.text)) <= 120
        ]
        if not candidates:
            raise ValueError("transcript captions cannot fit the bounded cue resource budget")
        _, index = min(candidates)
        _merge_caption_pair(intervals, index)

    cues = tuple(
        CaptionCue(start_ms=item.start_ms, end_ms=item.end_ms, text=item.text) for item in intervals
    )
    validate_caption_cues(cues, clip_duration_ms=clip_duration_ms)
    return cues


def _coalesce_short_caption_intervals(
    intervals: list[_CaptionInterval], *, clip_duration_ms: int
) -> None:
    while True:
        short_index = next(
            (
                index
                for index, item in enumerate(intervals)
                if item.end_ms - item.start_ms < MIN_CAPTION_CUE_MS
            ),
            None,
        )
        if short_index is None:
            return
        if len(intervals) == 1:
            if clip_duration_ms < MIN_CAPTION_CUE_MS:
                raise ValueError("clip is too short for a safe caption cue")
            start_ms = min(intervals[0].start_ms, clip_duration_ms - MIN_CAPTION_CUE_MS)
            intervals[0].start_ms = max(0, start_ms)
            intervals[0].end_ms = intervals[0].start_ms + MIN_CAPTION_CUE_MS
            return
        pair_indexes = []
        if short_index > 0:
            pair_indexes.append(short_index - 1)
        if short_index + 1 < len(intervals):
            pair_indexes.append(short_index)
        compatible = [
            index
            for index in pair_indexes
            if len(_join_caption_text(intervals[index].text, intervals[index + 1].text)) <= 120
        ]
        if not compatible:
            raise ValueError("short transcript caption cannot be merged without truncating text")
        _merge_caption_pair(intervals, min(compatible))


def _merge_caption_pair(intervals: list[_CaptionInterval], index: int) -> None:
    left = intervals[index]
    right = intervals[index + 1]
    intervals[index : index + 2] = [
        _CaptionInterval(
            start_ms=left.start_ms,
            end_ms=right.end_ms,
            text=_join_caption_text(left.text, right.text),
        )
    ]


def _join_caption_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    separator = " " if left[-1:].isascii() and right[:1].isascii() else ""
    return f"{left}{separator}{right}"


def captions_to_srt(cues: tuple[CaptionCue, ...]) -> str:
    rows: list[str] = []
    for index, cue in enumerate(cues, start=1):
        rows.extend(
            [
                str(index),
                f"{ms_to_srt(cue.start_ms)} --> {ms_to_srt(cue.end_ms)}",
                cue.text,
                "",
            ]
        )
    return "\n".join(rows)
