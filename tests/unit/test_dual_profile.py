from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.transcript import TranscriptDocument
from liveclip.pipeline.dual_profile import (
    AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION,
    AUDIT_OVERLAP_MIN_SHORTER_FRACTION,
    AUDIT_SAME_END_TOLERANCE_MS,
    DUAL_PROFILE_ALGORITHM_VERSION,
    DUAL_PROFILE_ROUTING_POLICY_VERSION,
    FLAG_PERSISTENCE_REASON_PREFIX,
    MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS,
    PROFILE_DURATION_CONTRACTS,
    AuditCandidatePair,
    AuditPairKind,
    BoundaryOpeningInvariantError,
    BoundaryReviewItem,
    BoundaryState,
    CandidateDisposition,
    CrossProfileVariantLinkOutput,
    DualProfileFinalResult,
    DualProfileRunManifest,
    DualQualityFlag,
    DualRiskTag,
    FinalProfileCandidate,
    FinalProfileResult,
    GlobalReviewItem,
    NestedPairDecision,
    NestedPairDecisionKind,
    ProfileBoundaryReviewOutput,
    ProfileDiscoveryOutput,
    ProfileGlobalAuditOutput,
    ProfileGlobalReviewOutput,
    ProfileManifestStats,
    RawProfileCandidate,
    VariantLinkItem,
    apply_boundary_opening_fallback,
    apply_cross_profile_variant_links,
    assemble_final_profile_result,
    assert_no_cross_profile_dedup,
    audit_candidate_pairs,
    boundary_shrank_interval,
    discovery_persisted_flags,
    nested_candidate_pairs,
    plan_profile_discovery_windows,
    profile_statistics,
    semantic_cache_key,
    validate_audit_pair_decisions,
    validate_boundary_review_output,
    validate_discovery_output,
    validate_nested_pair_decisions,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.providers.llm.structured import _structured_preflight_errors

ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT = load_srt_transcript(ROOT / "tests/fixtures/8-30-full-transcript.srt")
SOURCE_HASH = "29b8751643ecc38a7183ab0c837a011cbca1e70a56de0788cd66292dbf364120"


def _raw(
    *,
    profile: ClipProfile,
    window_id: str,
    candidate_id: str,
    start_cue_id: int,
    end_cue_id: int,
) -> RawProfileCandidate:
    return RawProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id="shared_topic",
        source_window_id=window_id,
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        evidence_cue_ids=(start_cue_id, end_cue_id),
        title="测试候选",
        summary="一个完整连续的测试教学单元。",
        boundary_state=BoundaryState(
            opening_complete=True,
            ending_complete=True,
        ),
    )


def _assemble(
    *,
    profile: ClipProfile,
    candidate_id: str,
    start_cue_id: int,
    end_cue_id: int,
    status: CandidateDisposition = CandidateDisposition.SELECTED,
    quality_flags: tuple[DualQualityFlag, ...] = (),
    boundary_quality_flags: tuple[DualQualityFlag, ...] | None = None,
    risk_tags: tuple[DualRiskTag, ...] = (),
    score: float = 90,
) -> FinalProfileResult:
    boundary_flags = quality_flags if boundary_quality_flags is None else boundary_quality_flags
    windows = plan_profile_discovery_windows(TRANSCRIPT, profile)
    start_ms = TRANSCRIPT.segments[start_cue_id - 1].start_ms
    window = next(
        value for value in windows if value.ownership_start_ms <= start_ms < value.ownership_end_ms
    )
    raw = _raw(
        profile=profile,
        window_id=window.window_id,
        candidate_id=candidate_id,
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
    )
    discovery = ProfileDiscoveryOutput(
        profile=profile,
        window_id=window.window_id,
        candidates=(raw,),
    )
    validate_discovery_output(discovery, window=window, transcript=TRANSCRIPT)
    boundary = BoundaryReviewItem(
        candidate_id=candidate_id,
        profile=profile,
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        opening_complete=not boundary_flags,
        ending_complete=not boundary_flags,
        central_objective_complete=not boundary_flags,
        shortest_complete_boundary=not boundary_flags,
        quality_flags=boundary_flags,
        risk_tags=risk_tags,
        evidence_cue_ids=(start_cue_id, end_cue_id),
        review_reason="边界审查证据。",
    )
    review = GlobalReviewItem(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id="shared_topic",
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        title="测试候选",
        hook="测试钩子",
        summary="完整摘要。",
        score=score,
        review_status=status,
        quality_flags=quality_flags,
        risk_tags=risk_tags,
        evidence_cue_ids=(start_cue_id, end_cue_id),
        review_reason="全局审查证据。",
    )
    return assemble_final_profile_result(
        profile=profile,
        discoveries=(discovery,),
        boundaries=ProfileBoundaryReviewOutput(profile=profile, reviews=(boundary,)),
        global_review=ProfileGlobalReviewOutput(profile=profile, reviews=(review,)),
        transcript=TRANSCRIPT,
        top_n=15,
    )


def test_duration_boundaries_assign_exactly_ninety_seconds_to_short() -> None:
    short = PROFILE_DURATION_CONTRACTS[ClipProfile.SHORT_HIGHLIGHT]
    mini = PROFILE_DURATION_CONTRACTS[ClipProfile.MINI_LESSON]
    assert short.accepts(45_000)
    assert short.accepts(90_000)
    assert not mini.accepts(90_000)
    assert mini.accepts(90_001)
    assert mini.accepts(300_000)
    assert not mini.accepts(300_001)


def _final_candidate(
    *,
    profile: ClipProfile,
    duration_ms: int,
    score: float = 90,
    status: CandidateDisposition = CandidateDisposition.SELECTED,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id="boundary_candidate",
        profile=profile,
        source_candidate_ids=("boundary_candidate",),
        source_window_ids=("boundary_window",),
        start_cue_id=1,
        end_cue_id=2,
        start_ms=1_000,
        end_ms=1_000 + duration_ms,
        duration_ms=duration_ms,
        title="边界候选",
        hook="边界钩子",
        summary="边界摘要。",
        score=score,
        review_status=status,
        evidence_cue_ids=(1,),
        review_reason="Schema boundary fixture.",
    )


@pytest.mark.parametrize(
    ("profile", "duration_ms", "accepted"),
    [
        (ClipProfile.SHORT_HIGHLIGHT, 44_999, False),
        (ClipProfile.SHORT_HIGHLIGHT, 45_000, True),
        (ClipProfile.SHORT_HIGHLIGHT, 90_000, True),
        (ClipProfile.SHORT_HIGHLIGHT, 90_001, False),
        (ClipProfile.MINI_LESSON, 90_000, False),
        (ClipProfile.MINI_LESSON, 90_001, True),
        (ClipProfile.MINI_LESSON, 300_000, True),
        (ClipProfile.MINI_LESSON, 300_001, False),
    ],
)
def test_final_candidate_schema_enforces_exact_profile_duration_bounds(
    profile: ClipProfile, duration_ms: int, accepted: bool
) -> None:
    assert PROFILE_DURATION_CONTRACTS[profile].accepts(duration_ms) is accepted
    if accepted:
        assert _final_candidate(profile=profile, duration_ms=duration_ms).duration_ms == duration_ms
    else:
        with pytest.raises(ValueError, match="Profile duration"):
            _final_candidate(profile=profile, duration_ms=duration_ms)


def test_selected_candidate_score_must_be_strictly_above_seventy_five() -> None:
    with pytest.raises(ValueError, match="deterministic quality/risk gates"):
        _final_candidate(profile=ClipProfile.SHORT_HIGHLIGHT, duration_ms=60_000, score=75)
    assert (
        _final_candidate(profile=ClipProfile.SHORT_HIGHLIGHT, duration_ms=60_000, score=75.01).score
        == 75.01
    )
    manual = _final_candidate(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        duration_ms=60_000,
        score=75,
        status=CandidateDisposition.MANUAL_REVIEW,
    )
    assert manual.review_status == CandidateDisposition.MANUAL_REVIEW


def test_boundary_review_cannot_trim_discovery_health_risk_evidence() -> None:
    profile = ClipProfile.MINI_LESSON
    window = next(
        value
        for value in plan_profile_discovery_windows(TRANSCRIPT, profile)
        if value.ownership_start_ms <= 1_890_420 < value.ownership_end_ms
    )
    raw = _raw(
        profile=profile,
        window_id=window.window_id,
        candidate_id="risk_evidence_chain",
        start_cue_id=825,
        end_cue_id=939,
    ).model_copy(update={"risk_tags": (DualRiskTag.HEALTH_ADVICE,)})
    review = BoundaryReviewItem(
        candidate_id=raw.candidate_id,
        profile=profile,
        start_cue_id=826,
        end_cue_id=939,
        opening_complete=True,
        ending_complete=True,
        central_objective_complete=True,
        shortest_complete_boundary=True,
        risk_tags=raw.risk_tags,
        evidence_cue_ids=(826, 939),
        review_reason="错误地裁掉了 Discovery 的首个健康风险证据 cue。",
    )
    with pytest.raises(ValueError, match="removed a Discovery evidence cue"):
        validate_boundary_review_output(
            ProfileBoundaryReviewOutput(profile=profile, reviews=(review,)),
            profile=profile,
            candidates=(raw,),
            transcript=TRANSCRIPT,
            risk_record_ids=frozenset({raw.candidate_id}),
        )
    # The evidence lock is structural: a non-risk-pass candidate with the same
    # risk tag may trim an edge evidence cue, but never drop the risk tag itself.
    trimmed = validate_boundary_review_output(
        ProfileBoundaryReviewOutput(profile=profile, reviews=(review,)),
        profile=profile,
        candidates=(raw,),
        transcript=TRANSCRIPT,
        risk_record_ids=frozenset(),
    )
    assert trimmed.reviews[0].start_cue_id == 826
    with pytest.raises(ValueError, match="silently removed a Discovery risk"):
        validate_boundary_review_output(
            ProfileBoundaryReviewOutput(
                profile=profile, reviews=(review.model_copy(update={"risk_tags": ()}),)
            ),
            profile=profile,
            candidates=(raw,),
            transcript=TRANSCRIPT,
            risk_record_ids=frozenset(),
        )


