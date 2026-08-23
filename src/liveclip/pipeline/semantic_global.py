from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Protocol

import tiktoken
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment

SafeIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
BoundedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MANUAL_REVIEW_RISKS = frozenset(
    {
        "medical_diagnosis_high",
        "absolute_claim",
        "commercial_claim",
        "music_rights_review",
    }
)
HARD_MANUAL_REVIEW_RISKS = frozenset({"medical_diagnosis_high"})

# Discovery needs enough budget to understand the whole source when possible.
# Global Review already receives Discovery's complete topic map, so repeating a
# long, low-value transcript is only worthwhile when the entire request is
# comfortably smaller than the Discovery budget.  The fraction is applied to
# the user-configurable full-context ratio rather than to a fixture duration or
# cue count.
GLOBAL_REVIEW_FULL_CONTEXT_SHARE = 0.55
GLOBAL_REVIEW_SEMANTIC_CONTEXT_MODE = "semantic_context"
GLOBAL_REVIEW_ADJACENT_CONTEXT_CUES = 2
GLOBAL_REVIEW_PREFERRED_CANDIDATE_CONTEXT_MS = 30_000
GLOBAL_REVIEW_MINIMUM_CANDIDATE_CONTEXT_MS = 15_000
GLOBAL_REVIEW_CANDIDATE_CONTEXT_STEP_MS = 5_000
DURATION_REJECTION_AUDIT_TOLERANCE_MS = 1_000
GLOBAL_REVIEW_CUE_COLUMNS = (
    "cue_id",
    "start_ms",
    "end_ms",
    "original_text",
    "normalized_text",
    "normalization_note",
)


class SemanticGlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum_duration_ms: int = Field(default=45_000, ge=1_000, le=600_000)
    target_duration_ms: int = Field(default=60_000, ge=1_000, le=600_000)
    maximum_duration_ms: int = Field(default=90_000, ge=1_000, le=600_000)
    score_threshold_exclusive: float = Field(default=75.0, ge=0, le=100)
    max_clips: int = Field(default=15, ge=1, le=100)
    full_context_budget_ratio: float = Field(default=0.58, ge=0.1, le=0.8)
    model_context_tokens: int = Field(default=128_000, ge=16_000, le=2_000_000)
    tokenizer_name: str = Field(
        default="o200k_base",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    output_reserve_tokens: int = Field(default=16_000, ge=2_000, le=200_000)
    safety_margin_tokens: int = Field(default=1_000, ge=1_000, le=200_000)
    fallback_target_duration_ms: int = Field(default=900_000, ge=60_000, le=3_600_000)
    fallback_minimum_duration_ms: int = Field(default=600_000, ge=60_000, le=3_600_000)
    fallback_maximum_duration_ms: int = Field(default=1_200_000, ge=60_000, le=3_600_000)
    fallback_context_guard_ms: int = Field(default=30_000, ge=0, le=300_000)
    global_context_ms: int = Field(default=90_000, ge=30_000, le=300_000)
    window_duration_ms: int = Field(default=120_000, ge=60_000, le=600_000)
    window_overlap_ms: int = Field(default=60_000, ge=1_000, le=300_000)
    window_batch_size: int = Field(default=4, ge=1, le=12)
    window_discovery_concurrency: int = Field(default=5, ge=1, le=8)

    @model_validator(mode="after")
    def validate_ranges(self) -> SemanticGlobalConfig:
        if not self.minimum_duration_ms <= self.target_duration_ms <= self.maximum_duration_ms:
            raise ValueError("semantic global duration must satisfy minimum <= target <= maximum")
        if not (
            self.fallback_minimum_duration_ms
            <= self.fallback_target_duration_ms
            <= self.fallback_maximum_duration_ms
        ):
            raise ValueError("fallback duration must satisfy minimum <= target <= maximum")
        if self.window_overlap_ms >= self.window_duration_ms:
            raise ValueError("semantic window overlap must be shorter than the window")
        if self.window_duration_ms < self.maximum_duration_ms:
            raise ValueError("semantic window must fit the maximum clip duration")
        budget = int(self.model_context_tokens * self.full_context_budget_ratio)
        if self.output_reserve_tokens + self.safety_margin_tokens >= budget:
            raise ValueError("semantic global output reserve leaves no bounded input budget")
        return self

    @property
    def fallback_overlap_ms(self) -> int:
        return self.maximum_duration_ms + self.fallback_context_guard_ms


class SemanticCue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cue_id: int = Field(ge=1)
    segment_id: SafeIdentifier
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    original_text: str = Field(min_length=1, max_length=4_000)
    normalized_text: str | None = Field(default=None, min_length=1, max_length=4_000)
    normalization_note: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_interval(self) -> SemanticCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("cue end must be greater than start")
        if (self.normalized_text is None) != (self.normalization_note is None):
            raise ValueError("normalized cue text requires a normalization note")
        return self


class CueRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> CueRange:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("cue range is reversed")
        return self


class CandidateStatus(StrEnum):
    FOUND = "found"
    NO_CANDIDATE = "no_candidate"


class NoCandidateReasonCode(StrEnum):
    NO_GENERAL_VALUE = "no_general_value"
    INCOMPLETE_TOPIC = "incomplete_topic"
    CANNOT_FORM_CONTINUOUS_CLIP = "cannot_form_continuous_clip"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    ASR_TOO_UNCERTAIN = "asr_too_uncertain"
    OUTSIDE_OWNERSHIP = "outside_ownership"
    INVALID_REFERENCE_REMOVED = "invalid_candidate_reference_removed"


class OpeningRelevance(StrEnum):
    DIRECT = "direct"
    NECESSARY_CONTEXT = "necessary_context"
    IRRELEVANT = "irrelevant"


class BoundaryCompactness(StrEnum):
    SHORTEST_COMPLETE = "shortest_complete"
    CONTAINS_REMOVABLE_CONTEXT = "contains_removable_context"


class SourceFidelity(StrEnum):
    FAITHFUL = "faithful"
    UNSUPPORTED_REFRAME = "unsupported_reframe"


class QualityFlag(StrEnum):
    CONTEXT_DEPENDENT_OPENING = "context_dependent_opening"
    IRRELEVANT_INTRO = "irrelevant_intro"
    IRRELEVANT_OUTRO = "irrelevant_outro"
    REPEATED_LIVE_CTA = "repeated_live_cta"
    SALES_HEAVY = "sales_heavy"
    ASR_UNCERTAIN = "asr_uncertain"
    TOPIC_NOT_CLOSED = "topic_not_closed"
    INCOMPLETE_ENDING = "incomplete_ending"
    TOPIC_SWITCH_INSIDE = "topic_switch_inside"
    SOURCE_TITLE_MISMATCH = "source_title_mismatch"
    PADDED_WITH_IRRELEVANT_CONTENT = "padded_with_irrelevant_content"


MANUAL_REVIEW_QUALITY_FLAGS = frozenset(
    {
        QualityFlag.CONTEXT_DEPENDENT_OPENING,
        QualityFlag.REPEATED_LIVE_CTA,
        QualityFlag.SALES_HEAVY,
        QualityFlag.ASR_UNCERTAIN,
    }
)


class RiskType(StrEnum):
    MEDICAL_DIAGNOSIS_HIGH = "medical_diagnosis_high"
    GENERAL_HEALTH_WARNING = "general_health_warning"
    ABSOLUTE_CLAIM = "absolute_claim"
    COMMERCIAL_CLAIM = "commercial_claim"
    SENSITIVITY_REVIEW = "sensitivity_review"
    MUSIC_RIGHTS_REVIEW = "music_rights_review"


class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: RiskType
    severity: RiskSeverity
    reason: BoundedText = Field(max_length=400)
    source_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=80)


class BoundarySide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class BoundaryTopicReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    side: BoundarySide
    topic_summary: BoundedText = Field(max_length=240)
    viewer_promise: BoundedText = Field(max_length=200)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=40)
    continuation_expected: bool
    related_candidate_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=20)


class DiscoveryTopicUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic_id: SafeIdentifier
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    summary: BoundedText = Field(max_length=240)
    value_density: Literal["low", "medium", "high"]
    candidate_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=50)
    candidate_status: CandidateStatus
    no_candidate_reason_code: NoCandidateReasonCode | None
    ideal_start_cue_id: int | None = Field(default=None, ge=1)
    ideal_end_cue_id: int | None = Field(default=None, ge=1)
    model_claimed_duration_sec: float | None = Field(default=None, ge=0, le=86_400)

    @model_validator(mode="after")
    def validate_candidate_disposition(self) -> DiscoveryTopicUnit:
        if self.candidate_status == CandidateStatus.FOUND:
            if not self.candidate_ids:
                raise ValueError("found Discovery topic must reference at least one candidate")
            if self.no_candidate_reason_code is not None:
                raise ValueError("found Discovery topic cannot have a no-candidate reason")
        else:
            if self.candidate_ids:
                raise ValueError("no-candidate Discovery topic cannot reference candidates")
            if self.no_candidate_reason_code is None:
                raise ValueError("no-candidate Discovery topic requires a reason code")
        return self


class DiscoveryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: SafeIdentifier
    parent_topic: BoundedText = Field(max_length=160)
    viewer_promise: BoundedText = Field(max_length=200)
    content_type: SafeIdentifier
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    hook: BoundedText = Field(max_length=160)
    payoff: BoundedText = Field(max_length=240)
    standalone_context: BoundedText = Field(max_length=400)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=80)
    boundary_notes: BoundedText = Field(max_length=400)
    source_opening_quote: BoundedText = Field(max_length=400)
    source_closing_quote: BoundedText = Field(max_length=400)
    opening_relevance: OpeningRelevance
    ending_complete: bool
    first_complete_payoff_cue_id: int = Field(ge=1)
    minimum_duration_extension_cue_ids: tuple[int, ...] = Field(max_length=80)
    boundary_compactness: BoundaryCompactness
    topic_core_start_cue_id: int = Field(ge=1)
    topic_core_end_cue_id: int = Field(ge=1)
    irrelevant_intro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    irrelevant_outro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    quality_flags: tuple[QualityFlag, ...] = Field(default_factory=tuple, max_length=12)
    risks: tuple[RiskAssessment, ...] = Field(default_factory=tuple, max_length=12)


class DiscoveryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_id: SafeIdentifier
    source_range: CueRange
    starts_inside_open_topic: bool = False
    ends_inside_open_topic: bool = False
    boundary_topics: tuple[BoundaryTopicReport, ...] = Field(default_factory=tuple, max_length=8)
    topic_units: tuple[DiscoveryTopicUnit, ...] = Field(max_length=200)
    candidates: tuple[DiscoveryCandidate, ...] = Field(max_length=100)


class ReviewDecision(StrEnum):
    SELECTED = "selected"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"


class EditorialDecision(StrEnum):
    KEEP = "keep"
    DROP = "drop"


class ReviewStatus(StrEnum):
    CLEAR = "clear"
    MANUAL = "manual"


class EndCueSpeakerRole(StrEnum):
    ANSWERER = "answerer"
    LISTENER = "listener"
    UNKNOWN = "unknown"


class EndCueFunction(StrEnum):
    SUBSTANTIVE_PAYOFF = "substantive_payoff"
    SAME_PROMISE_CLARIFICATION = "same_promise_clarification"
    RHETORICAL_CLOSURE = "rhetorical_closure"
    LISTENER_RESPONSE = "listener_response"
    NEW_TOPIC_OR_QUESTION = "new_topic_or_question"
    NOISE_OR_UNKNOWN = "noise_or_unknown"


class FollowingCueRelation(StrEnum):
    """The semantic relationship between a proposed end and its next source cue."""

    CONTINUES_SAME_UTTERANCE = "continues_same_utterance"
    REQUIRED_SAME_PROMISE = "required_same_promise"
    OPTIONAL_OR_REDUNDANT = "optional_or_redundant"
    NEW_TOPIC_OR_NOISE = "new_topic_or_noise"
    SOURCE_END = "source_end"


class ClipOrigin(StrEnum):
    DISCOVERY = "discovery"
    GLOBAL_REVIEW_RECOVERY = "global_review_recovery"


class CoverageDecisionValue(StrEnum):
    REPRESENTED = "represented"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"


class CoverageReasonCode(StrEnum):
    REPRESENTED_BY_CLIP = "represented_by_clip"
    NO_GENERAL_VALUE = "no_general_value"
    INCOMPLETE_TOPIC = "incomplete_topic"
    CANNOT_FORM_CONTINUOUS_CLIP = "cannot_form_continuous_clip"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    DUPLICATE_OF_OTHER_TOPIC = "duplicate_of_other_topic"
    RISK_REQUIRES_MANUAL_REVIEW = "risk_requires_manual_review"
    ASR_TOO_UNCERTAIN = "asr_too_uncertain"


class BoundaryAlternativeCompleteness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class BoundaryAlternativeAudit(BaseModel):
    """Agent-authored semantic challenge to a rejected ideal range.

    Python validates only cue existence, duration and relation to the attempted
    range.  Whether the alternative actually fulfils its stated promise remains
    an Agent judgment, recorded so a rejection cannot silently skip a viable
    shorter, extended or re-bounded continuous clip.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    viewer_promise: BoundedText = Field(max_length=200)
    completeness: BoundaryAlternativeCompleteness
    reason: BoundedText = Field(max_length=400)


class ScoreDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    standalone: int = Field(ge=0, le=20)
    general_value: int = Field(ge=0, le=20)
    interest: int = Field(ge=0, le=20)
    completeness: int = Field(ge=0, le=20)
    evidence: int = Field(ge=0, le=10)
    edit_cleanliness: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return (
            self.standalone
            + self.general_value
            + self.interest
            + self.completeness
            + self.evidence
            + self.edit_cleanliness
        )


class GlobalReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    global_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=30)


class GlobalReviewStatistics(BaseModel):
    """Deterministic final counts; the Agent never authors these values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    discovery_candidate_count: int = Field(ge=0)
    globally_recovered_clip_count: int = Field(ge=0)
    kept_clip_count: int = Field(ge=0)
    selected_clip_count: int = Field(ge=0)
    manual_review_clip_count: int = Field(ge=0)
    rejected_candidate_group_count: int = Field(ge=0)
    rejected_clip_count: int = Field(ge=0)
    rejected_topic_count: int = Field(ge=0)
    global_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=60)


class GlobalReviewClip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: SafeIdentifier
    source_candidate_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=30)
    source_topic_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    origin: ClipOrigin
    editorial_decision: EditorialDecision
    review_status: ReviewStatus
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    parent_topic: BoundedText = Field(max_length=160)
    viewer_promise: BoundedText = Field(max_length=200)
    title: BoundedText = Field(max_length=40)
    content_type: SafeIdentifier
    hook: BoundedText = Field(max_length=160)
    payoff: BoundedText = Field(max_length=240)
    source_opening_quote: BoundedText = Field(max_length=400)
    source_opening_promise: BoundedText = Field(max_length=240)
    viewer_promise_matches_source_opening: bool
    source_closing_quote: BoundedText = Field(max_length=400)
    end_cue_speaker_role: EndCueSpeakerRole
    end_cue_function: EndCueFunction
    following_cue_id: int | None = Field(default=None, ge=1)
    following_cue_quote: str | None = Field(default=None, min_length=1, max_length=400)
    following_cue_relation: FollowingCueRelation
    end_boundary_reason: BoundedText = Field(max_length=400)
    opening_relevance: OpeningRelevance
    ending_complete: bool
    first_complete_payoff_cue_id: int = Field(ge=1)
    minimum_duration_extension_cue_ids: tuple[int, ...] = Field(max_length=80)
    boundary_compactness: BoundaryCompactness
    source_fidelity: SourceFidelity
    source_fidelity_notes: BoundedText = Field(max_length=400)
    topic_core_start_cue_id: int = Field(ge=1)
    topic_core_end_cue_id: int = Field(ge=1)
    irrelevant_intro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    irrelevant_outro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    quality_flags: tuple[QualityFlag, ...] = Field(default_factory=tuple, max_length=12)
    score_dimensions: ScoreDimensions
    risks: tuple[RiskAssessment, ...] = Field(default_factory=tuple, max_length=12)
    review_reason: BoundedText = Field(max_length=400)


class RejectedCandidateGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    topic_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=30)
    reason_code: CoverageReasonCode
    reason: BoundedText = Field(max_length=400)
    duplicate_of_clip_id: SafeIdentifier | None = None
    duplicate_of_topic_id: SafeIdentifier | None = None
    ideal_start_cue_id: int | None = Field(default=None, ge=1)
    ideal_end_cue_id: int | None = Field(default=None, ge=1)
    model_claimed_duration_sec: float | None = Field(default=None, ge=0, le=86_400)
    boundary_alternatives: tuple[BoundaryAlternativeAudit, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    risks: tuple[RiskAssessment, ...] = Field(default_factory=tuple, max_length=12)


class CoverageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic_id: SafeIdentifier
    decision: CoverageDecisionValue
    clip_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=30)
    ideal_start_cue_id: int | None = Field(default=None, ge=1)
    ideal_end_cue_id: int | None = Field(default=None, ge=1)
    model_claimed_duration_sec: float | None = Field(default=None, ge=0, le=86_400)
    boundary_alternatives: tuple[BoundaryAlternativeAudit, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    reason_code: CoverageReasonCode
    reason: BoundedText = Field(max_length=400)
    duplicate_of_clip_id: SafeIdentifier | None = None
    duplicate_of_topic_id: SafeIdentifier | None = None


class ValidatedCoverageDecision(CoverageDecision):
    """Coverage audit enriched exclusively from deterministic Discovery facts."""

    topic_summary: BoundedText = Field(max_length=240)
    value_density: Literal["medium", "high"]
    actual_start_time_ms: int | None = Field(default=None, ge=0)
    actual_end_time_ms: int | None = Field(default=None, ge=0)
    actual_duration_sec: float | None = Field(default=None, ge=0, le=86_400)


class GlobalReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    review_summary: GlobalReviewSummary
    clips: tuple[GlobalReviewClip, ...] = Field(max_length=100)
    rejected_candidates: tuple[RejectedCandidateGroup, ...] = Field(max_length=100)
    coverage_decisions: tuple[CoverageDecision, ...] = Field(max_length=200)
    coverage_notes: tuple[str, ...] = Field(max_length=50)


class BoundaryRefinementItem(BaseModel):
    """A score-neutral source-boundary patch for one reviewed clip."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: SafeIdentifier
    editorial_decision: Literal[EditorialDecision.KEEP]
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    viewer_promise: BoundedText = Field(max_length=200)
    title: BoundedText = Field(max_length=40)
    hook: BoundedText = Field(max_length=160)
    payoff: BoundedText = Field(max_length=240)
    source_opening_quote: BoundedText = Field(max_length=400)
    source_opening_promise: BoundedText = Field(max_length=240)
    viewer_promise_matches_source_opening: bool
    source_closing_quote: BoundedText = Field(max_length=400)
    end_cue_speaker_role: EndCueSpeakerRole
    end_cue_function: EndCueFunction
    following_cue_id: int | None = Field(default=None, ge=1)
    following_cue_quote: str | None = Field(default=None, min_length=1, max_length=400)
    following_cue_relation: FollowingCueRelation
    end_boundary_reason: BoundedText = Field(max_length=400)
    opening_relevance: OpeningRelevance
    ending_complete: bool
    first_complete_payoff_cue_id: int = Field(ge=1)
    minimum_duration_extension_cue_ids: tuple[int, ...] = Field(max_length=80)
    boundary_compactness: BoundaryCompactness
    source_fidelity: SourceFidelity
    source_fidelity_notes: BoundedText = Field(max_length=400)
    topic_core_start_cue_id: int = Field(ge=1)
    topic_core_end_cue_id: int = Field(ge=1)
    irrelevant_intro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    irrelevant_outro_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    quality_flags: tuple[QualityFlag, ...] = Field(default_factory=tuple, max_length=12)
    review_reason: BoundedText = Field(max_length=400)


class BoundaryRefinementOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clips: tuple[BoundaryRefinementItem, ...] = Field(max_length=100)


class SemanticInputMode(StrEnum):
    FULL_CONTEXT = "full_context"
    FALLBACK = "fallback"
    WINDOWED = "windowed"
    BOUNDARY_BRIDGE = "boundary_bridge"


class SemanticTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> SemanticTimeRange:
        if self.end_ms <= self.start_ms:
            raise ValueError("semantic time range is reversed or empty")
        return self


class SemanticInputUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    unit_id: SafeIdentifier
    source_range: CueRange
    cues: tuple[SemanticCue, ...] = Field(min_length=1)
    estimated_tokens: int = Field(ge=1)
    context_range_ms: SemanticTimeRange | None = None
    ownership_range_ms: SemanticTimeRange | None = None
    logical_windows_ms: tuple[SemanticTimeRange, ...] = Field(default_factory=tuple, max_length=12)
    bridge_boundary_ms: int | None = Field(default=None, ge=0)
    triggering_boundary_topics: tuple[BoundaryTopicReport, ...] = Field(
        default_factory=tuple,
        max_length=20,
    )


class SemanticInputPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    mode: SemanticInputMode
    tokenizer_name: str
    context_window_tokens: int
    budget_ratio: float
    prompt_tokens: int
    transcript_tokens: int
    output_reserve_tokens: int
    safety_margin_tokens: int
    budget_tokens: int
    units: tuple[SemanticInputUnit, ...] = Field(min_length=1)


class StructuredStageResult(Protocol):
    output: BaseModel


@dataclass(frozen=True, slots=True)
class ValidatedGlobalClip:
    clip: GlobalReviewClip
    decision: ReviewDecision
    start_ms: int
    end_ms: int
    duration_ms: int
    final_score: int
    validation_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedGlobalReview:
    selected: tuple[ValidatedGlobalClip, ...]
    manual_review: tuple[ValidatedGlobalClip, ...]
    rejected: tuple[ValidatedGlobalClip, ...]
    rejected_candidates: tuple[RejectedCandidateGroup, ...]
    coverage_decisions: tuple[ValidatedCoverageDecision, ...]
    global_review_summary: GlobalReviewStatistics
    validation_notes: tuple[str, ...]


@dataclass(slots=True)
class _ContextRequest:
    candidate_ids: list[str]
    topic_ids: list[str]
    parent_topics: list[str]
    lower_ms: int
    upper_ms: int


class TokenEstimator:
    def __init__(self, encoding_name: str) -> None:
        try:
            self._encoding = tiktoken.get_encoding(encoding_name)
        except (KeyError, ValueError) as exc:
            raise ValueError("configured tokenizer is not installed") from exc
        self.name = encoding_name

    def count(self, value: str) -> int:
        return len(self._encoding.encode(value, disallowed_special=()))


def transcript_cues(transcript: TranscriptDocument) -> tuple[SemanticCue, ...]:
    return tuple(
        SemanticCue(
            cue_id=index,
            segment_id=segment.segment_id,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            original_text=segment.text,
        )
        for index, segment in enumerate(transcript.segments, start=1)
    )


def plan_semantic_input(
    transcript: TranscriptDocument,
    *,
    prompt: str,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator | None = None,
) -> SemanticInputPlan:
    cues = transcript_cues(transcript)
    if not cues:
        raise ValueError("semantic global clipping requires timestamped transcript cues")
    resolved_estimator = estimator or TokenEstimator(config.tokenizer_name)
    prompt_tokens = resolved_estimator.count(prompt)
    transcript_payload = _cues_payload(cues)
    transcript_tokens = resolved_estimator.count(transcript_payload)
    budget_tokens = int(config.model_context_tokens * config.full_context_budget_ratio)
    full_total = (
        prompt_tokens
        + transcript_tokens
        + config.output_reserve_tokens
        + config.safety_margin_tokens
    )
    units: tuple[SemanticInputUnit, ...]
    if full_total <= budget_tokens:
        units = (
            SemanticInputUnit(
                unit_id="full_context",
                source_range=CueRange(
                    start_cue_id=cues[0].cue_id,
                    end_cue_id=cues[-1].cue_id,
                ),
                cues=cues,
                estimated_tokens=prompt_tokens + transcript_tokens,
            ),
        )
        mode = SemanticInputMode.FULL_CONTEXT
    else:
        per_unit_budget = (
            budget_tokens
            - prompt_tokens
            - config.output_reserve_tokens
            - config.safety_margin_tokens
        )
        if per_unit_budget <= 0:
            raise ValueError("semantic global prompt leaves no fallback transcript budget")
        units = _fallback_units(
            cues,
            config=config,
            estimator=resolved_estimator,
            transcript_token_budget=per_unit_budget,
            prompt_tokens=prompt_tokens,
        )
        mode = SemanticInputMode.FALLBACK
    return SemanticInputPlan(
        mode=mode,
        tokenizer_name=resolved_estimator.name,
        context_window_tokens=config.model_context_tokens,
        budget_ratio=config.full_context_budget_ratio,
        prompt_tokens=prompt_tokens,
        transcript_tokens=transcript_tokens,
        output_reserve_tokens=config.output_reserve_tokens,
        safety_margin_tokens=config.safety_margin_tokens,
        budget_tokens=budget_tokens,
        units=units,
    )


def plan_semantic_windowed_input(
    transcript: TranscriptDocument,
    *,
    prompt: str,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator | None = None,
) -> SemanticInputPlan:
    """Plan bounded rolling semantic windows regardless of full-context capacity.

    The overlap is transport context only.  It never implies semantic identity,
    duplicate removal or clip merging.  Those decisions remain with Global Review.
    """

    cues = transcript_cues(transcript)
    if not cues:
        raise ValueError("semantic windowed clipping requires timestamped transcript cues")
    resolved_estimator = estimator or TokenEstimator(config.tokenizer_name)
    prompt_tokens = resolved_estimator.count(prompt)
    transcript_tokens = resolved_estimator.count(_cues_payload(cues))
    budget_tokens = int(config.model_context_tokens * config.full_context_budget_ratio)
    per_unit_budget = (
        budget_tokens - prompt_tokens - config.output_reserve_tokens - config.safety_margin_tokens
    )
    if per_unit_budget <= 0:
        raise ValueError("semantic window prompt leaves no transcript budget")
    units = _rolling_window_units(
        cues,
        source_duration_ms=transcript.source_duration_ms,
        config=config,
        estimator=resolved_estimator,
        transcript_token_budget=per_unit_budget,
        prompt_tokens=prompt_tokens,
    )
    return SemanticInputPlan(
        mode=SemanticInputMode.WINDOWED,
        tokenizer_name=resolved_estimator.name,
        context_window_tokens=config.model_context_tokens,
        budget_ratio=config.full_context_budget_ratio,
        prompt_tokens=prompt_tokens,
        transcript_tokens=transcript_tokens,
        output_reserve_tokens=config.output_reserve_tokens,
        safety_margin_tokens=config.safety_margin_tokens,
        budget_tokens=budget_tokens,
        units=units,
    )


def plan_boundary_bridge_units(
    transcript: TranscriptDocument,
    *,
    input_plan: SemanticInputPlan,
    discovery_outputs: tuple[DiscoveryOutput, ...],
    config: SemanticGlobalConfig,
    estimator: TokenEstimator | None = None,
) -> tuple[SemanticInputUnit, ...]:
    """Create a fixed adjacent-window union for each reported open batch edge."""

    if input_plan.mode != SemanticInputMode.WINDOWED:
        return ()
    if len(input_plan.units) != len(discovery_outputs):
        raise ValueError("window Discovery outputs do not match the planned batches")
    cues = transcript_cues(transcript)
    resolved_estimator = estimator or TokenEstimator(config.tokenizer_name)
    transcript_budget = (
        input_plan.budget_tokens
        - input_plan.prompt_tokens
        - input_plan.output_reserve_tokens
        - input_plan.safety_margin_tokens
    )
    bridges: list[SemanticInputUnit] = []
    for previous_unit, current_unit, previous_output, current_output in zip(
        input_plan.units[:-1],
        input_plan.units[1:],
        discovery_outputs[:-1],
        discovery_outputs[1:],
        strict=True,
    ):
        if not previous_unit.logical_windows_ms or not current_unit.logical_windows_ms:
            raise ValueError("window batch lacks its logical-window audit")
        if current_unit.ownership_range_ms is None:
            raise ValueError("window batch lacks its ownership interval")
        triggering_reports = (
            *_transport_risk_boundary_reports(
                unit=previous_unit,
                output=previous_output,
                side=BoundarySide.RIGHT,
                config=config,
            ),
            *_transport_risk_boundary_reports(
                unit=current_unit,
                output=current_output,
                side=BoundarySide.LEFT,
                config=config,
            ),
        )
        if not triggering_reports:
            continue
        left_window = previous_unit.logical_windows_ms[-1]
        right_window = current_unit.logical_windows_ms[0]
        boundary_ms = current_unit.ownership_range_ms.start_ms
        context_start_ms = left_window.start_ms
        context_end_ms = right_window.end_ms
        selected = _cues_for_time_range(
            cues,
            start_ms=context_start_ms,
            end_ms=context_end_ms,
        )
        unit_tokens = resolved_estimator.count(_cues_payload(selected))
        if unit_tokens > transcript_budget:
            raise ValueError("semantic boundary bridge exceeds the transcript token budget")
        bridges.append(
            SemanticInputUnit(
                unit_id=f"bridge_{len(bridges) + 1:03d}",
                source_range=CueRange(
                    start_cue_id=selected[0].cue_id,
                    end_cue_id=selected[-1].cue_id,
                ),
                cues=selected,
                estimated_tokens=input_plan.prompt_tokens + unit_tokens,
                context_range_ms=SemanticTimeRange(
                    start_ms=context_start_ms,
                    end_ms=context_end_ms,
                ),
                logical_windows_ms=(left_window, right_window),
                bridge_boundary_ms=boundary_ms,
                triggering_boundary_topics=triggering_reports,
            )
        )
    return tuple(bridges)


def _transport_risk_boundary_reports(
    *,
    unit: SemanticInputUnit,
    output: DiscoveryOutput,
    side: BoundarySide,
    config: SemanticGlobalConfig,
) -> tuple[BoundaryTopicReport, ...]:
    """Require Agent evidence that an open topic can outgrow ordinary batch lookahead."""

    ownership = unit.ownership_range_ms
    if ownership is None:
        return ()
    cue_map = {cue.cue_id: cue for cue in unit.cues}
    reports: list[BoundaryTopicReport] = []
    for report in output.boundary_topics:
        if report.side != side or not report.continuation_expected:
            continue
        evidence_ids = set(report.evidence_cue_ids)
        topics = tuple(
            topic
            for topic in output.topic_units
            if topic.value_density in {"medium", "high"}
            and any(topic.start_cue_id <= cue_id <= topic.end_cue_id for cue_id in evidence_ids)
        )
        if side == BoundarySide.RIGHT:
            at_risk = any(
                cue_map[topic.start_cue_id].start_ms < ownership.end_ms for topic in topics
            )
        else:
            previous_context_end_ms = ownership.start_ms + config.window_overlap_ms
            at_risk = any(
                cue_map[topic.end_cue_id].end_ms > previous_context_end_ms for topic in topics
            )
        if at_risk:
            reports.append(report)
    return tuple(reports)


def validate_discovery_output(
    output: DiscoveryOutput,
    *,
    unit: SemanticInputUnit,
    config: SemanticGlobalConfig,
) -> DiscoveryOutput:
    cue_map = {cue.cue_id: cue for cue in unit.cues}
    errors: list[str] = []
    expected_range = (unit.source_range.start_cue_id, unit.source_range.end_cue_id)
    actual_range = (output.source_range.start_cue_id, output.source_range.end_cue_id)
    if actual_range != expected_range:
        errors.append(
            "Discovery source range differs from the supplied input unit: "
            f"expected={expected_range}, actual={actual_range}; copy expected exactly"
        )
    topic_ids = [topic.topic_id for topic in output.topic_units]
    candidate_ids = [candidate.candidate_id for candidate in output.candidates]
    if len(topic_ids) != len(set(topic_ids)) or len(candidate_ids) != len(set(candidate_ids)):
        errors.append("Discovery IDs must be unique within an input unit")
    if not output.topic_units:
        errors.append("Discovery must return a complete non-empty topic map")
    ordered_topics = sorted(
        output.topic_units,
        key=lambda value: (value.start_cue_id, value.end_cue_id, value.topic_id),
    )
    if [value.topic_id for value in output.topic_units] != [
        value.topic_id for value in ordered_topics
    ]:
        errors.append("Discovery topic map must be returned in chronological cue order")
    if ordered_topics and (
        ordered_topics[0].start_cue_id != unit.source_range.start_cue_id
        or ordered_topics[-1].end_cue_id != unit.source_range.end_cue_id
    ):
        errors.append("Discovery topic map must cover the full supplied source range")
    cue_gaps = [
        (previous.end_cue_id + 1, current.start_cue_id - 1)
        for previous, current in pairwise(ordered_topics)
        if current.start_cue_id > previous.end_cue_id + 1
    ]
    if cue_gaps:
        errors.append(f"Discovery topic map contains uncovered cue gaps: {cue_gaps}")
    cue_overlaps = [
        (current.start_cue_id, min(previous.end_cue_id, current.end_cue_id))
        for previous, current in pairwise(ordered_topics)
        if current.start_cue_id <= previous.end_cue_id
    ]
    if cue_overlaps:
        errors.append(f"Discovery topic map contains overlapping cue ranges: {cue_overlaps}")
    known_candidate_ids = set(candidate_ids)
    for boundary in output.boundary_topics:
        if any(cue_id not in cue_map for cue_id in boundary.evidence_cue_ids):
            errors.append("boundary topic evidence contains an unknown cue ID")
        if not set(boundary.related_candidate_ids).issubset(known_candidate_ids):
            errors.append("boundary topic references an unknown candidate")
    if output.starts_inside_open_topic and not any(
        value.side == BoundarySide.LEFT and value.continuation_expected
        for value in output.boundary_topics
    ):
        errors.append("open left edge requires a structured left boundary topic")
    if output.ends_inside_open_topic and not any(
        value.side == BoundarySide.RIGHT and value.continuation_expected
        for value in output.boundary_topics
    ):
        errors.append("open right edge requires a structured right boundary topic")
    referenced_candidate_ids: set[str] = set()
    for topic in output.topic_units:
        if unit.unit_id != "full_context" and not topic.topic_id.startswith(f"{unit.unit_id}_"):
            errors.append(f"{topic.topic_id}: topic ID lacks its input unit prefix")
        try:
            _validated_interval(topic.start_cue_id, topic.end_cue_id, cue_map)
        except ValueError as exc:
            errors.append(f"{topic.topic_id}: {exc}")
        if not set(topic.candidate_ids).issubset(known_candidate_ids):
            errors.append(f"{topic.topic_id}: references an unknown candidate")
        referenced_candidate_ids.update(topic.candidate_ids)
    if referenced_candidate_ids != known_candidate_ids:
        missing = sorted(known_candidate_ids - referenced_candidate_ids)
        errors.append(f"Discovery candidates lack a topic reference: {missing}")
    for candidate in output.candidates:
        if unit.unit_id != "full_context" and not candidate.candidate_id.startswith(
            f"{unit.unit_id}_"
        ):
            errors.append(f"{candidate.candidate_id}: candidate ID lacks its input unit prefix")
        try:
            start, end = _validated_interval(
                candidate.start_cue_id,
                candidate.end_cue_id,
                cue_map,
            )
        except ValueError as exc:
            errors.append(f"{candidate.candidate_id}: {exc}")
            continue
        duration = end.end_ms - start.start_ms
        if not config.minimum_duration_ms <= duration <= config.maximum_duration_ms:
            errors.append(
                f"{candidate.candidate_id}: duration {duration / 1_000:.3f}s is outside "
                "the runtime bounds"
            )
        if unit.ownership_range_ms is not None and not (
            unit.ownership_range_ms.start_ms <= start.start_ms < unit.ownership_range_ms.end_ms
        ):
            errors.append(
                f"{candidate.candidate_id}: start cue is outside the batch ownership interval"
            )
        if unit.bridge_boundary_ms is not None and not (
            start.start_ms < unit.bridge_boundary_ms < end.end_ms
        ):
            errors.append(
                f"{candidate.candidate_id}: boundary-bridge candidate must cross its boundary"
            )
        if len(candidate.evidence_cue_ids) != len(set(candidate.evidence_cue_ids)):
            errors.append(f"{candidate.candidate_id}: evidence cue IDs must be unique")
        if any(
            cue_id not in cue_map
            or cue_id < candidate.start_cue_id
            or cue_id > candidate.end_cue_id
            for cue_id in candidate.evidence_cue_ids
        ):
            errors.append(f"{candidate.candidate_id}: evidence must stay inside its interval")
        try:
            _validate_candidate_facts(candidate, cue_map=cue_map)
        except ValueError as exc:
            errors.append(f"{candidate.candidate_id}: {exc}")
        parent_topics = [
            topic for topic in output.topic_units if candidate.candidate_id in topic.candidate_ids
        ]
        ordered_parents = sorted(parent_topics, key=lambda value: value.start_cue_id)
        if not ordered_parents or not (
            ordered_parents[0].start_cue_id <= candidate.start_cue_id
            and candidate.end_cue_id <= ordered_parents[-1].end_cue_id
        ):
            errors.append(f"{candidate.candidate_id}: must stay inside its referencing topic span")
        elif any(
            current.start_cue_id != previous.end_cue_id + 1
            for previous, current in pairwise(ordered_parents)
        ):
            errors.append(
                f"{candidate.candidate_id}: referencing topics must form one continuous span"
            )
    if errors:
        raise ValueError("Discovery validation errors: " + " | ".join(dict.fromkeys(errors)))
    return output


def namespace_discovery_output(
    output: DiscoveryOutput,
    *,
    unit: SemanticInputUnit,
) -> tuple[DiscoveryOutput, tuple[str, ...]]:
    """Give transport-local Agent IDs a deterministic globally unique namespace.

    Identifier spelling has no editorial meaning.  Real models commonly return
    ``topic_001`` even when asked for a batch prefix; treating that as a semantic
    repair wastes a model call and can make an otherwise valid batch fail.  This
    normalization rewrites only IDs and their references, never cue boundaries,
    text, value judgments, risks or candidate decisions.
    """

    if unit.unit_id == "full_context":
        return _remove_impossible_topic_candidate_references(output)
    prefix = f"{unit.unit_id}_"
    topic_ids = {value.topic_id for value in output.topic_units}
    candidate_ids = {value.candidate_id for value in output.candidates}
    topic_map = {
        value: value if value.startswith(prefix) else f"{prefix}{value}" for value in topic_ids
    }
    candidate_map = {
        value: value if value.startswith(prefix) else f"{prefix}{value}" for value in candidate_ids
    }
    if len(set(topic_map.values())) != len(topic_map) or len(set(candidate_map.values())) != len(
        candidate_map
    ):
        raise ValueError("Discovery ID namespacing produced a collision")
    namespaced = any(key != value for key, value in (*topic_map.items(), *candidate_map.items()))
    normalized = (
        output.model_copy(
            update={
                "topic_units": tuple(
                    topic.model_copy(
                        update={
                            "topic_id": topic_map[topic.topic_id],
                            "candidate_ids": tuple(
                                candidate_map.get(value, value) for value in topic.candidate_ids
                            ),
                        }
                    )
                    for topic in output.topic_units
                ),
                "candidates": tuple(
                    candidate.model_copy(
                        update={"candidate_id": candidate_map[candidate.candidate_id]}
                    )
                    for candidate in output.candidates
                ),
                "boundary_topics": tuple(
                    boundary.model_copy(
                        update={
                            "related_candidate_ids": tuple(
                                candidate_map.get(value, value)
                                for value in boundary.related_candidate_ids
                            )
                        }
                    )
                    for boundary in output.boundary_topics
                ),
            }
        )
        if namespaced
        else output
    )
    normalized, reference_notes = _remove_impossible_topic_candidate_references(normalized)
    notes = (f"namespaced_discovery_ids:{unit.unit_id}",) if namespaced else ()
    return normalized, (*notes, *reference_notes)


def _remove_impossible_topic_candidate_references(
    output: DiscoveryOutput,
) -> tuple[DiscoveryOutput, tuple[str, ...]]:
    """Remove only candidate references whose cue intervals cannot intersect.

    This repairs deterministic relationship bookkeeping without inventing a
    semantic association. Unknown IDs remain untouched so validation still
    fails loudly, and Python never adds a candidate to a topic.
    """

    candidate_ranges = {
        candidate.candidate_id: (candidate.start_cue_id, candidate.end_cue_id)
        for candidate in output.candidates
    }
    notes: list[str] = []
    topics: list[DiscoveryTopicUnit] = []
    for topic in output.topic_units:
        kept: list[str] = []
        for candidate_id in topic.candidate_ids:
            interval = candidate_ranges.get(candidate_id)
            if interval is None:
                kept.append(candidate_id)
                continue
            if interval[1] < topic.start_cue_id or interval[0] > topic.end_cue_id:
                notes.append(
                    f"removed_nonoverlapping_candidate_reference:{topic.topic_id}:{candidate_id}"
                )
                continue
            kept.append(candidate_id)
        update: dict[str, object] = {"candidate_ids": tuple(kept)}
        if topic.candidate_status == CandidateStatus.FOUND and topic.candidate_ids and not kept:
            update.update(
                {
                    "candidate_status": CandidateStatus.NO_CANDIDATE,
                    "no_candidate_reason_code": (NoCandidateReasonCode.INVALID_REFERENCE_REMOVED),
                }
            )
            notes.append(f"normalized_empty_found_topic:{topic.topic_id}")
        topics.append(topic.model_copy(update=update))
    if not notes:
        return output, ()
    return output.model_copy(update={"topic_units": tuple(topics)}), tuple(notes)


def combine_discovery_outputs(
    outputs: tuple[DiscoveryOutput, ...],
    *,
    cues: tuple[SemanticCue, ...],
) -> dict[str, object]:
    """Build the semantic index consumed by Global Review.

    Discovery's complete response remains the persisted audit artifact.  Global
    Review also receives the original transcript, so repeating source quotes,
    prose boundary explanations and fields that it must independently re-audit
    wastes context without adding evidence.  Keep the complete topic map and
    every candidate's semantic identity/evidence/risk here, together with
    Python-authoritative time facts.  This is transport compaction only: it
    neither filters candidates nor changes any semantic disposition.
    """

    cue_map = {cue.cue_id: cue for cue in cues}
    candidate_ids: set[str] = set()
    topic_ids: set[str] = set()
    candidates: list[dict[str, object]] = []
    topics: list[dict[str, object]] = []
    for unit_index, output in enumerate(outputs, start=1):
        for candidate in output.candidates:
            if candidate.candidate_id in candidate_ids:
                raise ValueError("Discovery candidate IDs must be globally unique")
            candidate_ids.add(candidate.candidate_id)
            start, end = _validated_interval(
                candidate.start_cue_id,
                candidate.end_cue_id,
                cue_map,
            )
            candidates.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "parent_topic": candidate.parent_topic,
                    "viewer_promise": candidate.viewer_promise,
                    "content_type": candidate.content_type,
                    "start_cue_id": candidate.start_cue_id,
                    "end_cue_id": candidate.end_cue_id,
                    "hook": candidate.hook,
                    "payoff": candidate.payoff,
                    "evidence_cue_ids": list(candidate.evidence_cue_ids),
                    "opening_relevance": candidate.opening_relevance.value,
                    "quality_flags": [value.value for value in candidate.quality_flags],
                    "risks": [value.model_dump(mode="json") for value in candidate.risks],
                    "calculated_start_time_ms": start.start_ms,
                    "calculated_end_time_ms": end.end_ms,
                    "calculated_duration_sec": (end.end_ms - start.start_ms) / 1_000,
                }
            )
        for topic in output.topic_units:
            if topic.topic_id in topic_ids:
                raise ValueError("Discovery topic IDs must be globally unique")
            topic_ids.add(topic.topic_id)
            start, end = _validated_interval(topic.start_cue_id, topic.end_cue_id, cue_map)
            topic_payload: dict[str, object] = {
                "discovery_unit": unit_index,
                "topic_id": topic.topic_id,
                "start_cue_id": topic.start_cue_id,
                "end_cue_id": topic.end_cue_id,
                "summary": topic.summary,
                "value_density": topic.value_density,
                "candidate_ids": list(topic.candidate_ids),
                "topic_start_time_ms": start.start_ms,
                "topic_end_time_ms": end.end_ms,
                "topic_total_duration_sec": (end.end_ms - start.start_ms) / 1_000,
            }
            # Candidate disposition and its rejection rationale remain in the
            # complete persisted Discovery audit.  Global Review receives the
            # topic-to-candidate map but must independently decide coverage
            # from source evidence instead of anchoring on a fallible earlier
            # conclusion.
            topics.append(topic_payload)
    return {
        "input_units": [
            {
                "discovery_unit": unit_index,
                "source_range": output.source_range.model_dump(mode="json"),
                "starts_inside_open_topic": output.starts_inside_open_topic,
                "ends_inside_open_topic": output.ends_inside_open_topic,
                "boundary_topics": [
                    value.model_dump(mode="json") for value in output.boundary_topics
                ],
            }
            for unit_index, output in enumerate(outputs, start=1)
        ],
        "topic_units": topics,
        "candidates": candidates,
        "discovery_candidate_count": len(candidates),
    }


def build_global_review_payload(
    transcript: TranscriptDocument,
    *,
    input_plan: SemanticInputPlan,
    discovery_outputs: tuple[DiscoveryOutput, ...],
    config: SemanticGlobalConfig,
    prompt: str = "",
    estimator: TokenEstimator | None = None,
) -> dict[str, object]:
    cues = transcript_cues(transcript)
    discovery = combine_discovery_outputs(discovery_outputs, cues=cues)
    windowed_review = input_plan.mode == SemanticInputMode.WINDOWED
    if windowed_review:
        # Window Discovery persists a complete topic map for audit, but Global
        # Review is deliberately candidate scoped.  Shipping scores of
        # low/no-candidate transport topics makes the final editor spend its
        # context and output budget re-litigating Discovery instead of
        # comparing real candidate boundaries.  This is a deterministic
        # projection over Agent-authored status: it does not create, reject,
        # merge or score any semantic candidate.
        topic_units = discovery["topic_units"]
        if not isinstance(topic_units, list):
            raise ValueError("combined Discovery topic transport is invalid")
        discovery["topic_units"] = [
            topic
            for topic in topic_units
            if isinstance(topic, dict)
            if topic["candidate_ids"]
            or (str(topic["topic_id"]).startswith("bridge_") and topic["value_density"] == "high")
        ]
    semantic_evidence: dict[str, object] = {
        "cue_columns": list(GLOBAL_REVIEW_CUE_COLUMNS),
        "semantic_contexts": _global_semantic_contexts(
            cues,
            discovery_outputs=discovery_outputs,
            adjacent_cue_count=GLOBAL_REVIEW_ADJACENT_CONTEXT_CUES,
            candidate_context_ms=(
                GLOBAL_REVIEW_PREFERRED_CANDIDATE_CONTEXT_MS if windowed_review else 0
            ),
            include_topic_catalog=not windowed_review,
        ),
    }
    full_evidence: dict[str, object] = {
        "cue_columns": list(GLOBAL_REVIEW_CUE_COLUMNS),
        "full_transcript_rows": _global_cue_rows(cues),
    }
    # Put the authoritative source evidence before the fallible Discovery
    # index in serialized model transport.  Global Review must form its own
    # source-grounded judgment instead of anchoring on a prior no-candidate
    # explanation.  JSON object order has no effect on deterministic parsing.
    payload: dict[str, object] = {
        "schema_version": "2",
        "mode": GLOBAL_REVIEW_SEMANTIC_CONTEXT_MODE,
        "runtime": _runtime_payload(config),
        "evidence": semantic_evidence,
        "discovery": discovery,
    }
    if windowed_review:
        discovery["review_scope"] = "candidate_topics_and_boundary_bridges"
        # Candidate evidence is the only expandable transport guard in the
        # windowed Global Review package.  Keep every Agent-authored candidate,
        # linked topic and boundary bridge, then reduce only the extra context
        # symmetrically when the preferred 30 seconds narrowly exceeds the
        # configured model budget.  The 15-second floor remains sufficient for
        # the final editor to inspect whether a proposed opening/ending depends
        # on adjacent source material.  This is transport compaction, not a
        # semantic ranking, filtering or de-duplication rule.
        hard_budget = int(config.model_context_tokens * config.full_context_budget_ratio)
        for context_guard_ms in range(
            GLOBAL_REVIEW_PREFERRED_CANDIDATE_CONTEXT_MS,
            GLOBAL_REVIEW_MINIMUM_CANDIDATE_CONTEXT_MS - 1,
            -GLOBAL_REVIEW_CANDIDATE_CONTEXT_STEP_MS,
        ):
            payload["evidence"] = {
                "cue_columns": list(GLOBAL_REVIEW_CUE_COLUMNS),
                "candidate_context_guard_ms": context_guard_ms,
                "semantic_contexts": _global_semantic_contexts(
                    cues,
                    discovery_outputs=discovery_outputs,
                    adjacent_cue_count=GLOBAL_REVIEW_ADJACENT_CONTEXT_CUES,
                    candidate_context_ms=context_guard_ms,
                    include_topic_catalog=False,
                ),
            }
            if (
                _semantic_request_tokens(
                    prompt,
                    payload,
                    config=config,
                    estimator=estimator,
                )
                <= hard_budget
            ):
                return payload
        raise ValueError("Global Review semantic context package exceeds its token budget")
    if input_plan.mode == SemanticInputMode.FULL_CONTEXT:
        full_payload = {**payload, "mode": input_plan.mode.value, "evidence": full_evidence}
        full_request_tokens = _semantic_request_tokens(
            prompt,
            full_payload,
            config=config,
            estimator=estimator,
        )
        comfortable_full_budget = int(
            config.model_context_tokens
            * config.full_context_budget_ratio
            * GLOBAL_REVIEW_FULL_CONTEXT_SHARE
        )
        if full_request_tokens <= comfortable_full_budget:
            payload = full_payload
    request_tokens = _semantic_request_tokens(
        prompt,
        payload,
        config=config,
        estimator=estimator,
    )
    hard_budget = int(config.model_context_tokens * config.full_context_budget_ratio)
    if request_tokens > hard_budget:
        raise ValueError("Global Review semantic context package exceeds its token budget")
    return payload


def boundary_refinement_target_ids(output: GlobalReviewOutput) -> tuple[str, ...]:
    """Select clips whose own structured audit asks for a boundary re-check."""

    return tuple(
        clip.clip_id
        for clip in output.clips
        if clip.editorial_decision == EditorialDecision.KEEP
        and (clip.quality_flags or clip.opening_relevance != OpeningRelevance.DIRECT)
    )


def build_boundary_refinement_payload(
    transcript: TranscriptDocument,
    *,
    output: GlobalReviewOutput,
    config: SemanticGlobalConfig,
    context_guard_ms: int = 30_000,
) -> dict[str, object] | None:
    """Build one compact, score-neutral boundary audit for flagged kept clips."""

    target_ids = set(boundary_refinement_target_ids(output))
    if not target_ids:
        return None
    cues = transcript_cues(transcript)
    cue_map = {cue.cue_id: cue for cue in cues}
    targets: list[dict[str, object]] = []
    contexts: list[dict[str, object]] = []
    for clip in output.clips:
        if clip.clip_id not in target_ids:
            continue
        start, end = _validated_interval(clip.start_cue_id, clip.end_cue_id, cue_map)
        lower_ms = max(0, start.start_ms - context_guard_ms)
        upper_ms = min(transcript.source_duration_ms, end.end_ms + context_guard_ms)
        evidence = tuple(cue for cue in cues if cue.end_ms >= lower_ms and cue.start_ms <= upper_ms)
        target = clip.model_dump(mode="json")
        target.update(
            {
                "calculated_start_time_ms": start.start_ms,
                "calculated_end_time_ms": end.end_ms,
                "calculated_duration_sec": (end.end_ms - start.start_ms) / 1_000,
                "legal_end_cue_ids_from_current_start": [
                    cue.cue_id
                    for cue in evidence
                    if config.minimum_duration_ms
                    <= cue.end_ms - start.start_ms
                    <= config.maximum_duration_ms
                ],
                "legal_start_cue_ids_to_current_end": [
                    cue.cue_id
                    for cue in evidence
                    if config.minimum_duration_ms
                    <= end.end_ms - cue.start_ms
                    <= config.maximum_duration_ms
                ],
                "end_alternatives_from_current_start": [
                    {
                        "end_cue_id": cue.cue_id,
                        "duration_sec": (cue.end_ms - start.start_ms) / 1_000,
                        "end_quote": cue.original_text,
                        "following_cue_id": (
                            evidence[index + 1].cue_id if index + 1 < len(evidence) else None
                        ),
                        "following_quote": (
                            evidence[index + 1].original_text if index + 1 < len(evidence) else None
                        ),
                    }
                    for index, cue in enumerate(evidence)
                    if config.minimum_duration_ms
                    <= cue.end_ms - start.start_ms
                    <= config.maximum_duration_ms
                ],
            }
        )
        targets.append(target)
        contexts.append(
            {
                "context_id": f"boundary_{clip.clip_id}",
                "clip_id": clip.clip_id,
                "source_range": {
                    "start_cue_id": evidence[0].cue_id,
                    "end_cue_id": evidence[-1].cue_id,
                },
                "cue_rows": _global_cue_rows(evidence),
            }
        )
    return {
        "schema_version": "1",
        "runtime": _runtime_payload(config),
        "cue_columns": list(GLOBAL_REVIEW_CUE_COLUMNS),
        "clips": targets,
        "contexts": contexts,
    }


def apply_boundary_refinement(
    output: GlobalReviewOutput,
    refinement: BoundaryRefinementOutput,
) -> tuple[GlobalReviewOutput, tuple[str, ...]]:
    """Apply source-boundary patches without changing scores, risks or provenance."""

    expected = set(boundary_refinement_target_ids(output))
    actual = [item.clip_id for item in refinement.clips]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError(
            "Boundary refinement must return every target clip exactly once: "
            f"missing={sorted(expected - set(actual))}, unexpected={sorted(set(actual) - expected)}"
        )
    patch_map = {item.clip_id: item for item in refinement.clips}
    notes: list[str] = []
    clips: list[GlobalReviewClip] = []
    for clip in output.clips:
        item = patch_map.get(clip.clip_id)
        if item is None:
            clips.append(clip)
            continue
        update = item.model_dump(mode="python", exclude={"clip_id"})
        risk_cue_ids = {cue_id for risk in clip.risks for cue_id in risk.source_cue_ids}
        if any(cue_id < item.start_cue_id or cue_id > item.end_cue_id for cue_id in risk_cue_ids):
            clips.append(clip)
            notes.append(f"boundary_refinement_ignored_risk_evidence_loss:{clip.clip_id}")
            continue
        clips.append(clip.model_copy(update=update))
        if (clip.start_cue_id, clip.end_cue_id) != (item.start_cue_id, item.end_cue_id):
            notes.append(
                f"boundary_refined:{clip.clip_id}:{clip.start_cue_id}-{clip.end_cue_id}"
                f"->{item.start_cue_id}-{item.end_cue_id}"
            )
    return output.model_copy(update={"clips": tuple(clips)}), tuple(notes)


def semantic_request_tokens(
    prompt: str,
    payload: dict[str, object],
    *,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator | None = None,
) -> int:
    return _semantic_request_tokens(prompt, payload, config=config, estimator=estimator)


def _coverage_topic_ids(
    discovery_topics: dict[str, DiscoveryTopicUnit],
    *,
    input_mode: SemanticInputMode | None,
) -> set[str]:
    """Return semantic topics that require final coverage accounting.

    Windowed review is deliberately candidate-scoped.  A no-candidate bridge
    topic is added only when Discovery marked it high density; medium snippets
    used solely as transport context do not force Global Review to manufacture
    a disposition.  This selection uses Agent-authored topic facts, not text,
    overlap ratios or timing heuristics.
    """

    if input_mode != SemanticInputMode.WINDOWED:
        return {
            topic_id
            for topic_id, topic in discovery_topics.items()
            if topic.value_density in {"medium", "high"}
        }
    return {
        topic_id
        for topic_id, topic in discovery_topics.items()
        if topic.candidate_ids or (topic_id.startswith("bridge_") and topic.value_density == "high")
    }


def _normalize_global_review_output(
    output: GlobalReviewOutput,
    *,
    coverage_topic_ids: set[str],
) -> tuple[GlobalReviewOutput, tuple[str, ...]]:
    """Normalize deterministic coverage bookkeeping without changing clips.

    The Agent may repeat a topic row while revising its disposition, or retain
    bridge transport notes outside the candidate-scoped review contract.  The
    final semantic choice is taken from the strongest referenced kept result;
    Python only removes duplicate/out-of-scope rows and never creates a clip.
    """

    clip_map = {clip.clip_id: clip for clip in output.clips}
    chosen: dict[str, CoverageDecision] = {}
    notes: list[str] = []

    def priority(value: CoverageDecision) -> tuple[int, int]:
        referenced = [clip_map[item] for item in value.clip_ids if item in clip_map]
        kept = [item for item in referenced if item.editorial_decision == EditorialDecision.KEEP]
        manual = any(item.review_status == ReviewStatus.MANUAL for item in kept)
        if kept:
            return (3 if manual else 4, len(kept))
        return (1 if value.decision == CoverageDecisionValue.REJECTED else 2, 0)

    for decision in output.coverage_decisions:
        if decision.topic_id not in coverage_topic_ids:
            notes.append(f"coverage_out_of_scope_removed:{decision.topic_id}")
            continue
        current = chosen.get(decision.topic_id)
        if current is None:
            chosen[decision.topic_id] = decision
            continue
        if priority(decision) > priority(current):
            chosen[decision.topic_id] = decision
        notes.append(f"duplicate_coverage_removed:{decision.topic_id}")
    normalized_values: list[CoverageDecision] = []
    for topic_id in sorted(chosen):
        decision = chosen[topic_id]
        referenced = [clip_map[item] for item in decision.clip_ids if item in clip_map]
        kept = [item for item in referenced if item.editorial_decision == EditorialDecision.KEEP]
        if kept and any(item.review_status == ReviewStatus.MANUAL for item in kept):
            if decision.decision != CoverageDecisionValue.MANUAL_REVIEW:
                decision = decision.model_copy(
                    update={
                        "decision": CoverageDecisionValue.MANUAL_REVIEW,
                        "reason_code": CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW,
                    }
                )
                notes.append(f"coverage_status_aligned_to_manual:{topic_id}")
        elif kept and decision.decision != CoverageDecisionValue.REPRESENTED:
            decision = decision.model_copy(
                update={
                    "decision": CoverageDecisionValue.REPRESENTED,
                    "reason_code": CoverageReasonCode.REPRESENTED_BY_CLIP,
                }
            )
            notes.append(f"coverage_status_aligned_to_represented:{topic_id}")
        normalized_values.append(decision)
    normalized = tuple(normalized_values)
    return output.model_copy(update={"coverage_decisions": normalized}), tuple(dict.fromkeys(notes))


def validate_global_review(
    output: GlobalReviewOutput,
    *,
    transcript: TranscriptDocument,
    discovery_outputs: tuple[DiscoveryOutput, ...],
    config: SemanticGlobalConfig,
    input_mode: SemanticInputMode | None = None,
) -> ValidatedGlobalReview:
    cues = transcript_cues(transcript)
    cue_map = {cue.cue_id: cue for cue in cues}
    discovery_candidates = {
        candidate.candidate_id: candidate
        for discovery in discovery_outputs
        for candidate in discovery.candidates
    }
    discovery_ids = set(discovery_candidates)
    discovery_topics = {
        topic.topic_id: topic for discovery in discovery_outputs for topic in discovery.topic_units
    }
    expected_topic_count = sum(len(value.topic_units) for value in discovery_outputs)
    if len(discovery_topics) != expected_topic_count:
        raise ValueError("Discovery topic IDs must be globally unique before Global Review")
    coverage_topic_ids = _coverage_topic_ids(discovery_topics, input_mode=input_mode)
    output, output_normalizations = _normalize_global_review_output(
        output,
        coverage_topic_ids=coverage_topic_ids,
    )
    clip_ids = [clip.clip_id for clip in output.clips]
    if len(clip_ids) != len(set(clip_ids)):
        raise ValueError("Global Review clip IDs must be unique")
    clip_map = {clip.clip_id: clip for clip in output.clips}
    preflight_errors: list[str] = []
    try:
        _validate_global_summary(output, discovery_ids=discovery_ids)
    except ValueError as exc:
        preflight_errors.append(f"summary: {exc}")
    try:
        _validate_coverage_decisions(
            output.coverage_decisions,
            discovery_topics=discovery_topics,
            expected_topic_ids=coverage_topic_ids,
            clip_map=clip_map,
            cue_map=cue_map,
            config=config,
        )
    except ValueError as exc:
        preflight_errors.append(f"coverage: {exc}")
    try:
        _validate_rejected_candidates(
            output.rejected_candidates,
            discovery_candidates=discovery_candidates,
            discovery_topics=discovery_topics,
            clip_map=clip_map,
            cue_map=cue_map,
            config=config,
        )
    except ValueError as exc:
        preflight_errors.append(f"rejected_candidates: {exc}")
    for clip in output.clips:
        try:
            if any(value not in discovery_ids for value in clip.source_candidate_ids):
                raise ValueError("references an unknown Discovery candidate")
            if any(value not in discovery_topics for value in clip.source_topic_ids):
                raise ValueError("references an unknown Discovery topic")
            if clip.origin == ClipOrigin.DISCOVERY and not clip.source_candidate_ids:
                raise ValueError("Discovery-origin clip requires a source candidate")
            start, end = _validated_interval(clip.start_cue_id, clip.end_cue_id, cue_map)
            duration_ms = end.end_ms - start.start_ms
            if (
                clip.editorial_decision == EditorialDecision.KEEP
                and not config.minimum_duration_ms <= duration_ms <= config.maximum_duration_ms
            ):
                raise ValueError(f"duration {duration_ms / 1_000:.3f}s is outside runtime bounds")
            _validate_clip_quality(clip, cue_map=cue_map, config=config)
            _validate_risk_cues(
                clip.risks,
                cue_map=cue_map,
                start_cue_id=clip.start_cue_id,
                end_cue_id=clip.end_cue_id,
            )
        except ValueError as exc:
            preflight_errors.append(f"clip_id={clip.clip_id}: {exc}")
    if preflight_errors:
        raise ValueError(
            "Global Review validation errors: " + " | ".join(dict.fromkeys(preflight_errors))
        )
    selected: list[ValidatedGlobalClip] = []
    manual: list[ValidatedGlobalClip] = []
    rejected: list[ValidatedGlobalClip] = []
    global_notes: list[str] = list(output_normalizations)
    for clip in output.clips:
        if any(value not in discovery_ids for value in clip.source_candidate_ids):
            raise ValueError("Global Review references an unknown Discovery candidate")
        if any(value not in discovery_topics for value in clip.source_topic_ids):
            raise ValueError("Global Review references an unknown Discovery topic")
        if clip.origin == ClipOrigin.DISCOVERY and not clip.source_candidate_ids:
            raise ValueError("Discovery-origin Global Review clip requires a source candidate")
        start, end = _validated_interval(clip.start_cue_id, clip.end_cue_id, cue_map)
        duration_ms = end.end_ms - start.start_ms
        if (
            clip.editorial_decision == EditorialDecision.KEEP
            and not config.minimum_duration_ms <= duration_ms <= config.maximum_duration_ms
        ):
            raise ValueError("Global Review clip duration is outside the runtime bounds")
        _validate_clip_quality(clip, cue_map=cue_map, config=config)
        final_score = clip.score_dimensions.total
        notes: list[str] = []
        deduplicated_clip_risks = _merge_risks(clip.risks)
        if deduplicated_clip_risks != clip.risks:
            notes.append("duplicate_risks_removed")
        discovery_risks = _discovery_risks_for_clip(
            clip,
            discovery_candidates=discovery_candidates,
        )
        risks = _merge_risks(deduplicated_clip_risks, discovery_risks)
        if len(deduplicated_clip_risks) + len(discovery_risks) > len(risks) and (
            "duplicate_risks_removed" not in notes
        ):
            notes.append("duplicate_risks_removed")
        if risks != deduplicated_clip_risks:
            notes.append("risks_propagated_from_discovery")
        _validate_risk_cues(
            risks,
            cue_map=cue_map,
            start_cue_id=clip.start_cue_id,
            end_cue_id=clip.end_cue_id,
        )
        decision = _raw_review_decision(clip)
        if (
            any(value in MANUAL_REVIEW_QUALITY_FLAGS for value in clip.quality_flags)
            and decision == ReviewDecision.SELECTED
        ):
            decision = ReviewDecision.MANUAL_REVIEW
            notes.append("quality_gate_changed_selected_to_manual_review")
        if (
            any(_risk_requires_manual(value) for value in risks)
            and decision == ReviewDecision.SELECTED
        ):
            decision = ReviewDecision.MANUAL_REVIEW
            notes.append("risk_gate_changed_selected_to_manual_review")
        if final_score <= config.score_threshold_exclusive and decision in {
            ReviewDecision.SELECTED,
            ReviewDecision.MANUAL_REVIEW,
        }:
            decision = ReviewDecision.REJECTED
            notes.append("exclusive_score_gate_changed_kept_to_rejected")
        validated = ValidatedGlobalClip(
            clip=clip.model_copy(update={"risks": risks}),
            decision=decision,
            start_ms=start.start_ms,
            end_ms=end.end_ms,
            duration_ms=duration_ms,
            final_score=final_score,
            validation_notes=tuple(notes),
        )
        if decision == ReviewDecision.SELECTED:
            selected.append(validated)
        elif decision == ReviewDecision.MANUAL_REVIEW:
            manual.append(validated)
        else:
            rejected.append(validated)
        global_notes.extend(f"{clip.clip_id}:{note}" for note in notes)
    selected.sort(key=lambda item: (-item.final_score, item.start_ms, item.clip.clip_id))
    overflow = selected[config.max_clips :]
    selected = selected[: config.max_clips]
    for item in overflow:
        note = "top_n_ceiling_changed_selected_to_rejected"
        rejected.append(
            ValidatedGlobalClip(
                clip=item.clip,
                decision=ReviewDecision.REJECTED,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                duration_ms=item.duration_ms,
                final_score=item.final_score,
                validation_notes=(*item.validation_notes, note),
            )
        )
        global_notes.append(f"{item.clip.clip_id}:{note}")
    manual.sort(key=lambda item: (item.start_ms, item.clip.clip_id))
    rejected.sort(key=lambda item: (item.start_ms, item.clip.clip_id))
    kept = (*selected, *manual)
    validated_coverage = tuple(
        _validated_coverage_decision(
            decision,
            topic=discovery_topics[decision.topic_id],
            cue_map=cue_map,
        )
        for decision in output.coverage_decisions
    )
    statistics = GlobalReviewStatistics(
        discovery_candidate_count=len(discovery_ids),
        globally_recovered_clip_count=sum(
            value.clip.origin == ClipOrigin.GLOBAL_REVIEW_RECOVERY for value in kept
        ),
        kept_clip_count=len(kept),
        selected_clip_count=len(selected),
        manual_review_clip_count=len(manual),
        rejected_candidate_group_count=len(output.rejected_candidates),
        rejected_clip_count=len(rejected),
        rejected_topic_count=sum(
            value.decision == CoverageDecisionValue.REJECTED for value in output.coverage_decisions
        ),
        global_notes=(*output.review_summary.global_notes, *global_notes)[-60:],
    )
    return ValidatedGlobalReview(
        selected=tuple(selected),
        manual_review=tuple(manual),
        rejected=tuple(rejected),
        rejected_candidates=output.rejected_candidates,
        coverage_decisions=validated_coverage,
        global_review_summary=statistics,
        validation_notes=tuple(global_notes),
    )


def _validated_coverage_decision(
    decision: CoverageDecision,
    *,
    topic: DiscoveryTopicUnit,
    cue_map: dict[int, SemanticCue],
) -> ValidatedCoverageDecision:
    if topic.value_density not in {"medium", "high"}:
        raise ValueError("validated coverage can only enrich medium/high topics")
    actual_start_time_ms: int | None = None
    actual_end_time_ms: int | None = None
    actual_duration_sec: float | None = None
    if decision.ideal_start_cue_id is not None and decision.ideal_end_cue_id is not None:
        start, end = _validated_interval(
            decision.ideal_start_cue_id,
            decision.ideal_end_cue_id,
            cue_map,
        )
        actual_start_time_ms = start.start_ms
        actual_end_time_ms = end.end_ms
        actual_duration_sec = (end.end_ms - start.start_ms) / 1_000
    return ValidatedCoverageDecision.model_validate(
        {
            **decision.model_dump(mode="python"),
            "topic_summary": topic.summary,
            "value_density": topic.value_density,
            "actual_start_time_ms": actual_start_time_ms,
            "actual_end_time_ms": actual_end_time_ms,
            "actual_duration_sec": actual_duration_sec,
        }
    )


def _validate_structured_reason_fields(
    *,
    reason_code: CoverageReasonCode,
    ideal_start_cue_id: int | None,
    ideal_end_cue_id: int | None,
    duplicate_of_clip_id: str | None,
    duplicate_of_topic_id: str | None,
) -> None:
    if reason_code in {
        CoverageReasonCode.INCOMPLETE_TOPIC,
        CoverageReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
        CoverageReasonCode.DURATION_TOO_SHORT,
        CoverageReasonCode.DURATION_TOO_LONG,
    } and (ideal_start_cue_id is None or ideal_end_cue_id is None):
        raise ValueError("boundary-audited reason requires ideal cue boundaries")
    if reason_code == CoverageReasonCode.DUPLICATE_OF_OTHER_TOPIC and not (
        duplicate_of_clip_id or duplicate_of_topic_id
    ):
        raise ValueError("duplicate reason requires a target clip or topic")


def _validate_candidate_facts(
    candidate: DiscoveryCandidate,
    *,
    cue_map: dict[int, SemanticCue],
) -> None:
    _validated_interval(candidate.topic_core_start_cue_id, candidate.topic_core_end_cue_id, cue_map)
    if not (
        candidate.start_cue_id
        <= candidate.topic_core_start_cue_id
        <= candidate.topic_core_end_cue_id
        <= candidate.end_cue_id
    ):
        raise ValueError("Discovery topic core must stay inside its candidate interval")
    _validate_source_opening_quote(
        candidate.source_opening_quote,
        start_cue_id=candidate.start_cue_id,
        cue_map=cue_map,
    )
    _validate_source_closing_quote(
        candidate.source_closing_quote,
        end_cue_id=candidate.end_cue_id,
        cue_map=cue_map,
    )
    if not (
        candidate.topic_core_start_cue_id
        <= candidate.first_complete_payoff_cue_id
        <= candidate.topic_core_end_cue_id
    ):
        raise ValueError("Discovery first complete payoff must stay inside the topic core")
    _validate_irrelevant_cues(
        candidate.irrelevant_intro_cue_ids,
        candidate.irrelevant_outro_cue_ids,
        start_cue_id=candidate.start_cue_id,
        end_cue_id=candidate.end_cue_id,
        cue_map=cue_map,
    )
    _validate_irrelevant_positions(
        candidate.irrelevant_intro_cue_ids,
        candidate.irrelevant_outro_cue_ids,
        core_start_cue_id=candidate.topic_core_start_cue_id,
        core_end_cue_id=candidate.topic_core_end_cue_id,
    )
    _validate_risk_cues(
        candidate.risks,
        cue_map=cue_map,
        start_cue_id=candidate.start_cue_id,
        end_cue_id=candidate.end_cue_id,
    )


def _validate_global_summary(
    output: GlobalReviewOutput,
    *,
    discovery_ids: set[str],
) -> None:
    # The Agent owns only semantic dispositions.  Python verifies that every
    # Discovery candidate has exactly one disposition and derives every count
    # after score/risk/quality/Top-N gates have run.
    _global_candidate_dispositions(output, discovery_ids=discovery_ids)


def _global_candidate_dispositions(
    output: GlobalReviewOutput,
    *,
    discovery_ids: set[str],
) -> dict[str, ReviewDecision]:
    dispositions: dict[str, ReviewDecision] = {}
    for clip in output.clips:
        decision = _raw_review_decision(clip)
        for candidate_id in clip.source_candidate_ids:
            if candidate_id not in discovery_ids:
                raise ValueError("Global Review summary references an unknown candidate")
            if candidate_id in dispositions:
                raise ValueError(
                    f"Discovery candidate has multiple Global dispositions: {candidate_id}"
                )
            dispositions[candidate_id] = decision
    for group in output.rejected_candidates:
        for candidate_id in group.candidate_ids:
            if candidate_id not in discovery_ids:
                raise ValueError("Global rejection references an unknown candidate")
            if candidate_id in dispositions:
                raise ValueError(
                    f"Discovery candidate has multiple Global dispositions: {candidate_id}"
                )
            dispositions[candidate_id] = ReviewDecision.REJECTED
    missing = sorted(discovery_ids - set(dispositions))
    if missing:
        raise ValueError(f"Global Review omitted Discovery candidate dispositions: {missing}")
    return dispositions


def _validate_coverage_decisions(
    decisions: tuple[CoverageDecision, ...],
    *,
    discovery_topics: dict[str, DiscoveryTopicUnit],
    expected_topic_ids: set[str],
    clip_map: dict[str, GlobalReviewClip],
    cue_map: dict[int, SemanticCue],
    config: SemanticGlobalConfig,
) -> None:
    expected = expected_topic_ids
    actual_ids = [value.topic_id for value in decisions]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("Global Review coverage topic IDs must be unique")
    if set(actual_ids) != expected:
        missing = sorted(expected - set(actual_ids))
        unexpected = sorted(set(actual_ids) - expected)
        raise ValueError(
            "Global Review coverage is incomplete for medium/high topics: "
            f"missing={missing}, unexpected={unexpected}"
        )
    decisions_by_topic = {value.topic_id: value for value in decisions}
    for decision in decisions:
        topic = discovery_topics[decision.topic_id]
        _validate_structured_reason_fields(
            reason_code=decision.reason_code,
            ideal_start_cue_id=decision.ideal_start_cue_id,
            ideal_end_cue_id=decision.ideal_end_cue_id,
            duplicate_of_clip_id=decision.duplicate_of_clip_id,
            duplicate_of_topic_id=decision.duplicate_of_topic_id,
        )
        if (
            decision.decision
            in {
                CoverageDecisionValue.REPRESENTED,
                CoverageDecisionValue.MANUAL_REVIEW,
            }
            and not decision.clip_ids
        ):
            raise ValueError("kept coverage requires at least one clip ID")
        if any(clip_id not in clip_map for clip_id in decision.clip_ids):
            raise ValueError("Global Review coverage references an unknown clip")
        referenced = [clip_map[clip_id] for clip_id in decision.clip_ids]
        if decision.decision in {
            CoverageDecisionValue.REPRESENTED,
            CoverageDecisionValue.MANUAL_REVIEW,
        } and any(decision.topic_id not in clip.source_topic_ids for clip in referenced):
            raise ValueError("kept coverage clips must trace the represented source topic")
        if decision.decision in {
            CoverageDecisionValue.REPRESENTED,
            CoverageDecisionValue.MANUAL_REVIEW,
        } and any(
            clip.end_cue_id < topic.start_cue_id or clip.start_cue_id > topic.end_cue_id
            for clip in referenced
        ):
            raise ValueError("kept coverage clips must overlap the represented source topic")
        if decision.decision in {
            CoverageDecisionValue.REPRESENTED,
            CoverageDecisionValue.MANUAL_REVIEW,
        } and any(_raw_review_decision(clip) == ReviewDecision.REJECTED for clip in referenced):
            raise ValueError("kept coverage cannot reference a dropped clip")
        if decision.decision == CoverageDecisionValue.REJECTED and any(
            _raw_review_decision(clip) != ReviewDecision.REJECTED for clip in referenced
        ):
            raise ValueError("rejected coverage can only reference dropped clips")
        if (
            decision.decision == CoverageDecisionValue.REJECTED
            and decision.reason_code == CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW
        ):
            raise ValueError("risk requiring review cannot be a rejected topic disposition")
        _validate_reason_targets(
            reason_code=decision.reason_code,
            duplicate_of_clip_id=decision.duplicate_of_clip_id,
            duplicate_of_topic_id=decision.duplicate_of_topic_id,
            clip_map=clip_map,
            discovery_topics=discovery_topics,
            source_topic_ids=(decision.topic_id,),
        )
        if decision.reason_code in {
            CoverageReasonCode.INCOMPLETE_TOPIC,
            CoverageReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
            CoverageReasonCode.DURATION_TOO_SHORT,
            CoverageReasonCode.DURATION_TOO_LONG,
        }:
            assert decision.ideal_start_cue_id is not None
            assert decision.ideal_end_cue_id is not None
            if (
                decision.ideal_end_cue_id < topic.start_cue_id
                or decision.ideal_start_cue_id > topic.end_cue_id
            ):
                raise ValueError("coverage duration-rejection boundaries must overlap their topic")
            if decision.reason_code in {
                CoverageReasonCode.DURATION_TOO_SHORT,
                CoverageReasonCode.DURATION_TOO_LONG,
            }:
                _validate_duration_claim(
                    identifier=f"topic_id={decision.topic_id}",
                    reason_code=decision.reason_code,
                    start_cue_id=decision.ideal_start_cue_id,
                    end_cue_id=decision.ideal_end_cue_id,
                    cue_map=cue_map,
                    config=config,
                )
        _validate_boundary_alternatives(
            identifier=f"topic_id={decision.topic_id}",
            reason_code=decision.reason_code,
            ideal_start_cue_id=decision.ideal_start_cue_id,
            ideal_end_cue_id=decision.ideal_end_cue_id,
            alternatives=decision.boundary_alternatives,
            source_ranges=((topic.start_cue_id, topic.end_cue_id),),
            cue_map=cue_map,
        )
        if decision.duplicate_of_topic_id is not None:
            target = decisions_by_topic.get(decision.duplicate_of_topic_id)
            if target is None or target.decision == CoverageDecisionValue.REJECTED:
                raise ValueError("duplicate coverage target topic must be represented or manual")
    # Adjacency is transport structure, not semantic evidence.  Global Review
    # owns the decision whether neighboring topic units are one promise or two;
    # Python deliberately does not require a mechanically constructed
    # cross-topic alternative here.


def _validate_rejected_candidates(
    groups: tuple[RejectedCandidateGroup, ...],
    *,
    discovery_candidates: dict[str, DiscoveryCandidate],
    discovery_topics: dict[str, DiscoveryTopicUnit],
    clip_map: dict[str, GlobalReviewClip],
    cue_map: dict[int, SemanticCue],
    config: SemanticGlobalConfig,
) -> None:
    discovery_ids = set(discovery_candidates)
    for group in groups:
        if group.reason_code == CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW:
            raise ValueError("risk requiring review cannot be a rejected candidate disposition")
        _validate_structured_reason_fields(
            reason_code=group.reason_code,
            ideal_start_cue_id=group.ideal_start_cue_id,
            ideal_end_cue_id=group.ideal_end_cue_id,
            duplicate_of_clip_id=group.duplicate_of_clip_id,
            duplicate_of_topic_id=group.duplicate_of_topic_id,
        )
        if any(value not in discovery_ids for value in group.candidate_ids):
            raise ValueError("Global Review rejection references an unknown candidate")
        if any(value not in discovery_topics for value in group.topic_ids):
            raise ValueError("Global Review rejection references an unknown topic")
        _validate_reason_targets(
            reason_code=group.reason_code,
            duplicate_of_clip_id=group.duplicate_of_clip_id,
            duplicate_of_topic_id=group.duplicate_of_topic_id,
            clip_map=clip_map,
            discovery_topics=discovery_topics,
            source_topic_ids=group.topic_ids,
        )
        candidate_ranges = [
            discovery_candidates[value]
            for value in group.candidate_ids
            if value in discovery_candidates
        ]
        topic_ranges = [discovery_topics[value] for value in group.topic_ids]
        if group.reason_code in {
            CoverageReasonCode.INCOMPLETE_TOPIC,
            CoverageReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
            CoverageReasonCode.DURATION_TOO_SHORT,
            CoverageReasonCode.DURATION_TOO_LONG,
        }:
            assert group.ideal_start_cue_id is not None
            assert group.ideal_end_cue_id is not None
            overlaps_candidate = any(
                group.ideal_end_cue_id >= value.start_cue_id
                and group.ideal_start_cue_id <= value.end_cue_id
                for value in candidate_ranges
            )
            overlaps_topic = any(
                group.ideal_end_cue_id >= value.start_cue_id
                and group.ideal_start_cue_id <= value.end_cue_id
                for value in topic_ranges
            )
            if not overlaps_candidate and not overlaps_topic:
                raise ValueError(
                    "rejected duration boundaries must overlap a referenced candidate or topic"
                )
            if group.reason_code in {
                CoverageReasonCode.DURATION_TOO_SHORT,
                CoverageReasonCode.DURATION_TOO_LONG,
            }:
                _validate_duration_claim(
                    identifier=f"candidate_ids={','.join(group.candidate_ids)}",
                    reason_code=group.reason_code,
                    start_cue_id=group.ideal_start_cue_id,
                    end_cue_id=group.ideal_end_cue_id,
                    cue_map=cue_map,
                    config=config,
                )
        audit_ranges = [(value.start_cue_id, value.end_cue_id) for value in candidate_ranges]
        audit_ranges.extend((value.start_cue_id, value.end_cue_id) for value in topic_ranges)
        _validate_boundary_alternatives(
            identifier=f"candidate_ids={','.join(group.candidate_ids)}",
            reason_code=group.reason_code,
            ideal_start_cue_id=group.ideal_start_cue_id,
            ideal_end_cue_id=group.ideal_end_cue_id,
            alternatives=group.boundary_alternatives,
            source_ranges=tuple(audit_ranges),
            cue_map=cue_map,
        )
        _validate_risk_cues(group.risks, cue_map=cue_map)


def _validate_reason_targets(
    *,
    reason_code: CoverageReasonCode,
    duplicate_of_clip_id: str | None,
    duplicate_of_topic_id: str | None,
    clip_map: dict[str, GlobalReviewClip],
    discovery_topics: dict[str, DiscoveryTopicUnit],
    source_topic_ids: tuple[str, ...],
) -> None:
    if reason_code != CoverageReasonCode.DUPLICATE_OF_OTHER_TOPIC:
        return
    if duplicate_of_clip_id is not None and duplicate_of_clip_id not in clip_map:
        raise ValueError("duplicate rejection references an unknown clip")
    if duplicate_of_clip_id is not None and (
        _raw_review_decision(clip_map[duplicate_of_clip_id]) == ReviewDecision.REJECTED
    ):
        raise ValueError("duplicate rejection target clip must be kept")
    if duplicate_of_topic_id is not None and duplicate_of_topic_id not in discovery_topics:
        raise ValueError("duplicate rejection references an unknown topic")
    if duplicate_of_topic_id is not None and duplicate_of_topic_id in source_topic_ids:
        raise ValueError("duplicate rejection cannot target its own topic")


def _validate_duration_claim(
    *,
    identifier: str,
    reason_code: CoverageReasonCode,
    start_cue_id: int,
    end_cue_id: int,
    cue_map: dict[int, SemanticCue],
    config: SemanticGlobalConfig,
) -> None:
    start, end = _validated_interval(start_cue_id, end_cue_id, cue_map)
    actual_ms = end.end_ms - start.start_ms
    valid_claim = (
        reason_code == CoverageReasonCode.DURATION_TOO_LONG
        and actual_ms > config.maximum_duration_ms
    ) or (
        reason_code == CoverageReasonCode.DURATION_TOO_SHORT
        and actual_ms < config.minimum_duration_ms
    )
    # A rejected audit can use a cue whose boundary straddles the limit by a
    # fraction of a second while its direct semantic core begins/ends inside
    # that cue.  Do not rerun the entire Global Review for this near-boundary
    # bookkeeping discrepancy.  This tolerance never admits a kept clip;
    # selected/manual intervals still obey the exact configured bounds.
    if not valid_claim and reason_code == CoverageReasonCode.DURATION_TOO_SHORT:
        valid_claim = actual_ms < config.minimum_duration_ms + DURATION_REJECTION_AUDIT_TOLERANCE_MS
    if not valid_claim and reason_code == CoverageReasonCode.DURATION_TOO_LONG:
        valid_claim = actual_ms > config.maximum_duration_ms - DURATION_REJECTION_AUDIT_TOLERANCE_MS
    if valid_claim:
        return
    raise ValueError(
        "duration_claim_conflict "
        f"{identifier} reason_code={reason_code.value} "
        f"ideal_start_cue_id={start_cue_id} ideal_end_cue_id={end_cue_id} "
        f"actual_duration_sec={actual_ms / 1_000:.3f} "
        f"allowed_duration_sec={config.minimum_duration_ms / 1_000:.3f}-"
        f"{config.maximum_duration_ms / 1_000:.3f}; Python is authoritative; "
        f"re-evaluate this item and do not reuse {reason_code.value}"
    )


def _validate_boundary_alternatives(
    *,
    identifier: str,
    reason_code: CoverageReasonCode,
    ideal_start_cue_id: int | None,
    ideal_end_cue_id: int | None,
    alternatives: tuple[BoundaryAlternativeAudit, ...],
    source_ranges: tuple[tuple[int, int], ...],
    cue_map: dict[int, SemanticCue],
) -> None:
    """Validate optional Agent-authored boundary diagnostics.

    Rejected records must retain their ideal cue range, and Python remains the
    sole authority for explicit duration claims.  Alternatives are useful
    audit evidence, but making every rejected topic invent a legal 45--90s
    alternative caused a single diagnostic mistake to invalidate an otherwise
    usable full review.  They are therefore checked for real, ordered cue IDs
    and source relation only; they are never used by Python to infer semantics.
    """

    if not alternatives:
        return
    if ideal_start_cue_id is None or ideal_end_cue_id is None:
        raise ValueError(f"{identifier}: boundary alternatives require ideal cue boundaries")
    identities = [(value.start_cue_id, value.end_cue_id) for value in alternatives]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{identifier}: boundary alternative ranges must be unique")
    for alternative in alternatives:
        _validated_interval(
            alternative.start_cue_id,
            alternative.end_cue_id,
            cue_map,
        )
        identity = (alternative.start_cue_id, alternative.end_cue_id)
        if reason_code == CoverageReasonCode.DURATION_TOO_LONG:
            if not (
                ideal_start_cue_id <= alternative.start_cue_id
                and alternative.end_cue_id <= ideal_end_cue_id
                and identity != (ideal_start_cue_id, ideal_end_cue_id)
            ):
                raise ValueError(
                    f"{identifier}: overlong boundary alternative must be a strictly shorter "
                    "subrange of the claimed ideal range"
                )
        elif not any(
            alternative.end_cue_id >= source_start and alternative.start_cue_id <= source_end
            for source_start, source_end in source_ranges
        ):
            raise ValueError(
                f"{identifier}: boundary alternative must overlap the rejected source "
                "topic or candidate"
            )


def _validate_clip_quality(
    clip: GlobalReviewClip,
    *,
    cue_map: dict[int, SemanticCue],
    config: SemanticGlobalConfig,
) -> None:
    _validated_interval(clip.topic_core_start_cue_id, clip.topic_core_end_cue_id, cue_map)
    if not (
        clip.start_cue_id
        <= clip.topic_core_start_cue_id
        <= clip.topic_core_end_cue_id
        <= clip.end_cue_id
    ):
        raise ValueError(f"{clip.clip_id}: topic core must stay inside the clip interval")
    _validate_source_opening_quote(
        clip.source_opening_quote,
        start_cue_id=clip.start_cue_id,
        cue_map=cue_map,
    )
    _validate_source_closing_quote(
        clip.source_closing_quote,
        end_cue_id=clip.end_cue_id,
        cue_map=cue_map,
    )
    if clip.editorial_decision == EditorialDecision.DROP:
        # Dropped clips are preserved only as source-grounded audit records.
        # Publication-only completeness, compactness and score consistency
        # must not invalidate the entire Global Review response.
        return
    _validate_following_cue_audit(clip, cue_map=cue_map)
    if not (
        clip.topic_core_start_cue_id
        <= clip.first_complete_payoff_cue_id
        <= clip.topic_core_end_cue_id
    ):
        raise ValueError(f"{clip.clip_id}: first complete payoff must stay inside topic core")
    _validate_minimum_duration_extension(
        start_cue_id=clip.start_cue_id,
        end_cue_id=clip.end_cue_id,
        first_complete_payoff_cue_id=clip.first_complete_payoff_cue_id,
        minimum_duration_extension_cue_ids=clip.minimum_duration_extension_cue_ids,
        cue_map=cue_map,
        config=config,
        label=clip.clip_id,
        enforce_semantic_extension=True,
    )
    _validate_irrelevant_cues(
        clip.irrelevant_intro_cue_ids,
        clip.irrelevant_outro_cue_ids,
        start_cue_id=clip.start_cue_id,
        end_cue_id=clip.end_cue_id,
        cue_map=cue_map,
        allow_inside_interval=False,
    )
    _validate_irrelevant_positions(
        clip.irrelevant_intro_cue_ids,
        clip.irrelevant_outro_cue_ids,
        core_start_cue_id=clip.topic_core_start_cue_id,
        core_end_cue_id=clip.topic_core_end_cue_id,
    )
    flags = set(clip.quality_flags)
    if clip.opening_relevance == OpeningRelevance.IRRELEVANT and (
        clip.editorial_decision == EditorialDecision.KEEP
    ):
        raise ValueError(f"{clip.clip_id}: irrelevant opening cannot be kept")
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and not clip.viewer_promise_matches_source_opening
    ):
        raise ValueError(
            f"{clip.clip_id}: viewer promise must cover the actual source-opening question"
        )
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.review_status == ReviewStatus.CLEAR
        and clip.opening_relevance != OpeningRelevance.DIRECT
    ):
        raise ValueError(
            f"{clip.clip_id}: automatic selection requires a direct source opening; "
            "re-bound to the later direct question or use manual review"
        )
    if clip.editorial_decision == EditorialDecision.KEEP and not clip.ending_complete:
        raise ValueError(f"{clip.clip_id}: incomplete ending cannot be kept")
    allowed_end_functions = {
        EndCueFunction.SUBSTANTIVE_PAYOFF,
        EndCueFunction.SAME_PROMISE_CLARIFICATION,
        EndCueFunction.RHETORICAL_CLOSURE,
    }
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.end_cue_function not in allowed_end_functions
    ):
        raise ValueError(
            f"{clip.clip_id}: kept clip must end on payoff, same-promise clarification, "
            "or rhetorical closure"
        )
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.end_cue_speaker_role == EndCueSpeakerRole.LISTENER
    ):
        raise ValueError(f"{clip.clip_id}: listener response cannot be the kept clip boundary")
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.review_status == ReviewStatus.CLEAR
        and clip.end_cue_speaker_role != EndCueSpeakerRole.ANSWERER
    ):
        raise ValueError(f"{clip.clip_id}: automatic selection requires an answerer-owned end cue")
    if not clip.ending_complete and not flags & {
        QualityFlag.TOPIC_NOT_CLOSED,
        QualityFlag.INCOMPLETE_ENDING,
    }:
        raise ValueError(f"{clip.clip_id}: incomplete ending requires a quality flag")
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.boundary_compactness != BoundaryCompactness.SHORTEST_COMPLETE
    ):
        raise ValueError(f"{clip.clip_id}: kept clip must use the shortest complete boundary")
    if (
        clip.editorial_decision == EditorialDecision.KEEP
        and clip.source_fidelity != SourceFidelity.FAITHFUL
    ):
        raise ValueError(f"{clip.clip_id}: unsupported source reframe cannot be kept")
    if QualityFlag.SOURCE_TITLE_MISMATCH in flags:
        raise ValueError(f"{clip.clip_id}: faithful source summary conflicts with mismatch flag")
    if QualityFlag.PADDED_WITH_IRRELEVANT_CONTENT in flags and (
        clip.editorial_decision == EditorialDecision.KEEP
    ):
        raise ValueError(f"{clip.clip_id}: irrelevant padding cannot be kept")
    if QualityFlag.IRRELEVANT_INTRO in flags and clip.score_dimensions.edit_cleanliness > 5:
        raise ValueError(f"{clip.clip_id}: irrelevant intro requires edit_cleanliness <= 5")
    if QualityFlag.IRRELEVANT_OUTRO in flags and clip.score_dimensions.edit_cleanliness > 5:
        raise ValueError(f"{clip.clip_id}: irrelevant outro requires edit_cleanliness <= 5")
    if QualityFlag.CONTEXT_DEPENDENT_OPENING in flags and clip.score_dimensions.standalone > 12:
        raise ValueError(f"{clip.clip_id}: context-dependent opening requires standalone <= 12")
    if flags & {QualityFlag.TOPIC_NOT_CLOSED, QualityFlag.INCOMPLETE_ENDING}:
        if clip.score_dimensions.completeness > 10:
            raise ValueError(f"{clip.clip_id}: unclosed topic requires completeness <= 10")
        if clip.editorial_decision == EditorialDecision.KEEP:
            raise ValueError(f"{clip.clip_id}: unclosed topic cannot be kept")
    if QualityFlag.TOPIC_SWITCH_INSIDE in flags and (
        clip.editorial_decision == EditorialDecision.KEEP
    ):
        raise ValueError(f"{clip.clip_id}: removable topic switch cannot be kept")
    if QualityFlag.SOURCE_TITLE_MISMATCH in flags and (
        clip.editorial_decision == EditorialDecision.KEEP
    ):
        raise ValueError(f"{clip.clip_id}: source title mismatch cannot be kept")


def _validate_irrelevant_cues(
    intro_ids: tuple[int, ...],
    outro_ids: tuple[int, ...],
    *,
    start_cue_id: int,
    end_cue_id: int,
    cue_map: dict[int, SemanticCue],
    allow_inside_interval: bool = False,
) -> None:
    values = (*intro_ids, *outro_ids)
    if len(values) != len(set(values)):
        raise ValueError("irrelevant intro/outro cue IDs must be unique")
    if any(value not in cue_map for value in values):
        raise ValueError("irrelevant intro/outro cue IDs must exist in source evidence")
    if allow_inside_interval:
        return
    else:
        if any(value >= start_cue_id for value in intro_ids):
            raise ValueError("irrelevant intro cue IDs must precede the selected clip")
        if any(value <= end_cue_id for value in outro_ids):
            raise ValueError("irrelevant outro cue IDs must follow the selected clip")


def _validate_irrelevant_positions(
    intro_ids: tuple[int, ...],
    outro_ids: tuple[int, ...],
    *,
    core_start_cue_id: int,
    core_end_cue_id: int,
) -> None:
    if any(value >= core_start_cue_id for value in intro_ids):
        raise ValueError("irrelevant intro cue IDs must precede the semantic core")
    if any(value <= core_end_cue_id for value in outro_ids):
        raise ValueError("irrelevant outro cue IDs must follow the semantic core")


def _validate_source_opening_quote(
    quote: str,
    *,
    start_cue_id: int,
    cue_map: dict[int, SemanticCue],
) -> None:
    nearby = " ".join(
        cue_map[value].original_text
        for value in (start_cue_id, start_cue_id + 1)
        if value in cue_map
    )
    normalized_quote = "".join(quote.split())
    normalized_source = "".join(nearby.split())
    if not normalized_quote or normalized_quote not in normalized_source:
        raise ValueError("source_opening_quote must be copied from the start cue vicinity")


def _validate_source_closing_quote(
    quote: str,
    *,
    end_cue_id: int,
    cue_map: dict[int, SemanticCue],
) -> None:
    nearby = " ".join(
        cue_map[value].original_text for value in (end_cue_id - 1, end_cue_id) if value in cue_map
    )
    normalized_quote = "".join(quote.split())
    normalized_source = "".join(nearby.split())
    if not normalized_quote or normalized_quote not in normalized_source:
        raise ValueError("source_closing_quote must be copied from the end cue vicinity")


def _validate_following_cue_audit(
    clip: GlobalReviewClip,
    *,
    cue_map: dict[int, SemanticCue],
) -> None:
    """Validate source evidence for the Agent's semantic end-boundary judgment."""

    following_ids = [cue_id for cue_id in cue_map if cue_id > clip.end_cue_id]
    expected_following_id = min(following_ids) if following_ids else None
    if expected_following_id is None:
        if (
            clip.following_cue_id is not None
            or clip.following_cue_quote is not None
            or clip.following_cue_relation != FollowingCueRelation.SOURCE_END
        ):
            raise ValueError(
                f"{clip.clip_id}: a source-ending clip must use source_end and no following cue"
            )
        return
    if clip.following_cue_id != expected_following_id:
        raise ValueError(
            f"{clip.clip_id}: following_cue_id must be the immediate source cue "
            f"{expected_following_id}"
        )
    if clip.following_cue_relation == FollowingCueRelation.SOURCE_END:
        raise ValueError(f"{clip.clip_id}: source_end is invalid while a following cue exists")
    if clip.following_cue_quote is None:
        raise ValueError(f"{clip.clip_id}: following cue audit requires a source quote")
    normalized_quote = "".join(clip.following_cue_quote.split())
    normalized_source = "".join(cue_map[expected_following_id].original_text.split())
    if not normalized_quote or normalized_quote not in normalized_source:
        raise ValueError(
            f"{clip.clip_id}: following_cue_quote must be copied from the immediate next cue"
        )
    if clip.editorial_decision == EditorialDecision.KEEP and clip.following_cue_relation in {
        FollowingCueRelation.CONTINUES_SAME_UTTERANCE,
        FollowingCueRelation.REQUIRED_SAME_PROMISE,
    }:
        raise ValueError(
            f"{clip.clip_id}: kept end boundary is followed by required continuation; "
            "extend to the first complete payoff or drop"
        )


def _validate_minimum_duration_extension(
    *,
    start_cue_id: int,
    end_cue_id: int,
    first_complete_payoff_cue_id: int,
    minimum_duration_extension_cue_ids: tuple[int, ...],
    cue_map: dict[int, SemanticCue],
    config: SemanticGlobalConfig,
    label: str,
    enforce_semantic_extension: bool = True,
) -> None:
    """Prove why a shortest legal clip continues past its first payoff.

    A complete question-to-payoff suffix can be shorter than the configured
    minimum.  In that one case the clip may retain the immediately following
    same-promise clarification needed to reach the minimum.  The Agent must
    enumerate that extension so a later reviewer can distinguish it from
    silent CTA/sales padding.
    """

    if len(minimum_duration_extension_cue_ids) != len(set(minimum_duration_extension_cue_ids)):
        raise ValueError(f"{label}: minimum-duration extension cue IDs must be unique")
    if first_complete_payoff_cue_id == end_cue_id:
        if minimum_duration_extension_cue_ids:
            raise ValueError(f"{label}: payoff-ending clip cannot declare duration extension cues")
        return
    if enforce_semantic_extension:
        payoff_duration_ms = (
            cue_map[first_complete_payoff_cue_id].end_ms - cue_map[start_cue_id].start_ms
        )
        if payoff_duration_ms >= config.minimum_duration_ms:
            raise ValueError(
                f"{label}: first payoff already forms a legal "
                f"{payoff_duration_ms / 1_000:.3f}s clip; later material is removable"
            )
    expected = tuple(
        cue_id for cue_id in sorted(cue_map) if first_complete_payoff_cue_id < cue_id <= end_cue_id
    )
    if minimum_duration_extension_cue_ids != expected:
        raise ValueError(
            f"{label}: minimum-duration extension must enumerate every cue after payoff "
            f"through end; expected={expected}, actual={minimum_duration_extension_cue_ids}"
        )
    if not expected or expected[-1] != end_cue_id:
        raise ValueError(f"{label}: minimum-duration extension must reach the end cue")
    if not enforce_semantic_extension:
        # A dropped clip may intentionally preserve an invalid/padded boundary as
        # audit evidence.  Its extension list must still describe the interval
        # exactly, but it is not required to pretend that the padding belongs to
        # the semantic core.  Kept clips retain every shortest-boundary rule.
        return
    # The Agent already identifies these cues as same-promise clarification.
    # Requiring a second redundant core-end field to include them made harmless
    # bookkeeping disagreement fatal without adding semantic protection.


def _validate_risk_cues(
    risks: tuple[RiskAssessment, ...],
    *,
    cue_map: dict[int, SemanticCue],
    start_cue_id: int | None = None,
    end_cue_id: int | None = None,
) -> None:
    for risk in risks:
        if len(risk.source_cue_ids) != len(set(risk.source_cue_ids)):
            raise ValueError("risk source cue IDs must be unique")
        if any(value not in cue_map for value in risk.source_cue_ids):
            raise ValueError("risk references a cue outside the supplied evidence")
        if (
            start_cue_id is not None
            and end_cue_id is not None
            and any(value < start_cue_id or value > end_cue_id for value in risk.source_cue_ids)
        ):
            raise ValueError("risk source cue IDs must stay inside the candidate or clip")


def _merge_risks(
    *groups: tuple[RiskAssessment, ...],
) -> tuple[RiskAssessment, ...]:
    severity_rank = {
        RiskSeverity.LOW: 0,
        RiskSeverity.MEDIUM: 1,
        RiskSeverity.HIGH: 2,
    }
    grouped: dict[RiskType, list[RiskAssessment]] = {}
    for risk in (value for group in groups for value in group):
        grouped.setdefault(risk.type, []).append(risk)
    merged: list[RiskAssessment] = []
    for risk_type in sorted(grouped, key=lambda value: value.value):
        values = grouped[risk_type]
        highest = max(values, key=lambda value: severity_rank[value.severity])
        reasons = tuple(dict.fromkeys(value.reason for value in values))
        merged.append(
            RiskAssessment(
                type=risk_type,
                severity=highest.severity,
                reason="; ".join(reasons)[:400],
                source_cue_ids=tuple(
                    sorted({cue_id for value in values for cue_id in value.source_cue_ids})
                ),
            )
        )
    return tuple(merged)


def _discovery_risks_for_clip(
    clip: GlobalReviewClip,
    *,
    discovery_candidates: dict[str, DiscoveryCandidate],
) -> tuple[RiskAssessment, ...]:
    risks: list[RiskAssessment] = []
    for candidate in discovery_candidates.values():
        for risk in candidate.risks:
            retained_cues = tuple(
                value
                for value in risk.source_cue_ids
                if clip.start_cue_id <= value <= clip.end_cue_id
            )
            if retained_cues:
                risks.append(risk.model_copy(update={"source_cue_ids": retained_cues}))
    return tuple(risks)


def _risk_requires_manual(risk: RiskAssessment) -> bool:
    if risk.type.value in MANUAL_REVIEW_RISKS:
        return True
    return risk.type in {
        RiskType.GENERAL_HEALTH_WARNING,
        RiskType.SENSITIVITY_REVIEW,
    } and risk.severity in {RiskSeverity.MEDIUM, RiskSeverity.HIGH}


def _raw_review_decision(clip: GlobalReviewClip) -> ReviewDecision:
    if clip.editorial_decision == EditorialDecision.DROP:
        return ReviewDecision.REJECTED
    if clip.review_status == ReviewStatus.MANUAL:
        return ReviewDecision.MANUAL_REVIEW
    return ReviewDecision.SELECTED


def semantic_global_output_slots(
    transcript: TranscriptDocument,
    *,
    max_clips: int,
    minimum_duration_ms: int,
) -> tuple[CandidateClip, ...]:
    segments = transcript.segments
    if not segments:
        raise ValueError("semantic global output slots require transcript evidence")
    end_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if segment.end_ms - segments[0].start_ms >= minimum_duration_ms
        ),
        len(segments) - 1,
    )
    initial = segments[: end_index + 1]
    text = "\n".join(_timestamped_segment(segment) for segment in initial)[:24_000]
    segment_ids = tuple(segment.segment_id for segment in initial[:256])
    identity = hashlib.sha256(
        "\0".join(segment.segment_id for segment in segments).encode()
    ).hexdigest()[:16]
    return tuple(
        CandidateClip(
            candidate_id=f"semantic_global_{identity}_{index:03d}",
            source_start_ms=initial[0].start_ms,
            source_end_ms=initial[-1].end_ms,
            allowed_start_ms=segments[0].start_ms,
            allowed_end_ms=segments[-1].end_ms,
            text=text,
            context_before="",
            context_after="",
            rule_score=0.0,
            reasons=("semantic_global_output_slot", f"slot:{index}"),
            segment_ids=segment_ids,
        )
        for index in range(1, max_clips + 1)
    )


