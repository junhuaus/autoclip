from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import Final, Literal

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
# Artifacts written before any policy omit the marker and load as ``None``.
DUAL_PROFILE_ROUTING_POLICY_VERSION: Final = "quality-gate-risk-routing-v4"
FLAG_PERSISTENCE_REASON_PREFIX: Final = "Deterministic flag persistence: "
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

    def validate_against(
        self,
        result: DualProfileFinalResult,
        *,
        boundaries: Mapping[ClipProfile, ProfileBoundaryReviewOutput] | None = None,
    ) -> None:
        """Cross-check the manifest with the final result (and, when the run's
        Boundary Review output is available, with that output too)."""

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

    Nested pairs are exactly ``nested_candidate_pairs``.  Overlap pairs are the
    other selected/manual_review pairs in which neither candidate contains the
    other and the shared media is at least ``AUDIT_OVERLAP_MIN_SHORTER_FRACTION``
    of the shorter candidate's duration.  Containment without a shared edge stays
    unlisted, as before.  An overlap pair is ``near_identical`` when the members
    end within the Profile's ``AUDIT_SAME_END_TOLERANCE_MS`` or share at least
    ``AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION`` of the shorter candidate.
    """

    nested = nested_candidate_pairs(global_review)
    pairs = [
        AuditCandidatePair(
            outer_candidate_id=outer, inner_candidate_id=inner, pair_kind=AuditPairKind.NESTED
        )
        for outer, inner in nested
    ]
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    retained = sorted(
        (
            value
            for value in global_review.reviews
            if value.review_status
            in {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
        ),
        key=lambda value: (value.start_cue_id, -value.end_cue_id, value.candidate_id),
    )
    try:
        spans = {
            value.candidate_id: (
                cue_map[value.start_cue_id].start_ms,
                cue_map[value.end_cue_id].end_ms,
            )
            for value in retained
        }
    except KeyError as exc:
        raise ValueError("Global Review references an unknown cue") from exc
    tolerance_ms = AUDIT_SAME_END_TOLERANCE_MS[global_review.profile]
    for index, first in enumerate(retained):
        for second in retained[index + 1 :]:
            if first.profile != second.profile:
                continue
            first_start, first_end = spans[first.candidate_id]
            second_start, second_end = spans[second.candidate_id]
            if (first_start <= second_start and second_end <= first_end) or (
                second_start <= first_start and first_end <= second_end
            ):
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


def validate_audit_pair_decisions(
    pairs: Sequence[AuditCandidatePair],
    decisions: Sequence[NestedPairDecision],
    merged_review: ProfileGlobalReviewOutput,
) -> None:
    """Require one consistent audit decision for every listed nested or overlap pair.

    Every pair uses the ``validate_nested_pair_decisions`` semantics (exact
    coverage, direct or shared-representative duplicates, ``distinct_objective``
    without a direct reference).  Overlap pairs add two deterministic rules:

    * a ``duplicate`` decision must leave the resolved representative of each
      removed member ``selected`` or ``manual_review``, so deduplication never
      deletes the last retained version of that media;
    * a ``near_identical`` pair may not leave both members ``selected`` or
      ``manual_review``.  Whether a free-text reason really names a distinct
      objective cannot be checked deterministically, so near-identical media is
      never kept twice; the audit keeps one representative (or rejects/blocks a
      member on its own merits).
    """

    validate_nested_pair_decisions(
        tuple((pair.outer_candidate_id, pair.inner_candidate_id) for pair in pairs),
        decisions,
        merged_review,
    )
    review_map = {value.candidate_id: value for value in merged_review.reviews}
    retained = {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW}
    decision_map = {
        frozenset((value.outer_candidate_id, value.inner_candidate_id)): value
        for value in decisions
    }
    for pair in pairs:
        if pair.pair_kind != AuditPairKind.OVERLAP:
            continue
        members = [review_map[candidate_id] for candidate_id in sorted(pair.members)]
        if pair.near_identical and all(value.review_status in retained for value in members):
            raise ValueError(
                "Global Audit near-identical overlap pair "
                f"{pair.outer_candidate_id}/{pair.inner_candidate_id} cannot keep both "
                "candidates selected or manual_review; keep one representative"
            )
        if decision_map[pair.members].decision != NestedPairDecisionKind.DUPLICATE:
            continue
        for value in members:
            if value.review_status in retained or value.duplicate_of_candidate_id is None:
                continue
            representative = _duplicate_representative(value.candidate_id, review_map)
            if (
                representative is None
                or representative == value.candidate_id
                or review_map[representative].review_status not in retained
            ):
                raise ValueError(
                    "Global Audit overlap duplicate "
                    f"{pair.outer_candidate_id}/{pair.inner_candidate_id} must keep a "
                    "selected or manual_review representative"
                )


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

    def representative(candidate_id: str) -> str | None:
        return _duplicate_representative(candidate_id, review_map)

    for decision in decisions:
        key = frozenset((decision.outer_candidate_id, decision.inner_candidate_id))
        if key not in expected:
            raise ValueError(
                "Global Audit nested_pair_decisions references a pair that was not listed: "
                f"{decision.outer_candidate_id}/{decision.inner_candidate_id}"
            )
        if key in seen:
            raise ValueError("Global Audit decided a nested pair more than once")
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
                raise ValueError(
                    "Global Audit nested duplicate must leave one candidate rejected or "
                    "blocked with duplicate_of_candidate_id referencing the other, or both "
                    "rejected or blocked as duplicates of the same representative"
                )
        elif references:
            raise ValueError(
                "Global Audit marked a nested pair distinct_objective but one candidate "
                "still references the other as its duplicate"
            )
    missing = sorted("/".join(expected[key]) for key in set(expected) - seen)
    if missing:
        raise ValueError(
            "Global Audit nested_pair_decisions must cover every listed nested pair: "
            + ", ".join(missing[:20])
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

    Deterministic routing order (v4), each step only downgrading:

    1. validation of the review stages (unchanged: it sees only the merged
       Boundary/Global flags, so cached review outputs validate exactly as
       before), then Discovery gated-flag persistence per candidate;
    2. same-interval twin union of gated flags (it includes persisted flags);
    3. Profile-local Top-N over the rows still ``selected`` (rows blocked by
       steps 1--2 never take a slot);
    4. risk-record routing and the manual_review quality gate.
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
    for candidate_id, raw in raw_map.items():
        boundary = boundary_map[candidate_id]
        review = review_map[candidate_id]
        if boundary.profile != profile or review.profile != profile:
            raise ValueError("review candidate crossed Profile boundaries")
        if (review.start_cue_id, review.end_cue_id) != (
            boundary.start_cue_id,
            boundary.end_cue_id,
        ):
            raise ValueError("Global Review changed the final Boundary interval")
        try:
            start_ms = cue_map[review.start_cue_id].start_ms
            end_ms = cue_map[review.end_cue_id].end_ms
        except KeyError as exc:
            raise ValueError("review references an unknown cue") from exc
        if review.duplicate_of_candidate_id is not None:
            representative = raw_map.get(review.duplicate_of_candidate_id)
            if representative is None or representative.profile != profile:
                raise ValueError("semantic duplicate must reference the same Profile")
            allowed_duplicate_statuses = (
                {CandidateDisposition.REJECTED, CandidateDisposition.BLOCKED}
                if candidate_id in risk_records
                else {CandidateDisposition.REJECTED}
            )
            if review.review_status not in allowed_duplicate_statuses:
                raise ValueError("duplicate candidate must be retained as a rejected audit row")
        merged_quality = tuple(dict.fromkeys((*boundary.quality_flags, *review.quality_flags)))
        merged_risks = tuple(
            dict.fromkeys((*raw.risk_tags, *boundary.risk_tags, *review.risk_tags))
        )
        status = review.review_status
        if status == CandidateDisposition.SELECTED:
            if review.score <= score_threshold_exclusive:
                raise ValueError("selected candidate does not exceed the score threshold")
            if set(merged_quality) & AUTO_BLOCKING_QUALITY_FLAGS:
                raise ValueError("selected candidate has a blocking quality flag")
            if set(merged_risks) & AUTO_BLOCKING_RISK_TAGS:
                raise ValueError("selected candidate has a manual/blocking risk")
            if not (
                boundary.opening_complete
                and boundary.ending_complete
                and boundary.central_objective_complete
                and boundary.shortest_complete_boundary
            ):
                raise ValueError("selected candidate failed deterministic boundary facts")
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
    # Same interval -> same gated flags.  Candidates with an identical final
    # interval describe the same continuous media, so a gated quality flag found
    # on any of them applies to all of them, whatever their status.  This
    # includes topic_switch_inside and topic_not_closed: both describe the
    # media between the same two cues (an internal switch, or an ending that
    # does not close), not the title or framing a reviewer gave one twin, so a
    # differently titled twin cannot cure them.  Advisory flags (context/prior
    # steps) and source_title_mismatch depend on a twin's own framing and are
    # not shared.
    gated_by_interval: dict[tuple[int, int], set[DualQualityFlag]] = {}
    for value in final_values:
        gated_by_interval.setdefault((value.start_cue_id, value.end_cue_id), set()).update(
            set(value.quality_flags) & MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
        )
    shared: list[FinalProfileCandidate] = []
    for value in final_values:
        inherited = gated_by_interval[(value.start_cue_id, value.end_cue_id)] - set(
            value.quality_flags
        )
        if not inherited:
            shared.append(value)
            continue
        update: dict[str, object] = {
            "quality_flags": (
                *value.quality_flags,
                *sorted(inherited, key=lambda flag: flag.value),
            )
        }
        if value.review_status in {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
        }:
            # Never raise here: a twin's flag downgrades, it does not invalidate.
            update["review_status"] = CandidateDisposition.BLOCKED
            update["review_reason"] = f"Deterministic quality gate: {value.review_reason}"
        shared.append(value.model_copy(update=update))
    selected = sorted(
        (value for value in shared if value.review_status == CandidateDisposition.SELECTED),
        key=lambda value: (-value.score, value.start_ms, value.candidate_id),
    )
    keep_ids = {value.candidate_id for value in selected[:top_n]}
    normalized: list[FinalProfileCandidate] = []
    for value in shared:
        if (
            value.review_status == CandidateDisposition.SELECTED
            and value.candidate_id not in keep_ids
        ):
            value = value.model_copy(
                update={
                    "review_status": CandidateDisposition.REJECTED,
                    "review_reason": f"Profile-local Top-N exclusion: {value.review_reason}",
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
                    "review_reason": f"Deterministic risk routing: {value.review_reason}",
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
                    "review_reason": f"Deterministic quality gate: {value.review_reason}",
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
    """Discovery gated flags that survive Boundary Review (routing policy v4).

    A gated flag (``MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS``) that Discovery raised on
    the candidate describes media inside its Discovery interval.  Boundary Review
    can only resolve it by removing media: when it shrank the interval on at least
    one edge, the Boundary/Global flags are authoritative.  An unchanged or only
    extended interval still contains the flagged media, so clearing the flag in a
    review stage does not clear it here.  Advisory flags are never persisted.
    Returns the persisted flags not already in ``merged_quality``, in enum order.
    """

    if boundary_shrank_interval(raw, boundary):
        return ()
    gated = set(raw.quality_flags) & MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
    return tuple(flag for flag in DualQualityFlag if flag in gated and flag not in merged_quality)


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
    "AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION",
    "AUDIT_OVERLAP_MIN_SHORTER_FRACTION",
    "AUDIT_SAME_END_TOLERANCE_MS",
    "AUTO_BLOCKING_QUALITY_FLAGS",
    "AUTO_BLOCKING_RISK_TAGS",
    "DUAL_PROFILE_ALGORITHM_VERSION",
    "DUAL_PROFILE_ROUTING_POLICY_VERSION",
    "FLAG_PERSISTENCE_REASON_PREFIX",
    "MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS",
    "PROFILE_DURATION_CONTRACTS",
    "AuditCandidatePair",
    "AuditPairKind",
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
    "StaleCacheResolution",
    "VariantLinkItem",
    "apply_boundary_opening_fallback",
    "apply_cross_profile_variant_links",
    "assemble_final_profile_result",
    "assert_no_cross_profile_dedup",
    "audit_candidate_pairs",
    "boundary_shrank_interval",
    "discovery_persisted_flags",
    "nested_candidate_pairs",
    "plan_profile_discovery_windows",
    "profile_statistics",
    "semantic_cache_key",
    "validate_audit_pair_decisions",
    "validate_boundary_review_output",
    "validate_discovery_output",
    "validate_nested_pair_decisions",
]