def test_boundary_review_opening_flag_requires_an_incomplete_opening() -> None:
    profile = ClipProfile.MINI_LESSON
    raw = _raw(
        profile=profile,
        window_id="mini_window",
        candidate_id="opening_flag",
        start_cue_id=825,
        end_cue_id=939,
    )
    review = BoundaryReviewItem(
        candidate_id=raw.candidate_id,
        profile=profile,
        start_cue_id=825,
        end_cue_id=939,
        opening_complete=True,
        ending_complete=True,
        central_objective_complete=True,
        shortest_complete_boundary=True,
        quality_flags=(DualQualityFlag.CONTEXT_DEPENDENT_OPENING,),
        evidence_cue_ids=(825, 939),
        review_reason="保留了开头依赖标记。",
    )

    def validate(item: BoundaryReviewItem) -> ProfileBoundaryReviewOutput:
        return validate_boundary_review_output(
            ProfileBoundaryReviewOutput(profile=profile, reviews=(item,)),
            profile=profile,
            candidates=(raw,),
            transcript=TRANSCRIPT,
            risk_record_ids=frozenset(),
        )

    with pytest.raises(
        BoundaryOpeningInvariantError,
        match="context_dependent_opening requires opening_complete=false; violating "
        "candidates: opening_flag",
    ):
        validate(review)
    # Either coherent answer is valid: an incomplete opening that keeps the flag,
    # or a complete opening without it.  Other flags are not constrained.
    validate(review.model_copy(update={"opening_complete": False}))
    validate(review.model_copy(update={"quality_flags": ()}))
    validate(
        review.model_copy(update={"quality_flags": (DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,)})
    )


def test_boundary_opening_invariant_lists_every_violation_and_never_masks_others() -> None:
    profile = ClipProfile.MINI_LESSON
    raws = tuple(
        _raw(
            profile=profile,
            window_id="mini_window",
            candidate_id=candidate_id,
            start_cue_id=825,
            end_cue_id=939,
        )
        for candidate_id in ("first_flag", "clean", "second_flag")
    )

    def item(candidate_id: str, *, flagged: bool) -> BoundaryReviewItem:
        return BoundaryReviewItem(
            candidate_id=candidate_id,
            profile=profile,
            start_cue_id=825,
            end_cue_id=939,
            opening_complete=True,
            ending_complete=True,
            central_objective_complete=True,
            shortest_complete_boundary=True,
            quality_flags=(DualQualityFlag.CONTEXT_DEPENDENT_OPENING,) if flagged else (),
            evidence_cue_ids=(825, 939),
            review_reason="边界审查。",
        )

    output = ProfileBoundaryReviewOutput(
        profile=profile,
        reviews=(
            item("first_flag", flagged=True),
            item("clean", flagged=False),
            item("second_flag", flagged=True),
        ),
    )

    def validate(value: ProfileBoundaryReviewOutput) -> ProfileBoundaryReviewOutput:
        return validate_boundary_review_output(
            value, profile=profile, candidates=raws, transcript=TRANSCRIPT, risk_record_ids=()
        )

    with pytest.raises(BoundaryOpeningInvariantError) as caught:
        validate(output)
    assert caught.value.candidate_ids == ("first_flag", "second_flag")
    assert "violating candidates: first_flag, second_flag." in str(caught.value)
    # Any other failure, even on a later row, is a plain error, not the invariant.
    broken = output.model_copy(
        update={
            "reviews": (
                *output.reviews[:2],
                output.reviews[2].model_copy(update={"evidence_cue_ids": (940,)}),
            )
        }
    )
    with pytest.raises(ValueError, match="evidence lies outside") as other:
        validate(broken)
    assert not isinstance(other.value, BoundaryOpeningInvariantError)
    # The conservative fallback only downgrades the listed rows and then validates.
    fixed = apply_boundary_opening_fallback(output, caught.value.candidate_ids)
    assert validate(fixed) == fixed
    assert [value.opening_complete for value in fixed.reviews] == [False, True, False]
    assert [value.quality_flags for value in fixed.reviews] == [
        value.quality_flags for value in output.reviews
    ]


def test_run_manifest_stale_cache_audit_is_consistent() -> None:
    base = {
        "source_hash": SOURCE_HASH,
        "requested_profiles": ["short_highlight"],
        "executed_profiles": ["short_highlight"],
        "profiles": {
            "short_highlight": {
                "discovered": 0,
                "selected": 0,
                "manual_review": 0,
                "blocked": 0,
                "rejected": 0,
            }
        },
        "provider": "mock",
        "model": "mock",
        "prompt_files": {},
        "prompt_hashes": {},
        "calls": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
        "cache_hits": 0,
        "repair_count": 0,
    }
    # Manifests written before Stage 12b load with the defaults.
    legacy = DualProfileRunManifest.model_validate_json(json.dumps(base))
    assert legacy.stale_cache_refresh_enabled is False
    assert legacy.stale_cache_resolutions == ()
    resolution = {
        "stage": "boundary_review",
        "profile": "short_highlight",
        "cache_key": "a" * 64,
        "superseding_cache_key": "b" * 64,
        "error_summary": "invariant",
        "reused": False,
    }
    DualProfileRunManifest.model_validate_json(
        json.dumps(
            {
                **base,
                "stale_cache_refresh_enabled": True,
                "stale_cache_resolution_count": 1,
                "stale_cache_resolutions": [resolution],
            }
        )
    )
    with pytest.raises(ValueError, match="count differs"):
        DualProfileRunManifest.model_validate_json(
            json.dumps(
                {
                    **base,
                    "stale_cache_refresh_enabled": True,
                    "stale_cache_resolutions": [resolution],
                }
            )
        )
    with pytest.raises(ValueError, match="explicit refresh option"):
        DualProfileRunManifest.model_validate_json(
            json.dumps(
                {
                    **base,
                    "stale_cache_resolution_count": 1,
                    "stale_cache_resolutions": [resolution],
                }
            )
        )


def _fallback_manifest(
    result: FinalProfileResult,
    *,
    fallbacks: Sequence[Mapping[str, object]] = (),
    resolutions: Sequence[Mapping[str, object]] = (),
) -> tuple[DualProfileRunManifest, DualProfileFinalResult]:
    final = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(result.profile,),
        executed_profiles=(result.profile,),
        profiles={result.profile: result},
        routing_policy_version=DUAL_PROFILE_ROUTING_POLICY_VERSION,
    )
    manifest = DualProfileRunManifest.model_validate_json(
        json.dumps(
            {
                "source_hash": SOURCE_HASH,
                "requested_profiles": [result.profile.value],
                "executed_profiles": [result.profile.value],
                "profiles": {result.profile.value: result.statistics.model_dump(mode="json")},
                "provider": "mock",
                "model": "mock",
                "prompt_files": {},
                "prompt_hashes": {},
                "calls": {},
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "cache_hits": 0,
                "repair_count": 0,
                "stale_cache_refresh_enabled": bool(resolutions),
                "stale_cache_resolution_count": len(resolutions),
                "stale_cache_resolutions": list(resolutions),
                "boundary_opening_fallbacks": list(fallbacks),
            }
        )
    )
    return manifest, final


def _fallback_pool() -> FinalProfileResult:
    return _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            {
                "candidate_id": "fallback_manual",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.MANUAL_REVIEW,
            },
            {
                "candidate_id": "clean_selected",
                "start_cue_id": 941,
                "end_cue_id": 959,
                "status": CandidateDisposition.SELECTED,
                "score": 90,
            },
        ),
    )


def _boundaries_for(
    result: FinalProfileResult, *, incomplete: frozenset[str]
) -> dict[ClipProfile, ProfileBoundaryReviewOutput]:
    rows = tuple(
        BoundaryReviewItem(
            candidate_id=value.candidate_id,
            profile=result.profile,
            start_cue_id=value.start_cue_id,
            end_cue_id=value.end_cue_id,
            opening_complete=value.candidate_id not in incomplete,
            ending_complete=True,
            central_objective_complete=True,
            shortest_complete_boundary=True,
            quality_flags=(
                (DualQualityFlag.CONTEXT_DEPENDENT_OPENING,)
                if value.candidate_id in incomplete
                else ()
            ),
            evidence_cue_ids=(value.start_cue_id,),
            review_reason="边界审查证据。",
        )
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
    )
    return {result.profile: ProfileBoundaryReviewOutput(profile=result.profile, reviews=rows)}