def discovery_request_payload(
    unit: SemanticInputUnit,
    *,
    source_id: str,
    mode: SemanticInputMode,
    config: SemanticGlobalConfig,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "2",
        "source_id": source_id,
        "input_mode": mode.value,
        "input_unit_id": unit.unit_id,
        "source_range": unit.source_range.model_dump(mode="json"),
        "runtime": _runtime_payload(config),
        "cues": _cue_dicts(unit.cues),
    }
    if unit.context_range_ms is not None:
        payload["batch_context_ms"] = unit.context_range_ms.model_dump(mode="json")
    if unit.ownership_range_ms is not None:
        payload["ownership_interval_ms"] = unit.ownership_range_ms.model_dump(mode="json")
    if unit.logical_windows_ms:
        payload["logical_windows_ms"] = [
            value.model_dump(mode="json") for value in unit.logical_windows_ms
        ]
    if unit.bridge_boundary_ms is not None:
        payload["bridge_boundary_ms"] = unit.bridge_boundary_ms
    if unit.triggering_boundary_topics:
        payload["triggering_boundary_topics"] = [
            value.model_dump(mode="json") for value in unit.triggering_boundary_topics
        ]
    return payload


def semantic_repair_payload(
    request_payload: dict[str, object],
    invalid_output: BaseModel,
    *,
    validation_errors: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build a bounded repair-only payload without asking the model to rediscover content."""

    valid_cue_ids: list[int] = []
    available_cues: list[dict[str, object]] = []
    cues = request_payload.get("cues")
    if isinstance(cues, list):
        available_cues.extend(cue for cue in cues if isinstance(cue, dict))
        valid_cue_ids.extend(
            int(cue["cue_id"])
            for cue in cues
            if isinstance(cue, dict)
            and isinstance(cue.get("cue_id"), int)
            and not isinstance(cue["cue_id"], bool)
        )
    evidence = request_payload.get("evidence")
    if isinstance(evidence, dict):
        evidence_cues = _transport_cue_objects(evidence)
        available_cues.extend(evidence_cues)
        valid_cue_ids.extend(
            cue_id
            for cue in evidence_cues
            if isinstance((cue_id := cue.get("cue_id")), int) and not isinstance(cue_id, bool)
        )
    discovery = request_payload.get("discovery")
    candidate_ids: list[str] = []
    if isinstance(discovery, dict):
        candidates = discovery.get("candidates")
        if isinstance(candidates, list):
            candidate_ids = [
                str(candidate["candidate_id"])
                for candidate in candidates
                if isinstance(candidate, dict) and "candidate_id" in candidate
            ]
    invalid_payload = invalid_output.model_dump(mode="json")
    focus_ranges = _repair_ranges(invalid_payload)
    topic_gap_ranges = _topic_gap_ranges(
        invalid_payload,
        source_range=request_payload.get("source_range"),
    )
    if topic_gap_ranges:
        focus_ranges = topic_gap_ranges
    affected_evidence = _bounded_repair_evidence(available_cues, focus_ranges=focus_ranges)
    boundary_quote_options = _authoritative_boundary_quote_options(
        invalid_payload,
        available_cues=available_cues,
    )
    return {
        "schema_version": "2",
        "repair_only": True,
        "validation_errors": list(validation_errors),
        "immutable_transport_facts": {
            key: request_payload[key]
            for key in (
                "source_id",
                "input_mode",
                "input_unit_id",
                "source_range",
                "mode",
                "runtime",
            )
            if key in request_payload
        },
        "valid_cue_ids": sorted(set(valid_cue_ids)),
        "valid_discovery_candidate_ids": sorted(set(candidate_ids)),
        "preserve_item_ids": _repair_item_ids(invalid_payload),
        "repair_constraints": (
            "Preserve every existing item ID and all unaffected decisions. Discovery candidate "
            "IDs must remain exactly unchanged; never insert placeholder candidates. Topic-map "
            "gap repair may adjust topic boundaries or add fully described topics, but may not "
            "clear topic_units. For every cited quote validation error, copy one exact value from "
            "authoritative_boundary_quote_options for that unchanged boundary; copy its "
            "immediate_following_cue_id and exact_following_cue_quote when repairing an end "
            "audit; never paraphrase or concatenate source text."
        ),
        "authoritative_boundary_quote_options": boundary_quote_options,
        "authoritative_discovery": discovery if isinstance(discovery, dict) else None,
        "affected_evidence": affected_evidence,
        "invalid_output": invalid_payload,
    }


def _topic_gap_ranges(
    value: dict[str, object],
    *,
    source_range: object,
) -> tuple[tuple[int, int], ...]:
    topics = value.get("topic_units")
    if not isinstance(topics, list):
        return ()
    bounded = [
        topic
        for topic in topics
        if isinstance(topic, dict)
        and isinstance(topic.get("start_cue_id"), int)
        and not isinstance(topic["start_cue_id"], bool)
        and isinstance(topic.get("end_cue_id"), int)
        and not isinstance(topic["end_cue_id"], bool)
    ]
    ordered = sorted(
        bounded,
        key=lambda topic: (int(topic["start_cue_id"]), int(topic["end_cue_id"])),
    )
    if not ordered:
        return ()
    gaps: list[tuple[int, int]] = []
    if isinstance(source_range, dict):
        expected_start = source_range.get("start_cue_id")
        expected_end = source_range.get("end_cue_id")
        if isinstance(expected_start, int) and expected_start < int(ordered[0]["start_cue_id"]):
            gaps.append((expected_start, int(ordered[0]["start_cue_id"]) - 1))
        if isinstance(expected_end, int) and expected_end > int(ordered[-1]["end_cue_id"]):
            gaps.append((int(ordered[-1]["end_cue_id"]) + 1, expected_end))
    gaps.extend(
        (int(previous["end_cue_id"]) + 1, int(current["start_cue_id"]) - 1)
        for previous, current in pairwise(ordered)
        if int(current["start_cue_id"]) > int(previous["end_cue_id"]) + 1
    )
    return tuple(gaps)


def _repair_item_ids(value: dict[str, object]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for collection, identifier in (
        ("topic_units", "topic_id"),
        ("candidates", "candidate_id"),
        ("clips", "clip_id"),
    ):
        items = value.get(collection)
        if not isinstance(items, list):
            continue
        result[collection] = [
            str(item[identifier])
            for item in items
            if isinstance(item, dict) and isinstance(item.get(identifier), str)
        ]
    return result


def _authoritative_boundary_quote_options(
    value: dict[str, object],
    *,
    available_cues: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Give a repair call exact, bounded source strings for existing boundaries.

    Boundary quotes are audit evidence, so there is no reason to ask the model to
    transcribe them from a large evidence bundle.  Python still validates the
    returned choice; this helper does not change boundaries or semantic labels.
    """

    cue_map: dict[int, dict[str, object]] = {}
    for cue in available_cues:
        cue_id = cue.get("cue_id")
        if (
            isinstance(cue_id, int)
            and not isinstance(cue_id, bool)
            and isinstance(cue.get("original_text"), str)
        ):
            cue_map[cue_id] = cue
    options: list[dict[str, object]] = []
    for collection, identifier in (
        ("candidates", "candidate_id"),
        ("clips", "clip_id"),
    ):
        items = value.get(collection)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get(identifier), str):
                continue
            start = item.get("start_cue_id")
            end = item.get("end_cue_id")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
            ):
                continue
            opening = [
                str(cue_map[cue_id]["original_text"])
                for cue_id in (start, start + 1)
                if cue_id in cue_map
            ]
            closing = [
                str(cue_map[cue_id]["original_text"])
                for cue_id in (end - 1, end)
                if cue_id in cue_map
            ]
            if opening and closing:
                following_ids = [cue_id for cue_id in cue_map if cue_id > end]
                following_id = min(following_ids) if following_ids else None
                following_quote = (
                    str(cue_map[following_id]["original_text"])
                    if following_id is not None
                    else None
                )
                options.append(
                    {
                        "item_id": str(item[identifier]),
                        "start_cue_id": start,
                        "end_cue_id": end,
                        "exact_opening_quote_options": list(dict.fromkeys(opening)),
                        "exact_closing_quote_options": list(dict.fromkeys(closing)),
                        "immediate_following_cue_id": following_id,
                        "exact_following_cue_quote": following_quote,
                    }
                )
    return options


