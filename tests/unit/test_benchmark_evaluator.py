from __future__ import annotations

import json
from pathlib import Path

from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    DualRiskTag,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
    profile_statistics,
)
from scripts.evaluate_benchmark import evaluate

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = json.loads((ROOT / "liveclip_dual_profile_benchmark_v1.json").read_text())
SOURCE_HASH = str(BENCHMARK["source"]["sha256"])


def _candidate(
    anchor: dict[str, object],
    *,
    profile: ClipProfile,
    status: CandidateDisposition,
) -> FinalProfileCandidate:
    candidate_id = str(anchor["id"]).lower()
    risks = tuple(DualRiskTag(value) for value in anchor.get("risk_tags", []))
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id=str(anchor.get("variant_group_id", "")),
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}_fixture",),
        start_cue_id=int(anchor["cue_start"]),
        end_cue_id=int(anchor["cue_end"]),
        start_ms=int(anchor["start_ms"]),
        end_ms=int(anchor["end_ms"]),
        duration_ms=int(anchor["duration_ms"]),
        title=str(anchor["topic"]),
        hook=str(anchor["topic"]),
        summary=str(anchor["topic"]),
        score=90,
        review_status=status,
        risk_tags=risks,
        evidence_cue_ids=(int(anchor["cue_start"]), int(anchor["cue_end"])),
        review_reason="Evaluator fixture candidate.",
    )


def _profile_result(
    profile: ClipProfile,
    *,
    manual: tuple[FinalProfileCandidate, ...],
    blocked: tuple[FinalProfileCandidate, ...] = (),
) -> FinalProfileResult:
    values = (*manual, *blocked)
    raw_ids = tuple(value.candidate_id for value in values)
    return FinalProfileResult(
        profile=profile,
        raw_candidate_ids=raw_ids,
        manual_review=manual,
        blocked=blocked,
        statistics=profile_statistics(raw_ids, values),
    )


def _passing_result() -> tuple[DualProfileFinalResult, DualProfileRunManifest]:
    short = _profile_result(
        ClipProfile.SHORT_HIGHLIGHT,
        manual=tuple(
            _candidate(
                anchor,
                profile=ClipProfile.SHORT_HIGHLIGHT,
                status=CandidateDisposition.MANUAL_REVIEW,
            )
            for anchor in BENCHMARK["gold_short"]
        ),
    )
    long_gold = tuple(
        _candidate(
            anchor,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
        )
        for anchor in BENCHMARK["gold_mini_lesson"]
    )
    risk = tuple(
        _candidate(
            anchor,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.BLOCKED,
        )
        for anchor in BENCHMARK["risk_anchors"]
    )
    long = _profile_result(ClipProfile.MINI_LESSON, manual=long_gold, blocked=risk)
    profiles = {
        ClipProfile.SHORT_HIGHLIGHT: short,
        ClipProfile.MINI_LESSON: long,
    }
    result = DualProfileFinalResult(
        source_hash=SOURCE_HASH,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles=profiles,
    )
    manifest = DualProfileRunManifest(
        source_hash=SOURCE_HASH,
        requested_profiles=result.requested_profiles,
        executed_profiles=result.executed_profiles,
        profiles={
            key: ProfileManifestStats(**value.statistics.model_dump())
            for key, value in profiles.items()
        },
        provider="mock",
        model="mock-dual-v1",
        prompt_files={"discovery": ("fixture",)},
        prompt_hashes={"discovery": "a" * 64},
        calls={"discovery": 2, "boundary_review": 2, "global_review": 2},
        input_tokens=100,
        output_tokens=100,
        latency_ms=1,
        cache_hits=0,
        repair_count=0,
    )
    return result, manifest


def test_evaluator_passes_only_complete_dual_profile_contract() -> None:
    result, manifest = _passing_result()
    report = evaluate(BENCHMARK, result, manifest)
    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["short_hits"] == 8
    assert report["mini_lesson_hits"] == 6
    assert report["matched_p0"] == ["L01", "L02", "L03"]
    assert not report["hard_failures"]


def test_evaluator_fails_when_required_p0_is_absent() -> None:
    result, _ = _passing_result()
    long = result.profiles[ClipProfile.MINI_LESSON]
    retained = tuple(value for value in long.manual_review if value.candidate_id != "l03")
    replacement = _profile_result(
        ClipProfile.MINI_LESSON,
        manual=retained,
        blocked=long.blocked,
    )
    altered = DualProfileFinalResult(
        source_hash=result.source_hash,
        requested_profiles=result.requested_profiles,
        executed_profiles=result.executed_profiles,
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: result.profiles[ClipProfile.SHORT_HIGHLIGHT],
            ClipProfile.MINI_LESSON: replacement,
        },
    )
    manifest = DualProfileRunManifest(
        source_hash=altered.source_hash,
        requested_profiles=altered.requested_profiles,
        executed_profiles=altered.executed_profiles,
        profiles={
            key: ProfileManifestStats(**value.statistics.model_dump())
            for key, value in altered.profiles.items()
        },
        provider="mock",
        model="mock-dual-v1",
        prompt_files={"discovery": ("fixture",)},
        prompt_hashes={"discovery": "a" * 64},
        calls={"discovery": 2, "boundary_review": 2, "global_review": 2},
        input_tokens=100,
        output_tokens=100,
        latency_ms=1,
        cache_hits=0,
        repair_count=0,
    )
    report = evaluate(BENCHMARK, altered, manifest)
    assert report["status"] == "FAIL"
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]