def test_run_manifest_cross_checks_boundary_opening_fallbacks() -> None:
    result = _fallback_pool()
    record = {
        "profile": "short_highlight",
        "subject_id": "short_highlight.boundary.001",
        "candidate_ids": ["fallback_manual"],
    }
    manifest, final = _fallback_manifest(result, fallbacks=[record])
    manifest.validate_against(final)
    manifest.validate_against(
        final, boundaries=_boundaries_for(result, incomplete=frozenset({"fallback_manual"}))
    )
    # The Boundary Review row must really carry the downgrade.
    with pytest.raises(ValueError, match="still claims a complete opening"):
        manifest.validate_against(final, boundaries=_boundaries_for(result, incomplete=frozenset()))
    with pytest.raises(ValueError, match="outside the Boundary Review output"):
        manifest.validate_against(
            final,
            boundaries={
                ClipProfile.SHORT_HIGHLIGHT: ProfileBoundaryReviewOutput(
                    profile=ClipProfile.SHORT_HIGHLIGHT, reviews=()
                )
            },
        )
    # Unknown, selected, repeated and non-Boundary-Review records are refused.
    unknown, final = _fallback_manifest(result, fallbacks=[{**record, "candidate_ids": ["ghost"]}])
    with pytest.raises(ValueError, match="outside the run"):
        unknown.validate_against(final)
    selected, final = _fallback_manifest(
        result, fallbacks=[{**record, "candidate_ids": ["clean_selected"]}]
    )
    with pytest.raises(ValueError, match="was selected"):
        selected.validate_against(final)
    with pytest.raises(ValueError, match="repeats a candidate"):
        _fallback_manifest(
            result, fallbacks=[{**record, "candidate_ids": ["fallback_manual", "fallback_manual"]}]
        )
    with pytest.raises(ValueError, match="candidate IDs are not unique"):
        _fallback_manifest(
            result,
            fallbacks=[record, {**record, "subject_id": "short_highlight.boundary.002"}],
        )
    with pytest.raises(ValueError, match="repeats a Boundary Review batch"):
        _fallback_manifest(
            result,
            fallbacks=[record, {**record, "candidate_ids": ["clean_selected"]}],
        )
    for subject in (
        "short_highlight.global.001",
        "mini_lesson.boundary.001",
        "short_highlight.boundary.001.extra",
        "short_highlight.global_audit",
    ):
        with pytest.raises(ValueError, match="must name a Boundary Review batch"):
            _fallback_manifest(result, fallbacks=[{**record, "subject_id": subject}])
    other_profile, final = _fallback_manifest(
        result,
        fallbacks=[{**record, "profile": "mini_lesson", "subject_id": "mini_lesson.boundary.001"}],
    )
    with pytest.raises(ValueError, match="unexecuted Profile"):
        other_profile.validate_against(final)


def test_run_manifest_stale_resolution_must_name_a_different_superseding_key() -> None:
    result = _fallback_pool()
    resolution = {
        "stage": "global_audit",
        "profile": "short_highlight",
        "cache_key": "a" * 64,
        "superseding_cache_key": "b" * 64,
        "error_summary": "stale",
        "reused": True,
    }
    manifest, final = _fallback_manifest(result, resolutions=[resolution])
    manifest.validate_against(final)
    with pytest.raises(ValueError, match="different superseding key"):
        _fallback_manifest(result, resolutions=[{**resolution, "superseding_cache_key": "a" * 64}])


def test_long_discovery_uses_six_hundred_second_context_and_three_hundred_ownership() -> None:
    windows = plan_profile_discovery_windows(TRANSCRIPT, ClipProfile.MINI_LESSON)
    assert windows
    assert all(value.ownership_end_ms - value.ownership_start_ms <= 300_000 for value in windows)
    assert max(value.context_end_ms - value.context_start_ms for value in windows) == 600_000
    topic_start, topic_end = 1_890_420, 2_160_060
    owners = [
        value
        for value in windows
        if value.ownership_start_ms <= topic_start < value.ownership_end_ms
    ]
    assert len(owners) == 1
    assert owners[0].context_start_ms <= topic_start
    assert owners[0].context_end_ms >= topic_end
    assert windows[-1].context_end_ms == TRANSCRIPT.source_duration_ms
    assert windows[-1].context_start_ms == TRANSCRIPT.source_duration_ms - 600_000


def test_discovery_rejects_short_limit_applied_to_mini_candidate() -> None:
    windows = plan_profile_discovery_windows(TRANSCRIPT, ClipProfile.MINI_LESSON)
    window = next(
        value for value in windows if value.ownership_start_ms <= 1_637_560 < value.ownership_end_ms
    )
    candidate = _raw(
        profile=ClipProfile.MINI_LESSON,
        window_id=window.window_id,
        candidate_id="too_short_mini",
        start_cue_id=690,
        end_cue_id=719,
    )
    output = ProfileDiscoveryOutput(
        profile=ClipProfile.MINI_LESSON,
        window_id=window.window_id,
        candidates=(candidate,),
    )
    with pytest.raises(ValueError, match="Profile duration"):
        validate_discovery_output(output, window=window, transcript=TRANSCRIPT)


def test_same_topic_short_and_long_variants_are_both_retained() -> None:
    short = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="short_air_mix",
        start_cue_id=690,
        end_cue_id=719,
    )
    long = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id="long_air_mix",
        start_cue_id=690,
        end_cue_id=746,
        status=CandidateDisposition.MANUAL_REVIEW,
        risk_tags=(DualRiskTag.MUSIC_RIGHTS_REVIEW,),
    )
    assert short.selected[0].variant_group_id == long.manual_review[0].variant_group_id
    assert_no_cross_profile_dedup((short, long))


def test_cross_profile_variant_link_changes_labels_without_deleting_candidates() -> None:
    short = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="short_variant",
        start_cue_id=690,
        end_cue_id=719,
    )
    long = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id="long_variant",
        start_cue_id=690,
        end_cue_id=746,
        status=CandidateDisposition.MANUAL_REVIEW,
        risk_tags=(DualRiskTag.MUSIC_RIGHTS_REVIEW,),
    )
    linked = apply_cross_profile_variant_links(
        {
            ClipProfile.SHORT_HIGHLIGHT: short,
            ClipProfile.MINI_LESSON: long,
        },
        CrossProfileVariantLinkOutput(
            links=(
                VariantLinkItem(
                    candidate_id="short_variant",
                    variant_group_id="breathy_voice_family",
                ),
                VariantLinkItem(
                    candidate_id="long_variant",
                    variant_group_id="breathy_voice_family",
                ),
            )
        ),
    )
    assert linked[ClipProfile.SHORT_HIGHLIGHT].statistics == short.statistics
    assert linked[ClipProfile.MINI_LESSON].statistics == long.statistics
    assert (
        linked[ClipProfile.SHORT_HIGHLIGHT].selected[0].variant_group_id
        == linked[ClipProfile.MINI_LESSON].manual_review[0].variant_group_id
        == "breathy_voice_family"
    )


def test_cross_profile_duplicate_reference_is_rejected() -> None:
    short = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="short_balanced_mix",
        start_cue_id=941,
        end_cue_id=958,
    )
    long = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id="long_balanced_mix",
        start_cue_id=940,
        end_cue_id=991,
        status=CandidateDisposition.MANUAL_REVIEW,
        risk_tags=(DualRiskTag.ASR_UNCERTAIN,),
    )
    bad = long.manual_review[0].model_copy(
        update={"duplicate_of_candidate_id": short.selected[0].candidate_id}
    )
    altered = long.model_copy(update={"manual_review": (bad,)})
    with pytest.raises(ValueError, match="cross-Profile"):
        assert_no_cross_profile_dedup((short, altered))


def test_rgr02_quality_flags_forbid_automatic_selection() -> None:
    flags = (
        DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
        DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
        DualQualityFlag.TOPIC_NOT_CLOSED,
        DualQualityFlag.ASR_UNCERTAIN_BLOCKS_MEANING,
    )
    with pytest.raises(ValueError, match="blocking quality"):
        _assemble(
            profile=ClipProfile.SHORT_HIGHLIGHT,
            candidate_id="rgr02",
            start_cue_id=862,
            end_cue_id=887,
            quality_flags=flags,
        )
    manual = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="rgr02_manual",
        start_cue_id=862,
        end_cue_id=887,
        status=CandidateDisposition.BLOCKED,
        quality_flags=flags,
    )
    assert manual.blocked[0].quality_flags == flags


def test_manual_review_quality_gate_flag_set_uses_existing_enum_members() -> None:
    assert {value.value for value in MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS} == {
        "padded_with_irrelevant_content",
        "sales_or_cta_padding",
        "device_or_waiting_padding",
        "material_interruption",
        "topic_switch_inside",
        "topic_not_closed",
        "asr_uncertain_blocks_meaning",
    }
    assert DualQualityFlag.CONTEXT_DEPENDENT_OPENING not in MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
    assert DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS not in MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS


def test_boundary_flag_dropped_by_global_review_blocks_manual_review_candidate() -> None:
    # warm-22 shape: Boundary flags material_interruption, Global Review claims it is
    # resolved and returns manual_review without it; the merged flag must still gate.
    result = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="singing_channel_tight_voice",
        start_cue_id=941,
        end_cue_id=958,
        status=CandidateDisposition.MANUAL_REVIEW,
        boundary_quality_flags=(DualQualityFlag.MATERIAL_INTERRUPTION,),
    )
    assert result.manual_review == ()
    assert len(result.blocked) == 1
    blocked = result.blocked[0]
    assert blocked.review_status == CandidateDisposition.BLOCKED
    assert blocked.quality_flags == (DualQualityFlag.MATERIAL_INTERRUPTION,)
    assert blocked.review_reason == "Deterministic quality gate: 全局审查证据。"
    assert result.statistics.discovered == 1
    assert result.statistics.manual_review == 0
    assert result.statistics.blocked == 1
    assert result.statistics.selected == 0
    assert result.statistics.rejected == 0
    final = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        profiles={ClipProfile.SHORT_HIGHLIGHT: result},
        routing_policy_version=DUAL_PROFILE_ROUTING_POLICY_VERSION,
    )
    DualProfileRunManifest(
        source_hash=SOURCE_HASH,
        requested_profiles=final.requested_profiles,
        executed_profiles=final.executed_profiles,
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: ProfileManifestStats(**result.statistics.model_dump())
        },
        provider="fake",
        model="fake",
        prompt_files={},
        prompt_hashes={},
        calls={},
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        cache_hits=0,
        repair_count=0,
    ).validate_against(final)