def _repair_ranges(value: object) -> tuple[tuple[int, int], ...]:
    ranges: set[tuple[int, int]] = set()
    if isinstance(value, list):
        for item in value:
            ranges.update(_repair_ranges(item))
    elif isinstance(value, dict):
        for start_key, end_key in (
            ("ideal_start_cue_id", "ideal_end_cue_id"),
            ("topic_core_start_cue_id", "topic_core_end_cue_id"),
            ("start_cue_id", "end_cue_id"),
        ):
            start = value.get(start_key)
            end = value.get(end_key)
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and start <= end
            ):
                ranges.add((start, end))
        for item in value.values():
            ranges.update(_repair_ranges(item))
    return tuple(sorted(ranges))


def _bounded_repair_evidence(
    cues: list[dict[str, object]],
    *,
    focus_ranges: tuple[tuple[int, int], ...],
) -> list[dict[str, object]]:
    if not cues or not focus_ranges:
        return []
    included: dict[int, dict[str, object]] = {}
    for cue in cues:
        cue_id = cue.get("cue_id")
        if not isinstance(cue_id, int) or isinstance(cue_id, bool):
            continue
        if any(start - 3 <= cue_id <= end + 3 for start, end in focus_ranges):
            included[cue_id] = cue
    return [included[value] for value in sorted(included)[:600]]


