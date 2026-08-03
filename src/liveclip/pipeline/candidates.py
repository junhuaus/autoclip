# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment
from liveclip.pipeline.transcript import normalize_transcript_text

_SENTENCE_PATTERN = re.compile(r".+?(?:[。！？!?；;]+|$)", re.DOTALL)
_CLOSING_PUNCTUATION = ("。", "！", "？", "!", "?", "；", ";")
_HOOK_TERMS = (
    "为什么",
    "关键",
    "记住",
    "第一",
    "第二",
    "第三",
    "如果",
    "很多人",
    "最重要",
    "方法",
    "步骤",
    "误区",
)


class SilenceIntervalLike(Protocol):
    start_ms: int
    end_ms: int


SilenceInput: TypeAlias = tuple[int, int] | SilenceIntervalLike


class CandidateGenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum_duration_ms: int = Field(gt=0)
    maximum_duration_ms: int = Field(gt=0)
    rough_limit: int = Field(default=40, ge=3, le=200)
    top_n: int = Field(default=15, ge=1, le=100)
    context_ms: int = Field(default=5_000, ge=0, le=60_000)
    boundary_pause_ms: int = Field(default=900, ge=100, le=10_000)
    ngram_size: int = Field(default=3, ge=1, le=8)
    duplicate_interval_ratio: float = Field(default=0.72, ge=0, le=1)
    duplicate_text_jaccard: float = Field(default=0.72, ge=0, le=1)

    @model_validator(mode="after")
    def validate_durations(self) -> CandidateGenerationConfig:
        if self.maximum_duration_ms < self.minimum_duration_ms:
            raise ValueError("maximum candidate duration must not be below minimum")
        return self


@dataclass(frozen=True, slots=True)
class _SentenceUnit:
    start_ms: int
    end_ms: int
    text: str
    segment_ids: tuple[str, ...]

    @property
    def closes_expression(self) -> bool:
        return self.text.rstrip().endswith(_CLOSING_PUNCTUATION)


def generate_candidates(
    transcript: TranscriptDocument,
    *,
    config: CandidateGenerationConfig,
    silence_intervals: Sequence[SilenceInput] = (),
    volume_by_segment: Mapping[str, float] | None = None,
) -> tuple[CandidateClip, ...]:
    """Generate deterministic rough candidates on legal sentence/pause boundaries."""

    silences = _validated_silences(silence_intervals, transcript.source_duration_ms)
    units = _sentence_units(transcript.segments)
    rough: list[CandidateClip] = []
    for start_index, start_unit in enumerate(units):
        if not _legal_start(units, start_index, config.boundary_pause_ms):
            continue
        for end_index in range(start_index, len(units)):
            end_unit = units[end_index]
            duration_ms = end_unit.end_ms - start_unit.start_ms
            if duration_ms > config.maximum_duration_ms:
                break
            if duration_ms < config.minimum_duration_ms:
                continue
            if not _legal_end(units, end_index, config.boundary_pause_ms):
                continue
            text = "".join(unit.text.strip() for unit in units[start_index : end_index + 1])
            if not text or len(text) > 24_000:
                continue
            segment_ids = tuple(
                dict.fromkeys(
                    segment_id
                    for unit in units[start_index : end_index + 1]
                    for segment_id in unit.segment_ids
                )
            )
            score, reasons = _rule_score(
                units,
                start_index,
                end_index,
                config=config,
                silences=silences,
                volume_by_segment=volume_by_segment,
            )
            context_before = _context_before(
                transcript.segments,
                start_unit.start_ms,
                context_ms=config.context_ms,
            )
            context_after = _context_after(
                transcript.segments,
                end_unit.end_ms,
                context_ms=config.context_ms,
            )
            identity = hashlib.sha256(
                f"{start_unit.start_ms}\0{end_unit.end_ms}\0{text}".encode()
            ).hexdigest()[:16]
            rough.append(
                CandidateClip(
                    candidate_id=f"candidate_{identity}",
                    source_start_ms=start_unit.start_ms,
                    source_end_ms=end_unit.end_ms,
                    allowed_start_ms=max(0, start_unit.start_ms - config.context_ms),
                    allowed_end_ms=min(
                        transcript.source_duration_ms,
                        end_unit.end_ms + config.context_ms,
                    ),
                    text=text,
                    context_before=context_before,
                    context_after=context_after,
                    rule_score=score,
                    reasons=reasons,
                    segment_ids=segment_ids,
                )
            )

    ranked = _rank_candidates(rough)
    # Keep enough alternatives before deduplication so short Demo input can retain
    # several distinct, complete windows while long input remains bounded.
    prefiltered = ranked[: config.rough_limit * 4]
    unique = deduplicate_candidates(
        prefiltered,
        interval_threshold=config.duplicate_interval_ratio,
        text_threshold=config.duplicate_text_jaccard,
        ngram_size=config.ngram_size,
    )
    return tuple(unique[: config.rough_limit])