@pytest.mark.parametrize("flag", sorted(MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS))
def test_every_gated_quality_flag_downgrades_manual_review_to_blocked(
    flag: DualQualityFlag,
) -> None:
    result = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id=f"gated_{flag.value}",
        start_cue_id=940,
        end_cue_id=991,
        status=CandidateDisposition.MANUAL_REVIEW,
        quality_flags=(flag,),
    )
    assert result.manual_review == ()
    assert [value.candidate_id for value in result.blocked] == [f"gated_{flag.value}"]
    assert result.blocked[0].review_reason.startswith("Deterministic quality gate: ")
    assert (result.statistics.manual_review, result.statistics.blocked) == (0, 1)


@pytest.mark.parametrize(
    "flags",
    [
        (DualQualityFlag.CONTEXT_DEPENDENT_OPENING,),
        (DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,),
        (
            DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
            DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
        ),
    ],
)
def test_advisory_quality_flags_keep_manual_review(flags: tuple[DualQualityFlag, ...]) -> None:
    result = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="context_dependent",
        start_cue_id=941,
        end_cue_id=958,
        status=CandidateDisposition.MANUAL_REVIEW,
        boundary_quality_flags=flags,
    )
    assert result.blocked == ()
    assert len(result.manual_review) == 1
    assert result.manual_review[0].review_reason == "全局审查证据。"
    assert result.manual_review[0].quality_flags == flags
    assert (result.statistics.manual_review, result.statistics.blocked) == (1, 0)


def test_quality_gate_never_upgrades_or_touches_other_dispositions() -> None:
    selected = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="selected_clean",
        start_cue_id=941,
        end_cue_id=958,
    )
    assert [value.candidate_id for value in selected.selected] == ["selected_clean"]
    assert selected.selected[0].review_reason == "全局审查证据。"
    for status in (CandidateDisposition.BLOCKED, CandidateDisposition.REJECTED):
        result = _assemble(
            profile=ClipProfile.SHORT_HIGHLIGHT,
            candidate_id=f"{status.value}_gated",
            start_cue_id=941,
            end_cue_id=958,
            status=status,
            quality_flags=(DualQualityFlag.MATERIAL_INTERRUPTION,),
        )
        values = result.blocked if status == CandidateDisposition.BLOCKED else result.rejected
        assert len(values) == 1
        assert values[0].review_status == status
        assert values[0].review_reason == "全局审查证据。"
    with pytest.raises(ValueError, match="blocking quality"):
        _assemble(
            profile=ClipProfile.SHORT_HIGHLIGHT,
            candidate_id="selected_gated",
            start_cue_id=941,
            end_cue_id=958,
            boundary_quality_flags=(DualQualityFlag.MATERIAL_INTERRUPTION,),
        )


def test_pre_gate_final_artifacts_still_load_without_routing_policy_marker() -> None:
    # A historical artifact: no routing_policy_version and a manual_review row that
    # still carries a gated flag.  Loading must not re-route or raise.
    candidate = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="historical_manual",
        start_cue_id=941,
        end_cue_id=958,
        status=CandidateDisposition.MANUAL_REVIEW,
    ).manual_review[0]
    legacy_candidate = candidate.model_copy(
        update={"quality_flags": (DualQualityFlag.MATERIAL_INTERRUPTION,)}
    )
    legacy_profile = FinalProfileResult(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        raw_candidate_ids=("historical_manual",),
        manual_review=(legacy_candidate,),
        statistics=profile_statistics(("historical_manual",), (legacy_candidate,)),
    )
    payload = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        profiles={ClipProfile.SHORT_HIGHLIGHT: legacy_profile},
    ).model_dump(mode="json")
    payload.pop("routing_policy_version")
    assert "routing_policy_version" not in payload
    loaded = DualProfileFinalResult.model_validate_json(json.dumps(payload))
    assert loaded.routing_policy_version is None
    assert loaded.profiles[ClipProfile.SHORT_HIGHLIGHT].manual_review == (legacy_candidate,)
    marked = DualProfileFinalResult.model_validate_json(
        json.dumps({**payload, "routing_policy_version": DUAL_PROFILE_ROUTING_POLICY_VERSION})
    )
    assert marked.routing_policy_version == DUAL_PROFILE_ROUTING_POLICY_VERSION
    with pytest.raises(ValueError):
        DualProfileFinalResult.model_validate_json(
            json.dumps({**payload, "routing_policy_version": "unknown-policy"})
        )


def _assemble_pool(
    *,
    profile: ClipProfile,
    specs: tuple[dict[str, object], ...],
    risk_record_ids: frozenset[str] = frozenset(),
    top_n: int = 15,
) -> FinalProfileResult:
    windows = plan_profile_discovery_windows(TRANSCRIPT, profile)
    discoveries: list[ProfileDiscoveryOutput] = []
    boundaries: list[BoundaryReviewItem] = []
    reviews: list[GlobalReviewItem] = []
    for spec in specs:
        candidate_id = str(spec["candidate_id"])
        start_cue_id = int(cast(int, spec["start_cue_id"]))
        end_cue_id = int(cast(int, spec["end_cue_id"]))
        risk_tags = cast(tuple[DualRiskTag, ...], spec.get("risk_tags", ()))
        boundary_flags = cast(tuple[DualQualityFlag, ...], spec.get("boundary_flags", ()))
        review_flags = cast(tuple[DualQualityFlag, ...], spec.get("review_flags", ()))
        discovery_flags = cast(tuple[DualQualityFlag, ...], spec.get("discovery_flags", ()))
        raw_start = int(cast(int, spec.get("raw_start_cue_id", start_cue_id)))
        raw_end = int(cast(int, spec.get("raw_end_cue_id", end_cue_id)))
        start_ms = TRANSCRIPT.segments[raw_start - 1].start_ms
        window = next(
            value
            for value in windows
            if value.ownership_start_ms <= start_ms < value.ownership_end_ms
        )
        raw = _raw(
            profile=profile,
            window_id=window.window_id,
            candidate_id=candidate_id,
            start_cue_id=raw_start,
            end_cue_id=raw_end,
        ).model_copy(update={"risk_tags": risk_tags, "quality_flags": discovery_flags})
        discoveries.append(
            ProfileDiscoveryOutput(profile=profile, window_id=window.window_id, candidates=(raw,))
        )
        boundaries.append(
            BoundaryReviewItem(
                candidate_id=candidate_id,
                profile=profile,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                opening_complete=True,
                ending_complete=True,
                central_objective_complete=True,
                shortest_complete_boundary=True,
                quality_flags=boundary_flags,
                risk_tags=risk_tags,
                evidence_cue_ids=(start_cue_id, end_cue_id),
                review_reason="边界审查证据。",
            )
        )
        reviews.append(
            GlobalReviewItem(
                candidate_id=candidate_id,
                profile=profile,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                title="测试候选",
                hook="测试钩子",
                summary="完整摘要。",
                score=float(cast(float, spec.get("score", 70))),
                review_status=cast(CandidateDisposition, spec["status"]),
                duplicate_of_candidate_id=cast(str | None, spec.get("duplicate_of")),
                quality_flags=review_flags,
                risk_tags=risk_tags,
                evidence_cue_ids=(start_cue_id, end_cue_id),
                review_reason=str(spec.get("reason", "全局审查证据。")),
            )
        )
    return assemble_final_profile_result(
        profile=profile,
        discoveries=tuple(discoveries),
        boundaries=ProfileBoundaryReviewOutput(profile=profile, reviews=tuple(boundaries)),
        global_review=ProfileGlobalReviewOutput(profile=profile, reviews=tuple(reviews)),
        transcript=TRANSCRIPT,
        top_n=top_n,
        risk_record_ids=risk_record_ids,
    )


_RISK_POOL: tuple[dict[str, object], ...] = (
    {
        "candidate_id": "parent_lesson",
        "start_cue_id": 940,
        "end_cue_id": 991,
        "status": CandidateDisposition.BLOCKED,
        "risk_tags": (DualRiskTag.MEDICAL_CLAIM,),
    },
    {
        "candidate_id": "pass_record_duplicate",
        "start_cue_id": 941,
        "end_cue_id": 991,
        "status": CandidateDisposition.REJECTED,
        "duplicate_of": "parent_lesson",
        "risk_tags": (DualRiskTag.MEDICAL_CLAIM,),
        "reason": "与父候选重复。",
    },
    {
        "candidate_id": "base_duplicate",
        "start_cue_id": 942,
        "end_cue_id": 991,
        "status": CandidateDisposition.REJECTED,
        "duplicate_of": "parent_lesson",
        "reason": "与父候选重复。",
    },
    {
        "candidate_id": "pass_record_low_value",
        "start_cue_id": 943,
        "end_cue_id": 991,
        "status": CandidateDisposition.REJECTED,
        "risk_tags": (DualRiskTag.HEALTH_ADVICE,),
        "reason": "价值不足。",
    },
)