def _runtime_payload(config: SemanticGlobalConfig) -> dict[str, object]:
    return {
        "minimum_duration_sec": config.minimum_duration_ms / 1_000,
        "target_duration_sec": config.target_duration_ms / 1_000,
        "maximum_duration_sec": config.maximum_duration_ms / 1_000,
        "score_threshold_exclusive": config.score_threshold_exclusive,
        "max_clips": config.max_clips,
        "continuity": "one_continuous_cue_range",
        "window_duration_sec": config.window_duration_ms / 1_000,
        "window_overlap_sec": config.window_overlap_ms / 1_000,
    }


def _rolling_window_units(
    cues: tuple[SemanticCue, ...],
    *,
    source_duration_ms: int,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator,
    transcript_token_budget: int,
    prompt_tokens: int,
) -> tuple[SemanticInputUnit, ...]:
    """Create four-window batches while transmitting each source cue only once."""

    stride_ms = config.window_duration_ms - config.window_overlap_ms
    ownership_span_ms = stride_ms * config.window_batch_size
    context_span_ms = config.window_duration_ms + stride_ms * (config.window_batch_size - 1)
    units: list[SemanticInputUnit] = []
    batch_start_ms = 0
    while batch_start_ms < source_duration_ms:
        context_end_ms = min(source_duration_ms, batch_start_ms + context_span_ms)
        ownership_end_ms = min(source_duration_ms, batch_start_ms + ownership_span_ms)
        selected = _cues_for_time_range(
            cues,
            start_ms=batch_start_ms,
            end_ms=context_end_ms,
        )
        unit_tokens = estimator.count(_cues_payload(selected))
        if unit_tokens > transcript_token_budget:
            raise ValueError("semantic window batch exceeds the transcript token budget")
        logical_windows = tuple(
            SemanticTimeRange(
                start_ms=logical_start,
                end_ms=min(source_duration_ms, logical_start + config.window_duration_ms),
            )
            for index in range(config.window_batch_size)
            if (logical_start := batch_start_ms + index * stride_ms) < source_duration_ms
        )
        units.append(
            SemanticInputUnit(
                unit_id=f"window_batch_{len(units) + 1:03d}",
                source_range=CueRange(
                    start_cue_id=selected[0].cue_id,
                    end_cue_id=selected[-1].cue_id,
                ),
                cues=selected,
                estimated_tokens=prompt_tokens + unit_tokens,
                context_range_ms=SemanticTimeRange(
                    start_ms=batch_start_ms,
                    end_ms=context_end_ms,
                ),
                ownership_range_ms=SemanticTimeRange(
                    start_ms=batch_start_ms,
                    end_ms=ownership_end_ms,
                ),
                logical_windows_ms=logical_windows,
            )
        )
        batch_start_ms += ownership_span_ms
    if not units:
        raise ValueError("semantic rolling window planner produced no input units")
    return tuple(units)


