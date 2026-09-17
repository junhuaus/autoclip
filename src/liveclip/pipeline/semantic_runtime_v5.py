"""Typed V5 persisted artifacts and explicit projections into shared V4 quality gates."""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, Field, StringConstraints, model_validator

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.semantic_global import SemanticInputPlan
from liveclip.pipeline.semantic_lineage import (
    DiscoveryBatchOutputV5,
    FinalPartitionV5,
    FrozenV5,
    LineageLedgerV5,
    SafeID,
    TopicChainReviewV5,
    VersionedV5,
    namespace_discovery_batch_v5,
)
from liveclip.pipeline.semantic_profiles import (
    DiscoveryBatchOutputV4,
    GlobalReviewOutputV4,
    LinkReviewRequestV4,
    LinkReviewV4,
    TopicChainV4,
    ValidatedCandidateV4,
    ValidatedProfileResultV4,
)

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
RecordID = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
SlotID = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
T = TypeVar("T", bound=BaseModel)


def project_quality_v4(model: type[T], value: BaseModel) -> T:
    raw = value.model_dump(mode="json")
    projected = {key: item for key, item in raw.items() if key in model.model_fields}
    if "schema_version" in projected:
        projected["schema_version"] = "4"
    return model.model_validate_json(json.dumps(projected))


def discovery_for_links_v4(value: DiscoveryBatchOutputV5) -> DiscoveryBatchOutputV4:
    """Only the Link planner uses this view; the V5 source stays authoritative."""
    raw = value.model_dump(mode="json")
    raw.pop("contract_version")
    raw["schema_version"] = "4"
    raw["candidates"] = [
        {key: item for key, item in row.items() if key != "risks"} for row in raw["candidates"]
    ]
    return DiscoveryBatchOutputV4.model_validate_json(json.dumps(raw))


def final_partition_v5(result: ValidatedProfileResultV4) -> FinalPartitionV5:
    return FinalPartitionV5(
        selected=tuple(item.review.candidate_id for item in result.selected),
        manual=tuple(item.review.candidate_id for item in result.manual_review),
        blocked=tuple(item.review.candidate_id for item in result.blocked),
        rejected=tuple(item.review.candidate_id for item in result.rejected),
        top_n_excluded=tuple(item.review.candidate_id for item in result.top_n_excluded),
    )


class RoughLineageStateV5(VersionedV5):
    run_id: RecordID
    project_id: RecordID
    config_fingerprint: Digest
    source_hash: Digest
    input_plan: SemanticInputPlan
    local_discovery_outputs: tuple[DiscoveryBatchOutputV5, ...]
    discovery_outputs: tuple[DiscoveryBatchOutputV5, ...]
    link_review_requests: tuple[LinkReviewRequestV4, ...]
    link_reviews: tuple[LinkReviewV4, ...]
    topic_chains: tuple[TopicChainV4, ...]
    topic_chain_reviews: tuple[TopicChainReviewV5, ...]
    candidate_slot_map: dict[SafeID, SlotID]
    prompt_files: dict[str, tuple[str, ...]]
    stage_audits: dict[str, object]

    @model_validator(mode="after")
    def validate_slots(self) -> RoughLineageStateV5:
        if len(self.local_discovery_outputs) != len(
            self.input_plan.units
        ) or self.discovery_outputs != tuple(
            namespace_discovery_batch_v5(value) for value in self.local_discovery_outputs
        ):
            raise ValueError("Discovery namespacing differs from the local authoritative outputs")
        ids = [
            unit.candidate_id for review in self.topic_chain_reviews for unit in review.candidates
        ]
        if len(set(ids)) != len(ids) or set(self.candidate_slot_map) != set(ids):
            raise ValueError("lineage semantic unit slot map is incomplete or repeated")
        if len(set(self.candidate_slot_map.values())) != len(ids):
            raise ValueError("lineage persistent slot mapping is not one-to-one")
        return self


class MiniLessonArtifactConfigV5(FrozenV5):
    algorithm: Literal["semantic_windowed"] = "semantic_windowed"
    clip_profile: Literal["mini_lesson"] = "mini_lesson"
    minimum_clip_ms: Literal[90000] = 90000
    target_clip_ms: Literal[180000] = 180000
    maximum_clip_ms: Literal[300000] = 300000
    top_n: int = Field(ge=1, le=100)
    top_n_phase: Literal["after_final_validation"] = "after_final_validation"


class MiniLessonRoughArtifactV5(VersionedV5):
    config: MiniLessonArtifactConfigV5
    candidates: tuple[CandidateClip, ...]
    semantic_v5: RoughLineageStateV5

    @model_validator(mode="after")
    def validate_candidate_slots(self) -> MiniLessonRoughArtifactV5:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(ids)) != len(ids) or set(ids) != set(
            self.semantic_v5.candidate_slot_map.values()
        ):
            raise ValueError("rough candidate slots differ from the lineage mapping")
        return self