def test_risk_pass_duplicate_is_retained_blocked_with_its_reference() -> None:
    result = _assemble_pool(
        profile=ClipProfile.MINI_LESSON,
        specs=_RISK_POOL,
        risk_record_ids=frozenset({"pass_record_duplicate", "pass_record_low_value"}),
    )
    blocked = {value.candidate_id: value for value in result.blocked}
    duplicate = blocked["pass_record_duplicate"]
    assert duplicate.duplicate_of_candidate_id == "parent_lesson"
    assert duplicate.review_reason == "Deterministic risk routing: 与父候选重复。"
    assert duplicate.risk_tags == (DualRiskTag.MEDICAL_CLAIM,)
    low_value = blocked["pass_record_low_value"]
    assert low_value.duplicate_of_candidate_id is None
    assert low_value.review_reason == "Deterministic risk routing: 价值不足。"
    # A non-risk-pass duplicate keeps the model rejection.
    assert [value.candidate_id for value in result.rejected] == ["base_duplicate"]
    assert result.rejected[0].review_reason == "与父候选重复。"
    assert result.selected == () and result.manual_review == ()
    # Lineage and recomputed counts are conserved.
    assert result.statistics.discovered == 4
    assert (result.statistics.blocked, result.statistics.rejected) == (3, 1)
    assert set(result.raw_candidate_ids) == {
        source
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
        for source in value.source_candidate_ids
    }
    FinalProfileResult.model_validate(result.model_dump(mode="python"))


def test_risk_routing_is_inert_without_structural_risk_record_ids() -> None:
    result = _assemble_pool(profile=ClipProfile.MINI_LESSON, specs=_RISK_POOL)
    assert [value.candidate_id for value in result.blocked] == ["parent_lesson"]
    assert {value.candidate_id for value in result.rejected} == {
        "pass_record_duplicate",
        "base_duplicate",
        "pass_record_low_value",
    }


def test_blocked_duplicate_is_accepted_only_for_risk_pass_records() -> None:
    specs = (
        _RISK_POOL[0],
        {**_RISK_POOL[1], "status": CandidateDisposition.BLOCKED},
    )
    result = _assemble_pool(
        profile=ClipProfile.MINI_LESSON,
        specs=specs,
        risk_record_ids=frozenset({"pass_record_duplicate"}),
    )
    blocked = {value.candidate_id: value for value in result.blocked}
    assert blocked["pass_record_duplicate"].duplicate_of_candidate_id == "parent_lesson"
    assert blocked["pass_record_duplicate"].review_reason == "与父候选重复。"
    with pytest.raises(ValueError, match="rejected audit row"):
        _assemble_pool(profile=ClipProfile.MINI_LESSON, specs=specs)
    for status in (CandidateDisposition.MANUAL_REVIEW, CandidateDisposition.SELECTED):
        with pytest.raises(ValueError, match="rejected audit row"):
            _assemble_pool(
                profile=ClipProfile.MINI_LESSON,
                specs=(_RISK_POOL[0], {**_RISK_POOL[1], "status": status, "score": 90}),
                risk_record_ids=frozenset({"pass_record_duplicate"}),
            )


def test_risk_routing_never_upgrades_to_an_output() -> None:
    manual = _assemble_pool(
        profile=ClipProfile.MINI_LESSON,
        specs=(
            {
                "candidate_id": "pass_record_manual",
                "start_cue_id": 940,
                "end_cue_id": 991,
                "status": CandidateDisposition.MANUAL_REVIEW,
                "risk_tags": (DualRiskTag.MEDICAL_CLAIM,),
            },
        ),
        risk_record_ids=frozenset({"pass_record_manual"}),
    )
    assert [value.candidate_id for value in manual.manual_review] == ["pass_record_manual"]
    assert manual.manual_review[0].review_reason == "全局审查证据。"


def test_routing_policy_marker_accepts_v1_and_v2() -> None:
    result = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="marker",
        start_cue_id=941,
        end_cue_id=958,
    )
    payload = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        profiles={ClipProfile.SHORT_HIGHLIGHT: result},
    ).model_dump(mode="json")
    for marker in ("manual-review-quality-gate-v1", "quality-gate-risk-routing-v2", None):
        loaded = DualProfileFinalResult.model_validate_json(
            json.dumps({**payload, "routing_policy_version": marker})
        )
        assert loaded.routing_policy_version == marker


def _review_item(
    candidate_id: str,
    start_cue_id: int,
    end_cue_id: int,
    status: CandidateDisposition,
    duplicate_of: str | None = None,
) -> GlobalReviewItem:
    return GlobalReviewItem(
        candidate_id=candidate_id,
        profile=ClipProfile.MINI_LESSON,
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        title="测试候选",
        hook="测试钩子",
        summary="完整摘要。",
        score=70,
        review_status=status,
        duplicate_of_candidate_id=duplicate_of,
        evidence_cue_ids=(start_cue_id,),
        review_reason="全局审查证据。",
    )


def _nested_pool(*items: GlobalReviewItem) -> ProfileGlobalReviewOutput:
    return ProfileGlobalReviewOutput(profile=ClipProfile.MINI_LESSON, reviews=items)


def test_nested_pairs_list_only_retained_same_edge_containment() -> None:
    manual = CandidateDisposition.MANUAL_REVIEW
    pool = _nested_pool(
        _review_item("outer", 100, 160, CandidateDisposition.SELECTED),
        _review_item("same_start", 100, 140, manual),
        _review_item("same_end", 120, 160, manual),
        _review_item("strictly_inside", 110, 150, manual),
        _review_item("overlap_only", 150, 190, manual),
        _review_item("rejected_same_start", 100, 130, CandidateDisposition.REJECTED),
    )
    assert nested_candidate_pairs(pool) == (
        ("outer", "same_start"),
        ("outer", "same_end"),
    )


def test_nested_pair_decisions_must_cover_each_pair_once_and_agree_with_status() -> None:
    manual = CandidateDisposition.MANUAL_REVIEW
    initial = _nested_pool(
        _review_item("outer", 100, 160, manual),
        _review_item("inner", 100, 140, manual),
    )
    pairs = nested_candidate_pairs(initial)
    assert pairs == (("outer", "inner"),)
    distinct = NestedPairDecision(
        outer_candidate_id="outer",
        inner_candidate_id="inner",
        decision=NestedPairDecisionKind.DISTINCT_OBJECTIVE,
        reason="内侧候选回答另一个问题。",
    )
    validate_nested_pair_decisions(pairs, (distinct,), initial)
    with pytest.raises(ValueError, match="cover every listed nested pair"):
        validate_nested_pair_decisions(pairs, (), initial)
    with pytest.raises(ValueError, match="more than once"):
        validate_nested_pair_decisions(pairs, (distinct, distinct), initial)
    with pytest.raises(ValueError, match="not listed"):
        validate_nested_pair_decisions(
            pairs,
            (distinct.model_copy(update={"inner_candidate_id": "unknown"}),),
            initial,
        )
    duplicate = distinct.model_copy(update={"decision": NestedPairDecisionKind.DUPLICATE})
    # Containment alone never decides duplication: a duplicate decision needs a
    # rejected/blocked row that references the other candidate.
    with pytest.raises(ValueError, match="rejected or blocked"):
        validate_nested_pair_decisions(pairs, (duplicate,), initial)
    merged = _nested_pool(
        _review_item("outer", 100, 160, CandidateDisposition.REJECTED, duplicate_of="inner"),
        _review_item("inner", 100, 140, manual),
    )
    validate_nested_pair_decisions(pairs, (duplicate,), merged)
    # Either orientation is accepted; the shorter complete candidate may survive.
    validate_nested_pair_decisions(
        pairs,
        (
            duplicate.model_copy(
                update={"outer_candidate_id": "inner", "inner_candidate_id": "outer"}
            ),
        ),
        merged,
    )
    with pytest.raises(ValueError, match="distinct_objective"):
        validate_nested_pair_decisions(pairs, (distinct,), merged)


def test_nested_duplicate_accepts_members_of_a_three_way_cluster_with_one_representative() -> None:
    manual = CandidateDisposition.MANUAL_REVIEW
    rejected = CandidateDisposition.REJECTED
    # Three identical intervals of one lesson: every pair is listed.
    initial = _nested_pool(
        _review_item("rep", 100, 160, manual),
        _review_item("dup_a", 100, 160, manual),
        _review_item("dup_b", 100, 160, manual),
    )
    pairs = nested_candidate_pairs(initial)
    assert {frozenset(pair) for pair in pairs} == {
        frozenset(("rep", "dup_a")),
        frozenset(("rep", "dup_b")),
        frozenset(("dup_a", "dup_b")),
    }
    merged = _nested_pool(
        _review_item("rep", 100, 160, manual),
        _review_item("dup_a", 100, 160, rejected, duplicate_of="rep"),
        _review_item("dup_b", 100, 160, rejected, duplicate_of="rep"),
    )

    def decide(kind: NestedPairDecisionKind) -> tuple[NestedPairDecision, ...]:
        return tuple(
            NestedPairDecision(
                outer_candidate_id=outer,
                inner_candidate_id=inner,
                decision=kind,
                reason="同一课程的三个版本。",
            )
            for outer, inner in pairs
        )

    # All three pairs are true duplicates, including the two non-representatives.
    validate_nested_pair_decisions(pairs, decide(NestedPairDecisionKind.DUPLICATE), merged)
    # Existing guarantees are kept: distinct_objective still forbids a direct reference.
    with pytest.raises(ValueError, match="distinct_objective"):
        validate_nested_pair_decisions(
            pairs, decide(NestedPairDecisionKind.DISTINCT_OBJECTIVE), merged
        )
    # A shared representative needs both members left rejected/blocked as duplicates.
    retained_member = _nested_pool(
        _review_item("rep", 100, 160, manual),
        _review_item("dup_a", 100, 160, rejected, duplicate_of="rep"),
        _review_item("dup_b", 100, 160, manual),
    )
    with pytest.raises(ValueError, match="same representative"):
        validate_nested_pair_decisions(
            pairs, decide(NestedPairDecisionKind.DUPLICATE), retained_member
        )
    # Different representatives are not a shared-representative duplicate.
    split = _nested_pool(
        _review_item("rep", 100, 160, manual),
        _review_item("dup_a", 100, 160, rejected, duplicate_of="rep"),
        _review_item("dup_b", 100, 160, rejected, duplicate_of="other"),
        _review_item("other", 100, 140, manual),
    )
    a_b = tuple(
        decision
        for decision in decide(NestedPairDecisionKind.DUPLICATE)
        if {decision.outer_candidate_id, decision.inner_candidate_id} == {"dup_a", "dup_b"}
    )
    with pytest.raises(ValueError, match="same representative"):
        validate_nested_pair_decisions(
            tuple(p for p in pairs if set(p) == {"dup_a", "dup_b"}), a_b, split
        )
    # A duplicate-reference cycle resolves to no representative.
    cycle = _nested_pool(
        _review_item("dup_a", 100, 160, rejected, duplicate_of="dup_b"),
        _review_item("dup_b", 100, 160, rejected, duplicate_of="dup_a"),
    )
    # (The direct reference still satisfies the original rule for this pair.)
    validate_nested_pair_decisions(
        tuple(p for p in pairs if set(p) == {"dup_a", "dup_b"}), a_b, cycle
    )


