from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ALGORITHM_VERSION,
    PROFILE_DURATION_CONTRACTS,
    BoundaryReviewItem,
    BoundaryState,
    CandidateDisposition,
    CrossProfileVariantLinkOutput,
    DualProfileFinalResult,
    DualQualityFlag,
    DualRiskTag,
    FinalProfileResult,
    GlobalReviewItem,
    ProfileBoundaryReviewOutput,
    ProfileDiscoveryOutput,
    ProfileGlobalReviewOutput,
    RawProfileCandidate,
    VariantLinkItem,
    apply_cross_profile_variant_links,
    assemble_final_profile_result,
    assert_no_cross_profile_dedup,
    plan_profile_discovery_windows,
    semantic_cache_key,
    validate_boundary_review_output,
    validate_discovery_output,
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
    risk_tags: tuple[DualRiskTag, ...] = (),
    score: float = 90,
) -> FinalProfileResult:
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
        opening_complete=not quality_flags,
        ending_complete=not quality_flags,
        central_objective_complete=not quality_flags,
        shortest_complete_boundary=not quality_flags,
        quality_flags=quality_flags,
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
        )


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