def _cues_for_time_range(
    cues: tuple[SemanticCue, ...],
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[SemanticCue, ...]:
    selected = tuple(cue for cue in cues if cue.end_ms > start_ms and cue.start_ms < end_ms)
    if not selected:
        raise ValueError("semantic time range contains no transcript cues")
    return selected


def _fallback_units(
    cues: tuple[SemanticCue, ...],
    *,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator,
    transcript_token_budget: int,
    prompt_tokens: int,
) -> tuple[SemanticInputUnit, ...]:
    units: list[SemanticInputUnit] = []
    start_index = 0
    while start_index < len(cues):
        end_index = start_index
        while end_index + 1 < len(cues):
            current_duration = cues[end_index].end_ms - cues[start_index].start_ms
            if current_duration >= config.fallback_target_duration_ms:
                break
            prospective = cues[start_index : end_index + 2]
            duration = prospective[-1].end_ms - prospective[0].start_ms
            tokens = estimator.count(_cues_payload(prospective))
            if duration > config.fallback_maximum_duration_ms or tokens > transcript_token_budget:
                break
            end_index += 1
        selected = cues[start_index : end_index + 1]
        duration = selected[-1].end_ms - selected[0].start_ms
        if duration < config.fallback_minimum_duration_ms and end_index < len(cues) - 1:
            raise ValueError("token budget cannot fit the minimum fallback transcript duration")
        unit_tokens = estimator.count(_cues_payload(selected))
        units.append(
            SemanticInputUnit(
                unit_id=f"fallback_{len(units) + 1:03d}",
                source_range=CueRange(
                    start_cue_id=selected[0].cue_id,
                    end_cue_id=selected[-1].cue_id,
                ),
                cues=selected,
                estimated_tokens=prompt_tokens + unit_tokens,
            )
        )
        if end_index == len(cues) - 1:
            break
        next_start_ms = selected[-1].end_ms - config.fallback_overlap_ms
        overlap_starts = [
            index
            for index in range(start_index + 1, end_index + 1)
            if cues[index].start_ms <= next_start_ms
        ]
        next_index = overlap_starts[-1] if overlap_starts else start_index + 1
        if next_index <= start_index:
            raise ValueError("fallback window planner did not advance")
        start_index = next_index
    return tuple(units)


def _global_semantic_contexts(
    cues: tuple[SemanticCue, ...],
    *,
    discovery_outputs: tuple[DiscoveryOutput, ...],
    adjacent_cue_count: int,
    candidate_context_ms: int = 0,
    include_topic_catalog: bool = True,
) -> list[dict[str, object]]:
    """Build complete semantic evidence without making semantic decisions.

    Every Discovery candidate and every medium/high topic contributes its raw
    continuous cue range plus a small adjacent-cue transport guard.  Python only
    unions overlapping transport ranges; it does not use overlap to decide
    topic identity, duplication, value, mergeability or clip boundaries.
    """

    cue_map = {cue.cue_id: cue for cue in cues}
    cue_indexes = {cue.cue_id: index for index, cue in enumerate(cues)}

    def context_bounds(start_cue_id: int, end_cue_id: int) -> tuple[int, int]:
        start_index = max(0, cue_indexes[start_cue_id] - adjacent_cue_count)
        end_index = min(len(cues) - 1, cue_indexes[end_cue_id] + adjacent_cue_count)
        return cues[start_index].start_ms, cues[end_index].end_ms

    requested: list[_ContextRequest] = []
    for output in discovery_outputs:
        for candidate in output.candidates:
            lower, upper = context_bounds(candidate.start_cue_id, candidate.end_cue_id)
            lower = max(0, lower - candidate_context_ms)
            upper += candidate_context_ms
            linked_topic_ids: list[str] = []
            for topic in output.topic_units:
                if candidate.candidate_id not in topic.candidate_ids:
                    continue
                linked_topic_ids.append(topic.topic_id)
                # A candidate can be a narrower Discovery proposal than its
                # linked topic.  Global Review must see the complete linked
                # topic to compare all feasible boundaries, even in windowed
                # mode; this is still local candidate evidence, not a rescan.
                topic_start = cue_map[topic.start_cue_id]
                topic_end = cue_map[topic.end_cue_id]
                lower = min(lower, topic_start.start_ms)
                upper = max(upper, topic_end.end_ms)
            requested.append(
                _ContextRequest(
                    candidate_ids=[candidate.candidate_id],
                    topic_ids=linked_topic_ids,
                    parent_topics=[candidate.parent_topic],
                    lower_ms=lower,
                    upper_ms=upper,
                )
            )
        for topic in output.topic_units:
            if not include_topic_catalog:
                continue
            if topic.value_density not in {"medium", "high"}:
                continue
            topic_lower, topic_upper = context_bounds(topic.start_cue_id, topic.end_cue_id)
            requested.append(
                _ContextRequest(
                    candidate_ids=list(topic.candidate_ids),
                    topic_ids=[topic.topic_id],
                    parent_topics=[],
                    lower_ms=topic_lower,
                    upper_ms=topic_upper,
                )
            )
        if any(topic.topic_id.startswith("bridge_") for topic in output.topic_units):
            bridge_start = cue_map[output.source_range.start_cue_id]
            bridge_end = cue_map[output.source_range.end_cue_id]
            requested.append(
                _ContextRequest(
                    candidate_ids=[value.candidate_id for value in output.candidates],
                    topic_ids=[value.topic_id for value in output.topic_units],
                    parent_topics=[],
                    lower_ms=bridge_start.start_ms,
                    upper_ms=bridge_end.end_ms,
                )
            )
    merged: list[_ContextRequest] = []
    for item in sorted(requested, key=lambda value: (value.lower_ms, value.upper_ms)):
        if merged and item.lower_ms <= merged[-1].upper_ms:
            current = merged[-1]
            current.upper_ms = max(current.upper_ms, item.upper_ms)
            current.candidate_ids = list(
                dict.fromkeys((*current.candidate_ids, *item.candidate_ids))
            )
            current.topic_ids = list(dict.fromkeys((*current.topic_ids, *item.topic_ids)))
            current.parent_topics = list(
                dict.fromkeys((*current.parent_topics, *item.parent_topics))
            )
        else:
            merged.append(item)
    contexts: list[dict[str, object]] = []
    for index, item in enumerate(merged, start=1):
        lower = item.lower_ms
        upper = item.upper_ms
        evidence = tuple(cue for cue in cues if cue.end_ms >= lower and cue.start_ms <= upper)
        contexts.append(
            {
                "context_id": f"context_{index:03d}",
                "candidate_ids": item.candidate_ids,
                "topic_ids": item.topic_ids,
                "parent_topics": item.parent_topics,
                "source_range": {
                    "start_cue_id": evidence[0].cue_id,
                    "end_cue_id": evidence[-1].cue_id,
                },
                "cue_rows": _global_cue_rows(evidence),
            }
        )
    return contexts


def _semantic_request_tokens(
    prompt: str,
    payload: dict[str, object],
    *,
    config: SemanticGlobalConfig,
    estimator: TokenEstimator | None,
) -> int:
    resolved_estimator = estimator or TokenEstimator(config.tokenizer_name)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        resolved_estimator.count(prompt)
        + resolved_estimator.count(serialized)
        + config.output_reserve_tokens
        + config.safety_margin_tokens
    )