class ProfileStatisticsV5(FrozenV5):
    original_candidate_count: int = Field(ge=0)
    derived_unit_count: int = Field(ge=0)
    chain_new_unit_count: int = Field(ge=0)
    boundary_candidate_count: int = Field(ge=0)
    qualified_before_top_n: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    manual_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    top_n_excluded_count: int = Field(ge=0)


class ValidatedProfileResultV5(FrozenV5):
    selected: tuple[ValidatedCandidateV4, ...]
    manual_review: tuple[ValidatedCandidateV4, ...]
    blocked: tuple[ValidatedCandidateV4, ...]
    rejected: tuple[ValidatedCandidateV4, ...]
    top_n_excluded: tuple[ValidatedCandidateV4, ...]
    statistics: ProfileStatisticsV5


def lineage_profile_v5(
    result: ValidatedProfileResultV4, ledger: LineageLedgerV5
) -> ValidatedProfileResultV5:
    stats = result.statistics.model_dump(mode="python")
    stats.pop("discovery_candidate_count")
    return ValidatedProfileResultV5(
        selected=result.selected,
        manual_review=result.manual_review,
        blocked=result.blocked,
        rejected=result.rejected,
        top_n_excluded=result.top_n_excluded,
        statistics=ProfileStatisticsV5.model_validate(
            {
                **stats,
                "original_candidate_count": ledger.counts.originals,
                "derived_unit_count": ledger.counts.derived_units,
                "chain_new_unit_count": ledger.counts.chain_new_units,
            }
        ),
    )


class UnifiedSemanticResultV5(VersionedV5):
    run_id: RecordID
    project_id: RecordID
    config_fingerprint: Digest
    source_hash: Digest
    validation_contract: Literal["semantic-v4-quality-v2"] = "semantic-v4-quality-v2"
    run_metadata: dict[str, object]
    profiles: dict[ClipProfile, ValidatedProfileResultV5]
    lineage: LineageLedgerV5
    candidate_slot_map: dict[SafeID, SlotID]
    persistent_candidate_ids: dict[SafeID, RecordID]
    global_review: GlobalReviewOutputV4 | None
    stage_audits: dict[str, object]

    @model_validator(mode="after")
    def validate_final_accounting(self) -> UnifiedSemanticResultV5:
        if set(self.profiles) != {ClipProfile.MINI_LESSON}:
            raise ValueError("V5 runtime result requires the mini lesson profile")
        profile = self.profiles[ClipProfile.MINI_LESSON]
        for partition_field, profile_field in (
            ("selected", "selected"),
            ("manual", "manual_review"),
            ("blocked", "blocked"),
            ("rejected", "rejected"),
            ("top_n_excluded", "top_n_excluded"),
        ):
            values = getattr(profile, profile_field)
            if any(item.disposition.value != partition_field for item in values):
                raise ValueError("quality disposition differs from its recorded group")
            if tuple(item.review.candidate_id for item in values) != getattr(
                self.lineage.partition, partition_field
            ):
                raise ValueError("lineage final partition differs from the actual quality result")
            if getattr(profile.statistics, f"{partition_field}_count") != len(values):
                raise ValueError("lineage final statistics differ from the actual partition")
        counts, stats = self.lineage.counts, profile.statistics
        if (
            stats.original_candidate_count,
            stats.derived_unit_count,
            stats.chain_new_unit_count,
            stats.boundary_candidate_count,
        ) != (counts.originals, counts.derived_units, counts.chain_new_units, counts.units):
            raise ValueError("lineage source and unit counts differ")
        if stats.qualified_before_top_n != counts.selected + counts.top_n_excluded:
            raise ValueError("lineage qualified count differs from actual Top-N partition")
        ids = {outcome.unit.candidate_id for outcome in self.lineage.outcomes}
        for mapping in (self.candidate_slot_map, self.persistent_candidate_ids):
            if set(mapping) != ids or len(set(mapping.values())) != len(ids):
                raise ValueError("final lineage persistent mapping is incomplete or repeated")
        if bool(ids) != (self.global_review is not None):
            raise ValueError("final lineage Global Review presence differs from its units")
        if self.global_review is not None:
            global_reviews = {review.candidate_id: review for review in self.global_review.reviews}
            actual_reviews = {
                item.review.candidate_id: item.review
                for values in (
                    profile.selected,
                    profile.manual_review,
                    profile.blocked,
                    profile.rejected,
                    profile.top_n_excluded,
                )
                for item in values
            }
            if (
                len(global_reviews) != len(self.global_review.reviews)
                or set(global_reviews) != ids
                or global_reviews != actual_reviews
            ):
                raise ValueError("Global Review differs from the recorded quality outputs")
        return self
