from __future__ import annotations

import re
import unicodedata
from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.edit_plan import CaptionCue, normalize_display_text, reject_executable_text
from liveclip.domain.transcript import TranscriptSegment, TranscriptWord

MAX_KEYWORD_OCCURRENCES = 6
MAX_KEYWORD_CHARACTERS = 24

_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{1,23}|[\u3400-\u9fff]{2,}")
_LOW_INFORMATION_TERMS = {
    "一个",
    "一些",
    "这个",
    "那个",
    "就是",
    "其实",
    "然后",
    "因为",
    "所以",
    "但是",
    "而且",
    "可以",
    "可能",
    "什么",
    "怎么",
    "我们",
    "你们",
    "他们",
    "这里",
    "这样",
    "那样",
}
_LOW_INFORMATION_EDGE_CHARACTERS = frozenset(
    "的一是在了和与或而也都就又把被让给对从到这那有很会能要我你他她它们个"
)


class KeywordTimingPrecision(StrEnum):
    WORD = "word"
    SEGMENT = "segment"


class KeywordOccurrence(BaseModel):
    """A grounded keyword occurrence on both clip and source timelines."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    text: str = Field(min_length=2, max_length=MAX_KEYWORD_CHARACTERS)
    clip_start_ms: int = Field(ge=0)
    clip_end_ms: int = Field(gt=0)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    timing_precision: KeywordTimingPrecision

    @model_validator(mode="after")
    def validate_grounded_interval(self) -> KeywordOccurrence:
        if self.clip_end_ms <= self.clip_start_ms:
            raise ValueError("keyword clip interval must be positive")
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("keyword source interval must be positive")
        if self.clip_end_ms - self.clip_start_ms != self.source_end_ms - self.source_start_ms:
            raise ValueError("keyword clip and source intervals must have equal duration")
        normalized = normalize_display_text(
            self.text,
            maximum_characters=MAX_KEYWORD_CHARACTERS,
        )
        if len(normalized) < 2:
            raise ValueError("keyword is too short after normalization")
        reject_executable_text(normalized)
        return self


def derive_keyword_occurrences(
    captions: tuple[CaptionCue, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
    title: str,
    hook: str = "",
    reason: str = "",
    segments: tuple[TranscriptSegment, ...] = (),
    limit: int = MAX_KEYWORD_OCCURRENCES,
) -> tuple[KeywordOccurrence, ...]:
    """Select useful phrases and bind every time to persisted transcript evidence.

    Editorial metadata only helps rank phrases. A returned phrase must occur in a
    fully contained persisted transcript segment. Word timing is used only for an
    exact persisted-word match; otherwise that ASR segment is returned as a range.
    """

    if source_start_ms < 0 or source_end_ms <= source_start_ms:
        raise ValueError("source interval is invalid")
    if not 1 <= limit <= MAX_KEYWORD_OCCURRENCES:
        raise ValueError("keyword limit is outside the supported range")
    if not captions or not segments:
        return ()

    grounded_segments = tuple(
        segment
        for segment in segments
        if segment.start_ms >= source_start_ms and segment.end_ms <= source_end_ms
    )
    if not grounded_segments:
        return ()
    evidence_texts = tuple(_canonical_text(segment.text) for segment in grounded_segments)
    candidate_scores: dict[str, int] = {}
    candidate_order: dict[str, int] = {}
    next_order = 0

    def add_hint(value: str, weight: int) -> None:
        nonlocal next_order
        for term in _terms_from_text(value):
            matching_segments = sum(term.casefold() in text.casefold() for text in evidence_texts)
            if not matching_segments:
                continue
            key = term.casefold()
            candidate_scores[key] = max(
                candidate_scores.get(key, 0),
                weight + len(term) * 5 + matching_segments * 3,
            )
            if key not in candidate_order:
                candidate_order[key] = next_order
                next_order += 1

    add_hint(title, 80)
    if not candidate_scores:
        add_hint(hook, 55)
        add_hint(reason, 35)

    if not candidate_scores:
        fallback_counts: Counter[str] = Counter()
        for value in evidence_texts:
            fallback_counts.update(_fallback_terms(value))
        for term, count in fallback_counts.items():
            key = term.casefold()
            candidate_scores.setdefault(key, len(term) * 3 + count * 4)
            if key not in candidate_order:
                candidate_order[key] = next_order
                next_order += 1

    # Ranking below never consumes proportional display-caption timing.

    ranked = sorted(
        candidate_scores,
        key=lambda value: (
            -candidate_scores[value],
            -len(value),
            candidate_order[value],
            value,
        ),
    )
    selected: list[str] = []
    for term in ranked:
        if any(term in existing or existing in term for existing in selected):
            continue
        selected.append(term)
        if len(selected) == limit:
            break

    results: list[KeywordOccurrence] = []
    for selected_term in selected:
        segment = _first_grounding_segment(
            selected_term,
            segments,
            source_start_ms=source_start_ms,
            source_end_ms=source_end_ms,
        )
        if segment is None:
            continue
        display_term = _display_term(selected_term, segment)
        word_interval = _find_word_interval(
            selected_term,
            segment.words or (),
            source_start_ms=max(source_start_ms, segment.start_ms),
            source_end_ms=min(source_end_ms, segment.end_ms),
        )
        if word_interval is not None:
            absolute_start, absolute_end = word_interval
            results.append(
                KeywordOccurrence(
                    text=display_term,
                    clip_start_ms=absolute_start - source_start_ms,
                    clip_end_ms=absolute_end - source_start_ms,
                    source_start_ms=absolute_start,
                    source_end_ms=absolute_end,
                    timing_precision=KeywordTimingPrecision.WORD,
                )
            )
            continue
        absolute_start = max(source_start_ms, segment.start_ms)
        absolute_end = min(source_end_ms, segment.end_ms)
        results.append(
            KeywordOccurrence(
                text=display_term,
                clip_start_ms=absolute_start - source_start_ms,
                clip_end_ms=absolute_end - source_start_ms,
                source_start_ms=absolute_start,
                source_end_ms=absolute_end,
                timing_precision=KeywordTimingPrecision.SEGMENT,
            )
        )
    return tuple(sorted(results, key=lambda item: (item.clip_start_ms, item.text.casefold())))


def _canonical_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _terms_from_text(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _TERM_PATTERN.finditer(_canonical_text(value)):
        token = match.group(0)
        if token[0].isascii():
            if _useful_term(token):
                terms.append(token)
            continue
        maximum_width = min(8, len(token))
        for width in range(maximum_width, 1, -1):
            for offset in range(0, len(token) - width + 1):
                term = token[offset : offset + width]
                if _useful_term(term):
                    terms.append(term)
    return tuple(dict.fromkeys(terms))


def _fallback_terms(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _TERM_PATTERN.finditer(value):
        token = match.group(0)
        if token[0].isascii():
            if _useful_term(token):
                terms.append(token)
            continue
        maximum_width = min(4, len(token))
        for width in range(maximum_width, 1, -1):
            for offset in range(0, len(token) - width + 1):
                term = token[offset : offset + width]
                if _useful_term(term):
                    terms.append(term)
    return tuple(dict.fromkeys(terms))


def _useful_term(value: str) -> bool:
    normalized = value.casefold().strip(".-")
    if len(normalized) < 2 or normalized in _LOW_INFORMATION_TERMS:
        return False
    if normalized.isdigit():
        return False
    if normalized.endswith(("第", "同", "做")):
        return False
    if normalized[0] in _LOW_INFORMATION_EDGE_CHARACTERS:
        return False
    if normalized[-1] in _LOW_INFORMATION_EDGE_CHARACTERS:
        return False
    return any(character.isalpha() for character in normalized)


def _display_term(term: str, segment: TranscriptSegment) -> str:
    canonical = _canonical_text(segment.text)
    offset = canonical.casefold().find(term)
    if offset < 0:
        raise ValueError("keyword candidate is not grounded in its transcript segment")
    return canonical[offset : offset + len(term)]


def _first_grounding_segment(
    term: str,
    segments: tuple[TranscriptSegment, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
) -> TranscriptSegment | None:
    """Use only a fully contained ASR segment as honest range evidence."""

    target = term.casefold()
    for segment in segments:
        if segment.start_ms < source_start_ms or segment.end_ms > source_end_ms:
            continue
        if target in _canonical_text(segment.text).casefold():
            return segment
    return None


def _find_word_interval(
    term: str,
    words: tuple[TranscriptWord, ...],
    *,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[int, int] | None:
    relevant = tuple(
        word for word in words if word.start_ms >= source_start_ms and word.end_ms <= source_end_ms
    )
    target = term.casefold()
    parts = tuple(_canonical_text(word.text).casefold() for word in relevant)
    for first_word_index in range(len(parts)):
        combined = ""
        for last_word_index in range(first_word_index, len(parts)):
            combined += parts[last_word_index]
            if combined == target:
                return (
                    relevant[first_word_index].start_ms,
                    relevant[last_word_index].end_ms,
                )
            if len(combined) >= len(target):
                break
    return None
