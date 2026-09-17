from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from liveclip.domain.clip_profile import ClipProfile, clip_profile_spec
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_VALIDATION,
    LEGACY_SEMANTIC_VALIDATION,
    SemanticValidationContract,
    uses_current_semantic_validation,
)
from liveclip.domain.transcript import TranscriptDocument
from liveclip.pipeline.semantic_global import SemanticCue, SemanticInputUnit, transcript_cues

SafeIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
BoundedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

SEMANTIC_RESULT_SCHEMA_VERSION = "4"


class TimeRangeV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> TimeRangeV4:
        if self.end_ms <= self.start_ms:
            raise ValueError("time range is reversed")
        return self


class TopicBoundaryV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    continues_previous_topic: bool = False
    topic_unfinished: bool = False
    topic_summary: str = Field(default="", max_length=320)
    central_question: str = Field(default="", max_length=320)
    continuation_expected: bool = False
    evidence_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    related_candidate_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=60)
    related_fragment_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=60)

    @model_validator(mode="after")
    def validate_evidence(self) -> TopicBoundaryV4:
        reports_open_topic = (
            self.continues_previous_topic or self.topic_unfinished or self.continuation_expected
        )
        if reports_open_topic and (
            not self.topic_summary
            or not self.central_question
            or not self.evidence_cue_ids
            or not self.related_fragment_ids
        ):
            raise ValueError(
                "an open topic boundary requires summary, objective, evidence, and fragment"
            )
        return self


class TopicFragmentV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic_fragment_id: SafeIdentifier
    logical_window_id: SafeIdentifier
    topic_summary: BoundedText = Field(max_length=320)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    touches_left_boundary: bool
    touches_right_boundary: bool
    left_complete: bool
    right_complete: bool
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=120)
    possible_profiles: tuple[ClipProfile, ...] = Field(min_length=1, max_length=2)
    source_batch_id: SafeIdentifier

    @model_validator(mode="after")
    def validate_fragment(self) -> TopicFragmentV4:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("topic fragment cue range is reversed")
        if len(set(self.possible_profiles)) != len(self.possible_profiles):
            raise ValueError("topic fragment profiles must be unique")
        if not self.touches_left_boundary and not self.left_complete:
            raise ValueError("an incomplete left side must touch the logical-window boundary")
        if not self.touches_right_boundary and not self.right_complete:
            raise ValueError("an incomplete right side must touch the logical-window boundary")
        return self


class DiscoveryCandidateV4(BaseModel):
    """High-recall discovery proposal; no score, risk gate, or duration gate is applied here."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: SafeIdentifier
    source_topic_id: SafeIdentifier
    topic_fragment_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=80)
    topic_summary: BoundedText = Field(max_length=320)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=160)
    possible_profiles: tuple[ClipProfile, ...] = Field(min_length=1, max_length=2)
    risk_flags: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    source_window_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=20)
    source_batch_id: SafeIdentifier

    @model_validator(mode="after")
    def validate_candidate(self) -> DiscoveryCandidateV4:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("Discovery candidate cue range is reversed")
        if len(set(self.possible_profiles)) != len(self.possible_profiles):
            raise ValueError("Discovery candidate profiles must be unique")
        return self


class LogicalWindowDiscoveryV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    logical_window_id: SafeIdentifier
    window_start_ms: int = Field(ge=0)
    window_end_ms: int = Field(gt=0)
    candidate_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=100)
    fragment_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=100)
    left_boundary: TopicBoundaryV4
    right_boundary: TopicBoundaryV4
    coverage_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=40)

    @model_validator(mode="after")
    def validate_window(self) -> LogicalWindowDiscoveryV4:
        if self.window_end_ms <= self.window_start_ms:
            raise ValueError("logical window is reversed")
        return self


class DiscoveryBatchOutputV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["4"] = "4"
    batch_id: SafeIdentifier
    batch_context: TimeRangeV4
    ownership_interval: TimeRangeV4
    logical_windows: tuple[LogicalWindowDiscoveryV4, ...] = Field(min_length=1, max_length=4)
    candidates: tuple[DiscoveryCandidateV4, ...] = Field(default_factory=tuple, max_length=160)
    topic_fragments: tuple[TopicFragmentV4, ...] = Field(default_factory=tuple, max_length=200)


class LinkRelationshipV4(StrEnum):
    CONTINUATION = "continuation"
    SUPPORTING_EXAMPLE = "supporting_example"
    NEXT_STEP_SAME_LESSON = "next_step_same_lesson"
    SUMMARY_SAME_LESSON = "summary_same_lesson"
    ADJACENT_BUT_INDEPENDENT = "adjacent_but_independent"
    TOPIC_SWITCH = "topic_switch"
    UNCERTAIN = "uncertain"


LINKING_RELATIONSHIPS = frozenset(
    {
        LinkRelationshipV4.CONTINUATION,
        LinkRelationshipV4.SUPPORTING_EXAMPLE,
        LinkRelationshipV4.NEXT_STEP_SAME_LESSON,
        LinkRelationshipV4.SUMMARY_SAME_LESSON,
    }
)


class LinkReviewRequestV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    link_review_id: SafeIdentifier
    boundary_ms: int = Field(ge=0)
    context_range: TimeRangeV4
    left_window_id: SafeIdentifier
    right_window_id: SafeIdentifier
    left_fragment: TopicFragmentV4
    right_fragment: TopicFragmentV4


class LinkReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    link_review_id: SafeIdentifier
    left_fragment_id: SafeIdentifier
    right_fragment_id: SafeIdentifier
    same_topic: bool
    same_central_objective: bool
    relationship: LinkRelationshipV4
    merged_topic_summary: BoundedText = Field(max_length=400)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    topic_closed_on_right: bool
    needs_next_boundary: bool
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_relationship(self) -> LinkReviewV4:
        should_link = self.same_topic and self.same_central_objective
        if should_link != (self.relationship in LINKING_RELATIONSHIPS):
            raise ValueError("link relationship contradicts same-topic/objective decision")
        if self.topic_closed_on_right and self.needs_next_boundary:
            raise ValueError("a topic closed on the right cannot require another boundary")
        return self


class TopicChainStatusV4(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    REJECTED = "rejected"


class TopicChainV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic_chain_id: SafeIdentifier
    fragment_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=200)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    topic_outline: tuple[BoundedText, ...] = Field(min_length=1, max_length=30)
    source_start_cue_id: int = Field(ge=1)
    source_end_cue_id: int = Field(ge=1)
    left_closed: bool
    right_closed: bool
    chain_status: TopicChainStatusV4
    link_review_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=200)

    @model_validator(mode="after")
    def validate_chain(self) -> TopicChainV4:
        if self.source_end_cue_id < self.source_start_cue_id:
            raise ValueError("Topic Chain cue range is reversed")
        if self.chain_status == TopicChainStatusV4.CLOSED and not (
            self.left_closed and self.right_closed
        ):
            raise ValueError("closed Topic Chain requires both semantic sides to be closed")
        return self


class ChainCandidateV4(BaseModel):
    """Agent-authored candidate or natural subunit derived from one Topic Chain."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: SafeIdentifier
    clip_profile: ClipProfile
    source_topic_id: SafeIdentifier
    topic_chain_id: SafeIdentifier
    source_fragment_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=200)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    title: BoundedText = Field(max_length=40)
    summary: BoundedText = Field(max_length=600)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=200)
    natural_subunit: bool = False
    natural_split_evidence_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    variant_of: SafeIdentifier | None = None
    variant_relationship: Literal["short_version_of", "long_version_of"] | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> ChainCandidateV4:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("chain candidate cue range is reversed")
        if self.natural_subunit and not self.natural_split_evidence_cue_ids:
            raise ValueError("a natural subunit requires semantic split evidence")
        if (self.variant_of is None) != (self.variant_relationship is None):
            raise ValueError("cross-profile variant relation requires both fields")
        return self


class TopicChainReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic_chain_id: SafeIdentifier
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    topic_outline: tuple[BoundedText, ...] = Field(min_length=1, max_length=30)
    left_closed: bool
    right_closed: bool
    chain_status: TopicChainStatusV4
    candidates: tuple[ChainCandidateV4, ...] = Field(default_factory=tuple, max_length=40)
    rejection_reason: (
        Literal[
            "topic_too_long_without_natural_split",
            "topic_not_closed",
            "no_complete_profile_candidate",
            "not_a_single_teaching_objective",
        ]
        | None
    ) = None
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_disposition(self) -> TopicChainReviewV4:
        if self.candidates and self.rejection_reason is not None:
            raise ValueError("a chain with candidates cannot also have a rejection reason")
        if not self.candidates and self.rejection_reason is None:
            raise ValueError("a chain without candidates requires an auditable rejection reason")
        if self.chain_status == TopicChainStatusV4.CLOSED and not (
            self.left_closed and self.right_closed
        ):
            raise ValueError("closed chain review requires both sides closed")
        return self


class InterruptionSeverityV4(StrEnum):
    NONE = "none"
    MINOR = "minor"
    MATERIAL = "material"


class InterruptionReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    severity: InterruptionSeverityV4
    type: SafeIdentifier
    evidence_cue_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=80)
    description: BoundedText = Field(max_length=400)
    blocking: bool

    @model_validator(mode="after")
    def validate_severity(self) -> InterruptionReviewV4:
        if self.severity == InterruptionSeverityV4.NONE and (
            self.blocking or self.evidence_cue_ids
        ):
            raise ValueError("none interruption cannot be blocking or cite interruption evidence")
        if self.severity == InterruptionSeverityV4.MATERIAL and not self.blocking:
            raise ValueError("unresolved material interruption must be blocking")
        return self


class QualityFlagV4(StrEnum):
    CONTEXT_DEPENDENT_OPENING = "context_dependent_opening"
    INCOMPLETE_ENDING = "incomplete_ending"
    IRRELEVANT_INTRO = "irrelevant_intro"
    IRRELEVANT_OUTRO = "irrelevant_outro"
    IRRELEVANT_INTERNAL_CONTENT = "irrelevant_internal_content"
    REPEATED_LIVE_CTA = "repeated_live_cta"
    EQUIPMENT_INTERRUPTION = "equipment_interruption"
    PADDED_TO_MIN_DURATION = "padded_to_min_duration"
    OVEREXTENDED_TO_MAX_DURATION = "overextended_to_max_duration"
    TOPIC_MIXED = "topic_mixed"
    TITLE_SOURCE_MISMATCH = "title_source_mismatch"
    ASR_MEANING_REVERSAL = "asr_meaning_reversal"
    DUPLICATE_WEAKER = "duplicate_weaker"
    CENTRAL_OBJECTIVE_INCOMPLETE = "central_objective_incomplete"
    MULTI_INTERVAL_EDIT = "multi_interval_edit"
    TOPIC_TOO_LONG_WITHOUT_NATURAL_SPLIT = "topic_too_long_without_natural_split"


BLOCKING_QUALITY_FLAGS_V4 = frozenset(QualityFlagV4)


class RiskFlagV4(StrEnum):
    MEDICAL_CLAIM = "medical_claim"
    HEALTH_ADVICE = "health_advice"
    ABSOLUTE_CLAIM = "absolute_claim"
    COMMERCIAL_CLAIM = "commercial_claim"
    SENSITIVITY_REVIEW = "sensitivity_review"
    MUSIC_RIGHTS_REVIEW = "music_rights_review"
    MINOR_PRIVACY = "minor_privacy"
    ASR_UNCERTAIN = "asr_uncertain"


class BoundaryEvidenceV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    opening_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=80)
    core_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=160)
    ending_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=80)


class ContentDecisionV4(StrEnum):
    KEEP = "keep"
    REPAIR_BOUNDARY = "repair_boundary"
    DROP = "drop"


class BoundaryReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: SafeIdentifier
    clip_profile: ClipProfile
    content_decision: ContentDecisionV4
    proposed_start_cue_id: int | None = Field(default=None, ge=1)
    proposed_end_cue_id: int | None = Field(default=None, ge=1)
    opening_complete: bool
    ending_complete: bool
    central_objective_complete: bool
    boundary_compactness: Literal["shortest_complete", "contains_removable_context"]
    opening_relevance: Literal["direct", "necessary_context", "irrelevant"]
    ending_relevance: Literal["necessary_conclusion", "redundant", "incomplete"]
    internal_topic_switch: bool
    contains_padding: bool
    continuous_source_interval: bool = True
    interruption_review: tuple[InterruptionReviewV4, ...] = Field(
        default_factory=tuple, max_length=30
    )
    quality_flags: tuple[QualityFlagV4, ...] = Field(default_factory=tuple, max_length=30)
    risk_flags: tuple[RiskFlagV4, ...] = Field(default_factory=tuple, max_length=20)
    evidence: BoundaryEvidenceV4
    review_reason: BoundedText = Field(max_length=800)

    @model_validator(mode="after")
    def validate_boundary(self) -> BoundaryReviewV4:
        if (self.proposed_start_cue_id is None) != (self.proposed_end_cue_id is None):
            raise ValueError("boundary proposal requires both cue IDs")
        if self.content_decision != ContentDecisionV4.DROP and self.proposed_start_cue_id is None:
            raise ValueError("kept or repaired boundary requires one concrete interval")
        if not self.continuous_source_interval and QualityFlagV4.MULTI_INTERVAL_EDIT not in (
            self.quality_flags
        ):
            raise ValueError("a non-continuous proposal must expose multi_interval_edit")
        return self


class ShortHighlightScoresV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    independence: int = Field(ge=0, le=20)
    completeness: int = Field(ge=0, le=20)
    single_topic: int = Field(ge=0, le=15)
    viewer_value: int = Field(ge=0, le=20)
    source_fidelity: int = Field(ge=0, le=15)
    edit_cleanliness: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class MiniLessonScoresV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    central_objective_clarity: int = Field(ge=0, le=20)
    completeness_and_closure: int = Field(ge=0, le=20)
    teaching_structure: int = Field(ge=0, le=15)
    standalone_understanding: int = Field(ge=0, le=15)
    information_density: int = Field(ge=0, le=10)
    edit_cleanliness: int = Field(ge=0, le=10)
    title_summary_fidelity: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


ScoreDimensionsV4 = ShortHighlightScoresV4 | MiniLessonScoresV4


class PublishStatusV4(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    BLOCKED = "blocked"


class CandidateGlobalReviewV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: SafeIdentifier
    clip_profile: ClipProfile
    source_topic_id: SafeIdentifier
    topic_chain_id: SafeIdentifier
    source_fragment_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=200)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    title: BoundedText = Field(max_length=40)
    summary: BoundedText = Field(max_length=600)
    content_decision: ContentDecisionV4
    publish_status: PublishStatusV4
    quality_flags: tuple[QualityFlagV4, ...] = Field(default_factory=tuple, max_length=30)
    risk_flags: tuple[RiskFlagV4, ...] = Field(default_factory=tuple, max_length=20)
    interruption_review: tuple[InterruptionReviewV4, ...] = Field(
        default_factory=tuple, max_length=30
    )
    scores: ScoreDimensionsV4
    total_score: int = Field(ge=0, le=100)
    duplicate_group_id: SafeIdentifier | None = None
    duplicate_of: SafeIdentifier | None = None
    variant_of: SafeIdentifier | None = None
    variant_relationship: Literal["short_version_of", "long_version_of"] | None = None
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=200)
    review_reason: BoundedText = Field(max_length=800)

    @model_validator(mode="after")
    def validate_review(self) -> CandidateGlobalReviewV4:
        if self.total_score != self.scores.total:
            raise ValueError("total_score must equal the deterministic score dimensions")
        if self.clip_profile == ClipProfile.SHORT_HIGHLIGHT and not isinstance(
            self.scores, ShortHighlightScoresV4
        ):
            raise ValueError("short_highlight requires the short scorecard")
        if self.clip_profile == ClipProfile.MINI_LESSON and not isinstance(
            self.scores, MiniLessonScoresV4
        ):
            raise ValueError("mini_lesson requires the mini-lesson scorecard")
        if self.duplicate_of == self.candidate_id:
            raise ValueError("a duplicate cannot reference itself")
        duplicate_flagged = QualityFlagV4.DUPLICATE_WEAKER in self.quality_flags
        if (self.duplicate_of is None) == duplicate_flagged:
            raise ValueError(
                "duplicate_of and duplicate_weaker must describe the same weaker duplicate"
            )
        if self.duplicate_of is not None and self.duplicate_group_id is None:
            raise ValueError("a weaker duplicate requires duplicate_group_id audit provenance")
        if (self.variant_of is None) != (self.variant_relationship is None):
            raise ValueError("variant relation requires both fields")
        return self


class GlobalReviewOutputV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["4"] = "4"
    clip_profile: ClipProfile
    reviews: tuple[CandidateGlobalReviewV4, ...] = Field(min_length=1, max_length=200)
    global_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=80)


class CandidateDispositionV4(StrEnum):
    SELECTED = "selected"
    MANUAL = "manual"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    TOP_N_EXCLUDED = "top_n_excluded"


class ValidatedCandidateV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    review: CandidateGlobalReviewV4
    disposition: CandidateDispositionV4
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    validation_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=40)


class ProfileStatisticsV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    discovery_candidate_count: int = Field(ge=0)
    boundary_candidate_count: int = Field(ge=0)
    qualified_before_top_n: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    manual_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    top_n_excluded_count: int = Field(ge=0)


class ValidatedProfileResultV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected: tuple[ValidatedCandidateV4, ...] = ()
    manual_review: tuple[ValidatedCandidateV4, ...] = ()
    blocked: tuple[ValidatedCandidateV4, ...] = ()
    rejected: tuple[ValidatedCandidateV4, ...] = ()
    top_n_excluded: tuple[ValidatedCandidateV4, ...] = ()
    statistics: ProfileStatisticsV4


class CoverageDecisionV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_id: SafeIdentifier
    source_kind: Literal["candidate", "fragment", "topic_chain"]
    destination_id: SafeIdentifier | None = None
    disposition: Literal[
        "discovered",
        "linked",
        "chain_candidate",
        "selected",
        "manual",
        "blocked",
        "rejected",
        "top_n_excluded",
    ]
    reason: BoundedText = Field(max_length=600)