def test_global_audit_output_requires_explicit_nested_pair_decisions() -> None:
    legacy = {"profile": "mini_lesson", "replacements": [], "audit_reason": "旧缓存输出。"}
    with pytest.raises(ValueError):
        ProfileGlobalAuditOutput.model_validate_json(json.dumps(legacy))
    current = ProfileGlobalAuditOutput.model_validate_json(
        json.dumps({**legacy, "nested_pair_decisions": []})
    )
    assert current.nested_pair_decisions == ()


def _by_id(result: FinalProfileResult) -> dict[str, FinalProfileCandidate]:
    return {
        value.candidate_id: value
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
    }


@pytest.mark.parametrize("flag_side", ["boundary_flags", "review_flags"])
def test_same_interval_twins_share_gated_flags_both_ways(flag_side: str) -> None:
    flag = DualQualityFlag.MATERIAL_INTERRUPTION
    for flagged, clean in (("twin_a", "twin_b"), ("twin_b", "twin_a")):
        specs = tuple(
            {
                "candidate_id": candidate_id,
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.MANUAL_REVIEW,
                **({flag_side: (flag,)} if candidate_id == flagged else {}),
            }
            for candidate_id in ("twin_a", "twin_b")
        )
        result = _assemble_pool(profile=ClipProfile.SHORT_HIGHLIGHT, specs=specs)
        values = _by_id(result)
        assert result.manual_review == ()
        assert values[clean].review_status == CandidateDisposition.BLOCKED
        assert flag in values[clean].quality_flags
        assert values[clean].review_reason == "Deterministic quality gate: 全局审查证据。"
        assert (result.statistics.blocked, result.statistics.manual_review) == (2, 0)


def test_selected_twin_inheriting_a_gated_flag_is_blocked_without_raising() -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            {
                "candidate_id": "clean_selected",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.SELECTED,
                "score": 90,
            },
            {
                "candidate_id": "flagged_rejected",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.REJECTED,
                "boundary_flags": (DualQualityFlag.SALES_OR_CTA_PADDING,),
            },
            {
                "candidate_id": "other_interval",
                "start_cue_id": 941,
                "end_cue_id": 959,
                "status": CandidateDisposition.SELECTED,
                "score": 88,
            },
        ),
    )
    values = _by_id(result)
    assert values["clean_selected"].review_status == CandidateDisposition.BLOCKED
    assert DualQualityFlag.SALES_OR_CTA_PADDING in values["clean_selected"].quality_flags
    assert values["clean_selected"].review_reason.startswith("Deterministic quality gate: ")
    assert values["flagged_rejected"].review_status == CandidateDisposition.REJECTED
    assert [value.candidate_id for value in result.selected] == ["other_interval"]


def test_advisory_and_source_title_flags_are_not_shared_between_twins() -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            {
                "candidate_id": "clean_selected",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.SELECTED,
                "score": 90,
            },
            {
                "candidate_id": "clean_manual",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.MANUAL_REVIEW,
            },
            {
                "candidate_id": "advisory_blocked",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.BLOCKED,
                "boundary_flags": (
                    DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
                    DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
                    DualQualityFlag.SOURCE_TITLE_MISMATCH,
                ),
            },
        ),
    )
    values = _by_id(result)
    assert values["clean_selected"].review_status == CandidateDisposition.SELECTED
    assert values["clean_selected"].quality_flags == ()
    assert values["clean_manual"].review_status == CandidateDisposition.MANUAL_REVIEW
    assert values["clean_manual"].quality_flags == ()


def test_risk_record_twin_shares_flags_and_stays_blocked() -> None:
    result = _assemble_pool(
        profile=ClipProfile.MINI_LESSON,
        specs=(
            {
                "candidate_id": "risk_pass_twin",
                "start_cue_id": 940,
                "end_cue_id": 991,
                "status": CandidateDisposition.REJECTED,
                "risk_tags": (DualRiskTag.MEDICAL_CLAIM,),
                "boundary_flags": (DualQualityFlag.TOPIC_SWITCH_INSIDE,),
            },
            {
                "candidate_id": "base_twin",
                "start_cue_id": 940,
                "end_cue_id": 991,
                "status": CandidateDisposition.MANUAL_REVIEW,
            },
        ),
        risk_record_ids=frozenset({"risk_pass_twin"}),
    )
    values = _by_id(result)
    assert values["risk_pass_twin"].review_status == CandidateDisposition.BLOCKED
    assert values["risk_pass_twin"].review_reason.startswith("Deterministic risk routing: ")
    assert values["base_twin"].review_status == CandidateDisposition.BLOCKED
    assert DualQualityFlag.TOPIC_SWITCH_INSIDE in values["base_twin"].quality_flags
    assert values["base_twin"].review_reason.startswith("Deterministic quality gate: ")


def test_risk_record_excluded_by_top_n_is_retained_blocked() -> None:
    specs: tuple[dict[str, object], ...] = (
        {
            "candidate_id": "top_selected",
            "start_cue_id": 941,
            "end_cue_id": 958,
            "status": CandidateDisposition.SELECTED,
            "score": 95,
        },
        {
            "candidate_id": "risk_pass_selected",
            "start_cue_id": 941,
            "end_cue_id": 959,
            "status": CandidateDisposition.SELECTED,
            "score": 80,
            "risk_tags": (DualRiskTag.COMMERCIAL_CLAIM,),
        },
        {
            "candidate_id": "base_selected",
            "start_cue_id": 941,
            "end_cue_id": 960,
            "status": CandidateDisposition.SELECTED,
            "score": 79,
        },
    )
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=specs,
        risk_record_ids=frozenset({"risk_pass_selected"}),
        top_n=1,
    )
    values = _by_id(result)
    assert [value.candidate_id for value in result.selected] == ["top_selected"]
    risk = values["risk_pass_selected"]
    assert risk.review_status == CandidateDisposition.BLOCKED
    assert risk.review_reason == (
        "Deterministic risk routing: Profile-local Top-N exclusion: 全局审查证据。"
    )
    assert values["base_selected"].review_status == CandidateDisposition.REJECTED
    assert values["base_selected"].review_reason.startswith("Profile-local Top-N exclusion: ")


def test_final_evidence_cues_are_limited_to_the_final_interval() -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            {
                "candidate_id": "trimmed",
                "raw_start_cue_id": 940,
                "raw_end_cue_id": 959,
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.MANUAL_REVIEW,
            },
        ),
    )
    candidate = result.manual_review[0]
    assert candidate.evidence_cue_ids == (941, 958)
    assert all(
        candidate.start_cue_id <= cue <= candidate.end_cue_id for cue in candidate.evidence_cue_ids
    )


def test_routing_policy_marker_accepts_every_published_version() -> None:
    assert DUAL_PROFILE_ROUTING_POLICY_VERSION == "quality-gate-risk-routing-v4"
    result = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="marker_v3",
        start_cue_id=941,
        end_cue_id=958,
    )
    payload = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT,),
        profiles={ClipProfile.SHORT_HIGHLIGHT: result},
    ).model_dump(mode="json")
    payload.pop("routing_policy_version")
    assert (
        DualProfileFinalResult.model_validate_json(json.dumps(payload)).routing_policy_version
        is None
    )
    for marker in (
        "manual-review-quality-gate-v1",
        "quality-gate-risk-routing-v2",
        "quality-gate-risk-routing-v3",
        "quality-gate-risk-routing-v4",
    ):
        loaded = DualProfileFinalResult.model_validate_json(
            json.dumps({**payload, "routing_policy_version": marker})
        )
        assert loaded.routing_policy_version == marker


def test_cache_identity_contains_profile_and_window() -> None:
    base = dict(
        source_hash=SOURCE_HASH,
        window_start=0,
        window_end=600_000,
        prompt_hash="a" * 64,
        model="gpt-test",
        model_settings={"reasoning": "medium"},
    )
    short = semantic_cache_key(profile=ClipProfile.SHORT_HIGHLIGHT, **base)
    mini = semantic_cache_key(profile=ClipProfile.MINI_LESSON, **base)
    shifted = semantic_cache_key(
        profile=ClipProfile.MINI_LESSON,
        **{**base, "window_start": 300_000, "window_end": 900_000},
    )
    assert len({short, mini, shifted}) == 3


