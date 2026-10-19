from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Literal

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


class ProfileGlobalAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: ClipProfile
    replacements: tuple[GlobalReviewItem, ...]
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

    def validate_against(self, result: DualProfileFinalResult) -> None:
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


def validate_boundary_review_output(
    output: ProfileBoundaryReviewOutput,
    *,
    profile: ClipProfile,
    candidates: Sequence[RawProfileCandidate],
    transcript: TranscriptDocument,
) -> ProfileBoundaryReviewOutput:
    if output.profile != profile:
        raise ValueError("Boundary Review used the wrong Profile")
    candidate_map = {value.candidate_id: value for value in candidates}
    review_map = {value.candidate_id: value for value in output.reviews}
    if len(candidate_map) != len(candidates) or len(review_map) != len(output.reviews):
        raise ValueError("Boundary Review candidate IDs are not unique")
    if set(candidate_map) != set(review_map):
        raise ValueError("Boundary Review must cover every raw candidate exactly once")
    cue_map = {value.cue_id: value for value in transcript_cues(transcript)}
    contract = PROFILE_DURATION_CONTRACTS[profile]
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
        raw = candidate_map[candidate_id]
        if not set(review.risk_tags).issuperset(raw.risk_tags):
            raise ValueError("Boundary Review silently removed a Discovery risk")
        evidence_preservation_tags = {
            DualRiskTag.MEDICAL_CLAIM,
            DualRiskTag.MEDICAL_DIAGNOSIS_HIGH,
            DualRiskTag.HEALTH_ADVICE,
            DualRiskTag.SENSITIVITY_REVIEW,
        }
        if set(raw.risk_tags) & evidence_preservation_tags and any(
            cue_id < review.start_cue_id or cue_id > review.end_cue_id
            for cue_id in raw.evidence_cue_ids
        ):
            raise ValueError(
                "Boundary Review removed a Discovery evidence cue from a medical, health, "
                "or sensitivity risk chain"
            )
    return output


def assemble_final_profile_result(
    *,
    profile: ClipProfile,
    discoveries: Sequence[ProfileDiscoveryOutput],
    boundaries: ProfileBoundaryReviewOutput,
    global_review: ProfileGlobalReviewOutput,
    transcript: TranscriptDocument,
    top_n: int,
    score_threshold_exclusive: float = 75.0,
) -> FinalProfileResult:
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
            if review.review_status != CandidateDisposition.REJECTED:
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
                quality_flags=merged_quality,
                risk_tags=merged_risks,
                evidence_cue_ids=tuple(
                    dict.fromkeys(
                        (
                            *raw.evidence_cue_ids,
                            *boundary.evidence_cue_ids,
                            *review.evidence_cue_ids,
                        )
                    )
                ),
                duplicate_of_candidate_id=review.duplicate_of_candidate_id,
                review_reason=review.review_reason,
            )
        )
    selected = sorted(
        (value for value in final_values if value.review_status == CandidateDisposition.SELECTED),
        key=lambda value: (-value.score, value.start_ms, value.candidate_id),
    )
    keep_ids = {value.candidate_id for value in selected[:top_n]}
    normalized: list[FinalProfileCandidate] = []
    for value in final_values:
        if (
            value.review_status == CandidateDisposition.SELECTED
            and value.candidate_id not in keep_ids
        ):
            normalized.append(
                value.model_copy(
                    update={
                        "review_status": CandidateDisposition.REJECTED,
                        "review_reason": f"Profile-local Top-N exclusion: {value.review_reason}",
                    }
                )
            )
        else:
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
    "AUTO_BLOCKING_QUALITY_FLAGS",
    "AUTO_BLOCKING_RISK_TAGS",
    "DUAL_PROFILE_ALGORITHM_VERSION",
    "PROFILE_DURATION_CONTRACTS",
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
    "ProfileBoundaryReviewOutput",
    "ProfileDiscoveryOutput",
    "ProfileGlobalAuditOutput",
    "ProfileGlobalReviewOutput",
    "ProfileManifestStats",
    "ProfileStatistics",
    "RawProfileCandidate",
    "VariantLinkItem",
    "apply_cross_profile_variant_links",
    "assemble_final_profile_result",
    "assert_no_cross_profile_dedup",
    "plan_profile_discovery_windows",
    "profile_statistics",
    "semantic_cache_key",
    "validate_boundary_review_output",
    "validate_discovery_output",
]