class UnifiedSemanticResultV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["4"] = "4"
    run_metadata: dict[str, object]
    profiles: dict[ClipProfile, ValidatedProfileResultV4]
    topic_chains: tuple[TopicChainV4, ...]
    coverage_decisions: tuple[CoverageDecisionV4, ...]
    validation_notes: tuple[str, ...]
    global_review_summary: dict[str, object]


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parents = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parents[value]
        if parent != value:
            self.parents[value] = self.find(parent)
        return self.parents[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parents[right_root] = left_root


def validate_discovery_batch_v4(
    output: DiscoveryBatchOutputV4,
    *,
    expected_batch_id: str,
    expected_context: TimeRangeV4,
    expected_ownership: TimeRangeV4,
    expected_windows: Sequence[TimeRangeV4],
    transcript: TranscriptDocument,
    available_cue_ids: Sequence[int] | None = None,
) -> DiscoveryBatchOutputV4:
    """Validate transport ownership and source references, never semantic quality."""

    if output.batch_id != expected_batch_id:
        raise ValueError("Discovery batch ID does not match the request")
    if output.batch_context != expected_context or output.ownership_interval != expected_ownership:
        raise ValueError("Discovery batch context or ownership interval changed")
    actual_windows = tuple(
        TimeRangeV4(start_ms=value.window_start_ms, end_ms=value.window_end_ms)
        for value in output.logical_windows
    )
    if actual_windows != tuple(expected_windows):
        raise ValueError("Discovery must report every logical window exactly once")
    cue_map = _cue_map(transcript)
    if available_cue_ids is not None:
        allowed_cues = set(available_cue_ids)
        cue_map = {key: value for key, value in cue_map.items() if key in allowed_cues}
    window_ids = [value.logical_window_id for value in output.logical_windows]
    candidate_ids = [value.candidate_id for value in output.candidates]
    fragment_ids = [value.topic_fragment_id for value in output.topic_fragments]
    if len(window_ids) != len(set(window_ids)):
        raise ValueError("Discovery logical window IDs must be unique")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Discovery candidate IDs must be unique within a batch")
    if len(fragment_ids) != len(set(fragment_ids)):
        raise ValueError("Discovery fragment IDs must be unique within a batch")
    windows = {value.logical_window_id: value for value in output.logical_windows}
    fragments = {value.topic_fragment_id: value for value in output.topic_fragments}
    candidates = {value.candidate_id: value for value in output.candidates}
    for window in output.logical_windows:
        if any(value not in candidates for value in window.candidate_ids):
            raise ValueError("logical window references an unknown candidate")
        if any(value not in fragments for value in window.fragment_ids):
            raise ValueError("logical window references an unknown fragment")
        boundary_refs = {
            *window.left_boundary.related_fragment_ids,
            *window.right_boundary.related_fragment_ids,
        }
        if any(value not in fragments for value in boundary_refs):
            raise ValueError("logical boundary references an unknown fragment")
    for fragment in output.topic_fragments:
        if fragment.logical_window_id not in windows:
            raise ValueError("topic fragment references an unknown logical window")
        if fragment.source_batch_id != output.batch_id:
            raise ValueError("topic fragment source batch changed")
        _validate_cue_interval(fragment.start_cue_id, fragment.end_cue_id, cue_map)
        _validate_known_cues(fragment.evidence_cue_ids, cue_map)
    for candidate in output.candidates:
        if candidate.source_batch_id != output.batch_id:
            raise ValueError("Discovery candidate source batch changed")
        if any(value not in fragments for value in candidate.topic_fragment_ids):
            raise ValueError("Discovery candidate references an unknown fragment")
        if any(value not in windows for value in candidate.source_window_ids):
            raise ValueError("Discovery candidate references an unknown logical window")
        start, _end = _validate_cue_interval(candidate.start_cue_id, candidate.end_cue_id, cue_map)
        if not expected_ownership.start_ms <= start.start_ms < expected_ownership.end_ms:
            raise ValueError("Discovery candidate start is outside deterministic batch ownership")
        _validate_known_cues(candidate.evidence_cue_ids, cue_map)
    return output


def namespace_discovery_batch_v4(
    output: DiscoveryBatchOutputV4,
) -> tuple[DiscoveryBatchOutputV4, tuple[str, ...]]:
    """Namespace transport-local IDs without changing any semantic fact."""

    prefix = f"{output.batch_id}_"

    def namespaced(value: str) -> str:
        return value if value.startswith(prefix) else f"{prefix}{value}"

    fragment_map = {
        value.topic_fragment_id: namespaced(value.topic_fragment_id)
        for value in output.topic_fragments
    }
    candidate_map = {
        value.candidate_id: namespaced(value.candidate_id) for value in output.candidates
    }
    topic_ids = {value.source_topic_id for value in output.candidates}
    topic_map = {value: namespaced(value) for value in topic_ids}
    changed = any(key != value for key, value in (*fragment_map.items(), *candidate_map.items()))
    fragments = tuple(
        value.model_copy(update={"topic_fragment_id": fragment_map[value.topic_fragment_id]})
        for value in output.topic_fragments
    )
    candidates = tuple(
        value.model_copy(
            update={
                "candidate_id": candidate_map[value.candidate_id],
                "source_topic_id": topic_map[value.source_topic_id],
                "topic_fragment_ids": tuple(
                    fragment_map[item] for item in value.topic_fragment_ids
                ),
            }
        )
        for value in output.candidates
    )

    def boundary(value: TopicBoundaryV4) -> TopicBoundaryV4:
        return value.model_copy(
            update={
                "related_candidate_ids": tuple(
                    candidate_map[item] for item in value.related_candidate_ids
                ),
                "related_fragment_ids": tuple(
                    fragment_map[item] for item in value.related_fragment_ids
                ),
            }
        )

    windows = tuple(
        value.model_copy(
            update={
                "candidate_ids": tuple(candidate_map[item] for item in value.candidate_ids),
                "fragment_ids": tuple(fragment_map[item] for item in value.fragment_ids),
                "left_boundary": boundary(value.left_boundary),
                "right_boundary": boundary(value.right_boundary),
            }
        )
        for value in output.logical_windows
    )
    normalized = output.model_copy(
        update={
            "logical_windows": windows,
            "candidates": candidates,
            "topic_fragments": fragments,
        }
    )
    return normalized, (("transport_ids_namespaced",) if changed else ())


def plan_link_review_requests_v4(
    outputs: Sequence[DiscoveryBatchOutputV4],
) -> tuple[LinkReviewRequestV4, ...]:
    """Route adjacent-window evidence using Agent boundary facts only.

    The 90-second context on each side is transport selection. No time distance,
    overlap, text, or cue similarity decides whether fragments belong together.
    """

    windows: list[tuple[LogicalWindowDiscoveryV4, Mapping[str, TopicFragmentV4]]] = []
    for output in outputs:
        batch_fragments = {value.topic_fragment_id: value for value in output.topic_fragments}
        windows.extend((window, batch_fragments) for window in output.logical_windows)
    windows.sort(key=lambda value: (value[0].window_start_ms, value[0].logical_window_id))
    unique_windows: list[tuple[LogicalWindowDiscoveryV4, Mapping[str, TopicFragmentV4]]] = []
    seen: set[tuple[int, int]] = set()
    for window, window_fragments in windows:
        window_identity = (window.window_start_ms, window.window_end_ms)
        if window_identity in seen:
            continue
        seen.add(window_identity)
        unique_windows.append((window, window_fragments))
    planned: dict[tuple[str, str], LinkReviewRequestV4] = {}
    for (left, left_fragments), (right, right_fragments) in pairwise(unique_windows):
        if not (
            left.right_boundary.topic_unfinished or right.left_boundary.continues_previous_topic
        ):
            continue
        # A single open-side report is sufficient to schedule the review. The
        # opposite window's fragments are transport candidates only; the Agent
        # still decides whether any pair shares a topic/objective.
        left_ids = left.right_boundary.related_fragment_ids or left.fragment_ids
        right_ids = right.left_boundary.related_fragment_ids or right.fragment_ids
        for left_id in left_ids:
            for right_id in right_ids:
                pair = (left_id, right_id)
                if pair in planned:
                    continue
                link_identity = hashlib.sha256("\0".join(pair).encode()).hexdigest()[:16]
                boundary_ms = right.window_start_ms
                context_start_ms = max(0, boundary_ms - 90_000)
                planned[pair] = LinkReviewRequestV4(
                    link_review_id=f"link_{link_identity}",
                    boundary_ms=boundary_ms,
                    context_range=TimeRangeV4(
                        start_ms=context_start_ms,
                        end_ms=max(boundary_ms + 90_000, context_start_ms + 180_000),
                    ),
                    left_window_id=left.logical_window_id,
                    right_window_id=right.logical_window_id,
                    left_fragment=left_fragments[left_id],
                    right_fragment=right_fragments[right_id],
                )
    return tuple(
        sorted(planned.values(), key=lambda value: (value.boundary_ms, value.link_review_id))
    )


def plan_followup_link_review_requests_v4(
    outputs: Sequence[DiscoveryBatchOutputV4],
    *,
    existing_requests: Sequence[LinkReviewRequestV4],
    completed_reviews: Sequence[LinkReviewV4],
) -> tuple[LinkReviewRequestV4, ...]:
    """Route the next boundary only when an Agent says the linked topic remains open."""

    windows: list[tuple[LogicalWindowDiscoveryV4, Mapping[str, TopicFragmentV4]]] = []
    for output in outputs:
        batch_fragments = {value.topic_fragment_id: value for value in output.topic_fragments}
        windows.extend((window, batch_fragments) for window in output.logical_windows)
    windows.sort(key=lambda item: (item[0].window_start_ms, item[0].logical_window_id))
    unique: list[tuple[LogicalWindowDiscoveryV4, Mapping[str, TopicFragmentV4]]] = []
    seen_windows: set[tuple[int, int]] = set()
    for window, fragments in windows:
        identity = (window.window_start_ms, window.window_end_ms)
        if identity not in seen_windows:
            seen_windows.add(identity)
            unique.append((window, fragments))
    fragment_window_index = {
        fragment_id: index
        for index, (window, _fragments) in enumerate(unique)
        for fragment_id in window.fragment_ids
    }
    existing_pairs = {
        (value.left_fragment.topic_fragment_id, value.right_fragment.topic_fragment_id)
        for value in existing_requests
    }
    fragment_map = {
        value.topic_fragment_id: value for output in outputs for value in output.topic_fragments
    }
    planned: list[LinkReviewRequestV4] = []
    for review in completed_reviews:
        if not (review.same_topic and review.same_central_objective and review.needs_next_boundary):
            continue
        window_index = fragment_window_index.get(review.right_fragment_id)
        if window_index is None or window_index + 1 >= len(unique):
            continue
        left_window, _left_fragments = unique[window_index]
        right_window, _right_fragments = unique[window_index + 1]
        for right_id in right_window.fragment_ids:
            pair = (review.right_fragment_id, right_id)
            if pair in existing_pairs:
                continue
            link_identity = hashlib.sha256("\0".join(pair).encode()).hexdigest()[:16]
            boundary_ms = right_window.window_start_ms
            context_start_ms = max(0, boundary_ms - 90_000)
            planned.append(
                LinkReviewRequestV4(
                    link_review_id=f"link_{link_identity}",
                    boundary_ms=boundary_ms,
                    context_range=TimeRangeV4(
                        start_ms=context_start_ms,
                        end_ms=max(boundary_ms + 90_000, context_start_ms + 180_000),
                    ),
                    left_window_id=left_window.logical_window_id,
                    right_window_id=right_window.logical_window_id,
                    left_fragment=fragment_map[review.right_fragment_id],
                    right_fragment=fragment_map[right_id],
                )
            )
            existing_pairs.add(pair)
    return tuple(sorted(planned, key=lambda value: (value.boundary_ms, value.link_review_id)))


def validate_link_review_v4(
    review: LinkReviewV4,
    *,
    request: LinkReviewRequestV4,
    transcript: TranscriptDocument,
) -> LinkReviewV4:
    if (
        review.link_review_id != request.link_review_id
        or review.left_fragment_id != request.left_fragment.topic_fragment_id
        or review.right_fragment_id != request.right_fragment.topic_fragment_id
    ):
        raise ValueError("Link Review changed its deterministic request identity")
    cue_map = {
        value.cue_id: value
        for value in transcript_cues(transcript)
        if value.end_ms > request.context_range.start_ms
        and value.start_ms < request.context_range.end_ms
    }
    _validate_known_cues(review.evidence_cue_ids, cue_map)
    return review


def assemble_topic_chains_v4(
    fragments: Sequence[TopicFragmentV4],
    link_reviews: Sequence[LinkReviewV4],
) -> tuple[TopicChainV4, ...]:
    """Build graph components only from explicit positive Agent link decisions."""

    fragment_map = {value.topic_fragment_id: value for value in fragments}
    if len(fragment_map) != len(fragments):
        raise ValueError("Topic Fragment IDs must be globally unique")
    links_by_id: dict[str, LinkReviewV4] = {}
    union = _UnionFind(fragment_map)
    for review in link_reviews:
        if review.link_review_id in links_by_id:
            raise ValueError("Link Review IDs must be unique")
        links_by_id[review.link_review_id] = review
        if (
            review.left_fragment_id not in fragment_map
            or review.right_fragment_id not in fragment_map
        ):
            raise ValueError("Link Review references an unknown Topic Fragment")
        if review.same_topic and review.same_central_objective:
            union.union(review.left_fragment_id, review.right_fragment_id)
    groups: dict[str, list[TopicFragmentV4]] = {}
    for fragment in fragments:
        groups.setdefault(union.find(fragment.topic_fragment_id), []).append(fragment)
    chains: list[TopicChainV4] = []
    for values in groups.values():
        values.sort(
            key=lambda value: (
                value.start_cue_id,
                value.end_cue_id,
                value.topic_fragment_id,
            )
        )
        fragment_ids = tuple(value.topic_fragment_id for value in values)
        fragment_id_set = set(fragment_ids)
        relevant_links = tuple(
            review
            for review in link_reviews
            if review.same_topic
            and review.same_central_objective
            and review.left_fragment_id in fragment_id_set
            and review.right_fragment_id in fragment_id_set
        )
        topic_source = relevant_links[-1] if relevant_links else None
        central_question = (
            topic_source.central_question
            if topic_source is not None
            else values[0].central_question
        )
        learning_outcome = (
            topic_source.learning_outcome
            if topic_source is not None
            else values[0].learning_outcome
        )
        left_closed = values[0].left_complete
        right_closed = values[-1].right_complete
        if relevant_links and relevant_links[-1].topic_closed_on_right:
            right_closed = True
        chain_hash = hashlib.sha256("\0".join(fragment_ids).encode()).hexdigest()[:16]
        chains.append(
            TopicChainV4(
                topic_chain_id=f"chain_{chain_hash}",
                fragment_ids=fragment_ids,
                central_question=central_question,
                learning_outcome=learning_outcome,
                topic_outline=tuple(dict.fromkeys(value.topic_summary for value in values)),
                source_start_cue_id=min(value.start_cue_id for value in values),
                source_end_cue_id=max(value.end_cue_id for value in values),
                left_closed=left_closed,
                right_closed=right_closed,
                chain_status=(
                    TopicChainStatusV4.CLOSED
                    if left_closed and right_closed
                    else TopicChainStatusV4.OPEN
                ),
                link_review_ids=tuple(value.link_review_id for value in relevant_links),
            )
        )
    return tuple(
        sorted(chains, key=lambda value: (value.source_start_cue_id, value.topic_chain_id))
    )


def validate_topic_chain_review_v4(
    review: TopicChainReviewV4,
    *,
    chain: TopicChainV4,
    transcript: TranscriptDocument,
) -> TopicChainReviewV4:
    if review.topic_chain_id != chain.topic_chain_id:
        raise ValueError("Topic Chain review ID does not match its input")
    transcript_cue_map = _cue_map(transcript)
    chain_start, chain_end = _validate_cue_interval(
        chain.source_start_cue_id, chain.source_end_cue_id, transcript_cue_map
    )
    chain_duration_ms = chain_end.end_ms - chain_start.start_ms
    cue_map = {
        cue_id: cue
        for cue_id, cue in transcript_cue_map.items()
        if cue.end_ms > chain_start.start_ms and cue.start_ms < chain_end.end_ms
    }
    _validate_known_cues(review.evidence_cue_ids, cue_map)
    candidate_ids: set[str] = set()
    for candidate in review.candidates:
        if candidate.candidate_id in candidate_ids:
            raise ValueError("Topic Chain candidate IDs must be unique")
        candidate_ids.add(candidate.candidate_id)
        if candidate.topic_chain_id != chain.topic_chain_id:
            raise ValueError("Topic Chain candidate references another chain")
        if not set(candidate.source_fragment_ids).issubset(chain.fragment_ids):
            raise ValueError("Topic Chain candidate references an unknown chain fragment")
        start, end = _validate_cue_interval(candidate.start_cue_id, candidate.end_cue_id, cue_map)
        if (
            candidate.start_cue_id < chain.source_start_cue_id
            or candidate.end_cue_id > chain.source_end_cue_id
        ):
            raise ValueError("Topic Chain candidate escapes the reviewed chain")
        duration_ms = end.end_ms - start.start_ms
        spec = clip_profile_spec(candidate.clip_profile)
        if not spec.minimum_duration_ms <= duration_ms <= spec.maximum_duration_ms:
            raise ValueError("Topic Chain candidate duration is outside its profile")
        _validate_known_cues(candidate.evidence_cue_ids, cue_map)
        _validate_known_cues(candidate.natural_split_evidence_cue_ids, cue_map)
        if (
            chain_duration_ms > clip_profile_spec(ClipProfile.MINI_LESSON).maximum_duration_ms
            and candidate.clip_profile == ClipProfile.MINI_LESSON
            and not candidate.natural_subunit
        ):
            raise ValueError("a >300s chain requires Agent-authored natural teaching subunits")
    if (
        chain_duration_ms > clip_profile_spec(ClipProfile.MINI_LESSON).maximum_duration_ms
        and not review.candidates
        and review.rejection_reason != "topic_too_long_without_natural_split"
    ):
        raise ValueError("an unsplit >300s chain requires the explicit too-long rejection")
    return review


def boundary_consistency_errors_v4(value: Mapping[str, object]) -> list[str]:
    """Check explicit model facts, including partially schema-invalid JSON.

    No text interpretation, repair, or semantic defaulting occurs here. Reverse
    implications are intentionally not inferred from broader quality flags.
    """

    flags = _raw_quality_flags_v4(value)
    required: list[str] = []
    for field, flag in (
        ("opening_complete", "context_dependent_opening"),
        ("ending_complete", "incomplete_ending"),
        ("central_objective_complete", "central_objective_incomplete"),
        ("continuous_source_interval", "multi_interval_edit"),
    ):
        if value.get(field) is False:
            required.append(flag)
    for field, flag in (
        ("contains_padding", "padded_to_min_duration"),
        ("internal_topic_switch", "topic_mixed"),
    ):
        if value.get(field) is True:
            required.append(flag)
    for field, expected, flag in (
        ("opening_relevance", "irrelevant", "irrelevant_intro"),
        ("ending_relevance", "redundant", "irrelevant_outro"),
        ("ending_relevance", "incomplete", "incomplete_ending"),
    ):
        if value.get(field) == expected:
            required.append(flag)
    errors = [
        f"Boundary quality consistency: explicit fact requires {flag}"
        for flag in sorted(set(required) - flags)
    ]
    if value.get("ending_relevance") == "incomplete" and value.get("ending_complete") is True:
        errors.append("Boundary quality consistency: incomplete ending cannot be ending_complete")
    if value.get("boundary_compactness") == "contains_removable_context" and value.get(
        "content_decision"
    ) in ("keep", "repair_boundary"):
        errors.append("Boundary quality consistency: retained interval must be shortest_complete")
    if "proposed_start_cue_id" in value and "proposed_end_cue_id" in value:
        start, end = value["proposed_start_cue_id"], value["proposed_end_cue_id"]
        if (start is None and type(end) is int) or (type(start) is int and end is None):
            errors.append("boundary proposal requires both cue IDs")
        if start is None and value.get("content_decision") in ("keep", "repair_boundary"):
            errors.append("kept or repaired boundary requires one concrete interval")
    errors.extend(interruption_consistency_errors_v4(value))
    return errors


def _raw_quality_flags_v4(value: Mapping[str, object]) -> set[str]:
    raw = value.get("quality_flags")
    return {flag for flag in raw if isinstance(flag, str)} if isinstance(raw, list) else set()


def interruption_consistency_errors_v4(value: Mapping[str, object]) -> list[str]:
    errors = []
    raw = value.get("interruption_review")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence_cue_ids")
        if item.get("severity") == "none" and (
            item.get("blocking") is True or (isinstance(evidence, list) and bool(evidence))
        ):
            errors.append("none interruption cannot be blocking or cite interruption evidence")
        if item.get("severity") == "material" and item.get("blocking") is False:
            errors.append("unresolved material interruption must be blocking")
    return errors


def global_cross_field_errors_v4(value: Mapping[str, object]) -> list[str]:
    """Collect independent wire invariants even when another field is invalid."""

    errors = interruption_consistency_errors_v4(value)
    raw_scores = value.get("scores")
    if isinstance(raw_scores, dict):
        for profile, model in (
            ("short_highlight", ShortHighlightScoresV4),
            ("mini_lesson", MiniLessonScoresV4),
        ):
            try:
                scores = model.model_validate_json(json.dumps(raw_scores))
            except ValueError:
                continue
            if type(value.get("total_score")) is int and value["total_score"] != scores.total:
                errors.append("total_score must equal the deterministic score dimensions")
            actual_profile = value.get("clip_profile")
            if actual_profile in ("short_highlight", "mini_lesson") and actual_profile != profile:
                errors.append(
                    "mini_lesson requires the mini-lesson scorecard"
                    if actual_profile == "mini_lesson"
                    else "short_highlight requires the short scorecard"
                )
            break
    target = value.get("duplicate_of")
    if isinstance(target, str) and target == value.get("candidate_id"):
        errors.append("a duplicate cannot reference itself")
    if "duplicate_of" in value and (target is None or isinstance(target, str)):
        if isinstance(value.get("quality_flags"), list) and (
            (target is None) == ("duplicate_weaker" in _raw_quality_flags_v4(value))
        ):
            errors.append(
                "duplicate_of and duplicate_weaker must describe the same weaker duplicate"
            )
        if (
            isinstance(target, str)
            and "duplicate_group_id" in value
            and value["duplicate_group_id"] is None
        ):
            errors.append("a weaker duplicate requires duplicate_group_id audit provenance")
    if (
        "variant_of" in value
        and "variant_relationship" in value
        and (value["variant_of"] is None or isinstance(value["variant_of"], str))
        and value["variant_relationship"] in (None, "short_version_of", "long_version_of")
        and (value["variant_of"] is None) != (value["variant_relationship"] is None)
    ):
        errors.append("variant relation requires both fields")
    return errors


def duplicate_representative_errors_v4(
    reviews: Sequence[Mapping[str, object]], rejected_ids: set[str]
) -> list[str]:
    """Require direct, retained representatives; never choose one in code."""

    by_id = {
        identifier: review
        for review in reviews
        if isinstance(identifier := review.get("candidate_id"), str)
    }
    errors = []
    for review in reviews:
        target = review.get("duplicate_of")
        if not isinstance(target, str):
            continue
        representative = by_id.get(target)
        if (
            representative is None
            or target in rejected_ids
            or representative.get("duplicate_of") is not None
            or "duplicate_weaker" in _raw_quality_flags_v4(representative)
        ):
            errors.append(
                f"{review.get('candidate_id')}: duplicate representative must be a stronger "
                "retained candidate"
            )
    return errors


def quality_preflight_errors_v4(request: Mapping[str, object], output: object) -> list[str]:
    """Collect available v2 facts before the provider spends its sole repair."""

    if request.get("validation_contract") != CURRENT_SEMANTIC_VALIDATION:
        return []
    if not isinstance(output, dict):
        return []
    if request.get("stage") == "boundary_review":
        errors = boundary_consistency_errors_v4(output)
        candidate = request.get("candidate")
        if isinstance(candidate, dict):
            for field in ("candidate_id", "clip_profile"):
                if field in output and field in candidate and output[field] != candidate[field]:
                    errors.append(f"Boundary Review {field} does not match its input")
            proposed = (output.get("proposed_start_cue_id"), output.get("proposed_end_cue_id"))
            original = (candidate.get("start_cue_id"), candidate.get("end_cue_id"))
            if all(type(value) is int for value in (*proposed, *original)):
                if output.get("content_decision") == "keep" and proposed != original:
                    errors.append("keep must preserve the candidate interval")
                if output.get("content_decision") == "repair_boundary" and proposed == original:
                    errors.append("repair_boundary must change the interval")
        context = _raw_context_cues_v4(request.get("cues"))
        if context is not None:
            profile = (
                candidate.get("clip_profile")
                if isinstance(candidate, dict)
                else request.get("clip_profile")
            )
            expected_profile = (
                ClipProfile(profile)
                if isinstance(profile, str) and profile in {value.value for value in ClipProfile}
                else None
            )
            errors.extend(
                boundary_reference_errors_v4(output, context, expected_profile=expected_profile)
            )
        return errors
    if request.get("stage") != "global_review":
        return []
    raw_reviews = output.get("reviews")
    if not isinstance(raw_reviews, list):
        return []
    reviews = [review for review in raw_reviews if isinstance(review, dict)]
    raw_candidates = request.get("candidates")
    candidates = (
        {
            value["candidate_id"]: value
            for value in raw_candidates
            if isinstance(value, dict) and isinstance(value.get("candidate_id"), str)
        }
        if isinstance(raw_candidates, list)
        else {}
    )
    raw_boundaries = request.get("boundary_reviews")
    boundaries = (
        {
            value["candidate_id"]: value
            for value in raw_boundaries
            if isinstance(value, dict) and isinstance(value.get("candidate_id"), str)
        }
        if isinstance(raw_boundaries, list)
        else {}
    )
    rejected: set[str] = set()
    errors = []
    if "clip_profile" in output and output["clip_profile"] != request.get("clip_profile"):
        errors.append("Global Review profile does not match its request")
    if isinstance(raw_candidates, list):
        identifiers = [review.get("candidate_id") for review in reviews]
        known_identifiers = [value for value in identifiers if isinstance(value, str)]
        if set(known_identifiers) - set(candidates):
            errors.append("Global Review references unknown candidate IDs")
        if len(known_identifiers) != len(set(known_identifiers)):
            errors.append("Global Review contains duplicate candidate IDs")
        if len(known_identifiers) == len(identifiers) and set(known_identifiers) != set(candidates):
            errors.append("Global Review must return every Profile candidate exactly once")
    threshold = request.get("score_threshold_exclusive")
    raw_contexts = request.get("candidate_contexts")
    contexts = (
        {
            value["candidate_id"]: _raw_context_cues_v4(value.get("cues"))
            for value in raw_contexts
            if isinstance(value, dict) and isinstance(value.get("candidate_id"), str)
        }
        if isinstance(raw_contexts, list)
        else {}
    )
    for review in reviews:
        errors.extend(global_cross_field_errors_v4(review))
        identifier = review.get("candidate_id")
        if not isinstance(identifier, str):
            continue
        boundary = boundaries.get(identifier, {})
        candidate = candidates.get(identifier, {})
        context = contexts.get(identifier)
        if context is not None:
            errors.extend(global_reference_errors_v4(review, context))
        for field in ("clip_profile", "source_topic_id", "topic_chain_id", "source_fragment_ids"):
            if field not in review or field not in candidate:
                continue
            actual, expected = review[field], candidate[field]
            if field == "source_fragment_ids":
                if not isinstance(actual, list) or not isinstance(expected, list):
                    continue
                if not all(isinstance(value, str) for value in (*actual, *expected)):
                    continue
                actual, expected = set(actual), set(expected)
            if actual != expected:
                errors.append(f"{identifier}: Global Review changed {field} provenance")
        for edge in ("start", "end"):
            field = f"{edge}_cue_id"
            expected_cue = boundary.get(f"proposed_{field}") or candidate.get(field)
            if (
                type(review.get(field)) is int
                and type(expected_cue) is int
                and review[field] != expected_cue
            ):
                errors.append(
                    f"{identifier}: Global Review must score the actual Boundary Review interval"
                )
        errors.extend(boundary_consistency_errors_v4(boundary))
        flags = _raw_quality_flags_v4(review) | _raw_quality_flags_v4(boundary)
        score: int | None = None
        raw_scores = review.get("scores")
        if isinstance(raw_scores, dict):
            try:
                score_model = (
                    MiniLessonScoresV4
                    if request.get("clip_profile") == "mini_lesson"
                    else ShortHighlightScoresV4
                )
                score = score_model.model_validate_json(json.dumps(raw_scores)).total
            except ValueError:
                pass  # Missing/invalid score facts are not reconstructed.
        interruptions = [
            item
            for record in (review, boundary)
            if isinstance(items := record.get("interruption_review"), list)
            for item in items
            if isinstance(item, dict)
        ]
        # Only affirmative, available facts establish rejection. Full Schema,
        # cue/time/score checks still run in the typed final validator.
        if (
            review.get("content_decision") in ("drop", "repair_boundary")
            or boundary.get("content_decision") == "drop"
            or bool(flags & BLOCKING_QUALITY_FLAGS_V4)
            or any(item.get("blocking") is True for item in interruptions)
            or (
                score is not None
                and isinstance(threshold, (int, float))
                and not isinstance(threshold, bool)
                and score <= threshold
            )
        ):
            rejected.add(identifier)
    return [*errors, *duplicate_representative_errors_v4(reviews, rejected)]


def _raw_context_cues_v4(raw: object) -> dict[int, SemanticCue] | None:
    if not isinstance(raw, list):
        return None
    # Preserve global IDs. Rebuilding a local TranscriptDocument would renumber
    # them and could authorize another candidate's evidence.
    cues: dict[int, SemanticCue] = {}
    for value in raw:
        if not isinstance(value, dict):
            continue
        try:
            cue = SemanticCue.model_validate_json(json.dumps(value))
        except ValueError:
            continue  # Unavailable/invalid authority cannot grant a reference.
        cues[cue.cue_id] = cue
    return cues


def _reference_errors_v4(
    values: object, cue_map: Mapping[int, SemanticCue], field: str
) -> list[str]:
    if not isinstance(values, list):
        return []
    unknown = [value for value in values if type(value) is int and value not in cue_map]
    return [f"{field} references unknown or out-of-context cue IDs: {unknown}"] if unknown else []


def _interruption_reference_errors_v4(
    review: Mapping[str, object], cue_map: Mapping[int, SemanticCue]
) -> list[str]:
    rows = review.get("interruption_review")
    if not isinstance(rows, list):
        return []
    return [
        error
        for index, row in enumerate(rows)
        if isinstance(row, dict)
        for error in _reference_errors_v4(
            row.get("evidence_cue_ids"), cue_map, f"interruption_review.{index}.evidence_cue_ids"
        )
    ]


def _interval_reference_errors_v4(
    start_id: object, end_id: object, cue_map: Mapping[int, SemanticCue]
) -> list[str]:
    errors = _reference_errors_v4([start_id, end_id], cue_map, "interval")
    if type(start_id) is int and type(end_id) is int and end_id < start_id:
        errors.append("cue interval is reversed")
    return errors


def boundary_reference_errors_v4(
    review: Mapping[str, object],
    cue_map: Mapping[int, SemanticCue],
    *,
    expected_profile: ClipProfile | None,
) -> list[str]:
    """Shared raw/final checks using only this Boundary request's authority."""

    errors = _interruption_reference_errors_v4(review, cue_map)
    evidence = review.get("evidence")
    if isinstance(evidence, dict):
        for field in ("opening_cue_ids", "core_cue_ids", "ending_cue_ids"):
            errors.extend(_reference_errors_v4(evidence.get(field), cue_map, f"evidence.{field}"))
    # Missing/invalid decisions grant no inferred retained interval obligation.
    # DROP and undecided outputs still require valid evidence.
    if review.get("content_decision") not in ("keep", "repair_boundary"):
        return errors
    start_id, end_id = review.get("proposed_start_cue_id"), review.get("proposed_end_cue_id")
    errors.extend(_interval_reference_errors_v4(start_id, end_id, cue_map))
    if (
        type(start_id) is int
        and type(end_id) is int
        and start_id in cue_map
        and end_id in cue_map
        and expected_profile is not None
    ):
        spec = clip_profile_spec(expected_profile)
        duration = cue_map[end_id].end_ms - cue_map[start_id].start_ms
        if not spec.minimum_duration_ms <= duration <= spec.maximum_duration_ms:
            errors.append("Boundary Review duration is outside its Profile")
    if review.get("continuous_source_interval") is False:
        errors.append("the first mini-lesson release supports one continuous interval only")
    return errors


def global_reference_errors_v4(
    review: Mapping[str, object], cue_map: Mapping[int, SemanticCue]
) -> list[str]:
    """Do not authorize a reference from another candidate's context."""

    return [
        *_interval_reference_errors_v4(
            review.get("start_cue_id"), review.get("end_cue_id"), cue_map
        ),
        *_reference_errors_v4(review.get("evidence_cue_ids"), cue_map, "evidence_cue_ids"),
        *_interruption_reference_errors_v4(review, cue_map),
    ]


def validate_boundary_review_v4(
    review: BoundaryReviewV4,
    *,
    candidate: ChainCandidateV4,
    transcript: TranscriptDocument,
    validation_contract: SemanticValidationContract = LEGACY_SEMANTIC_VALIDATION,
) -> BoundaryReviewV4:
    if uses_current_semantic_validation(validation_contract):
        errors = boundary_consistency_errors_v4(review.model_dump(mode="json"))
        if errors:
            raise ValueError(" | ".join(errors))
    if (
        review.candidate_id != candidate.candidate_id
        or review.clip_profile != candidate.clip_profile
    ):
        raise ValueError("Boundary Review candidate/profile does not match its input")
    transcript_cue_map = _cue_map(transcript)
    candidate_start, candidate_end = _validate_cue_interval(
        candidate.start_cue_id,
        candidate.end_cue_id,
        transcript_cue_map,
    )
    context_start_ms = max(0, candidate_start.start_ms - 30_000)
    context_end_ms = min(transcript.source_duration_ms, candidate_end.end_ms + 30_000)
    cue_map = {
        cue_id: cue
        for cue_id, cue in transcript_cue_map.items()
        if cue.end_ms > context_start_ms and cue.start_ms < context_end_ms
    }
    if uses_current_semantic_validation(validation_contract):
        reference_errors = boundary_reference_errors_v4(
            review.model_dump(mode="json"), cue_map, expected_profile=candidate.clip_profile
        )
        if reference_errors:
            raise ValueError(" | ".join(reference_errors))
    referenced = {
        *review.evidence.opening_cue_ids,
        *review.evidence.core_cue_ids,
        *review.evidence.ending_cue_ids,
        *(cue for value in review.interruption_review for cue in value.evidence_cue_ids),
    }
    _validate_known_cues(referenced, cue_map)
    if review.content_decision == ContentDecisionV4.DROP:
        return review
    start_id = review.proposed_start_cue_id
    end_id = review.proposed_end_cue_id
    assert start_id is not None and end_id is not None
    start, end = _validate_cue_interval(start_id, end_id, cue_map)
    spec = clip_profile_spec(review.clip_profile)
    duration_ms = end.end_ms - start.start_ms
    if not spec.minimum_duration_ms <= duration_ms <= spec.maximum_duration_ms:
        raise ValueError("Boundary Review duration is outside its Profile")
    if not review.continuous_source_interval:
        raise ValueError("the first mini-lesson release supports one continuous interval only")
    if review.content_decision == ContentDecisionV4.KEEP and (
        start_id,
        end_id,
    ) != (candidate.start_cue_id, candidate.end_cue_id):
        raise ValueError("keep must preserve the candidate interval")
    if review.content_decision == ContentDecisionV4.REPAIR_BOUNDARY and (
        start_id,
        end_id,
    ) == (candidate.start_cue_id, candidate.end_cue_id):
        raise ValueError("repair_boundary must change the interval")
    return review


_MANUAL_RISK_FLAGS_V4 = frozenset(
    {
        RiskFlagV4.HEALTH_ADVICE,
        RiskFlagV4.ABSOLUTE_CLAIM,
        RiskFlagV4.COMMERCIAL_CLAIM,
        RiskFlagV4.SENSITIVITY_REVIEW,
        RiskFlagV4.MUSIC_RIGHTS_REVIEW,
        RiskFlagV4.MINOR_PRIVACY,
        RiskFlagV4.ASR_UNCERTAIN,
    }
)
_BLOCKED_RISK_FLAGS_V4 = frozenset({RiskFlagV4.MEDICAL_CLAIM})


def validate_profile_global_review_v4(
    output: GlobalReviewOutputV4,
    *,
    candidates: Sequence[ChainCandidateV4],
    boundary_reviews: Sequence[BoundaryReviewV4],
    transcript: TranscriptDocument,
    profile: ClipProfile,
    top_n: int,
    score_threshold_exclusive: float = 75.0,
    validation_contract: SemanticValidationContract = LEGACY_SEMANTIC_VALIDATION,
) -> ValidatedProfileResultV4:
    strict_quality = uses_current_semantic_validation(validation_contract)
    if output.clip_profile != profile:
        raise ValueError("Global Review profile does not match its request")
    candidate_map = {
        value.candidate_id: value for value in candidates if value.clip_profile == profile
    }
    boundary_map = {
        value.candidate_id: value for value in boundary_reviews if value.clip_profile == profile
    }
    review_ids = [value.candidate_id for value in output.reviews]
    if len(candidate_map) != len([value for value in candidates if value.clip_profile == profile]):
        raise ValueError("Profile candidates must have unique IDs")
    if set(boundary_map) != set(candidate_map) or len(boundary_map) != len(
        [value for value in boundary_reviews if value.clip_profile == profile]
    ):
        raise ValueError("Global Review requires one unique Boundary Review per candidate")
    if len(review_ids) != len(set(review_ids)) or set(review_ids) != set(candidate_map):
        raise ValueError("Global Review must return every Profile candidate exactly once")
    duplicate_targets = {
        value.duplicate_of for value in output.reviews if value.duplicate_of is not None
    }
    if not duplicate_targets.issubset(candidate_map):
        raise ValueError("a weaker duplicate must reference a candidate in this Profile review")
    cue_map = _cue_map(transcript)
    selected: list[ValidatedCandidateV4] = []
    manual: list[ValidatedCandidateV4] = []
    blocked: list[ValidatedCandidateV4] = []
    rejected: list[ValidatedCandidateV4] = []
    for review in output.reviews:
        candidate = candidate_map[review.candidate_id]
        boundary = boundary_map[review.candidate_id]
        if strict_quality:
            validate_boundary_review_v4(
                boundary,
                candidate=candidate,
                transcript=transcript,
                validation_contract=validation_contract,
            )
        if review.clip_profile != profile:
            raise ValueError("Global Review contains a competing Profile")
        if (
            review.source_topic_id != candidate.source_topic_id
            or review.topic_chain_id != candidate.topic_chain_id
            or set(review.source_fragment_ids) != set(candidate.source_fragment_ids)
        ):
            raise ValueError("Global Review changed source provenance")
        if boundary.proposed_start_cue_id is None or boundary.proposed_end_cue_id is None:
            start_id, end_id = candidate.start_cue_id, candidate.end_cue_id
        else:
            start_id, end_id = boundary.proposed_start_cue_id, boundary.proposed_end_cue_id
        if (review.start_cue_id, review.end_cue_id) != (start_id, end_id):
            raise ValueError("Global Review must score the actual Boundary Review interval")
        start, end = _validate_cue_interval(start_id, end_id, cue_map)
        duration_ms = end.end_ms - start.start_ms
        local_context = {
            cue_id: cue
            for cue_id, cue in cue_map.items()
            if cue.end_ms > max(0, start.start_ms - 30_000)
            and cue.start_ms < min(transcript.source_duration_ms, end.end_ms + 30_000)
        }
        if strict_quality:
            reference_errors = global_reference_errors_v4(
                review.model_dump(mode="json"), local_context
            )
            if reference_errors:
                raise ValueError(" | ".join(reference_errors))
        _validate_known_cues(review.evidence_cue_ids, local_context)
        quality_flags = set((*boundary.quality_flags, *review.quality_flags))
        risk_flags = set((*boundary.risk_flags, *review.risk_flags))
        interruptions = (*boundary.interruption_review, *review.interruption_review)
        notes: list[str] = []
        disposition = CandidateDispositionV4.SELECTED
        spec = clip_profile_spec(profile)
        if boundary.content_decision == ContentDecisionV4.DROP:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("boundary_drop_gate")
        elif review.content_decision != ContentDecisionV4.KEEP:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("content_keep_gate")
        elif not spec.minimum_duration_ms <= duration_ms <= spec.maximum_duration_ms:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("profile_duration_gate")
        elif not boundary.continuous_source_interval:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("single_continuous_interval_gate")
        elif quality_flags & BLOCKING_QUALITY_FLAGS_V4:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("blocking_quality_gate")
        elif any(value.blocking for value in interruptions):
            disposition = CandidateDispositionV4.REJECTED
            notes.append("blocking_interruption_gate")
        elif review.scores.total <= score_threshold_exclusive:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("exclusive_score_gate")
        elif risk_flags & _BLOCKED_RISK_FLAGS_V4:
            disposition = CandidateDispositionV4.BLOCKED
            notes.append("blocking_risk_gate")
        elif review.publish_status == PublishStatusV4.BLOCKED:
            disposition = CandidateDispositionV4.BLOCKED
            notes.append("agent_publish_block_gate")
        elif risk_flags & _MANUAL_RISK_FLAGS_V4:
            disposition = CandidateDispositionV4.MANUAL
            notes.append("manual_risk_gate")
        elif review.publish_status == PublishStatusV4.MANUAL:
            disposition = CandidateDispositionV4.MANUAL
            notes.append("agent_manual_gate")
        elif review.publish_status != PublishStatusV4.AUTO:
            disposition = CandidateDispositionV4.REJECTED
            notes.append("publish_auto_gate")
        validated = ValidatedCandidateV4(
            review=review,
            disposition=disposition,
            start_ms=start.start_ms,
            end_ms=end.end_ms,
            duration_ms=duration_ms,
            validation_notes=tuple(notes),
        )
        if disposition == CandidateDispositionV4.SELECTED:
            selected.append(validated)
        elif disposition == CandidateDispositionV4.MANUAL:
            manual.append(validated)
        elif disposition == CandidateDispositionV4.BLOCKED:
            blocked.append(validated)
        else:
            rejected.append(validated)
    if strict_quality:
        errors = duplicate_representative_errors_v4(
            [review.model_dump(mode="json") for review in output.reviews],
            {value.review.candidate_id for value in rejected},
        )
        if errors:
            raise ValueError(" | ".join(errors))
    selected.sort(
        key=lambda value: (
            -value.review.total_score,
            value.start_ms,
            value.review.candidate_id,
        )
    )
    qualified_before_top_n = len(selected)
    overflow = [
        value.model_copy(
            update={
                "disposition": CandidateDispositionV4.TOP_N_EXCLUDED,
                "validation_notes": (*value.validation_notes, "top_n_ceiling"),
            }
        )
        for value in selected[top_n:]
    ]
    selected = selected[:top_n]
    manual.sort(key=lambda value: (value.start_ms, value.review.candidate_id))
    blocked.sort(key=lambda value: (value.start_ms, value.review.candidate_id))
    rejected.sort(key=lambda value: (value.start_ms, value.review.candidate_id))
    return ValidatedProfileResultV4(
        selected=tuple(selected),
        manual_review=tuple(manual),
        blocked=tuple(blocked),
        rejected=tuple(rejected),
        top_n_excluded=tuple(overflow),
        statistics=ProfileStatisticsV4(
            discovery_candidate_count=len(candidate_map),
            boundary_candidate_count=len(boundary_map),
            qualified_before_top_n=qualified_before_top_n,
            selected_count=len(selected),
            manual_count=len(manual),
            blocked_count=len(blocked),
            rejected_count=len(rejected),
            top_n_excluded_count=len(overflow),
        ),
    )


def build_discovery_payload_v4(
    unit: SemanticInputUnit,
    *,
    source_id: str,
    source_hash: str,
    profile: ClipProfile,
    prompt_hash: str,
) -> dict[str, object]:
    if unit.context_range_ms is None or unit.ownership_range_ms is None:
        raise ValueError("v4 Discovery requires a windowed input unit")
    logical_windows = [
        {
            "logical_window_id": (f"{unit.unit_id}_window_{index:02d}"),
            "start_ms": value.start_ms,
            "end_ms": value.end_ms,
        }
        for index, value in enumerate(unit.logical_windows_ms, start=1)
    ]
    return {
        "schema_version": SEMANTIC_RESULT_SCHEMA_VERSION,
        "stage": "discovery",
        "source_id": source_id,
        "source_hash": source_hash,
        "clip_profile": profile.value,
        "batch_id": unit.unit_id,
        "prompt_hash": prompt_hash,
        "batch_context": unit.context_range_ms.model_dump(mode="json"),
        "ownership_interval": unit.ownership_range_ms.model_dump(mode="json"),
        "logical_windows": logical_windows,
        "ownership_contract": (
            "A candidate is recorded only by the batch whose ownership interval contains "
            "its start cue. This decides transport ownership only, never semantic identity."
        ),
        "discovery_contract": (
            "High recall: do not apply score, Top-N, duration, or publish-risk gates."
        ),
        "cues": [value.model_dump(mode="json") for value in unit.cues],
    }


def build_link_review_payload_v4(
    request: LinkReviewRequestV4,
    *,
    transcript: TranscriptDocument,
    source_hash: str,
    profile: ClipProfile,
    prompt_hash: str,
) -> dict[str, object]:
    cues = [
        value
        for value in transcript_cues(transcript)
        if value.end_ms > request.context_range.start_ms
        and value.start_ms < request.context_range.end_ms
    ]
    if not cues:
        raise ValueError("Link Review context contains no transcript cues")
    return {
        "schema_version": SEMANTIC_RESULT_SCHEMA_VERSION,
        "stage": "link_review",
        "source_hash": source_hash,
        "clip_profile": profile.value,
        "prompt_hash": prompt_hash,
        "link_review_id": request.link_review_id,
        "boundary_ms": request.boundary_ms,
        "context_range": request.context_range.model_dump(mode="json"),
        "left_window_id": request.left_window_id,
        "right_window_id": request.right_window_id,
        "left_fragment": request.left_fragment.model_dump(mode="json"),
        "right_fragment": request.right_fragment.model_dump(mode="json"),
        "cues": [value.model_dump(mode="json") for value in cues],
    }


def build_topic_chain_review_payload_v4(
    chain: TopicChainV4,
    *,
    transcript: TranscriptDocument,
    source_hash: str,
    profile: ClipProfile,
    prompt_hash: str,
    link_reviews: Sequence[LinkReviewV4],
) -> dict[str, object]:
    cue_map = _cue_map(transcript)
    start, end = _validate_cue_interval(chain.source_start_cue_id, chain.source_end_cue_id, cue_map)
    cues = [
        value
        for value in cue_map.values()
        if value.end_ms > start.start_ms and value.start_ms < end.end_ms
    ]
    spec = clip_profile_spec(profile)
    return {
        "schema_version": SEMANTIC_RESULT_SCHEMA_VERSION,
        "stage": "topic_chain",
        "source_hash": source_hash,
        "clip_profile": profile.value,
        "prompt_hash": prompt_hash,
        "topic_chain": chain.model_dump(mode="json"),
        "link_reviews": [
            value.model_dump(mode="json")
            for value in link_reviews
            if value.link_review_id in chain.link_review_ids
        ],
        "profile_contract": {
            "minimum_ms": spec.minimum_duration_ms,
            "target_ms": spec.target_duration_ms,
            "maximum_ms": spec.maximum_duration_ms,
            "continuous_source_intervals": 1,
            "natural_split_required_above_maximum": True,
        },
        "cues": [value.model_dump(mode="json") for value in cues],
    }


def build_boundary_review_payload_v4(
    candidate: ChainCandidateV4,
    *,
    chain: TopicChainV4,
    transcript: TranscriptDocument,
    source_hash: str,
    prompt_hash: str,
    discovery_evidence: Sequence[DiscoveryBatchOutputV4],
    link_reviews: Sequence[LinkReviewV4],
    context_ms: int = 30_000,
) -> dict[str, object]:
    cue_map = _cue_map(transcript)
    start, end = _validate_cue_interval(candidate.start_cue_id, candidate.end_cue_id, cue_map)
    context_start = max(0, start.start_ms - context_ms)
    context_end = min(transcript.source_duration_ms, end.end_ms + context_ms)
    cues = [
        value
        for value in cue_map.values()
        if value.end_ms > context_start and value.start_ms < context_end
    ]
    fragment_ids = set(candidate.source_fragment_ids)
    source_fragments = [
        value.model_dump(mode="json")
        for output in discovery_evidence
        for value in output.topic_fragments
        if value.topic_fragment_id in fragment_ids
    ]
    return {
        "schema_version": SEMANTIC_RESULT_SCHEMA_VERSION,
        "stage": "boundary_review",
        "source_hash": source_hash,
        "clip_profile": candidate.clip_profile.value,
        "prompt_hash": prompt_hash,
        "candidate": candidate.model_dump(mode="json"),
        "topic_chain": chain.model_dump(mode="json"),
        "source_fragments": source_fragments,
        "link_reviews": [
            value.model_dump(mode="json")
            for value in link_reviews
            if value.link_review_id in chain.link_review_ids
        ],
        "context_range": {"start_ms": context_start, "end_ms": context_end},
        "cues": [value.model_dump(mode="json") for value in cues],
    }


def build_global_review_payload_v4(
    candidates: Sequence[ChainCandidateV4],
    *,
    boundary_reviews: Sequence[BoundaryReviewV4],
    topic_chains: Sequence[TopicChainV4],
    transcript: TranscriptDocument,
    source_hash: str,
    profile: ClipProfile,
    prompt_hash: str,
    top_n: int,
    context_ms: int = 30_000,
) -> dict[str, object]:
    profile_candidates = tuple(value for value in candidates if value.clip_profile == profile)
    profile_boundaries = tuple(value for value in boundary_reviews if value.clip_profile == profile)
    candidate_ids = {value.candidate_id for value in profile_candidates}
    if {value.candidate_id for value in profile_boundaries} != candidate_ids:
        raise ValueError("Global Review payload requires every Profile boundary review")
    chain_ids = {value.topic_chain_id for value in profile_candidates}
    cue_map = _cue_map(transcript)
    boundary_map = {value.candidate_id: value for value in profile_boundaries}
    contexts: list[dict[str, object]] = []
    for candidate in profile_candidates:
        boundary = boundary_map[candidate.candidate_id]
        start_cue_id = boundary.proposed_start_cue_id or candidate.start_cue_id
        end_cue_id = boundary.proposed_end_cue_id or candidate.end_cue_id
        start, end = _validate_cue_interval(start_cue_id, end_cue_id, cue_map)
        context_start = max(0, start.start_ms - context_ms)
        context_end = min(transcript.source_duration_ms, end.end_ms + context_ms)
        contexts.append(
            {
                "candidate_id": candidate.candidate_id,
                "context_range": {"start_ms": context_start, "end_ms": context_end},
                "cues": [
                    value.model_dump(mode="json")
                    for value in cue_map.values()
                    if value.end_ms > context_start and value.start_ms < context_end
                ],
            }
        )
    return {
        "schema_version": SEMANTIC_RESULT_SCHEMA_VERSION,
        "stage": "global_review",
        "source_hash": source_hash,
        "clip_profile": profile.value,
        "prompt_hash": prompt_hash,
        "score_threshold_exclusive": 75,
        "top_n_contract": {"maximum": top_n, "padding_forbidden": True},
        "candidates": [value.model_dump(mode="json") for value in profile_candidates],
        "boundary_reviews": [value.model_dump(mode="json") for value in profile_boundaries],
        "topic_chains": [
            value.model_dump(mode="json")
            for value in topic_chains
            if value.topic_chain_id in chain_ids
        ],
        "candidate_contexts": contexts,
    }


def _cue_map(transcript: TranscriptDocument) -> dict[int, SemanticCue]:
    return {value.cue_id: value for value in transcript_cues(transcript)}


def _validate_cue_interval(
    start_cue_id: int,
    end_cue_id: int,
    cue_map: Mapping[int, SemanticCue],
) -> tuple[SemanticCue, SemanticCue]:
    if start_cue_id not in cue_map or end_cue_id not in cue_map:
        raise ValueError("interval references an unknown cue ID")
    if end_cue_id < start_cue_id:
        raise ValueError("cue interval is reversed")
    return cue_map[start_cue_id], cue_map[end_cue_id]


def _validate_known_cues(values: Iterable[int], cue_map: Mapping[int, SemanticCue]) -> None:
    if any(value not in cue_map for value in values):
        raise ValueError("semantic evidence references an unknown cue ID")


__all__ = [
    "BLOCKING_QUALITY_FLAGS_V4",
    "SEMANTIC_RESULT_SCHEMA_VERSION",
    "BoundaryReviewV4",
    "CandidateDispositionV4",
    "CandidateGlobalReviewV4",
    "ChainCandidateV4",
    "ContentDecisionV4",
    "CoverageDecisionV4",
    "DiscoveryBatchOutputV4",
    "DiscoveryCandidateV4",
    "GlobalReviewOutputV4",
    "InterruptionReviewV4",
    "InterruptionSeverityV4",
    "LinkRelationshipV4",
    "LinkReviewRequestV4",
    "LinkReviewV4",
    "LogicalWindowDiscoveryV4",
    "MiniLessonScoresV4",
    "ProfileStatisticsV4",
    "PublishStatusV4",
    "QualityFlagV4",
    "RiskFlagV4",
    "ShortHighlightScoresV4",
    "TimeRangeV4",
    "TopicBoundaryV4",
    "TopicChainReviewV4",
    "TopicChainStatusV4",
    "TopicChainV4",
    "TopicFragmentV4",
    "UnifiedSemanticResultV4",
    "ValidatedCandidateV4",
    "ValidatedProfileResultV4",
    "assemble_topic_chains_v4",
    "build_boundary_review_payload_v4",
    "build_discovery_payload_v4",
    "build_global_review_payload_v4",
    "build_link_review_payload_v4",
    "build_topic_chain_review_payload_v4",
    "namespace_discovery_batch_v4",
    "plan_followup_link_review_requests_v4",
    "plan_link_review_requests_v4",
    "validate_boundary_review_v4",
    "validate_discovery_batch_v4",
    "validate_link_review_v4",
    "validate_profile_global_review_v4",
    "validate_topic_chain_review_v4",
]
