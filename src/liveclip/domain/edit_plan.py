from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from liveclip.domain.time import ms_to_srt


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


class CaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: SafeShortText = Field(max_length=120)

    @model_validator(mode="after")
    def validate_interval_and_text(self) -> CaptionCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("caption end_ms must be greater than start_ms")
        reject_executable_text(self.text)
        return self


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
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)], ...
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
        return self

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


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
    previous_start = -1
    for cue in cues:
        if cue.start_ms < previous_start:
            raise ValueError("caption cues must be ordered by start_ms")
        if cue.end_ms > clip_duration_ms:
            raise ValueError("caption cue exceeds clip duration")
        previous_start = cue.start_ms


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