def test_cache_identity_changes_with_output_schema() -> None:
    base = dict(
        source_hash=SOURCE_HASH,
        profile=ClipProfile.MINI_LESSON,
        window_start=0,
        window_end=600_000,
        prompt_hash="a" * 64,
        model="gpt-test",
    )
    review = semantic_cache_key(
        **base,
        model_settings={"reasoning": "high", "output_model": "ProfileGlobalReviewOutput"},
    )
    audit = semantic_cache_key(
        **base,
        model_settings={"reasoning": "high", "output_model": "ProfileGlobalAuditOutput"},
    )
    assert review != audit


def test_final_result_recomputes_counts_and_conserves_raw_candidates() -> None:
    short = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="short_complete",
        start_cue_id=941,
        end_cue_id=958,
    )
    long = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id="long_complete",
        start_cue_id=940,
        end_cue_id=991,
        status=CandidateDisposition.MANUAL_REVIEW,
        risk_tags=(DualRiskTag.ASR_UNCERTAIN,),
    )
    result = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: short,
            ClipProfile.MINI_LESSON: long,
        },
    )
    assert result.profiles[ClipProfile.SHORT_HIGHLIGHT].statistics.selected == 1
    bad_statistics = short.statistics.model_copy(update={"selected": 0})
    payload = short.model_dump(mode="python")
    payload["statistics"] = bad_statistics
    with pytest.raises(ValueError, match="recomputed"):
        FinalProfileResult.model_validate(payload)


def test_profile_local_top_n_does_not_consume_other_profile_quota() -> None:
    short = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="short_quota",
        start_cue_id=941,
        end_cue_id=958,
    )
    long = _assemble(
        profile=ClipProfile.MINI_LESSON,
        candidate_id="long_quota",
        start_cue_id=940,
        end_cue_id=991,
        status=CandidateDisposition.MANUAL_REVIEW,
        risk_tags=(DualRiskTag.ASR_UNCERTAIN,),
    )
    assert short.statistics.selected == 1
    assert long.statistics.manual_review == 1


def test_final_candidate_schema_exposes_required_profile_lineage_fields() -> None:
    result = _assemble(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        candidate_id="schema_candidate",
        start_cue_id=941,
        end_cue_id=958,
    )
    payload = result.selected[0].model_dump(mode="json")
    assert {
        "profile",
        "variant_group_id",
        "source_candidate_ids",
        "start_ms",
        "end_ms",
        "duration_ms",
        "review_status",
        "quality_flags",
        "risk_tags",
    } <= set(payload)


def test_dual_profile_uses_its_own_preflight_contract() -> None:
    assert (
        _structured_preflight_errors(
            {"algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION},
            {"candidates": [{"candidate_id": "direct-contract"}]},
        )
        == []
    )


# Stage 13 Fix 1: Discovery gated-flag persistence (routing policy v4).

_GATED = DualQualityFlag.TOPIC_SWITCH_INSIDE


def _persistence_spec(
    candidate_id: str,
    *,
    raw: tuple[int, int],
    final: tuple[int, int],
    status: CandidateDisposition = CandidateDisposition.MANUAL_REVIEW,
    discovery_flags: tuple[DualQualityFlag, ...] = (_GATED,),
    score: float = 70,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "raw_start_cue_id": raw[0],
        "raw_end_cue_id": raw[1],
        "start_cue_id": final[0],
        "end_cue_id": final[1],
        "status": status,
        "discovery_flags": discovery_flags,
        "score": score,
    }


@pytest.mark.parametrize(
    ("raw", "final"),
    [((941, 958), (941, 958)), ((941, 958), (940, 958)), ((941, 958), (940, 959))],
    ids=["unchanged", "extended_start", "extended_both"],
)
def test_discovery_gated_flag_survives_an_unchanged_or_extended_interval(
    raw: tuple[int, int], final: tuple[int, int]
) -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(_persistence_spec("flagged", raw=raw, final=final),),
    )
    assert result.manual_review == ()
    (blocked,) = result.blocked
    assert _GATED in blocked.quality_flags
    assert blocked.review_reason == f"{FLAG_PERSISTENCE_REASON_PREFIX}全局审查证据。"
    assert (result.statistics.manual_review, result.statistics.blocked) == (0, 1)


@pytest.mark.parametrize(
    ("raw", "final"),
    [((940, 958), (941, 958)), ((941, 959), (941, 958)), ((940, 958), (941, 959))],
    ids=["start_later", "end_earlier", "start_later_end_extended"],
)
def test_a_trimmed_edge_lets_boundary_review_clear_the_discovery_flag(
    raw: tuple[int, int], final: tuple[int, int]
) -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(_persistence_spec("trimmed", raw=raw, final=final),),
    )
    (kept,) = result.manual_review
    assert kept.quality_flags == ()
    assert result.blocked == ()


def test_advisory_discovery_flags_are_never_persisted() -> None:
    advisory = (
        DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
        DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
        DualQualityFlag.SOURCE_TITLE_MISMATCH,
    )
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            _persistence_spec(
                "advisory", raw=(941, 958), final=(941, 958), discovery_flags=advisory
            ),
        ),
    )
    (kept,) = result.manual_review
    assert kept.quality_flags == ()
    assert kept.review_reason == "全局审查证据。"


def test_flag_persistence_only_downgrades_and_never_raises_or_promotes() -> None:
    specs = (
        _persistence_spec(
            "selected_flagged",
            raw=(941, 958),
            final=(941, 958),
            status=CandidateDisposition.SELECTED,
            score=95,
        ),
        _persistence_spec(
            "rejected_flagged",
            raw=(941, 959),
            final=(941, 959),
            status=CandidateDisposition.REJECTED,
        ),
        _persistence_spec(
            "blocked_flagged", raw=(941, 960), final=(941, 960), status=CandidateDisposition.BLOCKED
        ),
    )
    result = _assemble_pool(profile=ClipProfile.SHORT_HIGHLIGHT, specs=specs)
    values = _by_id(result)
    # A selected row is downgraded to blocked (FinalProfileCandidate forbids a
    # selected row with a gated flag), never rejected as invalid.
    assert values["selected_flagged"].review_status == CandidateDisposition.BLOCKED
    assert values["selected_flagged"].review_reason.startswith(FLAG_PERSISTENCE_REASON_PREFIX)
    # Rejected and blocked rows keep their status; the flag is recorded.
    assert values["rejected_flagged"].review_status == CandidateDisposition.REJECTED
    assert values["rejected_flagged"].review_reason == "全局审查证据。"
    assert values["blocked_flagged"].review_status == CandidateDisposition.BLOCKED
    assert values["blocked_flagged"].review_reason == "全局审查证据。"
    assert all(_GATED in value.quality_flags for value in values.values())
    assert result.selected == () and result.manual_review == ()


def test_flag_persistence_runs_before_twin_union_and_top_n() -> None:
    result = _assemble_pool(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        specs=(
            # Highest score, but its unchanged interval keeps a Discovery gated flag.
            _persistence_spec(
                "flagged_top",
                raw=(941, 958),
                final=(941, 958),
                status=CandidateDisposition.SELECTED,
                score=99,
            ),
            # Same final interval, clean everywhere: it inherits the persisted flag.
            {
                "candidate_id": "twin",
                "start_cue_id": 941,
                "end_cue_id": 958,
                "status": CandidateDisposition.MANUAL_REVIEW,
            },
            {
                "candidate_id": "clean_second",
                "start_cue_id": 941,
                "end_cue_id": 959,
                "status": CandidateDisposition.SELECTED,
                "score": 80,
            },
        ),
        top_n=1,
    )
    values = _by_id(result)
    # The blocked row never takes the single Top-N slot.
    assert [value.candidate_id for value in result.selected] == ["clean_second"]
    assert values["flagged_top"].review_status == CandidateDisposition.BLOCKED
    assert values["flagged_top"].review_reason.startswith(FLAG_PERSISTENCE_REASON_PREFIX)
    assert values["twin"].review_status == CandidateDisposition.BLOCKED
    assert _GATED in values["twin"].quality_flags
    assert values["twin"].review_reason.startswith("Deterministic quality gate: ")


def test_persisted_flags_helper_reports_only_new_gated_flags() -> None:
    raw = _raw(
        profile=ClipProfile.SHORT_HIGHLIGHT,
        window_id="w",
        candidate_id="c",
        start_cue_id=10,
        end_cue_id=20,
    ).model_copy(
        update={
            "quality_flags": (
                DualQualityFlag.MATERIAL_INTERRUPTION,
                DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
                DualQualityFlag.DEVICE_OR_WAITING_PADDING,
            )
        }
    )

    def boundary(start: int, end: int) -> BoundaryReviewItem:
        return BoundaryReviewItem(
            candidate_id="c",
            profile=ClipProfile.SHORT_HIGHLIGHT,
            start_cue_id=start,
            end_cue_id=end,
            opening_complete=True,
            ending_complete=True,
            central_objective_complete=True,
            shortest_complete_boundary=True,
            evidence_cue_ids=(start,),
            review_reason="r",
        )

    assert not boundary_shrank_interval(raw, boundary(9, 21))
    assert boundary_shrank_interval(raw, boundary(11, 21))
    assert boundary_shrank_interval(raw, boundary(9, 19))
    assert discovery_persisted_flags(raw, boundary(10, 20)) == (
        DualQualityFlag.MATERIAL_INTERRUPTION,
        DualQualityFlag.DEVICE_OR_WAITING_PADDING,
    )
    assert discovery_persisted_flags(
        raw, boundary(10, 20), (DualQualityFlag.MATERIAL_INTERRUPTION,)
    ) == (DualQualityFlag.DEVICE_OR_WAITING_PADDING,)
    assert discovery_persisted_flags(raw, boundary(11, 20)) == ()


