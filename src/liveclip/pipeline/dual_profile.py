from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.transcript import TranscriptDocument
from liveclip.pipeline.semantic_global import SemanticCue, transcript_cues

DUAL_PROFILE_ALGORITHM_VERSION = "dual-profile-direct-v1"
DUAL_PROFILE_SCHEMA_VERSION = "1"
# Four 120-second logical scans start 60 seconds apart.  The batched context
# includes the final logical start plus the maximum 90-second candidate so a
# candidate owned near the right edge cannot be truncated.
SHORT_CONTEXT_MS = 330_000
SHORT_OWNERSHIP_MS = 240_000
SHORT_STRIDE_MS = 240_000
MINI_CONTEXT_MS = 600_000
MINI_OWNERSHIP_MS = 300_000
MINI_STRIDE_MS = 300_000


class CandidateDisposition(StrEnum):
    SELECTED = "selected"
    MANUAL_REVIEW = "manual_review"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class DualQualityFlag(StrEnum):
    CONTEXT_DEPENDENT_OPENING = "context_dependent_opening"
    MISSING_REQUIRED_PRIOR_STEPS = "missing_required_prior_steps"
    TOPIC_NOT_CLOSED = "topic_not_closed"
    PADDED_WITH_IRRELEVANT_CONTENT = "padded_with_irrelevant_content"
    MATERIAL_INTERRUPTION = "material_interruption"
    ASR_UNCERTAIN_BLOCKS_MEANING = "asr_uncertain_blocks_meaning"
    SOURCE_TITLE_MISMATCH = "source_title_mismatch"
    TOPIC_SWITCH_INSIDE = "topic_switch_inside"
    SALES_OR_CTA_PADDING = "sales_or_cta_padding"
    DEVICE_OR_WAITING_PADDING = "device_or_waiting_padding"


class DualRiskTag(StrEnum):
    MEDICAL_CLAIM = "medical_claim"
    MEDICAL_DIAGNOSIS_HIGH = "medical_diagnosis_high"
    HEALTH_ADVICE = "health_advice"
    ABSOLUTE_CLAIM = "absolute_claim"
    SENSITIVITY_REVIEW = "sensitivity_review"
    MUSIC_RIGHTS_REVIEW = "music_rights_review"
    PARTICIPANT_AUDIO = "participant_audio"
    MINOR_PRIVACY = "minor_privacy"
    ASR_UNCERTAIN = "asr_uncertain"
    COMMERCIAL_CLAIM = "commercial_claim"


AUTO_BLOCKING_QUALITY_FLAGS = frozenset(DualQualityFlag)
# PRODUCT_SPEC: unresolved boundary, cleanliness, padding and mixed-topic quality
# flags drop the candidate.  A model ``manual_review`` disposition cannot keep such a
# row reviewable; final assembly deterministically downgrades it to ``blocked``.
# Opening-context and prior-step flags remain advisory for human review.
MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS = frozenset(
    {
        DualQualityFlag.PADDED_WITH_IRRELEVANT_CONTENT,
        DualQualityFlag.SALES_OR_CTA_PADDING,
        DualQualityFlag.DEVICE_OR_WAITING_PADDING,
        DualQualityFlag.MATERIAL_INTERRUPTION,
        DualQualityFlag.TOPIC_SWITCH_INSIDE,
        DualQualityFlag.TOPIC_NOT_CLOSED,
        DualQualityFlag.ASR_UNCERTAIN_BLOCKS_MEANING,
    }
)
# Routing policy v5 splits the gated flags into two disjoint classes; together
# they are exactly ``MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`` (no gated flag is in
# neither class; a module-level check below enforces this, so a new gated
# flag must be classified explicitly).
# Structural flags describe the media inside the interval (an interior
# interruption or topic switch, an ending that does not close, ASR that blocks
# the meaning).  Boundary Review can resolve them only by removing media, so a
# Discovery-raised structural flag persists unless Boundary Review shrank an edge.
PERSISTED_STRUCTURAL_GATED_FLAGS: Final = frozenset(
    {
        DualQualityFlag.MATERIAL_INTERRUPTION,
        DualQualityFlag.TOPIC_SWITCH_INSIDE,
        DualQualityFlag.TOPIC_NOT_CLOSED,
        DualQualityFlag.ASR_UNCERTAIN_BLOCKS_MEANING,
    }
)
# Padding flags describe removable EDGE material only (unrelated interior
# content is material_interruption or topic_switch_inside).  Boundary Review is
# the edge authority and sees the surrounding context, so a Discovery padding
# flag is not persisted: it follows Boundary Review's output (and any flag
# Global Review or the Global Audit legitimately sets), still gated as before.
PADDING_GATED_FLAGS: Final = frozenset(
    {
        DualQualityFlag.DEVICE_OR_WAITING_PADDING,
        DualQualityFlag.SALES_OR_CTA_PADDING,
        DualQualityFlag.PADDED_WITH_IRRELEVANT_CONTENT,
    }
)
if not PERSISTED_STRUCTURAL_GATED_FLAGS.isdisjoint(PADDING_GATED_FLAGS) or (
    PERSISTED_STRUCTURAL_GATED_FLAGS | PADDING_GATED_FLAGS != MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
):
    raise RuntimeError("every gated quality flag must be exactly structural or padding")
# Audit marker for the deterministic final routing policy.
#   v1: manual_review rows with a gated quality flag are downgraded to blocked.
#   v2: v1 plus records of the dedicated risk-discovery pass are never rejected;
#       a rejected risk record is retained as blocked (never an output).
#   v3: v2 plus same-interval candidates share their gated quality flags (a
#       selected or manual_review twin that inherits one becomes blocked), risk
#       records excluded by Top-N are retained as blocked, and final evidence
#       cue IDs are limited to the final interval.
#   v4: v3 plus Discovery gated-flag persistence: a gated flag that Discovery
#       raised on a candidate survives into the final flags unless Boundary
#       Review shrank that candidate's interval on at least one edge; a
#       selected or manual_review row that keeps one becomes blocked.
#   v5: v4 restricted to structural gated flags
#       (``PERSISTED_STRUCTURAL_GATED_FLAGS``); Discovery padding flags
#       (``PADDING_GATED_FLAGS``) are not persisted and follow Boundary Review.
#   v6: v5 plus the same-interval twin union no longer uses records of the
#       dedicated risk-discovery pass as flag SOURCES: a risk record keeps its
#       own flags and status and still receives the gated flags of its non-risk
#       twins, while non-risk twins share flags with each other as in v3
#       (``same_interval_twin_flags`` is the single rule).
#   v7: v6 plus risk-twin review: a non-risk row still ``selected`` after the
#       twin union whose identical interval has a risk-discovery twin carrying an
#       automatic-blocking risk tag (``AUTO_BLOCKING_RISK_TAGS``) is downgraded
#       to ``manual_review`` before Top-N; risk tags are not copied
#       (``risk_twin_review`` is the single rule).
# Artifacts written before any policy omit the marker and load as ``None``.
DUAL_PROFILE_ROUTING_POLICY_VERSION: Final = "quality-gate-risk-routing-v7"
AUTO_BLOCKING_RISK_TAGS = frozenset(
    {
        "medical_claim",
        "medical_diagnosis_high",
        "health_advice",
        "absolute_claim",
        "sensitivity_review",
        "music_rights_review",
        "participant_audio",
        "minor_privacy",
        "asr_uncertain",
    }
)


class ProfileDurationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    min_duration_ms: int = Field(ge=1_000, le=600_000)
    max_duration_ms: int = Field(ge=1_000, le=600_000)
    min_inclusive: bool
    max_inclusive: bool

    @model_validator(mode="after")
    def validate_order(self) -> ProfileDurationContract:
        if self.min_duration_ms >= self.max_duration_ms:
            raise ValueError("Profile duration bounds must be ordered")
        return self

    def accepts(self, duration_ms: int) -> bool:
        minimum_ok = (
            duration_ms >= self.min_duration_ms
            if self.min_inclusive
            else duration_ms > self.min_duration_ms
        )
        maximum_ok = (
            duration_ms <= self.max_duration_ms
            if self.max_inclusive
            else duration_ms < self.max_duration_ms
        )
        return minimum_ok and maximum_ok


PROFILE_DURATION_CONTRACTS: dict[ClipProfile, ProfileDurationContract] = {
    ClipProfile.SHORT_HIGHLIGHT: ProfileDurationContract(
        min_duration_ms=45_000,
        max_duration_ms=90_000,
        min_inclusive=True,
        max_inclusive=True,
    ),
    ClipProfile.MINI_LESSON: ProfileDurationContract(
        min_duration_ms=90_000,
        max_duration_ms=300_000,
        min_inclusive=False,
        max_inclusive=True,
    ),
}


class DualProfileRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    requested_profiles: tuple[ClipProfile, ...] = (
        ClipProfile.SHORT_HIGHLIGHT,
        ClipProfile.MINI_LESSON,
    )
    profiles: dict[ClipProfile, ProfileDurationContract] = Field(
        default_factory=lambda: dict(PROFILE_DURATION_CONTRACTS)
    )
    top_n: dict[ClipProfile, int] = Field(
        default_factory=lambda: {
            ClipProfile.SHORT_HIGHLIGHT: 15,
            ClipProfile.MINI_LESSON: 15,
        }
    )
    score_threshold_exclusive: float = Field(default=75.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_profiles(self) -> DualProfileRunConfig:
        if not self.requested_profiles or len(set(self.requested_profiles)) != len(
            self.requested_profiles
        ):
            raise ValueError("requested Profiles must be non-empty and unique")
        expected = set(self.requested_profiles)
        if set(self.profiles) != expected or set(self.top_n) != expected:
            raise ValueError("duration and Top-N configuration must cover requested Profiles")
        if any(value < 1 or value > 100 for value in self.top_n.values()):
            raise ValueError("Profile Top-N must be between 1 and 100")
        for profile in expected:
            if self.profiles[profile] != PROFILE_DURATION_CONTRACTS[profile]:
                raise ValueError("current dual Profile duration contracts are immutable")
        return self


class DiscoveryWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    window_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    profile: ClipProfile
    context_start_ms: int = Field(ge=0)
    context_end_ms: int = Field(gt=0)
    ownership_start_ms: int = Field(ge=0)
    ownership_end_ms: int = Field(gt=0)
    cues: tuple[SemanticCue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> DiscoveryWindow:
        if self.context_end_ms <= self.context_start_ms:
            raise ValueError("Discovery context range is reversed")
        if self.ownership_end_ms <= self.ownership_start_ms:
            raise ValueError("Discovery ownership range is reversed")
        if not (
            self.context_start_ms <= self.ownership_start_ms
            and self.ownership_end_ms <= self.context_end_ms
        ):
            raise ValueError("Discovery ownership must be inside its context")
        if any(
            cue.end_ms <= self.context_start_ms or cue.start_ms >= self.context_end_ms
            for cue in self.cues
        ):
            raise ValueError("Discovery window contains a cue outside its context")
        return self


class BoundaryState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    continues_from_left: bool = False
    continues_to_right: bool = False
    opening_complete: bool
    ending_complete: bool


class RawProfileCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    profile: ClipProfile
    variant_group_id: str = Field(default="", max_length=96, pattern=r"^[A-Za-z0-9_-]*$")
    source_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    source_window_id: str = Field(min_length=1, max_length=96)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    boundary_state: BoundaryState
    quality_flags: tuple[DualQualityFlag, ...] = Field(default_factory=tuple)
    risk_tags: tuple[DualRiskTag, ...] = Field(default_factory=tuple, max_length=20)

    @model_validator(mode="after")
    def validate_cue_order(self) -> RawProfileCandidate:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("candidate cue range is reversed")
        if any(
            cue_id < self.start_cue_id or cue_id > self.end_cue_id
            for cue_id in self.evidence_cue_ids
        ):
            raise ValueError("candidate evidence cue lies outside its interval")
        return self


class ProfileDiscoveryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    window_id: str
    candidates: tuple[RawProfileCandidate, ...] = Field(default_factory=tuple, max_length=40)
    risk_observations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)


class BoundaryReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str
    profile: ClipProfile
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    opening_complete: bool
    ending_complete: bool
    central_objective_complete: bool
    shortest_complete_boundary: bool
    quality_flags: tuple[DualQualityFlag, ...] = Field(default_factory=tuple)
    risk_tags: tuple[DualRiskTag, ...] = Field(default_factory=tuple, max_length=20)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=100)
    review_reason: str = Field(min_length=1, max_length=800)


class ProfileBoundaryReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    reviews: tuple[BoundaryReviewItem, ...]


class GlobalReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str
    profile: ClipProfile
    variant_group_id: str = Field(default="", max_length=96, pattern=r"^[A-Za-z0-9_-]*$")
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=600)
    score: float = Field(ge=0, le=100)
    review_status: CandidateDisposition
    duplicate_of_candidate_id: str | None = None
    quality_flags: tuple[DualQualityFlag, ...] = Field(default_factory=tuple)
    risk_tags: tuple[DualRiskTag, ...] = Field(default_factory=tuple, max_length=20)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=100)
    review_reason: str = Field(min_length=1, max_length=800)


class ProfileGlobalReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    reviews: tuple[GlobalReviewItem, ...]


class NestedPairDecisionKind(StrEnum):
    DUPLICATE = "duplicate"
    DISTINCT_OBJECTIVE = "distinct_objective"


class AuditPairKind(StrEnum):
    NESTED = "nested"
    OVERLAP = "overlap"
    # Stage 13b: strict containment without a shared edge, listed only when the
    # inner candidate is a near-copy of the outer one (always ``near_identical``).
    CONTAINMENT = "containment"


# Overlap adjudication (Stage 13): a same-Profile retained pair in which neither
# candidate contains the other is listed for the Global Audit when the shared
# media is at least this fraction of the shorter candidate's duration.
AUDIT_OVERLAP_MIN_SHORTER_FRACTION: Final = Fraction(1, 2)
# An overlap pair sharing at least this fraction of the shorter candidate, or
# ending at the same point within the Profile's boundary tolerance, is
# near-identical media: the audit may not keep both members retained.
AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION: Final = Fraction(9, 10)
AUDIT_SAME_END_TOLERANCE_MS: Final[Mapping[ClipProfile, int]] = MappingProxyType(
    {ClipProfile.SHORT_HIGHLIGHT: 3_000, ClipProfile.MINI_LESSON: 5_000}
)


class AuditCandidatePair(BaseModel):
    """One Python-listed same-Profile pair the Global Audit must decide.

    ``outer_candidate_id`` is the containing candidate of a nested pair, or the
    earlier-starting candidate of an overlap pair.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outer_candidate_id: str
    inner_candidate_id: str
    pair_kind: AuditPairKind
    near_identical: bool = False

    @property
    def members(self) -> frozenset[str]:
        return frozenset((self.outer_candidate_id, self.inner_candidate_id))


class NestedPairDecision(BaseModel):
    """Global Audit decision for one Python-listed same-Profile pair (nested or overlap)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outer_candidate_id: str
    inner_candidate_id: str
    decision: NestedPairDecisionKind
    reason: str = Field(min_length=1, max_length=600)


class ProfileGlobalAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    replacements: tuple[GlobalReviewItem, ...]
    # Required on purpose: every audit output written by this contract carries an
    # explicit (possibly empty) decision list. Pre-contract cached audit outputs
    # can never be reused because the audit prompt hash and payload both changed.
    nested_pair_decisions: tuple[NestedPairDecision, ...]
    audit_reason: str = Field(min_length=1, max_length=1_200)


class VariantLinkItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str
    variant_group_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")


class CrossProfileVariantLinkOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    links: tuple[VariantLinkItem, ...]


class FinalProfileCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str
    profile: ClipProfile
    variant_group_id: str = ""
    source_candidate_ids: tuple[str, ...]
    source_window_ids: tuple[str, ...]
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    title: str
    hook: str
    summary: str
    score: float = Field(ge=0, le=100)
    review_status: CandidateDisposition
    quality_flags: tuple[DualQualityFlag, ...] = ()
    risk_tags: tuple[DualRiskTag, ...] = ()
    evidence_cue_ids: tuple[int, ...]
    duplicate_of_candidate_id: str | None = None
    review_reason: str

    @model_validator(mode="after")
    def validate_interval(self) -> FinalProfileCandidate:
        if self.end_ms <= self.start_ms or self.duration_ms != self.end_ms - self.start_ms:
            raise ValueError("final candidate duration is inconsistent")
        if not PROFILE_DURATION_CONTRACTS[self.profile].accepts(self.duration_ms):
            raise ValueError("final candidate violates its Profile duration")
        if self.review_status == CandidateDisposition.SELECTED and (
            self.score <= 75
            or set(self.quality_flags) & AUTO_BLOCKING_QUALITY_FLAGS
            or set(self.risk_tags) & AUTO_BLOCKING_RISK_TAGS
        ):
            raise ValueError("automatic selection violates deterministic quality/risk gates")
        return self


class ProfileStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    discovered: int = Field(ge=0)
    selected: int = Field(ge=0)
    manual_review: int = Field(ge=0)
    blocked: int = Field(ge=0)
    rejected: int = Field(ge=0)

    @property
    def terminal_total(self) -> int:
        return self.selected + self.manual_review + self.blocked + self.rejected


class FinalProfileResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    raw_candidate_ids: tuple[str, ...]
    selected: tuple[FinalProfileCandidate, ...] = ()
    manual_review: tuple[FinalProfileCandidate, ...] = ()
    blocked: tuple[FinalProfileCandidate, ...] = ()
    rejected: tuple[FinalProfileCandidate, ...] = ()
    statistics: ProfileStatistics

    @model_validator(mode="after")
    def validate_partition(self) -> FinalProfileResult:
        groups = {
            CandidateDisposition.SELECTED: self.selected,
            CandidateDisposition.MANUAL_REVIEW: self.manual_review,
            CandidateDisposition.BLOCKED: self.blocked,
            CandidateDisposition.REJECTED: self.rejected,
        }
        flattened = tuple(value for values in groups.values() for value in values)
        if any(value.profile != self.profile for value in flattened):
            raise ValueError("Profile result contains another Profile")
        if any(
            value.review_status != status for status, values in groups.items() for value in values
        ):
            raise ValueError("candidate is stored in the wrong terminal array")
        identities = [value.candidate_id for value in flattened]
        if len(identities) != len(set(identities)):
            raise ValueError("candidate appears in more than one terminal array")
        raw = set(self.raw_candidate_ids)
        traced = {source for value in flattened for source in value.source_candidate_ids}
        if raw != traced:
            raise ValueError("raw/final candidate lineage is not exactly conserved")
        expected = profile_statistics(self.raw_candidate_ids, flattened)
        if self.statistics != expected:
            raise ValueError("Profile statistics were not recomputed from final arrays")
        return self


class DualProfileFinalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    algorithm_version: Literal["dual-profile-direct-v1"] = "dual-profile-direct-v1"
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_profiles: tuple[ClipProfile, ...]
    executed_profiles: tuple[ClipProfile, ...]
    profiles: dict[ClipProfile, FinalProfileResult]
    # Optional audit marker; absent (``None``) in artifacts that predate the
    # deterministic manual-review quality gate.
    routing_policy_version: (
        Literal[
            "manual-review-quality-gate-v1",
            "quality-gate-risk-routing-v2",
            "quality-gate-risk-routing-v3",
            "quality-gate-risk-routing-v4",
            "quality-gate-risk-routing-v5",
            "quality-gate-risk-routing-v6",
            "quality-gate-risk-routing-v7",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_execution(self) -> DualProfileFinalResult:
        if len(set(self.requested_profiles)) != len(self.requested_profiles):
            raise ValueError("requested Profiles are duplicated")
        if len(set(self.executed_profiles)) != len(self.executed_profiles):
            raise ValueError("executed Profiles are duplicated")
        if set(self.profiles) != set(self.executed_profiles):
            raise ValueError("executed Profiles differ from final Profile results")
        if any(key != value.profile for key, value in self.profiles.items()):
            raise ValueError("Profile result key differs from its payload")
        return self


class ProfileManifestStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    discovered: int = Field(ge=0)
    selected: int = Field(ge=0)
    manual_review: int = Field(ge=0)
    blocked: int = Field(ge=0)
    rejected: int = Field(ge=0)


class StaleCacheResolution(BaseModel):
    """One cached output that failed current validation under ``--refresh-stale-cache``.

    The stale entry is never modified. ``superseding_cache_key`` names the entry
    whose model settings add the sha256 of the stale output's canonical JSON
    (``model_dump``); ``reused`` is true when that entry already existed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: str = Field(min_length=1, max_length=64)
    profile: str = Field(min_length=1, max_length=64)
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    superseding_cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    error_summary: str = Field(min_length=1, max_length=500)
    reused: bool


class BoundaryOpeningFallback(BaseModel):
    """Rows downgraded to ``opening_complete=false`` after repair and regeneration.

    The fallback exists only for Boundary Review, so ``subject_id`` must name one of
    the Profile's Boundary Review batches (``<profile>.boundary.<NNN>``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    subject_id: str = Field(min_length=1, max_length=160)
    candidate_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_boundary_subject(self) -> BoundaryOpeningFallback:
        if (
            re.fullmatch(rf"{re.escape(self.profile.value)}\.boundary\.\d{{3,}}", self.subject_id)
            is None
        ):
            raise ValueError("Boundary opening fallback must name a Boundary Review batch")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("Boundary opening fallback repeats a candidate")
        return self


class AuditPairRule(StrEnum):
    NEAR_IDENTICAL_PAIR = "near_identical_pair"
    OVERLAP_REPRESENTATIVE = "overlap_representative"
    PERSISTED_FLAG_REPRESENTATIVE = "persisted_flag_representative"
    # Stage 13c: a duplicate whose resolved representative the fallback blocked.
    ORPHANED_DUPLICATE = "orphaned_duplicate"


class AuditPairViolation(BaseModel):
    """One violation of a deterministic Stage 13/13b audit-pair rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule: AuditPairRule
    outer_candidate_id: str
    inner_candidate_id: str
    # The member removed as a duplicate (representative rules only).
    duplicate_candidate_id: str | None = None


AUDIT_FALLBACK_REASON_PREFIX: Final = "Deterministic audit fallback: "
FLAG_PERSISTENCE_REASON_PREFIX: Final = "Deterministic flag persistence: "
QUALITY_GATE_REASON_PREFIX: Final = "Deterministic quality gate: "
RISK_ROUTING_REASON_PREFIX: Final = "Deterministic risk routing: "
TOP_N_REASON_PREFIX: Final = "Profile-local Top-N exclusion: "
# Stage 15b (routing v7): the only Python-only prefix on a ``manual_review`` row.
RISK_TWIN_REVIEW_REASON_PREFIX: Final = "Deterministic risk-twin review: "
# Reason prefixes that only Python may write (Stage 13c). Model review reasons
# may not start with one, so every prefixed final row is a Python decision.
DETERMINISTIC_REASON_PREFIXES: Final = (
    AUDIT_FALLBACK_REASON_PREFIX,
    FLAG_PERSISTENCE_REASON_PREFIX,
    QUALITY_GATE_REASON_PREFIX,
    RISK_ROUTING_REASON_PREFIX,
    TOP_N_REASON_PREFIX,
    RISK_TWIN_REVIEW_REASON_PREFIX,
)


def reject_reserved_reason_prefixes(
    items: Iterable[GlobalReviewItem], *, fallback_blocked: Collection[str] = frozenset()
) -> None:
    """Model review reasons may not start with a Python-only routing prefix.

    The only exemption: a row in ``fallback_blocked`` (blocked by the Global Audit
    fallback itself) may carry the audit-fallback prefix, and no other prefix.
    """

    exempt = frozenset(fallback_blocked)
    for item in items:
        if item.candidate_id in exempt and item.review_reason.startswith(
            AUDIT_FALLBACK_REASON_PREFIX
        ):
            continue
        if item.review_reason.startswith(DETERMINISTIC_REASON_PREFIXES):
            raise ValueError(
                f"review_reason of {item.candidate_id} starts with a prefix reserved for "
                "deterministic Python routing; write the reason without it"
            )


class AuditPairFallback(BaseModel):
    """One downgrade-only Global Audit fallback action recorded in the run manifest.

    ``near_identical_pair``: the pair was resolved by blocking
    ``blocked_candidate_id`` (a member of the pair); one record per resolved pair.
    Representative rules: the model's duplicate ``duplicate_candidate_id`` was
    accepted unchanged (nothing can be fixed without promoting a candidate).
    ``orphaned_duplicate``: the fallback blocked ``blocked_candidate_id``, the
    resolved representative of the rejected duplicate ``duplicate_candidate_id``;
    ``pair_kind`` names the listed pair of the two, or is ``None`` when they were
    not a listed pair (a Global Review-level duplicate).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    rule: AuditPairRule
    outer_candidate_id: str = Field(min_length=1)
    inner_candidate_id: str = Field(min_length=1)
    blocked_candidate_id: str | None = None
    duplicate_candidate_id: str | None = None
    pair_kind: AuditPairKind | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> AuditPairFallback:
        members = {self.outer_candidate_id, self.inner_candidate_id}
        if len(members) != 2:
            raise ValueError("audit pair fallback must name two different candidates")
        if self.rule == AuditPairRule.NEAR_IDENTICAL_PAIR:
            if (
                self.blocked_candidate_id not in members
                or self.duplicate_candidate_id
                or self.pair_kind is not None
            ):
                raise ValueError("near-identical audit fallback must block one pair member")
        elif self.rule == AuditPairRule.ORPHANED_DUPLICATE:
            if {self.blocked_candidate_id, self.duplicate_candidate_id} != members:
                raise ValueError(
                    "orphaned-duplicate audit fallback must name the blocked representative "
                    "and its duplicate"
                )
        elif (
            self.duplicate_candidate_id not in members
            or self.blocked_candidate_id
            or self.pair_kind is not None
        ):
            raise ValueError("representative audit fallback must name the pair's duplicate")
        return self


class DualProfileRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    algorithm_version: Literal["dual-profile-direct-v1"] = "dual-profile-direct-v1"
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_profiles: tuple[ClipProfile, ...]
    executed_profiles: tuple[ClipProfile, ...]
    profiles: dict[ClipProfile, ProfileManifestStats]
    provider: str
    model: str
    prompt_files: dict[str, tuple[str, ...]]
    prompt_hashes: dict[str, str]
    calls: dict[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    retry_count: int = Field(default=0, ge=0)
    repair_count: int = Field(ge=0)
    # Stage 12b audit fields; manifests written before them load with the defaults.
    stale_cache_refresh_enabled: bool = False
    stale_cache_resolution_count: int = Field(default=0, ge=0)
    stale_cache_resolutions: tuple[StaleCacheResolution, ...] = ()
    boundary_opening_fallbacks: tuple[BoundaryOpeningFallback, ...] = ()
    # Stage 13b audit field; manifests written before it load with the default.
    audit_pair_fallbacks: tuple[AuditPairFallback, ...] = ()
    # Stage 13c run diagnostic: per Profile, the rejected/blocked duplicates of the
    # final merged review whose resolved representative carries persisted
    # Discovery gated flags (so the representative is blocked by routing and the
    # duplicates are lost with it). The audit validator enforces this only for
    # listed pairs; Global Review-level duplicates rely on the prompt alone.
    persisted_flag_representative_duplicates: dict[ClipProfile, int] = Field(default_factory=dict)
    # Stage 15 run diagnostic (routing v6): per Profile, the number of
    # (candidate, gated flag) pairs that the same-interval twin union did NOT
    # propagate because only risk-discovery records of that interval carried the
    # flag (``same_interval_twin_flags``). Manifests written before it load with
    # the default.
    risk_twin_flags_not_propagated: dict[ClipProfile, int] = Field(default_factory=dict)
    # Stage 15b run diagnostic (routing v7): per Profile, the number of final rows
    # that risk-twin review downgraded from ``selected`` to ``manual_review``
    # (``risk_twin_review``). Manifests written before it load with the default.
    risk_twin_review_downgrades: dict[ClipProfile, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stale_cache_audit(self) -> DualProfileRunManifest:
        if self.stale_cache_resolution_count != len(self.stale_cache_resolutions):
            raise ValueError("stale cache resolution count differs from its records")
        if self.stale_cache_resolutions and not self.stale_cache_refresh_enabled:
            raise ValueError("stale cache resolutions require the explicit refresh option")
        self._check_audit_records()
        return self

    def _check_audit_records(self) -> None:
        if any(
            value.cache_key == value.superseding_cache_key for value in self.stale_cache_resolutions
        ):
            raise ValueError("stale cache resolution must name a different superseding key")
        fallback_ids = [
            (value.profile, candidate_id)
            for value in self.boundary_opening_fallbacks
            for candidate_id in value.candidate_ids
        ]
        if len(fallback_ids) != len(set(fallback_ids)):
            raise ValueError("Boundary opening fallback candidate IDs are not unique")
        subjects = [(value.profile, value.subject_id) for value in self.boundary_opening_fallbacks]
        if len(subjects) != len(set(subjects)):
            raise ValueError("Boundary opening fallback repeats a Boundary Review batch")
        actions = [
            (
                value.profile,
                value.rule,
                frozenset((value.outer_candidate_id, value.inner_candidate_id)),
                value.duplicate_candidate_id,
            )
            for value in self.audit_pair_fallbacks
        ]
        if len(actions) != len(set(actions)):
            raise ValueError("audit pair fallback repeats an action")
        near = [
            value
            for value in self.audit_pair_fallbacks
            if value.rule == AuditPairRule.NEAR_IDENTICAL_PAIR
        ]
        blocked = {(value.profile, value.blocked_candidate_id) for value in near}
        # Every blocked member keeps at least one retained near-identical partner.
        for profile, candidate_id in blocked:
            if not any(
                value.profile == profile
                and value.blocked_candidate_id == candidate_id
                and (
                    profile,
                    value.inner_candidate_id
                    if value.outer_candidate_id == candidate_id
                    else value.outer_candidate_id,
                )
                not in blocked
                for value in near
            ):
                raise ValueError(
                    "audit pair fallback blocked a member without a kept near-identical partner"
                )
        for value in self.audit_pair_fallbacks:
            if (
                value.rule == AuditPairRule.ORPHANED_DUPLICATE
                and (value.profile, value.blocked_candidate_id) not in blocked
            ):
                raise ValueError("orphaned duplicate names a representative the fallback kept")

    def validate_against(
        self,
        result: DualProfileFinalResult,
        *,
        boundaries: Mapping[ClipProfile, ProfileBoundaryReviewOutput] | None = None,
        risk_record_ids: Mapping[ClipProfile, Collection[str]] | None = None,
    ) -> None:
        """Cross-check the manifest with the final result (and, when the run's
        Boundary Review output is available, with that output too).

        When the structural risk-discovery membership of the run is supplied
        (``risk_record_ids``), the final arrays must satisfy the v6 twin rule
        (no flag left to inherit from a non-risk same-interval twin) and the v7
        risk-twin review rule (no ``selected`` row left to downgrade; every
        risk-twin review prefix backed by an automatic-blocking risk twin), and
        the ``risk_twin_flags_not_propagated`` and ``risk_twin_review_downgrades``
        diagnostics must equal the counts the same shared rules derive.
        """

        if (
            self.source_hash != result.source_hash
            or self.requested_profiles != result.requested_profiles
            or self.executed_profiles != result.executed_profiles
        ):
            raise ValueError("run manifest identity differs from final result")
        expected = {
            profile: ProfileManifestStats(**value.statistics.model_dump())
            for profile, value in result.profiles.items()
        }
        if self.profiles != expected:
            raise ValueError("run manifest Profile counts differ from final arrays")
        self._check_audit_records()
        if risk_record_ids is not None:
            not_propagated: dict[ClipProfile, int] = {}
            downgrades: dict[ClipProfile, int] = {}
            for profile, final_profile in result.profiles.items():
                final_rows = final_profile_rows(final_profile).values()
                profile_risk_ids = risk_record_ids.get(profile, ())
                twins = same_interval_twin_flags(final_rows, profile_risk_ids)
                if any(twins.inherited.values()):
                    raise ValueError("final result violates the same-interval twin flag rule")
                not_propagated[profile] = twins.not_propagated_count
                review = risk_twin_review(final_rows, profile_risk_ids)
                if review.pending:
                    raise ValueError("final result violates the risk-twin review rule")
                if any(candidate_id not in review.sources for candidate_id in review.downgraded):
                    raise ValueError(
                        "final row carries the risk-twin review prefix without an "
                        "automatic-blocking risk twin"
                    )
                downgrades[profile] = review.downgraded_count
            if self.risk_twin_flags_not_propagated != not_propagated:
                raise ValueError(
                    "run manifest risk-twin flag diagnostic differs from the final result"
                )
            if self.risk_twin_review_downgrades != downgrades:
                raise ValueError(
                    "run manifest risk-twin review diagnostic differs from the final result"
                )
        for fallback in self.boundary_opening_fallbacks:
            profile_result = result.profiles.get(fallback.profile)
            if profile_result is None:
                raise ValueError("Boundary opening fallback names an unexecuted Profile")
            # Every final row traces to exactly one Boundary Review row (assembly
            # requires full coverage), so final membership is Boundary membership.
            final_ids = {
                value.candidate_id
                for group in (
                    profile_result.selected,
                    profile_result.manual_review,
                    profile_result.blocked,
                    profile_result.rejected,
                )
                for value in group
            }
            selected_ids = {value.candidate_id for value in profile_result.selected}
            for candidate_id in fallback.candidate_ids:
                if candidate_id not in final_ids:
                    raise ValueError("Boundary opening fallback names a candidate outside the run")
                if candidate_id in selected_ids:
                    raise ValueError("Boundary opening fallback candidate was selected")
            if boundaries is not None:
                boundary = boundaries.get(fallback.profile)
                rows = (
                    {value.candidate_id: value for value in boundary.reviews}
                    if boundary is not None
                    else {}
                )
                for candidate_id in fallback.candidate_ids:
                    row = rows.get(candidate_id)
                    if row is None:
                        raise ValueError(
                            "Boundary opening fallback names a candidate outside the "
                            "Boundary Review output"
                        )
                    if row.opening_complete:
                        raise ValueError(
                            "Boundary opening fallback candidate still claims a complete opening"
                        )
        fallback_blocked = {
            (value.profile, value.blocked_candidate_id)
            for value in self.audit_pair_fallbacks
            if value.rule == AuditPairRule.NEAR_IDENTICAL_PAIR
        }
        for action in self.audit_pair_fallbacks:
            profile_result = result.profiles.get(action.profile)
            if profile_result is None:
                raise ValueError("audit pair fallback names an unexecuted Profile")
            status_by_id = final_profile_rows(profile_result)
            if not {action.outer_candidate_id, action.inner_candidate_id} <= set(status_by_id):
                raise ValueError("audit pair fallback names a candidate outside the run")
            if action.blocked_candidate_id is not None:
                blocked_row = status_by_id[action.blocked_candidate_id]
                if blocked_row.review_status != CandidateDisposition.BLOCKED or not (
                    blocked_row.review_reason.startswith(AUDIT_FALLBACK_REASON_PREFIX)
                ):
                    raise ValueError("audit pair fallback candidate was not blocked by it")
            if action.duplicate_candidate_id is not None:
                duplicate_row = status_by_id[action.duplicate_candidate_id]
                if duplicate_row.review_status not in {
                    CandidateDisposition.REJECTED,
                    CandidateDisposition.BLOCKED,
                }:
                    raise ValueError("audit pair fallback duplicate became an output")
                if (
                    action.rule == AuditPairRule.ORPHANED_DUPLICATE
                    and duplicate_row.duplicate_of_candidate_id is None
                ):
                    raise ValueError("orphaned duplicate lost its duplicate reference")
        # Reverse checks (Stage 13c): every Python-only prefix in the final arrays
        # is backed by its deterministic decision, so a model-written prefix is
        # refused here as well as at review validation.
        for profile, profile_result in result.profiles.items():
            for value in final_profile_rows(profile_result).values():
                reason = value.review_reason
                if reason.startswith(AUDIT_FALLBACK_REASON_PREFIX) and (
                    (profile, value.candidate_id) not in fallback_blocked
                ):
                    raise ValueError(
                        "final row carries the audit fallback prefix without a manifest record"
                    )
                if reason.startswith(TOP_N_REASON_PREFIX):
                    required_status = CandidateDisposition.REJECTED
                elif reason.startswith(RISK_TWIN_REVIEW_REASON_PREFIX):
                    required_status = CandidateDisposition.MANUAL_REVIEW
                elif reason.startswith(DETERMINISTIC_REASON_PREFIXES):
                    required_status = CandidateDisposition.BLOCKED
                else:
                    continue
                if value.review_status != required_status:
                    raise ValueError(
                        "final row carries a deterministic routing prefix inconsistent with "
                        "its status"
                    )


def final_profile_rows(result: FinalProfileResult) -> dict[str, FinalProfileCandidate]:
    """Every final row of one Profile by candidate ID, in terminal-array order."""

    return {
        value.candidate_id: value
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
    }


def plan_profile_discovery_windows(
    transcript: TranscriptDocument,
    profile: ClipProfile,
) -> tuple[DiscoveryWindow, ...]:
    cues = transcript_cues(transcript)
    if not cues:
        raise ValueError("transcript contains no cues")
    duration_ms = max(value.end_ms for value in cues)
    if profile == ClipProfile.SHORT_HIGHLIGHT:
        context_ms, ownership_ms, stride_ms = (
            SHORT_CONTEXT_MS,
            SHORT_OWNERSHIP_MS,
            SHORT_STRIDE_MS,
        )
    else:
        context_ms, ownership_ms, stride_ms = MINI_CONTEXT_MS, MINI_OWNERSHIP_MS, MINI_STRIDE_MS
    starts = list(range(0, max(duration_ms, 1), stride_ms))
    tail_start = max(0, duration_ms - context_ms)
    windows: list[DiscoveryWindow] = []
    for index, ownership_start_ms in enumerate(starts):
        context_start_ms = (
            tail_start
            if ownership_start_ms + context_ms > duration_ms and duration_ms > context_ms
            else ownership_start_ms
        )
        context_end_ms = min(duration_ms, context_start_ms + context_ms)
        ownership_end_ms = min(duration_ms, ownership_start_ms + ownership_ms)
        selected = tuple(
            value
            for value in cues
            if value.end_ms > context_start_ms and value.start_ms < context_end_ms
        )
        if not selected:
            continue
        windows.append(
            DiscoveryWindow(
                window_id=(
                    f"{profile.value}_{index:04d}_{context_start_ms}_{context_end_ms}_"
                    f"{ownership_start_ms}_{ownership_end_ms}"
                ),
                profile=profile,
                context_start_ms=context_start_ms,
                context_end_ms=context_end_ms,
                ownership_start_ms=ownership_start_ms,
                ownership_end_ms=ownership_end_ms,
                cues=selected,
            )
        )
    return tuple(windows)


def validate_discovery_output(
    output: ProfileDiscoveryOutput,
    *,
    window: DiscoveryWindow,
    transcript: TranscriptDocument,
) -> ProfileDiscoveryOutput:
    if output.profile != window.profile or output.window_id != window.window_id:
        raise ValueError("Discovery output identity differs from its request")
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    available = {value.cue_id for value in window.cues}
    seen: set[str] = set()
    contract = PROFILE_DURATION_CONTRACTS[window.profile]
    for candidate in output.candidates:
        if candidate.candidate_id in seen:
            raise ValueError("Discovery repeats a candidate ID")
        seen.add(candidate.candidate_id)
        if candidate.profile != window.profile or candidate.source_window_id != window.window_id:
            raise ValueError("Discovery candidate has the wrong Profile/window")
        referenced = set(range(candidate.start_cue_id, candidate.end_cue_id + 1))
        if not referenced <= available:
            raise ValueError("Discovery candidate references cues outside its context")
        try:
            start = cue_map[candidate.start_cue_id].start_ms
            end = cue_map[candidate.end_cue_id].end_ms
        except KeyError as exc:
            raise ValueError("Discovery candidate references an unknown cue") from exc
        if not (window.ownership_start_ms <= start < window.ownership_end_ms):
            raise ValueError(
                "Discovery candidate "
                f"{candidate.candidate_id!r} starts at {start} ms outside ownership "
                f"[{window.ownership_start_ms}, {window.ownership_end_ms})"
            )
        if not contract.accepts(end - start):
            raise ValueError(
                "Discovery candidate "
                f"{candidate.candidate_id!r} has duration {end - start} ms, which violates "
                f"Profile duration for {window.profile.value!r}: it must be "
                f"{'greater than or equal to' if contract.min_inclusive else 'greater than'} "
                f"{contract.min_duration_ms} ms and less than or equal to "
                f"{contract.max_duration_ms} ms"
            )
    return output


class BoundaryOpeningInvariantError(ValueError):
    """The only Boundary Review failure: ``context_dependent_opening`` rows that also
    claim ``opening_complete=true``. Every violating candidate ID is listed."""

    def __init__(self, candidate_ids: tuple[str, ...]) -> None:
        self.candidate_ids = candidate_ids
        super().__init__(
            "Boundary Review context_dependent_opening requires opening_complete=false; "
            f"violating candidates: {', '.join(candidate_ids)}. Set opening_complete to "
            "false for each, or remove the flag where the opening is complete"
        )


def apply_boundary_opening_fallback(
    output: ProfileBoundaryReviewOutput,
    candidate_ids: Collection[str],
) -> ProfileBoundaryReviewOutput:
    """Conservative last resort after repair and regeneration: only downgrade.

    The listed rows keep their ``context_dependent_opening`` flag and get
    ``opening_complete=false``; nothing else changes, so the candidate can never be
    selected but stays reviewable under the advisory-flag contract.
    """

    targets = frozenset(candidate_ids)
    return output.model_copy(
        update={
            "reviews": tuple(
                item.model_copy(update={"opening_complete": False})
                if item.candidate_id in targets
                else item
                for item in output.reviews
            )
        }
    )


def validate_boundary_review_output(
    output: ProfileBoundaryReviewOutput,
    *,
    profile: ClipProfile,
    candidates: Sequence[RawProfileCandidate],
    transcript: TranscriptDocument,
    risk_record_ids: Collection[str],
) -> ProfileBoundaryReviewOutput:
    """Validate Boundary Review facts.

    Risk tags are cumulative for every candidate.  The Discovery evidence-cue
    lock for medical/health/sensitivity risk chains applies only to records of
    the dedicated risk-discovery pass (``risk_record_ids``, derived
    structurally); other candidates may trim leading/trailing evidence cues
    while keeping every risk tag.
    """
    if output.profile != profile:
        raise ValueError("Boundary Review used the wrong Profile")
    risk_records = frozenset(risk_record_ids)
    candidate_map = {value.candidate_id: value for value in candidates}
    review_map = {value.candidate_id: value for value in output.reviews}
    if len(candidate_map) != len(candidates) or len(review_map) != len(output.reviews):
        raise ValueError("Boundary Review candidate IDs are not unique")
    if set(candidate_map) != set(review_map):
        raise ValueError("Boundary Review must cover every raw candidate exactly once")
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    contract = PROFILE_DURATION_CONTRACTS[profile]
    opening_violations: list[str] = []
    for candidate_id, review in review_map.items():
        if review.profile != profile:
            raise ValueError("Boundary Review candidate crossed Profile boundaries")
        try:
            start_ms = cue_map[review.start_cue_id].start_ms
            end_ms = cue_map[review.end_cue_id].end_ms
        except KeyError as exc:
            raise ValueError("Boundary Review references an unknown cue") from exc
        if review.end_cue_id < review.start_cue_id or not contract.accepts(end_ms - start_ms):
            raise ValueError("Boundary Review interval violates its Profile duration")
        if any(
            cue_id < review.start_cue_id or cue_id > review.end_cue_id
            for cue_id in review.evidence_cue_ids
        ):
            raise ValueError("Boundary Review evidence lies outside its final interval")
        if DualQualityFlag.CONTEXT_DEPENDENT_OPENING in review.quality_flags and (
            review.opening_complete
        ):
            # Consistency invariant: a kept opening dependency cannot coexist with a
            # complete opening. Collected so one message names every violating row;
            # it is raised only after every other check passed.
            opening_violations.append(candidate_id)
        raw = candidate_map[candidate_id]
        if not set(review.risk_tags).issuperset(raw.risk_tags):
            raise ValueError("Boundary Review silently removed a Discovery risk")
        evidence_preservation_tags = {
            DualRiskTag.MEDICAL_CLAIM,
            DualRiskTag.MEDICAL_DIAGNOSIS_HIGH,
            DualRiskTag.HEALTH_ADVICE,
            DualRiskTag.SENSITIVITY_REVIEW,
        }
        if (
            candidate_id in risk_records
            and set(raw.risk_tags) & evidence_preservation_tags
            and any(
                cue_id < review.start_cue_id or cue_id > review.end_cue_id
                for cue_id in raw.evidence_cue_ids
            )
        ):
            raise ValueError(
                "Boundary Review removed a Discovery evidence cue from a medical, health, "
                "or sensitivity risk chain"
            )
    if opening_violations:
        raise BoundaryOpeningInvariantError(tuple(opening_violations))
    return output


def nested_candidate_pairs(
    global_review: ProfileGlobalReviewOutput,
) -> tuple[tuple[str, str], ...]:
    """List same-Profile selected/manual_review pairs that share a start or end cue.

    Sharing an edge on one continuous interval means one candidate contains the
    other.  Each pair is returned once as ``(outer_candidate_id, inner_candidate_id)``
    in deterministic order.  Containment alone never decides duplication; the
    Global Audit must decide every listed pair explicitly.
    """
    retained = sorted(
        (
            value
            for value in global_review.reviews
            if value.review_status
            in {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
        ),
        key=lambda value: (value.start_cue_id, -value.end_cue_id, value.candidate_id),
    )
    pairs: list[tuple[str, str]] = []
    for index, outer in enumerate(retained):
        for inner in retained[index + 1 :]:
            if outer.profile != inner.profile:
                continue
            if inner.start_cue_id != outer.start_cue_id and inner.end_cue_id != outer.end_cue_id:
                continue
            if outer.start_cue_id <= inner.start_cue_id and inner.end_cue_id <= outer.end_cue_id:
                pairs.append((outer.candidate_id, inner.candidate_id))
    return tuple(pairs)


def audit_candidate_pairs(
    global_review: ProfileGlobalReviewOutput,
    transcript: TranscriptDocument,
) -> tuple[AuditCandidatePair, ...]:
    """List every same-Profile retained pair the Global Audit must decide.

    * ``nested``: exactly ``nested_candidate_pairs`` (shared edge cue, containment).
    * ``overlap``: other selected/manual_review pairs in which neither candidate
      contains the other and the shared media is at least
      ``AUDIT_OVERLAP_MIN_SHORTER_FRACTION`` of the shorter candidate.  It is
      ``near_identical`` when the ends are within the Profile's
      ``AUDIT_SAME_END_TOLERANCE_MS`` or the overlap is at least
      ``AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION`` of the shorter candidate.
    * ``containment`` (Stage 13b): one candidate strictly inside the other without
      a shared edge cue, listed only when it is a near-copy: the inner duration is
      at least ``AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION`` of the outer, or the ends
      are within the tolerance (Stage 13c: close starts alone do not qualify).
      Always ``near_identical``.  Other containment (a full lesson with a shorter
      clip inside it) stays unlisted.
    """

    nested = nested_candidate_pairs(global_review)
    pairs = [
        AuditCandidatePair(
            outer_candidate_id=outer, inner_candidate_id=inner, pair_kind=AuditPairKind.NESTED
        )
        for outer, inner in nested
    ]
    nested_keys = {frozenset(pair) for pair in nested}
    retained = sorted(
        (
            value
            for value in global_review.reviews
            if value.review_status
            in {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
        ),
        key=lambda value: (value.start_cue_id, -value.end_cue_id, value.candidate_id),
    )
    spans = candidate_spans_ms(retained, transcript)
    tolerance_ms = AUDIT_SAME_END_TOLERANCE_MS[global_review.profile]
    for index, first in enumerate(retained):
        for second in retained[index + 1 :]:
            if first.profile != second.profile:
                continue
            if frozenset((first.candidate_id, second.candidate_id)) in nested_keys:
                continue
            first_start, first_end = spans[first.candidate_id]
            second_start, second_end = spans[second.candidate_id]
            first_inside = second_start <= first_start and first_end <= second_end
            second_inside = first_start <= second_start and second_end <= first_end
            if first_inside or second_inside:
                outer, inner = (
                    (second, first)
                    if first_inside and not second_inside
                    else (
                        first,
                        second,
                    )
                )
                outer_start, outer_end = spans[outer.candidate_id]
                inner_start, inner_end = spans[inner.candidate_id]
                # User decision (2026-10-30): near-copy means the inner covers at
                # least 9/10 of the outer, or the ends are within the tolerance.
                if (
                    inner_end - inner_start
                    >= (outer_end - outer_start) * AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION
                    or outer_end - inner_end <= tolerance_ms
                ):
                    pairs.append(
                        AuditCandidatePair(
                            outer_candidate_id=outer.candidate_id,
                            inner_candidate_id=inner.candidate_id,
                            pair_kind=AuditPairKind.CONTAINMENT,
                            near_identical=True,
                        )
                    )
                continue
            overlap_ms = min(first_end, second_end) - max(first_start, second_start)
            shorter_ms = min(first_end - first_start, second_end - second_start)
            if overlap_ms <= 0 or overlap_ms < shorter_ms * AUDIT_OVERLAP_MIN_SHORTER_FRACTION:
                continue
            pairs.append(
                AuditCandidatePair(
                    outer_candidate_id=first.candidate_id,
                    inner_candidate_id=second.candidate_id,
                    pair_kind=AuditPairKind.OVERLAP,
                    near_identical=(
                        abs(first_end - second_end) <= tolerance_ms
                        or overlap_ms >= shorter_ms * AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION
                    ),
                )
            )
    return tuple(pairs)


def candidate_spans_ms(
    reviews: Iterable[GlobalReviewItem], transcript: TranscriptDocument
) -> dict[str, tuple[int, int]]:
    """Exact ``(start_ms, end_ms)`` of each review item from its cue IDs."""

    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    try:
        return {
            value.candidate_id: (
                cue_map[value.start_cue_id].start_ms,
                cue_map[value.end_cue_id].end_ms,
            )
            for value in reviews
        }
    except KeyError as exc:
        raise ValueError("Global Review references an unknown cue") from exc


def _duplicate_representative(
    candidate_id: str, review_map: Mapping[str, GlobalReviewItem]
) -> str | None:
    """Follow duplicate references to the retained representative (cycle-safe)."""

    visited: set[str] = set()
    current = candidate_id
    while True:
        if current in visited or current not in review_map:
            return None
        visited.add(current)
        following = review_map[current].duplicate_of_candidate_id
        if following is None:
            return current
        current = following


class AuditPairRuleError(ValueError):
    """The only Global Audit failures left are deterministic audit-pair rules.

    Raised only after every other audit check passed, so a caller can tell these
    (eligible for the downgrade-only audit fallback) from any other failure.
    """

    def __init__(self, violations: tuple[AuditPairViolation, ...]) -> None:
        self.violations = violations
        messages = []
        for value in violations:
            pair = f"{value.outer_candidate_id}/{value.inner_candidate_id}"
            if value.rule == AuditPairRule.NEAR_IDENTICAL_PAIR:
                messages.append(
                    f"Global Audit near-identical pair {pair} cannot keep both candidates "
                    "selected or manual_review; keep one representative"
                )
            elif value.rule == AuditPairRule.OVERLAP_REPRESENTATIVE:
                messages.append(
                    f"Global Audit overlap duplicate {pair}: duplicate "
                    f"{value.duplicate_candidate_id} must keep a selected or manual_review "
                    "representative"
                )
            else:
                messages.append(
                    f"Global Audit duplicate {pair}: duplicate {value.duplicate_candidate_id} "
                    "resolves to a representative with persisted Discovery gated flags, "
                    "which Python will block; choose a representative without persisted flags"
                )
        super().__init__(_join_errors(messages))

    @property
    def near_identical(self) -> tuple[AuditPairViolation, ...]:
        return tuple(v for v in self.violations if v.rule == AuditPairRule.NEAR_IDENTICAL_PAIR)


def validate_audit_pair_decisions(
    pairs: Sequence[AuditCandidatePair],
    decisions: Sequence[NestedPairDecision],
    merged_review: ProfileGlobalReviewOutput,
    *,
    persisted_flag_ids: Collection[str] = frozenset(),
) -> None:
    """Require one consistent audit decision for every listed pair.

    Every pair uses the ``validate_nested_pair_decisions`` semantics (exact
    coverage, direct or shared-representative duplicates, ``distinct_objective``
    without a direct reference); those failures raise a plain ``ValueError``
    first.  Then the deterministic rules below are collected into one
    ``AuditPairRuleError``:

    * ``near_identical`` pairs (overlap or containment) may not leave both
      members ``selected`` or ``manual_review``.  Whether a free-text reason
      really names a distinct objective cannot be checked deterministically, so
      near-identical media is never kept twice;
    * a ``duplicate`` decision on an overlap or containment pair must leave the
      resolved representative of each removed member ``selected`` or
      ``manual_review``, so deduplication never deletes the last retained version;
    * (Stage 13b) a ``duplicate`` decision on any pair may not resolve to a
      representative in ``persisted_flag_ids`` (Discovery gated flags that will
      persist into final routing), because Python will block that representative
      and its duplicates would be lost with it.
    """

    validate_nested_pair_decisions(
        tuple((pair.outer_candidate_id, pair.inner_candidate_id) for pair in pairs),
        decisions,
        merged_review,
    )
    review_map = {value.candidate_id: value for value in merged_review.reviews}
    retained = {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
    persisted = frozenset(persisted_flag_ids)
    decision_map = {
        frozenset((value.outer_candidate_id, value.inner_candidate_id)): value
        for value in decisions
    }
    violations: list[AuditPairViolation] = []
    for pair in pairs:
        members = [review_map[candidate_id] for candidate_id in sorted(pair.members)]
        identity = {
            "outer_candidate_id": pair.outer_candidate_id,
            "inner_candidate_id": pair.inner_candidate_id,
        }
        if pair.near_identical and all(value.review_status in retained for value in members):
            violations.append(
                AuditPairViolation(rule=AuditPairRule.NEAR_IDENTICAL_PAIR, **identity)
            )
        if decision_map[pair.members].decision != NestedPairDecisionKind.DUPLICATE:
            continue
        for value in members:
            if value.review_status in retained or value.duplicate_of_candidate_id is None:
                continue
            representative = _duplicate_representative(value.candidate_id, review_map)
            if pair.pair_kind != AuditPairKind.NESTED and (
                representative is None
                or representative == value.candidate_id
                or review_map[representative].review_status not in retained
            ):
                violations.append(
                    AuditPairViolation(
                        rule=AuditPairRule.OVERLAP_REPRESENTATIVE,
                        duplicate_candidate_id=value.candidate_id,
                        **identity,
                    )
                )
            elif representative is not None and representative in persisted:
                violations.append(
                    AuditPairViolation(
                        rule=AuditPairRule.PERSISTED_FLAG_REPRESENTATIVE,
                        duplicate_candidate_id=value.candidate_id,
                        **identity,
                    )
                )
    if violations:
        raise AuditPairRuleError(tuple(violations))


def resolved_duplicates(
    merged_review: ProfileGlobalReviewOutput,
) -> dict[str, tuple[str, ...]]:
    """Map each representative to the non-retained duplicates that resolve to it."""

    review_map = {value.candidate_id: value for value in merged_review.reviews}
    retained = {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
    result: dict[str, list[str]] = {}
    for value in merged_review.reviews:
        if value.duplicate_of_candidate_id is None or value.review_status in retained:
            continue
        representative = _duplicate_representative(value.candidate_id, review_map)
        if representative is not None and representative != value.candidate_id:
            result.setdefault(representative, []).append(value.candidate_id)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def plan_audit_pair_fallback(
    error: AuditPairRuleError,
    merged_review: ProfileGlobalReviewOutput,
    transcript: TranscriptDocument,
    *,
    persisted_flag_ids: Collection[str] = frozenset(),
) -> tuple[tuple[str, tuple[str, str]], ...]:
    """Choose which members to block for violating near-identical pairs.

    Members of violating pairs are visited in a fully deterministic keep order:

    1. no persisted Discovery gated flag first (final routing blocks such a
       member anyway);
    2. shorter duration (the user-approved "keep the shortest independently
       complete version" policy; a duplicate count is only a proxy and must
       not override it);
    3. (Stage 13c) more resolved duplicates, so among equally long members a
       representative is kept and its duplicates are not orphaned;
    4. earlier start, then smaller ID.

    Duplicates of a blocked representative are orphaned and recorded by the
    caller (``orphaned_duplicate``); nothing is promoted.

    A visited member that is not yet blocked is kept and every violating partner
    not yet decided is blocked, so every blocked member has a kept near-identical
    partner that stays retained.  Without persisted flags this blocks the
    longer member (ties: fewer resolved duplicates, then later start, then
    larger ID).  Coverage
    caveat: near-identical is not identical; for same-end or near-copy pairs the
    blocked longer member can hold media the kept shorter member lacks, which is
    the keep-the-shortest-complete-version policy.  (In a chain A > B > C where C
    blocks B, A/B is already resolved by B's block and A stays retained.)

    Returns one ``(blocked_id, (outer_id, inner_id))`` per violating pair, where
    ``blocked_id`` is the member whose block resolved that pair first.
    """

    review_map = {value.candidate_id: value for value in merged_review.reviews}
    partners: dict[str, dict[str, tuple[str, str]]] = {}
    for value in error.near_identical:
        pair = (value.outer_candidate_id, value.inner_candidate_id)
        partners.setdefault(pair[0], {})[pair[1]] = pair
        partners.setdefault(pair[1], {})[pair[0]] = pair
    spans = candidate_spans_ms((review_map[key] for key in partners), transcript)
    persisted = frozenset(persisted_flag_ids)
    duplicates = resolved_duplicates(merged_review)
    order = sorted(
        partners,
        key=lambda key: (
            key in persisted,
            spans[key][1] - spans[key][0],
            -len(duplicates.get(key, ())),
            spans[key][0],
            key,
        ),
    )
    kept: set[str] = set()
    block_sequence: dict[str, int] = {}
    for candidate_id in order:
        if candidate_id in block_sequence:
            continue
        kept.add(candidate_id)
        for partner in sorted(partners[candidate_id]):
            if partner not in kept and partner not in block_sequence:
                block_sequence[partner] = len(block_sequence)
    resolutions: list[tuple[str, tuple[str, str]]] = []
    for pair in sorted({pair for values in partners.values() for pair in values.values()}):
        blocked = sorted(
            (member for member in pair if member in block_sequence),
            key=block_sequence.__getitem__,
        )
        resolutions.append((blocked[0], pair))
    return tuple(sorted(resolutions))


def apply_audit_pair_blocks(
    output: ProfileGlobalAuditOutput,
    initial_review: ProfileGlobalReviewOutput,
    blocked_ids: Collection[str],
) -> ProfileGlobalAuditOutput:
    """Downgrade the listed retained candidates to ``blocked`` in the audit output."""

    targets = frozenset(blocked_ids)
    replacement_map = {value.candidate_id: value for value in output.replacements}
    updated = list(output.replacements)
    for item in initial_review.reviews:
        if item.candidate_id not in targets:
            continue
        base = replacement_map.get(item.candidate_id, item)
        if base.review_status not in {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
        }:
            raise ValueError("audit fallback may block only a retained candidate")
        blocked = base.model_copy(
            update={
                "review_status": CandidateDisposition.BLOCKED,
                "review_reason": f"{AUDIT_FALLBACK_REASON_PREFIX}{base.review_reason}"[:800],
            }
        )
        if item.candidate_id in replacement_map:
            updated = [blocked if v.candidate_id == item.candidate_id else v for v in updated]
        else:
            updated.append(blocked)
    return output.model_copy(update={"replacements": tuple(updated)})


def validate_nested_pair_decisions(
    pairs: Sequence[tuple[str, str]],
    decisions: Sequence[NestedPairDecision],
    merged_review: ProfileGlobalReviewOutput,
) -> None:
    """Require exactly one consistent audit decision for every listed nested pair.

    A ``duplicate`` decision needs one member left rejected/blocked with a direct
    duplicate reference to the other, or both members left rejected/blocked as
    duplicates that resolve to the same third representative (a cluster of three or
    more versions of one lesson).  ``distinct_objective`` forbids a direct reference.
    """

    expected = {frozenset(pair): pair for pair in pairs}
    seen: set[frozenset[str]] = set()
    review_map = {value.candidate_id: value for value in merged_review.reviews}
    non_retained = {CandidateDisposition.REJECTED, CandidateDisposition.BLOCKED}
    errors: list[str] = []

    def representative(candidate_id: str) -> str | None:
        return _duplicate_representative(candidate_id, review_map)

    for decision in decisions:
        key = frozenset((decision.outer_candidate_id, decision.inner_candidate_id))
        pair_text = f"{decision.outer_candidate_id}/{decision.inner_candidate_id}"
        if key not in expected:
            errors.append(
                "Global Audit nested_pair_decisions references a pair that was not listed: "
                f"{pair_text}"
            )
            continue
        if key in seen:
            errors.append(f"Global Audit decided pair {pair_text} more than once")
            continue
        seen.add(key)
        first, second = (
            review_map[decision.outer_candidate_id],
            review_map[decision.inner_candidate_id],
        )
        references = [
            value
            for value, other in ((first, second), (second, first))
            if value.duplicate_of_candidate_id == other.candidate_id
        ]
        if decision.decision == NestedPairDecisionKind.DUPLICATE:
            shared = representative(first.candidate_id)
            shares_representative = (
                shared is not None
                and shared not in {first.candidate_id, second.candidate_id}
                and shared == representative(second.candidate_id)
                and all(
                    value.duplicate_of_candidate_id is not None
                    and value.review_status in non_retained
                    for value in (first, second)
                )
            )
            if not shares_representative and not any(
                value.review_status in non_retained for value in references
            ):
                errors.append(
                    f"Global Audit pair {pair_text} is decided duplicate, but "
                    f"{_review_state(first)} and {_review_state(second)}; a duplicate "
                    "decision needs one member rejected or blocked with "
                    "duplicate_of_candidate_id naming the other, or both rejected or blocked "
                    "as duplicates of the same representative"
                )
        elif references:
            errors.extend(
                f"Global Audit marked pair {pair_text} distinct_objective, but "
                f"{_review_state(value)}; a distinct_objective pair may not reference each "
                "other as duplicates"
                for value in references
            )
    missing = sorted("/".join(expected[key]) for key in set(expected) - seen)
    if missing:
        errors.append(
            "Global Audit nested_pair_decisions must cover every listed nested pair: "
            + ", ".join(missing[:20])
        )
    if errors:
        raise ValueError(_join_errors(errors))


_MAX_REPORTED_ERRORS: Final = 20


def _review_state(item: GlobalReviewItem) -> str:
    reference = (
        f"duplicate_of {item.duplicate_of_candidate_id}"
        if item.duplicate_of_candidate_id is not None
        else "no duplicate_of"
    )
    return f"{item.candidate_id} is {item.review_status.value} with {reference}"


def _join_errors(errors: Sequence[str]) -> str:
    """One message with every violation (bounded), so a repair can fix them all."""

    shown = list(errors[:_MAX_REPORTED_ERRORS])
    if len(errors) > _MAX_REPORTED_ERRORS:
        shown.append(f"and {len(errors) - _MAX_REPORTED_ERRORS} more violations")
    return "; ".join(shown)


# A duplicate is never an output. Stage 13d (Controller decision): final assembly
# accepts either non-output status for any candidate, exactly as
# ``validate_nested_pair_decisions`` does (before, ``blocked`` was accepted only
# for risk-discovery records, so the two validators contradicted each other).
DUPLICATE_ALLOWED_STATUSES: Final = (CandidateDisposition.REJECTED, CandidateDisposition.BLOCKED)


def duplicate_status_violation(
    candidate_id: str,
    status: CandidateDisposition,
    duplicate_of: str,
) -> str | None:
    """Final-assembly rule for a row with ``duplicate_of_candidate_id``.

    Returns ``None`` when ``status`` is ``rejected`` or ``blocked``. A
    ``selected`` or ``manual_review`` duplicate is a hard validation error that
    names the candidate, its status, the duplicate target and the allowed
    statuses; Python never coerces it.
    """

    if status in DUPLICATE_ALLOWED_STATUSES:
        return None
    allowed_text = " or ".join(value.value for value in DUPLICATE_ALLOWED_STATUSES)
    return (
        f"duplicate {candidate_id} (status {status.value}, duplicate_of {duplicate_of}) is "
        "still an output: a candidate with duplicate_of_candidate_id must be "
        f"{allowed_text} (both are non-output), never selected or manual_review (make it "
        "non-output, or remove the reference if it is not a duplicate)"
    )


def assemble_final_profile_result(
    *,
    profile: ClipProfile,
    discoveries: Sequence[ProfileDiscoveryOutput],
    boundaries: ProfileBoundaryReviewOutput,
    global_review: ProfileGlobalReviewOutput,
    transcript: TranscriptDocument,
    top_n: int,
    score_threshold_exclusive: float = 75.0,
    risk_record_ids: Collection[str] = frozenset(),
) -> FinalProfileResult:
    """Validate review stages and deterministically route final dispositions.

    ``risk_record_ids`` must be derived structurally from the dedicated
    risk-discovery pass output, never from candidate-ID prefixes.  A rejected
    risk record is retained as ``blocked`` so risk material stays auditable.
    Routing only ever downgrades or retains; it never produces an output.

    Deterministic routing order (v7), each step only downgrading:

    1. validation of the review stages (unchanged: it sees only the merged
       Boundary/Global flags, so cached review outputs validate exactly as
       before), then Discovery structural gated-flag persistence per candidate
       (padding flags follow Boundary Review and are not persisted);
    2. same-interval twin union of gated flags (it includes persisted flags);
       risk records are not flag sources (``same_interval_twin_flags``);
    3. risk-twin review (``route_risk_twin_review``): a non-risk row still
       ``selected`` whose identical interval has a risk-discovery twin with an
       automatic-blocking risk tag becomes ``manual_review``;
    4. Profile-local Top-N over the rows still ``selected`` (rows downgraded by
       steps 1--3 never take a slot, so a replacement already obeys step 3);
    5. risk-record routing and the manual_review quality gate.
    """
    risk_records = frozenset(risk_record_ids)
    raw_candidates = tuple(value for output in discoveries for value in output.candidates)
    raw_map = {value.candidate_id: value for value in raw_candidates}
    if len(raw_map) != len(raw_candidates):
        raise ValueError("Discovery candidate IDs are not globally unique within Profile")
    boundary_map = {value.candidate_id: value for value in boundaries.reviews}
    review_map = {value.candidate_id: value for value in global_review.reviews}
    if boundaries.profile != profile or global_review.profile != profile:
        raise ValueError("review stage used the wrong Profile")
    if set(raw_map) != set(boundary_map) or set(raw_map) != set(review_map):
        raise ValueError("boundary/global review must cover every raw candidate exactly once")
    if len(boundary_map) != len(boundaries.reviews) or len(review_map) != len(
        global_review.reviews
    ):
        raise ValueError("review stage repeats a candidate")
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    final_values: list[FinalProfileCandidate] = []
    # Stage 13d: row-level rule violations are collected and reported together,
    # each naming its candidate, so one repair can fix every row.
    row_errors: list[str] = []
    for candidate_id, raw in raw_map.items():
        boundary = boundary_map[candidate_id]
        review = review_map[candidate_id]
        if boundary.profile != profile or review.profile != profile:
            raise ValueError(f"review candidate {candidate_id} crossed Profile boundaries")
        if (review.start_cue_id, review.end_cue_id) != (
            boundary.start_cue_id,
            boundary.end_cue_id,
        ):
            raise ValueError(f"Global Review changed the final Boundary interval of {candidate_id}")
        try:
            start_ms = cue_map[review.start_cue_id].start_ms
            end_ms = cue_map[review.end_cue_id].end_ms
        except KeyError as exc:
            raise ValueError(f"review of {candidate_id} references an unknown cue") from exc
        errors_before = len(row_errors)
        if review.duplicate_of_candidate_id is not None:
            representative = raw_map.get(review.duplicate_of_candidate_id)
            if representative is None or representative.profile != profile:
                row_errors.append(
                    f"duplicate {candidate_id} references {review.duplicate_of_candidate_id}, "
                    f"which is not a {profile.value} candidate of this review; a semantic "
                    "duplicate must reference the same Profile"
                )
            status_error = duplicate_status_violation(
                candidate_id, review.review_status, review.duplicate_of_candidate_id
            )
            if status_error is not None:
                row_errors.append(status_error)
        merged_quality = tuple(dict.fromkeys((*boundary.quality_flags, *review.quality_flags)))
        merged_risks = tuple(
            dict.fromkeys((*raw.risk_tags, *boundary.risk_tags, *review.risk_tags))
        )
        status = review.review_status
        if status == CandidateDisposition.SELECTED:
            if review.score <= score_threshold_exclusive:
                row_errors.append(
                    f"selected candidate {candidate_id} does not exceed the score threshold "
                    f"({review.score:g} <= {score_threshold_exclusive:g})"
                )
            blocking_flags = [
                flag.value for flag in merged_quality if flag in AUTO_BLOCKING_QUALITY_FLAGS
            ]
            if blocking_flags:
                row_errors.append(
                    f"selected candidate {candidate_id} has a blocking quality flag "
                    f"({', '.join(blocking_flags)})"
                )
            blocking_risks = [tag.value for tag in merged_risks if tag in AUTO_BLOCKING_RISK_TAGS]
            if blocking_risks:
                row_errors.append(
                    f"selected candidate {candidate_id} has a manual/blocking risk "
                    f"({', '.join(blocking_risks)})"
                )
            if not (
                boundary.opening_complete
                and boundary.ending_complete
                and boundary.central_objective_complete
                and boundary.shortest_complete_boundary
            ):
                row_errors.append(
                    f"selected candidate {candidate_id} failed deterministic boundary facts"
                )
        if len(row_errors) != errors_before:
            continue
        persisted = discovery_persisted_flags(raw, boundary, merged_quality)
        review_reason = review.review_reason
        if persisted and status in {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
        }:
            # Never raise here: a persisted Discovery flag downgrades, it does not
            # invalidate the review output (its validation above is unchanged).
            status = CandidateDisposition.BLOCKED
            review_reason = f"{FLAG_PERSISTENCE_REASON_PREFIX}{review.review_reason}"
        final_values.append(
            FinalProfileCandidate(
                candidate_id=candidate_id,
                profile=profile,
                variant_group_id=review.variant_group_id or raw.variant_group_id,
                source_candidate_ids=(candidate_id,),
                source_window_ids=(raw.source_window_id,),
                start_cue_id=review.start_cue_id,
                end_cue_id=review.end_cue_id,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=end_ms - start_ms,
                title=review.title,
                hook=review.hook,
                summary=review.summary,
                score=review.score,
                review_status=status,
                quality_flags=(*merged_quality, *persisted),
                risk_tags=merged_risks,
                # Final evidence is limited to the final interval; the raw
                # Discovery artifacts keep the original evidence cue IDs.
                evidence_cue_ids=tuple(
                    cue_id
                    for cue_id in dict.fromkeys(
                        (
                            *raw.evidence_cue_ids,
                            *boundary.evidence_cue_ids,
                            *review.evidence_cue_ids,
                        )
                    )
                    if review.start_cue_id <= cue_id <= review.end_cue_id
                ),
                duplicate_of_candidate_id=review.duplicate_of_candidate_id,
                review_reason=review_reason,
            )
        )
    if row_errors:
        raise ValueError(_join_errors(row_errors))
    # Same interval -> same gated flags (``same_interval_twin_flags``, v6).
    # Candidates with an identical final interval describe the same continuous
    # media, so a gated quality flag found on a non-risk twin applies to all of
    # them, whatever their status.  This includes topic_switch_inside and
    # topic_not_closed: both describe the media between the same two cues, not
    # the title or framing a reviewer gave one twin, so a differently titled
    # twin cannot cure them.  Advisory flags (context/prior steps) and
    # source_title_mismatch depend on a twin's own framing and are not shared.
    # Records of the dedicated risk-discovery pass
    # keep their own flags and still receive their non-risk twins' flags, but are
    # not flag sources: that pass is instructed to preserve and flag interior
    # interruptions of a risk chain so the record is routed to blocked, which is
    # not a finding a non-risk twin's own reviews must inherit.
    twins = same_interval_twin_flags(final_values, risk_records)
    shared: list[FinalProfileCandidate] = []
    for value in final_values:
        inherited = twins.inherited[value.candidate_id]
        if not inherited:
            shared.append(value)
            continue
        update: dict[str, object] = {"quality_flags": (*value.quality_flags, *inherited)}
        if value.review_status in {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
        }:
            # Never raise here: a twin's flag downgrades, it does not invalidate.
            update["review_status"] = CandidateDisposition.BLOCKED
            update["review_reason"] = f"{QUALITY_GATE_REASON_PREFIX}{value.review_reason}"
        shared.append(value.model_copy(update=update))
    # Risk-twin review (v7).  It runs after the twin union, so only rows still
    # selected are considered (a blocked row stays blocked), and before Top-N, so
    # Top-N ranks only rows that already obey it and can never pick a
    # replacement that would then be downgraded.  Its inputs (intervals and the
    # risk twins' risk tags) are not changed by any later step, and a row it
    # downgrades carries no quality flag (a selected row carries none), so step 5
    # leaves it manual_review.
    reviewed = route_risk_twin_review(shared, risk_records)
    selected = sorted(
        (value for value in reviewed if value.review_status == CandidateDisposition.SELECTED),
        key=lambda value: (-value.score, value.start_ms, value.candidate_id),
    )
    keep_ids = {value.candidate_id for value in selected[:top_n]}
    normalized: list[FinalProfileCandidate] = []
    for value in reviewed:
        if (
            value.review_status == CandidateDisposition.SELECTED
            and value.candidate_id not in keep_ids
        ):
            value = value.model_copy(
                update={
                    "review_status": CandidateDisposition.REJECTED,
                    "review_reason": f"{TOP_N_REASON_PREFIX}{value.review_reason}",
                }
            )
        if (
            value.review_status == CandidateDisposition.REJECTED
            and value.candidate_id in risk_records
        ):
            # Benchmark risk rule: risk material ends manual_review or blocked and
            # never silently disappears, including after a Top-N exclusion.  Keep
            # the duplicate reference and the rejection evidence; blocked is never
            # materialized.
            value = value.model_copy(
                update={
                    "review_status": CandidateDisposition.BLOCKED,
                    "review_reason": f"{RISK_ROUTING_REASON_PREFIX}{value.review_reason}",
                }
            )
        elif value.review_status == CandidateDisposition.MANUAL_REVIEW and (
            set(value.quality_flags) & MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
        ):
            # Python only ever downgrades: the merged Boundary/Global quality flags
            # are authoritative over the model's manual_review disposition.
            value = value.model_copy(
                update={
                    "review_status": CandidateDisposition.BLOCKED,
                    "review_reason": f"{QUALITY_GATE_REASON_PREFIX}{value.review_reason}",
                }
            )
        normalized.append(value)
    grouped = {
        status: tuple(
            sorted(
                (value for value in normalized if value.review_status == status),
                key=lambda value: (value.start_ms, value.end_ms, value.candidate_id),
            )
        )
        for status in CandidateDisposition
    }
    statistics = profile_statistics(tuple(raw_map), tuple(normalized))
    return FinalProfileResult(
        profile=profile,
        raw_candidate_ids=tuple(raw_map),
        selected=grouped[CandidateDisposition.SELECTED],
        manual_review=grouped[CandidateDisposition.MANUAL_REVIEW],
        blocked=grouped[CandidateDisposition.BLOCKED],
        rejected=grouped[CandidateDisposition.REJECTED],
        statistics=statistics,
    )


def boundary_shrank_interval(raw: RawProfileCandidate, boundary: BoundaryReviewItem) -> bool:
    """True when Boundary Review moved the start later or the end earlier."""

    return boundary.start_cue_id > raw.start_cue_id or boundary.end_cue_id < raw.end_cue_id


def discovery_persisted_flags(
    raw: RawProfileCandidate,
    boundary: BoundaryReviewItem,
    merged_quality: Collection[DualQualityFlag] = (),
) -> tuple[DualQualityFlag, ...]:
    """Discovery structural gated flags that survive Boundary Review (policy v5).

    This is the single source of persisted flags: final assembly, the Global
    Audit payload (``persisted_discovery_gated_flags``), the persisted-flag
    representative rule and the near-identical pair fallback keep order all
    call it, so they cannot drift.

    A structural gated flag (``PERSISTED_STRUCTURAL_GATED_FLAGS``) that Discovery
    raised on the candidate describes media inside its Discovery interval.
    Boundary Review can only resolve it by removing media: when it shrank the
    interval on at least one edge, the Boundary/Global flags are authoritative.
    An unchanged or only extended interval still contains the flagged media, so
    clearing the flag in a review stage does not clear it here.  Padding flags
    (``PADDING_GATED_FLAGS``) describe edge material that Boundary Review, the
    edge authority, judges with the surrounding context, so they are never
    persisted from Discovery (they still gate when a review stage keeps them).
    Advisory flags are never persisted.  Returns the persisted flags not already
    in ``merged_quality``, in enum order.
    """

    if boundary_shrank_interval(raw, boundary):
        return ()
    gated = set(raw.quality_flags) & PERSISTED_STRUCTURAL_GATED_FLAGS
    return tuple(flag for flag in DualQualityFlag if flag in gated and flag not in merged_quality)


class SameIntervalTwinFlags(NamedTuple):
    """Result of the same-interval twin flag rule (routing v6).

    ``inherited`` maps every candidate ID to the gated flags it receives from
    its non-risk twins (sorted by flag value).  ``not_propagated`` maps every
    candidate ID to the gated flags that only risk-discovery twins of the same
    interval carry, which v6 does not propagate to it.
    """

    inherited: Mapping[str, tuple[DualQualityFlag, ...]]
    not_propagated: Mapping[str, tuple[DualQualityFlag, ...]]

    @property
    def not_propagated_count(self) -> int:
        return sum(len(flags) for flags in self.not_propagated.values())


def same_interval_twin_flags(
    values: Iterable[FinalProfileCandidate],
    risk_record_ids: Collection[str],
) -> SameIntervalTwinFlags:
    """The single same-interval twin flag rule (policy v6).

    Final assembly, the run-manifest diagnostic and its validator all call it.
    Candidates with an identical final interval share their gated quality
    flags (``MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS``; advisory flags depend on a
    twin's own framing and are never shared).  Only candidates outside
    ``risk_record_ids`` (records of the dedicated risk-discovery pass, derived
    structurally) act as sources; every twin, risk record or not, receives the
    sources' flags.  Applying the rule to its own output is a no-op: the
    ``inherited`` sets become empty and ``not_propagated`` is unchanged.
    """

    risk_records = frozenset(risk_record_ids)
    rows = tuple(values)
    sources: dict[tuple[int, int], set[DualQualityFlag]] = {}
    risk_flags: dict[tuple[int, int], list[tuple[str, frozenset[DualQualityFlag]]]] = {}
    for value in rows:
        interval = (value.start_cue_id, value.end_cue_id)
        gated = frozenset(value.quality_flags) & MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
        if value.candidate_id in risk_records:
            sources.setdefault(interval, set())
            risk_flags.setdefault(interval, []).append((value.candidate_id, gated))
        else:
            sources.setdefault(interval, set()).update(gated)
    inherited: dict[str, tuple[DualQualityFlag, ...]] = {}
    not_propagated: dict[str, tuple[DualQualityFlag, ...]] = {}
    for value in rows:
        interval = (value.start_cue_id, value.end_cue_id)
        own = set(value.quality_flags)
        shared = sources[interval]
        inherited[value.candidate_id] = tuple(sorted(shared - own, key=lambda flag: flag.value))
        # A risk record's own flags are in ``own`` and are subtracted below.
        from_risk_twins = {flag for _, flags in risk_flags.get(interval, ()) for flag in flags}
        not_propagated[value.candidate_id] = tuple(
            sorted(from_risk_twins - shared - own, key=lambda flag: flag.value)
        )
    return SameIntervalTwinFlags(
        inherited=MappingProxyType(inherited), not_propagated=MappingProxyType(not_propagated)
    )


class RiskTwinReview(NamedTuple):
    """Result of the risk-twin review rule (routing v7).

    ``sources`` maps every non-risk candidate ID whose identical final interval
    has at least one risk-discovery twin with an automatic-blocking risk tag to
    those twins, as ``(risk candidate ID, its automatic-blocking tags)`` sorted by
    candidate ID (tags in enum order).  ``pending`` lists the rows of ``sources``
    that are still ``selected`` (the rule downgrades them); ``downgraded`` lists
    the rows whose reason already carries ``RISK_TWIN_REVIEW_REASON_PREFIX``.
    """

    sources: Mapping[str, tuple[tuple[str, tuple[DualRiskTag, ...]], ...]]
    pending: tuple[str, ...]
    downgraded: tuple[str, ...]

    @property
    def downgraded_count(self) -> int:
        return len(self.downgraded)


def risk_twin_review(
    values: Iterable[FinalProfileCandidate],
    risk_record_ids: Collection[str],
) -> RiskTwinReview:
    """The single risk-twin review rule (policy v7).

    Final assembly (``route_risk_twin_review``), the run-manifest diagnostic and
    its validator all call it.  Since v6 a risk-discovery record is not a flag
    source for its same-interval twins, and risk tags were never shared, so a
    risk twin's automatic-blocking risk tag could no longer stop its non-risk
    twin from being published automatically.  The rule restores a human check
    without copying tags: only records in ``risk_record_ids`` (derived
    structurally from the risk-discovery pass) act as sources, whatever their
    own status, and only non-risk rows receive.
    """

    risk_records = frozenset(risk_record_ids)
    rows = tuple(values)
    tagged: dict[tuple[int, int], list[tuple[str, tuple[DualRiskTag, ...]]]] = {}
    for value in rows:
        if value.candidate_id not in risk_records:
            continue
        tags = tuple(
            tag for tag in DualRiskTag if tag in value.risk_tags and tag in AUTO_BLOCKING_RISK_TAGS
        )
        if tags:
            tagged.setdefault((value.start_cue_id, value.end_cue_id), []).append(
                (value.candidate_id, tags)
            )
    sources: dict[str, tuple[tuple[str, tuple[DualRiskTag, ...]], ...]] = {}
    for value in rows:
        twins = tagged.get((value.start_cue_id, value.end_cue_id))
        if twins and value.candidate_id not in risk_records:
            sources[value.candidate_id] = tuple(sorted(twins))
    return RiskTwinReview(
        sources=MappingProxyType(sources),
        pending=tuple(
            value.candidate_id
            for value in rows
            if value.candidate_id in sources
            and value.review_status == CandidateDisposition.SELECTED
        ),
        downgraded=tuple(
            value.candidate_id
            for value in rows
            if value.review_reason.startswith(RISK_TWIN_REVIEW_REASON_PREFIX)
        ),
    )


def route_risk_twin_review(
    values: Iterable[FinalProfileCandidate],
    risk_record_ids: Collection[str],
) -> tuple[FinalProfileCandidate, ...]:
    """Apply ``risk_twin_review``: every pending row becomes ``manual_review``.

    Downgrade only (never ``blocked``; rows already ``manual_review``,
    ``blocked`` or ``rejected`` are unchanged), risk tags are not copied, and
    the reason records the source risk twins and their tags.  Idempotent: on
    its own output nothing is pending.
    """

    rows = tuple(values)
    review = risk_twin_review(rows, risk_record_ids)
    pending = frozenset(review.pending)
    routed: list[FinalProfileCandidate] = []
    for value in rows:
        if value.candidate_id in pending:
            detail = "; ".join(
                f"same-interval risk-discovery twin {candidate_id} carries "
                + ", ".join(tag.value for tag in tags)
                for candidate_id, tags in review.sources[value.candidate_id]
            )
            value = value.model_copy(
                update={
                    "review_status": CandidateDisposition.MANUAL_REVIEW,
                    "review_reason": (
                        f"{RISK_TWIN_REVIEW_REASON_PREFIX}{detail}. {value.review_reason}"
                    ),
                }
            )
        routed.append(value)
    return tuple(routed)


def profile_statistics(
    raw_candidate_ids: Sequence[str],
    final_candidates: Sequence[FinalProfileCandidate],
) -> ProfileStatistics:
    counts = Counter(value.review_status for value in final_candidates)
    return ProfileStatistics(
        discovered=len(raw_candidate_ids),
        selected=counts[CandidateDisposition.SELECTED],
        manual_review=counts[CandidateDisposition.MANUAL_REVIEW],
        blocked=counts[CandidateDisposition.BLOCKED],
        rejected=counts[CandidateDisposition.REJECTED],
    )


def apply_cross_profile_variant_links(
    results: Mapping[ClipProfile, FinalProfileResult],
    output: CrossProfileVariantLinkOutput,
) -> dict[ClipProfile, FinalProfileResult]:
    """Apply editorial variant labels without changing status, score, boundaries, or lineage."""

    eligible = {
        value.candidate_id: value.profile
        for result in results.values()
        for values in (result.selected, result.manual_review)
        for value in values
    }
    links = {value.candidate_id: value.variant_group_id for value in output.links}
    if len(links) != len(output.links) or set(links) != set(eligible):
        raise ValueError("Variant Link must cover every selected/manual candidate exactly once")
    updated: dict[ClipProfile, FinalProfileResult] = {}
    for profile, result in results.items():
        groups = {
            status.value: tuple(
                value.model_copy(update={"variant_group_id": links[value.candidate_id]})
                if value.candidate_id in links
                else value
                for value in values
            )
            for status, values in (
                (CandidateDisposition.SELECTED, result.selected),
                (CandidateDisposition.MANUAL_REVIEW, result.manual_review),
                (CandidateDisposition.BLOCKED, result.blocked),
                (CandidateDisposition.REJECTED, result.rejected),
            )
        }
        updated[profile] = result.model_copy(update=groups)
    return updated


def semantic_cache_key(
    *,
    source_hash: str,
    profile: ClipProfile | str,
    window_start: int,
    window_end: int,
    prompt_hash: str,
    model: str,
    model_settings: Mapping[str, object],
    schema_version: str = DUAL_PROFILE_SCHEMA_VERSION,
) -> str:
    payload = {
        "source_hash": source_hash,
        "profile": profile.value if isinstance(profile, ClipProfile) else profile,
        "window_start": window_start,
        "window_end": window_end,
        "prompt_hash": prompt_hash,
        "model": model,
        "model_settings": dict(model_settings),
        "schema_version": schema_version,
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def assert_no_cross_profile_dedup(results: Iterable[FinalProfileResult]) -> None:
    profile_by_candidate = {
        value.candidate_id: result.profile
        for result in results
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
    }
    for result in results:
        for group in (result.selected, result.manual_review, result.blocked, result.rejected):
            for value in group:
                duplicate = value.duplicate_of_candidate_id
                if duplicate is not None and profile_by_candidate.get(duplicate) != result.profile:
                    raise ValueError("cross-Profile semantic deduplication is forbidden")


__all__ = [
    "AUDIT_FALLBACK_REASON_PREFIX",
    "AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION",
    "AUDIT_OVERLAP_MIN_SHORTER_FRACTION",
    "AUDIT_SAME_END_TOLERANCE_MS",
    "AUTO_BLOCKING_QUALITY_FLAGS",
    "AUTO_BLOCKING_RISK_TAGS",
    "DETERMINISTIC_REASON_PREFIXES",
    "DUAL_PROFILE_ALGORITHM_VERSION",
    "DUAL_PROFILE_ROUTING_POLICY_VERSION",
    "DUPLICATE_ALLOWED_STATUSES",
    "FLAG_PERSISTENCE_REASON_PREFIX",
    "MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS",
    "PADDING_GATED_FLAGS",
    "PERSISTED_STRUCTURAL_GATED_FLAGS",
    "PROFILE_DURATION_CONTRACTS",
    "QUALITY_GATE_REASON_PREFIX",
    "RISK_ROUTING_REASON_PREFIX",
    "RISK_TWIN_REVIEW_REASON_PREFIX",
    "TOP_N_REASON_PREFIX",
    "AuditCandidatePair",
    "AuditPairFallback",
    "AuditPairKind",
    "AuditPairRule",
    "AuditPairRuleError",
    "AuditPairViolation",
    "BoundaryOpeningFallback",
    "BoundaryOpeningInvariantError",
    "BoundaryReviewItem",
    "BoundaryState",
    "CandidateDisposition",
    "CrossProfileVariantLinkOutput",
    "DiscoveryWindow",
    "DualProfileFinalResult",
    "DualProfileRunConfig",
    "DualProfileRunManifest",
    "DualQualityFlag",
    "DualRiskTag",
    "FinalProfileCandidate",
    "FinalProfileResult",
    "GlobalReviewItem",
    "NestedPairDecision",
    "NestedPairDecisionKind",
    "ProfileBoundaryReviewOutput",
    "ProfileDiscoveryOutput",
    "ProfileGlobalAuditOutput",
    "ProfileGlobalReviewOutput",
    "ProfileManifestStats",
    "ProfileStatistics",
    "RawProfileCandidate",
    "RiskTwinReview",
    "SameIntervalTwinFlags",
    "StaleCacheResolution",
    "VariantLinkItem",
    "apply_audit_pair_blocks",
    "apply_boundary_opening_fallback",
    "apply_cross_profile_variant_links",
    "assemble_final_profile_result",
    "assert_no_cross_profile_dedup",
    "audit_candidate_pairs",
    "boundary_shrank_interval",
    "candidate_spans_ms",
    "discovery_persisted_flags",
    "duplicate_status_violation",
    "final_profile_rows",
    "nested_candidate_pairs",
    "plan_audit_pair_fallback",
    "plan_profile_discovery_windows",
    "profile_statistics",
    "reject_reserved_reason_prefixes",
    "resolved_duplicates",
    "risk_twin_review",
    "route_risk_twin_review",
    "same_interval_twin_flags",
    "semantic_cache_key",
    "validate_audit_pair_decisions",
    "validate_boundary_review_output",
    "validate_discovery_output",
    "validate_nested_pair_decisions",
]