def _validated_interval(
    start_cue_id: int,
    end_cue_id: int,
    cue_map: dict[int, SemanticCue],
) -> tuple[SemanticCue, SemanticCue]:
    try:
        start = cue_map[start_cue_id]
        end = cue_map[end_cue_id]
    except KeyError as exc:
        raise ValueError("model returned a cue ID outside the supplied evidence") from exc
    if end_cue_id < start_cue_id or end.end_ms <= start.start_ms:
        raise ValueError("model returned a reversed or empty cue interval")
    return start, end


def _cue_dicts(cues: tuple[SemanticCue, ...]) -> list[dict[str, object]]:
    # Omit absent normalization fields from model transport.  The original cue,
    # stable ID and exact timing remain present, while avoiding thousands of
    # repeated `null` keys in long full-context transcripts.  When normalized
    # text exists it is still included with its audit note.
    return [cue.model_dump(mode="json", exclude_none=True) for cue in cues]


def _global_cue_rows(cues: tuple[SemanticCue, ...]) -> list[list[object]]:
    """Serialize repeated Global Review evidence without repeated JSON keys."""

    return [
        [
            cue.cue_id,
            cue.start_ms,
            cue.end_ms,
            cue.original_text,
            cue.normalized_text,
            cue.normalization_note,
        ]
        for cue in cues
    ]