# Stage 13 Fix 2: overlap adjudication in the Global Audit.


def _second_transcript(tmp_path: Path) -> TranscriptDocument:
    """400 one-second cues: cue N spans [(N-1) s, N s)."""

    path = tmp_path / "seconds.srt"
    lines = []
    for index in range(1, 401):
        start, end = index - 1, index
        lines.append(
            f"{index}\n00:{start // 60:02d}:{start % 60:02d},000 --> "
            f"00:{end // 60:02d}:{end % 60:02d},000\n内容{index}\n"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return load_srt_transcript(path)


def _pool(profile: ClipProfile, *items: tuple[str, int, int, CandidateDisposition]):
    return ProfileGlobalReviewOutput(
        profile=profile,
        reviews=tuple(
            _review_item(candidate_id, start, end, status).model_copy(update={"profile": profile})
            for candidate_id, start, end, status in items
        ),
    )


def test_overlap_constants_are_named_and_exact() -> None:
    assert Fraction(1, 2) == AUDIT_OVERLAP_MIN_SHORTER_FRACTION
    assert Fraction(9, 10) == AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION
    assert dict(AUDIT_SAME_END_TOLERANCE_MS) == {
        ClipProfile.SHORT_HIGHLIGHT: 3_000,
        ClipProfile.MINI_LESSON: 5_000,
    }


def test_audit_pairs_list_overlaps_at_half_the_shorter_candidate(tmp_path: Path) -> None:
    transcript = _second_transcript(tmp_path)
    manual = CandidateDisposition.MANUAL_REVIEW
    # Cue N spans [(N-1) s, N s); a candidate [s, e] spans [(s-1) s, e s).
    pool = _pool(
        ClipProfile.MINI_LESSON,
        ("a", 1, 100, manual),  # [0, 100)
        ("half", 51, 150, manual),  # [50, 150): overlap 50 of 100 -> exactly 50%
        ("below", 52, 160, manual),  # [51, 160): overlap 49 of 100 with a -> below
        ("inside", 10, 60, manual),  # strictly inside a: containment, never listed
        ("same_start", 1, 80, manual),  # nested with a (shared start cue)
        ("rejected", 40, 120, CandidateDisposition.REJECTED),  # not retained
    )
    pairs = audit_candidate_pairs(pool, transcript)
    by_members = {pair.members: pair for pair in pairs}
    assert by_members[frozenset(("a", "same_start"))].pair_kind == AuditPairKind.NESTED
    half = by_members[frozenset(("a", "half"))]
    assert (half.pair_kind, half.outer_candidate_id, half.near_identical) == (
        AuditPairKind.OVERLAP,
        "a",
        False,
    )
    assert frozenset(("a", "below")) not in by_members
    assert frozenset(("a", "inside")) not in by_members
    assert not any("rejected" in pair.members for pair in pairs)
    # half [50,150) vs below [51,160): overlap 99 of 100 -> near-identical.
    assert by_members[frozenset(("half", "below"))].near_identical is True
    # Nested pairs come first and are exactly nested_candidate_pairs.
    nested = [pair for pair in pairs if pair.pair_kind == AuditPairKind.NESTED]
    assert [(p.outer_candidate_id, p.inner_candidate_id) for p in nested] == list(
        nested_candidate_pairs(pool)
    )
    assert pairs[: len(nested)] == tuple(nested)


@pytest.mark.parametrize(
    ("profile", "end_gap_s", "near"),
    [
        (ClipProfile.SHORT_HIGHLIGHT, 3, True),
        (ClipProfile.SHORT_HIGHLIGHT, 4, False),
        (ClipProfile.MINI_LESSON, 5, True),
        (ClipProfile.MINI_LESSON, 6, False),
    ],
)
def test_same_end_within_the_profile_tolerance_is_near_identical(
    tmp_path: Path, profile: ClipProfile, end_gap_s: int, near: bool
) -> None:
    transcript = _second_transcript(tmp_path)
    manual = CandidateDisposition.MANUAL_REVIEW
    # first [0, 60); second [40, 60 + gap): overlap 20 s of 20 + gap s (< 90%).
    pool = _pool(profile, ("first", 1, 60, manual), ("second", 41, 60 + end_gap_s, manual))
    (pair,) = audit_candidate_pairs(pool, transcript)
    assert pair.pair_kind == AuditPairKind.OVERLAP
    assert pair.near_identical is near


def test_ninety_percent_of_the_shorter_candidate_is_near_identical(tmp_path: Path) -> None:
    transcript = _second_transcript(tmp_path)
    manual = CandidateDisposition.MANUAL_REVIEW
    exactly = _pool(
        ClipProfile.MINI_LESSON, ("first", 1, 100, manual), ("second", 11, 120, manual)
    )  # [0,100) vs [10,120): overlap 90 of 100 -> 90%; ends 20 s apart
    (pair,) = audit_candidate_pairs(exactly, transcript)
    assert pair.near_identical is True
    below = _pool(ClipProfile.MINI_LESSON, ("first", 1, 100, manual), ("second", 12, 120, manual))
    (pair,) = audit_candidate_pairs(below, transcript)
    assert pair.near_identical is False


def _decision(outer: str, inner: str, kind: NestedPairDecisionKind) -> NestedPairDecision:
    return NestedPairDecision(
        outer_candidate_id=outer, inner_candidate_id=inner, decision=kind, reason="审计理由。"
    )


def test_audit_must_decide_overlap_pairs_with_the_safety_rules() -> None:
    manual = CandidateDisposition.MANUAL_REVIEW
    rejected = CandidateDisposition.REJECTED
    near = AuditCandidatePair(
        outer_candidate_id="long",
        inner_candidate_id="short",
        pair_kind=AuditPairKind.OVERLAP,
        near_identical=True,
    )
    loose = near.model_copy(update={"near_identical": False})
    both_kept = _nested_pool(
        _review_item("long", 100, 200, manual), _review_item("short", 110, 205, manual)
    )
    distinct = _decision("long", "short", NestedPairDecisionKind.DISTINCT_OBJECTIVE)
    duplicate = _decision("long", "short", NestedPairDecisionKind.DUPLICATE)
    # Every overlap pair must be decided.
    with pytest.raises(ValueError, match="cover every listed nested pair"):
        validate_audit_pair_decisions((near,), (), both_kept)
    # A loose overlap may keep both members as distinct objectives.
    validate_audit_pair_decisions((loose,), (distinct,), both_kept)
    # A near-identical pair may not keep both, whatever the reason says.
    with pytest.raises(ValueError, match="cannot keep both"):
        validate_audit_pair_decisions((near,), (distinct,), both_kept)
    # Keeping one representative resolves it.
    deduped = _nested_pool(
        _review_item("long", 100, 200, rejected, duplicate_of="short"),
        _review_item("short", 110, 205, manual),
    )
    validate_audit_pair_decisions((near,), (duplicate,), deduped)
    # Rejecting/blocking a member on its own merits is also allowed.
    own_merits = _nested_pool(
        _review_item("long", 100, 200, CandidateDisposition.BLOCKED),
        _review_item("short", 110, 205, manual),
    )
    validate_audit_pair_decisions((near,), (distinct,), own_merits)
    # Existing semantics still apply: distinct_objective forbids a direct reference.
    with pytest.raises(ValueError, match="distinct_objective"):
        validate_audit_pair_decisions((near,), (distinct,), deduped)
    # Deduplication never deletes the last retained version of the media.
    no_representative = _nested_pool(
        _review_item("long", 100, 200, rejected, duplicate_of="short"),
        _review_item("short", 110, 205, rejected),
    )
    with pytest.raises(ValueError, match="representative"):
        validate_audit_pair_decisions((loose,), (duplicate,), no_representative)
    # A shared third representative must itself stay retained.
    cluster = _nested_pool(
        _review_item("long", 100, 200, rejected, duplicate_of="rep"),
        _review_item("short", 110, 205, rejected, duplicate_of="rep"),
        _review_item("rep", 105, 204, manual),
    )
    validate_audit_pair_decisions((near,), (duplicate,), cluster)
    blocked_rep = _nested_pool(
        _review_item("long", 100, 200, rejected, duplicate_of="rep"),
        _review_item("short", 110, 205, rejected, duplicate_of="rep"),
        _review_item("rep", 105, 204, CandidateDisposition.BLOCKED),
    )
    with pytest.raises(ValueError, match="representative"):
        validate_audit_pair_decisions((near,), (duplicate,), blocked_rep)


def test_nested_pair_semantics_are_unchanged_by_overlap_rules() -> None:
    manual = CandidateDisposition.MANUAL_REVIEW
    rejected = CandidateDisposition.REJECTED
    nested = AuditCandidatePair(
        outer_candidate_id="outer", inner_candidate_id="inner", pair_kind=AuditPairKind.NESTED
    )
    # Nested pairs may still keep both as distinct objectives ...
    validate_audit_pair_decisions(
        (nested,),
        (_decision("outer", "inner", NestedPairDecisionKind.DISTINCT_OBJECTIVE),),
        _nested_pool(
            _review_item("outer", 100, 160, manual), _review_item("inner", 100, 140, manual)
        ),
    )
    # ... and the existing duplicate rule is unchanged (no retained-representative rule).
    validate_audit_pair_decisions(
        (nested,),
        (_decision("outer", "inner", NestedPairDecisionKind.DUPLICATE),),
        _nested_pool(
            _review_item("outer", 100, 160, rejected, duplicate_of="inner"),
            _review_item("inner", 100, 140, rejected),
        ),
    )
