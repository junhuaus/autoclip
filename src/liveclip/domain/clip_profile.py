from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClipProfile(StrEnum):
    """Independent editorial units with different deterministic duration contracts."""

    SHORT_HIGHLIGHT = "short_highlight"
    MINI_LESSON = "mini_lesson"


@dataclass(frozen=True, slots=True)
class ClipProfileSpec:
    profile: ClipProfile
    minimum_duration_ms: int
    target_duration_ms: int
    maximum_duration_ms: int
    content_unit: str


SHORT_HIGHLIGHT_SPEC = ClipProfileSpec(
    profile=ClipProfile.SHORT_HIGHLIGHT,
    minimum_duration_ms=45_000,
    target_duration_ms=60_000,
    maximum_duration_ms=90_000,
    content_unit="一个独立微观点、回答或高光时刻",
)

MINI_LESSON_SPEC = ClipProfileSpec(
    profile=ClipProfile.MINI_LESSON,
    minimum_duration_ms=90_000,
    target_duration_ms=180_000,
    maximum_duration_ms=300_000,
    content_unit="一个中心教学目标,可包含步骤、解释、示范、练习和结论",
)

CLIP_PROFILE_SPECS: dict[ClipProfile, ClipProfileSpec] = {
    ClipProfile.SHORT_HIGHLIGHT: SHORT_HIGHLIGHT_SPEC,
    ClipProfile.MINI_LESSON: MINI_LESSON_SPEC,
}


def clip_profile_spec(profile: ClipProfile | str) -> ClipProfileSpec:
    return CLIP_PROFILE_SPECS[ClipProfile(profile)]


__all__ = [
    "CLIP_PROFILE_SPECS",
    "MINI_LESSON_SPEC",
    "SHORT_HIGHLIGHT_SPEC",
    "ClipProfile",
    "ClipProfileSpec",
    "clip_profile_spec",
]