def _transport_cue_objects(value: object) -> list[dict[str, object]]:
    """Read both legacy cue objects and compact Global Review cue rows."""

    if isinstance(value, list):
        if (
            len(value) == len(GLOBAL_REVIEW_CUE_COLUMNS)
            and isinstance(value[0], int)
            and not isinstance(value[0], bool)
            and isinstance(value[1], int)
            and not isinstance(value[1], bool)
            and isinstance(value[2], int)
            and not isinstance(value[2], bool)
            and isinstance(value[3], str)
        ):
            return [
                {
                    key: item
                    for key, item in zip(GLOBAL_REVIEW_CUE_COLUMNS, value, strict=True)
                    if item is not None
                }
            ]
        return [cue for item in value for cue in _transport_cue_objects(item)]
    if not isinstance(value, dict):
        return []
    if (
        isinstance(value.get("cue_id"), int)
        and not isinstance(value.get("cue_id"), bool)
        and isinstance(value.get("start_ms"), int)
        and isinstance(value.get("end_ms"), int)
        and isinstance(value.get("original_text"), str)
    ):
        return [value]
    return [cue for item in value.values() for cue in _transport_cue_objects(item)]


def _cues_payload(cues: tuple[SemanticCue, ...]) -> str:
    return json.dumps(_cue_dicts(cues), ensure_ascii=False, separators=(",", ":"))


def _timestamped_segment(segment: TranscriptSegment) -> str:
    return f"[{segment.start_ms},{segment.end_ms}] {segment.text}"