def generate_fallback_candidates(
    transcript: TranscriptDocument,
    *,
    config: CandidateGenerationConfig,
    silence_intervals: Sequence[SilenceInput] = (),
    volume_by_segment: Mapping[str, float] | None = None,
) -> tuple[CandidateClip, ...]:
    """Generate rough candidates and apply configured no-LLM top-N selection."""

    rough = generate_candidates(
        transcript,
        config=config,
        silence_intervals=silence_intervals,
        volume_by_segment=volume_by_segment,
    )
    return fallback_select(rough, top_n=config.top_n)


def fallback_select(
    candidates: Sequence[CandidateClip],
    *,
    top_n: int,
) -> tuple[CandidateClip, ...]:
    """Stable no-LLM fallback ranked by the always-available deterministic score."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    return tuple(_rank_candidates(candidates)[:top_n])


def interval_overlap_ratio(left: CandidateClip, right: CandidateClip) -> float:
    intersection = max(
        0,
        min(left.source_end_ms, right.source_end_ms)
        - max(left.source_start_ms, right.source_start_ms),
    )
    if intersection == 0:
        return 0.0
    return intersection / min(left.duration_ms, right.duration_ms)


def normalized_char_ngrams(value: str, *, size: int = 3) -> frozenset[str]:
    if size <= 0:
        raise ValueError("n-gram size must be positive")
    normalized = normalize_transcript_text(value)
    if not normalized:
        return frozenset()
    if len(normalized) <= size:
        return frozenset((normalized,))
    return frozenset(
        normalized[index : index + size] for index in range(len(normalized) - size + 1)
    )


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def deduplicate_candidates(
    candidates: Sequence[CandidateClip],
    *,
    interval_threshold: float = 0.72,
    text_threshold: float = 0.72,
    ngram_size: int = 3,
) -> tuple[CandidateClip, ...]:
    if not 0 <= interval_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise ValueError("deduplication thresholds must be between zero and one")
    accepted: list[CandidateClip] = []
    grams: dict[str, frozenset[str]] = {}
    for candidate in _rank_candidates(candidates):
        candidate_grams = normalized_char_ngrams(candidate.text, size=ngram_size)
        duplicate = False
        for existing in accepted:
            overlap = interval_overlap_ratio(candidate, existing)
            if overlap == 0:
                continue
            similarity = jaccard_similarity(
                candidate_grams,
                grams[existing.candidate_id],
            )
            if (overlap >= interval_threshold and similarity >= 0.2) or (
                overlap >= 0.35 and similarity >= text_threshold
            ):
                duplicate = True
                break
        if not duplicate:
            accepted.append(candidate)
            grams[candidate.candidate_id] = candidate_grams
    return tuple(accepted)


def _sentence_units(segments: Sequence[TranscriptSegment]) -> tuple[_SentenceUnit, ...]:
    units: list[_SentenceUnit] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        duration = segment.end_ms - segment.start_ms
        for match in _SENTENCE_PATTERN.finditer(text):
            unit_text = match.group(0).strip()
            if not unit_text:
                continue
            start_ms = segment.start_ms + round(duration * match.start() / len(text))
            end_ms = segment.start_ms + round(duration * match.end() / len(text))
            end_ms = min(segment.end_ms, max(start_ms + 1, end_ms))
            units.append(
                _SentenceUnit(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=unit_text,
                    segment_ids=(segment.segment_id,),
                )
            )
    return tuple(sorted(units, key=lambda unit: (unit.start_ms, unit.end_ms, unit.text)))


def _legal_start(units: Sequence[_SentenceUnit], index: int, pause_ms: int) -> bool:
    if index == 0:
        return True
    previous = units[index - 1]
    return previous.closes_expression or units[index].start_ms - previous.end_ms >= pause_ms


def _legal_end(units: Sequence[_SentenceUnit], index: int, pause_ms: int) -> bool:
    current = units[index]
    if current.closes_expression or index == len(units) - 1:
        return True
    return units[index + 1].start_ms - current.end_ms >= pause_ms


def _rule_score(
    units: Sequence[_SentenceUnit],
    start_index: int,
    end_index: int,
    *,
    config: CandidateGenerationConfig,
    silences: Sequence[tuple[int, int]],
    volume_by_segment: Mapping[str, float] | None,
) -> tuple[float, tuple[str, ...]]:
    selected = units[start_index : end_index + 1]
    start_ms = selected[0].start_ms
    end_ms = selected[-1].end_ms
    duration_ms = end_ms - start_ms
    text = "".join(unit.text for unit in selected)
    reasons: list[str] = []

    target = (config.minimum_duration_ms + config.maximum_duration_ms) / 2
    radius = max(1.0, (config.maximum_duration_ms - config.minimum_duration_ms) / 2)
    duration_score = 30 * max(0.0, 1 - abs(duration_ms - target) / radius)
    reasons.append("时长接近目标区间")

    boundary_score = 20.0
    if not selected[-1].closes_expression:
        boundary_score -= 6
    else:
        reasons.append("句尾表达闭合")

    normalized_length = len(normalize_transcript_text(text))
    density = normalized_length / max(duration_ms / 1_000, 0.001)
    if density <= 8:
        density_score = min(15.0, density / 4 * 15)
    else:
        density_score = max(3.0, 15 - (density - 8) * 2)
    if density >= 2.5:
        reasons.append("发言密度良好")

    hook_score = 0.0
    opening = text[:40]
    hook_hits = [term for term in _HOOK_TERMS if term in opening]
    if hook_hits or "？" in opening or "?" in opening:
        hook_score = min(15.0, 8 + len(hook_hits) * 2)
        reasons.append("开头包含明确 Hook 信号")

    boundary_pause_score = 0.0
    if _has_boundary_pause(start_ms, end_ms, silences, config.boundary_pause_ms):
        boundary_pause_score = 10.0
        reasons.append("切点邻近停顿")
    elif start_index == 0 or end_index == len(units) - 1:
        boundary_pause_score = 6.0

    continuity_score = _continuity_score(selected)
    if continuity_score >= 3:
        reasons.append("话题连续")

    volume_score = 2.5
    if volume_by_segment:
        samples = [
            max(0.0, min(1.0, volume_by_segment[segment_id]))
            for unit in selected
            for segment_id in unit.segment_ids
            if segment_id in volume_by_segment
        ]
        if samples:
            volume_score = 5 * sum(samples) / len(samples)
            reasons.append("音量信号有效")

    score = min(
        100.0,
        duration_score
        + boundary_score
        + density_score
        + hook_score
        + boundary_pause_score
        + continuity_score
        + volume_score,
    )
    return round(score, 3), tuple(reasons[:12])


def _continuity_score(units: Sequence[_SentenceUnit]) -> float:
    if len(units) == 1:
        return 3.0
    similarities = [
        jaccard_similarity(
            normalized_char_ngrams(left.text, size=2),
            normalized_char_ngrams(right.text, size=2),
        )
        for left, right in pairwise(units)
    ]
    return min(5.0, 2.0 + 6.0 * sum(similarities) / len(similarities))


def _has_boundary_pause(
    start_ms: int,
    end_ms: int,
    silences: Sequence[tuple[int, int]],
    tolerance_ms: int,
) -> bool:
    start_pause = start_ms == 0 or any(
        abs(silence_end - start_ms) <= tolerance_ms for _, silence_end in silences
    )
    end_pause = any(abs(silence_start - end_ms) <= tolerance_ms for silence_start, _ in silences)
    return start_pause and end_pause


def _validated_silences(
    intervals: Sequence[SilenceInput],
    source_duration_ms: int,
) -> tuple[tuple[int, int], ...]:
    values: list[tuple[int, int]] = []
    for interval in intervals:
        if isinstance(interval, tuple):
            start_ms, end_ms = interval
        else:
            start_ms, end_ms = interval.start_ms, interval.end_ms
        if start_ms < 0 or end_ms <= start_ms or end_ms > source_duration_ms:
            raise ValueError("silence interval is outside the source timeline")
        values.append((start_ms, end_ms))
    return tuple(sorted(values))


def _context_before(
    segments: Sequence[TranscriptSegment],
    start_ms: int,
    *,
    context_ms: int,
) -> str:
    text = "".join(
        segment.text
        for segment in segments
        if segment.end_ms <= start_ms and segment.end_ms >= start_ms - context_ms
    )
    return text[-4_000:]


def _context_after(
    segments: Sequence[TranscriptSegment],
    end_ms: int,
    *,
    context_ms: int,
) -> str:
    text = "".join(
        segment.text
        for segment in segments
        if segment.start_ms >= end_ms and segment.start_ms <= end_ms + context_ms
    )
    return text[:4_000]


def _rank_candidates(candidates: Sequence[CandidateClip]) -> list[CandidateClip]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.rule_score,
            candidate.source_start_ms,
            candidate.duration_ms,
            candidate.candidate_id,
        ),
    )
