from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    DualQualityFlag,
    DualRiskTag,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
    profile_statistics,
)
from scripts.benchmark_gates import (
    NEGATIVE_ANCHOR_POLICIES,
    CandidateView,
    duration_allowed,
    is_exact_boundary,
    match_profile,
    negative_anchor_policies,
    tolerance_ms,
)
from scripts.evaluate_benchmark import evaluate

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = json.loads((ROOT / "liveclip_dual_profile_benchmark_v1.json").read_text())
SOURCE_HASH = str(BENCHMARK["source"]["sha256"])
RGR02 = next(value for value in BENCHMARK["regressions"] if value["id"] == "RGR-02")

Buckets = dict[CandidateDisposition, list[FinalProfileCandidate]]


def _anchor(anchor_id: str) -> dict[str, Any]:
    for section in ("gold_short", "gold_mini_lesson", "risk_anchors", "negative_anchors"):
        for value in BENCHMARK[section]:
            if value["id"] == anchor_id:
                return dict(value)
    raise KeyError(anchor_id)


def _custom(
    candidate_id: str,
    *,
    profile: ClipProfile,
    status: CandidateDisposition,
    start_ms: int,
    end_ms: int,
    start_cue_id: int,
    end_cue_id: int,
    score: float = 90,
    quality_flags: tuple[DualQualityFlag, ...] = (),
    risk_tags: tuple[DualRiskTag, ...] = (),
    evidence_cue_ids: tuple[int, ...] | None = None,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id="",
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}_fixture",),
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        title="Evaluator fixture",
        hook="Evaluator fixture",
        summary="Evaluator fixture",
        score=score,
        review_status=status,
        quality_flags=quality_flags,
        risk_tags=risk_tags,
        evidence_cue_ids=evidence_cue_ids or (start_cue_id, end_cue_id),
        review_reason="Evaluator fixture candidate.",
    )


def _candidate(
    anchor: dict[str, Any],
    *,
    profile: ClipProfile,
    status: CandidateDisposition,
    **overrides: Any,
) -> FinalProfileCandidate:
    values: dict[str, Any] = {
        "start_ms": int(anchor["start_ms"]),
        "end_ms": int(anchor["end_ms"]),
        "start_cue_id": int(anchor["cue_start"]),
        "end_cue_id": int(anchor["cue_end"]),
        "risk_tags": tuple(DualRiskTag(value) for value in anchor.get("risk_tags", [])),
    }
    values.update(overrides)
    candidate_id = str(values.pop("candidate_id", str(anchor["id"]).lower()))
    return _custom(candidate_id, profile=profile, status=status, **values)


def _profile_result(profile: ClipProfile, buckets: Buckets) -> FinalProfileResult:
    groups = {status: tuple(buckets.get(status, ())) for status in CandidateDisposition}
    values = tuple(value for items in groups.values() for value in items)
    raw_ids = tuple(value.candidate_id for value in values)
    return FinalProfileResult(
        profile=profile,
        raw_candidate_ids=raw_ids,
        selected=groups[CandidateDisposition.SELECTED],
        manual_review=groups[CandidateDisposition.MANUAL_REVIEW],
        blocked=groups[CandidateDisposition.BLOCKED],
        rejected=groups[CandidateDisposition.REJECTED],
        statistics=profile_statistics(raw_ids, values),
    )


def _passing_buckets() -> dict[ClipProfile, Buckets]:
    manual = CandidateDisposition.MANUAL_REVIEW
    return {
        ClipProfile.SHORT_HIGHLIGHT: {
            manual: [
                _candidate(anchor, profile=ClipProfile.SHORT_HIGHLIGHT, status=manual)
                for anchor in BENCHMARK["gold_short"]
            ]
        },
        ClipProfile.MINI_LESSON: {
            manual: [
                _candidate(anchor, profile=ClipProfile.MINI_LESSON, status=manual)
                for anchor in BENCHMARK["gold_mini_lesson"]
            ],
            CandidateDisposition.BLOCKED: [
                _candidate(
                    anchor,
                    profile=ClipProfile.MINI_LESSON,
                    status=CandidateDisposition.BLOCKED,
                )
                for anchor in BENCHMARK["risk_anchors"]
            ],
        },
    }


def _build(
    buckets: dict[ClipProfile, Buckets],
    *,
    source_hash: str = SOURCE_HASH,
    **manifest_overrides: Any,
) -> tuple[DualProfileFinalResult, DualProfileRunManifest]:
    profiles = {profile: _profile_result(profile, value) for profile, value in buckets.items()}
    result = DualProfileFinalResult(
        source_hash=source_hash,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles=profiles,
    )
    manifest_values: dict[str, Any] = {
        "source_hash": source_hash,
        "requested_profiles": result.requested_profiles,
        "executed_profiles": result.executed_profiles,
        "profiles": {
            key: ProfileManifestStats(**value.statistics.model_dump())
            for key, value in profiles.items()
        },
        "provider": "mock",
        "model": "mock-dual-v1",
        "prompt_files": {"discovery": ("fixture",)},
        "prompt_hashes": {"discovery": "a" * 64},
        "calls": {"discovery": 2, "boundary_review": 2, "global_review": 2},
        "input_tokens": 100,
        "output_tokens": 100,
        "latency_ms": 1,
        "cache_hits": 0,
        "repair_count": 0,
    }
    manifest_values.update(manifest_overrides)
    return result, DualProfileRunManifest(**manifest_values)


def _evaluate(buckets: dict[ClipProfile, Buckets], **kwargs: Any) -> dict[str, Any]:
    result, manifest = _build(buckets, **kwargs)
    return evaluate(BENCHMARK, result, manifest)


def _remove(buckets: Buckets, *candidate_ids: str) -> None:
    for status, values in buckets.items():
        buckets[status] = [value for value in values if value.candidate_id not in candidate_ids]


def test_evaluator_passes_only_complete_dual_profile_contract() -> None:
    report = _evaluate(_passing_buckets())
    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["short_hits"] == 8
    assert report["mini_lesson_hits"] == 6
    assert report["matched_p0"] == ["L01", "L02", "L03"]
    assert not report["hard_failures"]
    assert not report["pass_blockers"]
    assert not report["manual_adjudication_required"]
    assert not report["padding_findings"]
    assert all(report["audit"]["items"].values())
    assert report["source_hash_matches"] is True


def test_evaluator_fails_when_required_p0_is_absent() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.MINI_LESSON], "l03")
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]


def test_source_hash_mismatch_is_a_hard_failure() -> None:
    report = _evaluate(_passing_buckets(), source_hash="0" * 64)
    assert report["status"] == "FAIL"
    assert report["source_hash_matches"] is False
    assert "source_hash_mismatch" in report["hard_failures"]


def test_semantic_only_match_requires_manual_adjudication_and_is_not_a_hit() -> None:
    buckets = _passing_buckets()
    l02 = _anchor("L02")
    _remove(buckets[ClipProfile.MINI_LESSON], "l02")
    # Six seconds early: outside the 5 s tolerance, inside the legacy semantic rule,
    # and within tolerance of the N06 boundary so it is not padding.
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l02,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(l02["start_ms"]) - 6_000,
            start_cue_id=int(l02["cue_start"]) - 1,
        )
    )
    report = _evaluate(buckets)
    assert report["mini_lesson_hits"] == 5
    assert "L02" not in {value["anchor_id"] for value in report["mini_lesson_matches"]}
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]
    assert report["status"] == "FAIL"
    [entry] = report["manual_adjudication_required"]
    assert entry["anchor_id"] == "L02"
    assert entry["candidate_id"] == "l02"
    assert entry["decision"] == "manual_review"
    assert entry["start_delta_ms"] == -6_000
    assert entry["end_delta_ms"] == 0
    assert entry["time_coverage_percent"] == 100.0
    assert entry["cue_coverage_percent"] == 100.0
    assert entry["padding"] == []
    assert not report["padding_findings"]


def test_selected_negative_only_candidate_is_negative_anchor_output_not_padding() -> None:
    # Before operator decision B this negative-only output was irrelevant_padding.
    buckets = _passing_buckets()
    n05 = _anchor("N05")
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.SELECTED] = [
        _custom(
            "padded_selected",
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.SELECTED,
            start_ms=int(n05["start_ms"]) + 1_000,
            end_ms=int(n05["start_ms"]) + 61_000,
            start_cue_id=600,
            end_cue_id=620,
        )
    ]
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "negative_anchor_output" in report["hard_failures"]
    assert "negative_anchor_output" in report["direct_fail_conditions_hit"]
    assert "irrelevant_padding" not in report["hard_failures"]
    assert report["padding_findings"] == []
    [finding] = report["negative_anchor_output_findings"]
    assert (finding["candidate_id"], finding["negative_anchor_id"]) == ("padded_selected", "N05")
    assert finding["hard_failure"] is True
    assert "outside_nearest_anchor_ms" not in finding and "nearest_anchor_id" not in finding


def test_manual_review_candidate_padded_into_negative_anchor_fails_and_is_not_a_hit() -> None:
    buckets = _passing_buckets()
    l02 = _anchor("L02")
    _remove(buckets[ClipProfile.MINI_LESSON], "l02")
    # The legacy evaluator counted this N06-padded L02 as a semantic hit.
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l02,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(l02["start_ms"]) - 20_420,
            start_cue_id=int(l02["cue_start"]) - 5,
        )
    )
    report = _evaluate(buckets)
    assert "L02" not in {value["anchor_id"] for value in report["mini_lesson_matches"]}
    assert [
        (value["candidate_id"], value["negative_anchor_id"]) for value in report["padding_findings"]
    ] == [("l02", "N06")]
    # Controller decision D2: padding is a direct FAIL for manual_review outputs too.
    assert "irrelevant_padding" in report["hard_failures"]
    assert report["status"] == "FAIL"
    [entry] = report["manual_adjudication_required"]
    assert entry["padding"][0]["negative_anchor_id"] == "N06"
    # A semantic-only candidate earns no allowance (D2 applies; strict reading).
    [finding] = report["padding_findings"]
    assert finding["outside_allowed_overlap_ms"] == 19_160
    assert finding["nearest_anchor_id"] == "L02"
    assert finding["outside_nearest_anchor_ms"] == 19_160


def test_semantic_only_candidate_gets_no_padding_allowance() -> None:
    buckets = _passing_buckets()
    l02 = _anchor("L02")
    _remove(buckets[ClipProfile.MINI_LESSON], "l02")
    # Starting 12 s early is semantic-only for L02 (beyond the 5 s tolerance), so it
    # earns no allowance: its 10.74 s N06 overlap exceeds the tolerance and FAILs.
    # The overlap also lies wholly outside the nearest (unwidened) L02 interval.
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l02,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(l02["start_ms"]) - 12_000,
            start_cue_id=int(l02["cue_start"]) - 3,
        )
    )
    report = _evaluate(buckets)
    [finding] = report["padding_findings"]
    assert finding["negative_anchor_id"] == "N06"
    assert finding["outside_allowed_overlap_ms"] == 10_740
    assert finding["outside_nearest_anchor_ms"] == 10_740
    assert [value["anchor_id"] for value in report["manual_adjudication_required"]] == ["L02"]
    assert "irrelevant_padding" in report["hard_failures"]


def test_s08_hit_inside_n09_is_allowed_but_other_n09_content_is_negative_output() -> None:
    buckets = _passing_buckets()
    n09 = _anchor("N09")
    s08 = _anchor("S08")
    assert int(n09["start_ms"]) < int(s08["start_ms"]) < int(s08["end_ms"]) < int(n09["end_ms"])
    report = _evaluate(buckets)
    assert "S08" in {value["anchor_id"] for value in report["short_matches"]}
    assert not report["padding_findings"]

    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
        _custom(
            "n09_chaos",
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(s08["end_ms"]) + 30_000,
            end_ms=int(s08["end_ms"]) + 80_000,
            start_cue_id=2520,
            end_cue_id=2540,
        )
    )
    report = _evaluate(buckets)
    # Operator decision B: N09 permits only the S08 clean sub-interval, so any
    # other N09 output fails, even when routed to manual review.
    assert [
        (value["candidate_id"], value["negative_anchor_id"], value["hard_failure"])
        for value in report["negative_anchor_output_findings"]
    ] == [("n09_chaos", "N09", True)]
    assert report["padding_findings"] == []
    assert "negative_anchor_output" in report["hard_failures"]
    assert report["status"] == "FAIL"


def test_duplicate_s08_one_second_early_is_not_padding() -> None:
    buckets = _passing_buckets()
    s08 = _anchor("S08")
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            s08,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            candidate_id="s08_early",
            start_ms=int(s08["start_ms"]) - 1_000,
        )
    )
    report = _evaluate(buckets)
    # The duplicate loses the one-to-one assignment but keeps its exact-match allowance.
    assert [
        value["candidate_id"] for value in report["short_matches"] if value["anchor_id"] == "S08"
    ] == ["s08"]
    assert not report["padding_findings"]
    assert report["status"] == "PASS"


def test_clean_duplicate_is_preferred_over_flagged_duplicate() -> None:
    buckets = _passing_buckets()
    s01 = _anchor("S01")
    _remove(buckets[ClipProfile.SHORT_HIGHLIGHT], "s01")
    manual = buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW]
    manual.append(
        _candidate(
            s01,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            quality_flags=(DualQualityFlag.TOPIC_NOT_CLOSED,),
        )
    )
    manual.append(
        _candidate(
            s01,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            candidate_id="s01_clean",
            end_ms=int(s01["end_ms"]) + 1_000,
        )
    )
    report = _evaluate(buckets)
    s01_match = next(value for value in report["short_matches"] if value["anchor_id"] == "S01")
    assert s01_match["candidate_id"] == "s01_clean"
    assert report["qualified_boundary_hits"] == 14
    assert report["status"] == "PASS"


def test_mini_lesson_inside_forbidden_composite_fails_for_every_output_decision() -> None:
    first, second = BENCHMARK["forbidden_composite_intervals"]
    buckets = _passing_buckets()
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.SELECTED] = [
        _custom(
            "composite_selected",
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.SELECTED,
            start_ms=int(first["start_ms"]),
            end_ms=int(first["start_ms"]) + 138_000,
            start_cue_id=200,
            end_cue_id=260,
        )
    ]
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _custom(
            "composite_manual",
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(second["start_ms"]) + 800,
            end_ms=int(second["start_ms"]) + 150_800,
            start_cue_id=423,
            end_cue_id=480,
        )
    )
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "forbidden_composite_interval" in report["hard_failures"]
    assert {
        (value["candidate_id"], value["decision"])
        for value in report["forbidden_composite_findings"]
    } == {("composite_selected", "selected"), ("composite_manual", "manual_review")}
    assert not report["padding_findings"]


def test_manual_review_mini_lesson_inside_forbidden_composite_alone_fails() -> None:
    second = BENCHMARK["forbidden_composite_intervals"][1]
    buckets = _passing_buckets()
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _custom(
            "composite_manual",
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(second["start_ms"]) + 800,
            end_ms=int(second["start_ms"]) + 150_800,
            start_cue_id=423,
            end_cue_id=480,
        )
    )
    report = _evaluate(buckets)
    assert report["hard_failures"] == ["forbidden_composite_interval"]
    assert report["status"] == "FAIL"


def test_short_clip_inside_forbidden_composite_is_allowed() -> None:
    report = _evaluate(_passing_buckets())
    # S02 and S03 lie inside the second composite interval.
    assert {"S02", "S03"} <= {value["anchor_id"] for value in report["short_matches"]}
    assert not report["forbidden_composite_findings"]


@pytest.mark.parametrize("end_ms", [int(RGR02["end_ms"]), _anchor("L02")["end_ms"]])
def test_rgr02_original_and_extended_selected_fail(end_ms: int) -> None:
    buckets = _passing_buckets()
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.SELECTED] = [
        _custom(
            "rgr02_selected",
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.SELECTED,
            start_ms=int(RGR02["start_ms"]),
            end_ms=end_ms,
            start_cue_id=862,
            end_cue_id=939,
        )
    ]
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "RGR-02_auto_selected" in report["hard_failures"]
    [regression] = report["regressions"]
    assert regression["auto_selected"] == ["rgr02_selected"]


def test_rgr02_interval_without_all_required_flags_fails() -> None:
    required = tuple(DualQualityFlag(value) for value in RGR02["required_quality_flags"])

    def with_flags(flags: tuple[DualQualityFlag, ...]) -> dict[str, Any]:
        buckets = _passing_buckets()
        buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
            _custom(
                "rgr02_manual",
                profile=ClipProfile.SHORT_HIGHLIGHT,
                status=CandidateDisposition.MANUAL_REVIEW,
                start_ms=int(RGR02["start_ms"]),
                end_ms=int(RGR02["end_ms"]),
                start_cue_id=862,
                end_cue_id=887,
                quality_flags=flags,
            )
        )
        return _evaluate(buckets)

    report = with_flags(required[:-1])
    assert report["status"] == "FAIL"
    assert "RGR-02_required_flags_missing" in report["hard_failures"]
    assert report["regressions"][0]["required_flags_missing"] == [
        {
            "candidate_id": "rgr02_manual",
            "decision": "manual_review",
            "missing_quality_flags": [required[-1].value],
        }
    ]
    report = with_flags(required)
    assert not report["hard_failures"]
    assert report["status"] == "PASS"


def test_full_l02_does_not_trip_rgr02() -> None:
    buckets = _passing_buckets()
    l02 = _anchor("L02")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.SELECTED] = [
        _custom(
            "l02_selected",
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.SELECTED,
            start_ms=int(l02["start_ms"]),
            end_ms=int(l02["end_ms"]),
            start_cue_id=int(l02["cue_start"]),
            end_cue_id=int(l02["cue_end"]),
        )
    ]
    report = _evaluate(buckets)
    assert report["regressions"][0]["auto_selected"] == []
    assert report["regressions"][0]["required_flags_missing"] == []
    assert not any(value.startswith("RGR-02") for value in report["hard_failures"])


def test_conditional_status_follows_acceptance_conditional() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.SHORT_HIGHLIGHT], "s01", "s02")
    _remove(buckets[ClipProfile.MINI_LESSON], "l04", "l05", "l07")
    l07 = _anchor("L07")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l07,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            quality_flags=(DualQualityFlag.TOPIC_NOT_CLOSED,),
        )
    )
    report = _evaluate(buckets)
    # 15 + 20*6/8 + 30*4/6 + 15*9/10 + 10 + 10
    assert report["score"] == 83.5
    assert report["short_hits"] == 6
    assert report["mini_lesson_hits"] == 4
    assert not report["hard_failures"]
    assert set(report["pass_blockers"]) == {
        "short_recall_below_threshold",
        "mini_lesson_recall_below_threshold",
        "score_below_pass_threshold",
    }
    assert report["status"] == "CONDITIONAL"

    _remove(buckets[ClipProfile.MINI_LESSON], "l03")
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"


def test_boundary_score_is_qualified_fraction_of_hits() -> None:
    buckets = _passing_buckets()
    l04 = _anchor("L04")
    _remove(buckets[ClipProfile.MINI_LESSON], "l04")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l04,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            quality_flags=(DualQualityFlag.MATERIAL_INTERRUPTION,),
        )
    )
    report = _evaluate(buckets)
    assert report["qualified_boundary_hits"] == 13
    assert report["components"]["boundary_and_completeness"] == round(15 * 13 / 14, 2)

    empty = {
        ClipProfile.SHORT_HIGHLIGHT: {
            CandidateDisposition.REJECTED: [
                _custom(
                    "short_miss",
                    profile=ClipProfile.SHORT_HIGHLIGHT,
                    status=CandidateDisposition.REJECTED,
                    start_ms=600_000,
                    end_ms=650_000,
                    start_cue_id=150,
                    end_cue_id=160,
                )
            ]
        },
        ClipProfile.MINI_LESSON: {
            CandidateDisposition.REJECTED: [
                _custom(
                    "mini_miss",
                    profile=ClipProfile.MINI_LESSON,
                    status=CandidateDisposition.REJECTED,
                    start_ms=600_000,
                    end_ms=700_000,
                    start_cue_id=150,
                    end_cue_id=170,
                )
            ]
        },
    }
    report = _evaluate(empty)
    assert report["short_hits"] == report["mini_lesson_hits"] == 0
    assert report["components"]["boundary_and_completeness"] == 0
    assert report["status"] == "FAIL"


def test_audit_items_are_computed_and_empty_calls_score_zero() -> None:
    report = _evaluate(_passing_buckets(), calls={})
    assert report["audit"]["items"] == {
        "profile_counts": True,
        "candidate_dispositions": True,
        "version_hash": True,
        "call_data": False,
        "cache_repair_records": True,
    }
    assert report["components"]["audit_and_reproducibility"] == 8.0
    assert report["score"] == 98

    report = _evaluate(_passing_buckets(), prompt_hashes={}, input_tokens=0, output_tokens=0)
    assert report["audit"]["items"]["call_data"] is False


def test_manifest_count_mismatch_is_untraceable_audit_failure() -> None:
    result, manifest = _build(_passing_buckets())
    stats = dict(manifest.profiles)
    stats[ClipProfile.SHORT_HIGHLIGHT] = stats[ClipProfile.SHORT_HIGHLIGHT].model_copy(
        update={"discovered": 99}
    )
    report = evaluate(BENCHMARK, result, manifest.model_copy(update={"profiles": stats}))
    assert report["audit"]["items"]["profile_counts"] is False
    assert "untraceable_or_inconsistent_audit" in report["hard_failures"]
    assert report["status"] == "FAIL"


def test_risk_candidate_routed_outside_required_routing_fails() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.MINI_LESSON], "r01")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.REJECTED] = [
        _candidate(
            _anchor("R01"),
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.REJECTED,
        )
    ]
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "risk_suppressed_or_misrouted" in report["hard_failures"]
    assert "risk_suppressed_during_discovery" not in report["hard_failures"]
    assert report["risk_findings"]["R01"]["misrouted"][0]["decision"] == "rejected"
    assert {value["anchor_id"] for value in report["risk_matches"]} == {"R02"}


def test_risk_candidate_without_anchor_evidence_cues_is_not_matched() -> None:
    buckets = _passing_buckets()
    r01 = _anchor("R01")
    _remove(buckets[ClipProfile.MINI_LESSON], "r01")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.BLOCKED].append(
        _candidate(
            r01,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.BLOCKED,
            start_cue_id=int(r01["cue_start"]) - 2,
            evidence_cue_ids=(int(r01["cue_start"]) - 2, int(r01["cue_start"]) - 1),
        )
    )
    report = _evaluate(buckets)
    assert report["status"] == "FAIL"
    assert "risk_suppressed_or_misrouted" in report["hard_failures"]
    assert report["risk_findings"]["R01"]["missing_evidence_cues"][0]["candidate_id"] == "r01"


def test_risk_absent_from_every_bucket_is_suppressed_during_discovery() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.MINI_LESSON], "r02")
    report = _evaluate(buckets)
    assert "risk_suppressed_during_discovery" in report["hard_failures"]
    assert report["risk_suppressed_during_discovery"] == ["R02"]


def _evaluate_with_bypassed_selected_s01(**update: Any) -> dict[str, Any]:
    """Move S01 to ``selected`` via model_copy, bypassing the production validator.

    This proves each evaluator gate is enforced independently from the benchmark JSON.
    """

    result, manifest = _build(_passing_buckets())
    short = result.profiles[ClipProfile.SHORT_HIGHLIGHT]
    s01 = next(value for value in short.manual_review if value.candidate_id == "s01")
    rest = tuple(value for value in short.manual_review if value is not s01)
    bypassed = s01.model_copy(update={"review_status": CandidateDisposition.SELECTED, **update})
    stats = short.statistics.model_copy(update={"selected": 1, "manual_review": len(rest)})
    altered = short.model_copy(
        update={"selected": (bypassed,), "manual_review": rest, "statistics": stats}
    )
    profiles = {**result.profiles, ClipProfile.SHORT_HIGHLIGHT: altered}
    manifest_profiles = {
        **manifest.profiles,
        ClipProfile.SHORT_HIGHLIGHT: ProfileManifestStats(**stats.model_dump()),
    }
    return evaluate(
        BENCHMARK,
        result.model_copy(update={"profiles": profiles}),
        manifest.model_copy(update={"profiles": manifest_profiles}),
    )


def test_selected_score_gate_is_enforced_from_benchmark_json() -> None:
    report = _evaluate_with_bypassed_selected_s01(score=75)
    assert report["automatic_score_failures"] == ["s01"]
    assert "automatic_score_not_above_threshold" in report["hard_failures"]
    assert report["status"] == "FAIL"
    report = _evaluate_with_bypassed_selected_s01(score=75.01)
    assert report["automatic_score_failures"] == []
    assert not report["hard_failures"]
    assert report["status"] == "PASS"


def test_selected_candidate_with_manual_only_risk_fails() -> None:
    report = _evaluate_with_bypassed_selected_s01(risk_tags=(DualRiskTag.HEALTH_ADVICE,))
    assert "manual_or_blocking_risk_auto_selected" in report["hard_failures"]
    assert report["automatic_risk_failures"] == [
        {"candidate_id": "s01", "risk_tags": ["health_advice"]}
    ]
    assert report["status"] == "FAIL"
    # asr_uncertain is allowed on selectable anchors (S06/S07), so it is not manual-only.
    report = _evaluate_with_bypassed_selected_s01(risk_tags=(DualRiskTag.ASR_UNCERTAIN,))
    assert report["automatic_risk_failures"] == []
    assert report["status"] == "PASS"


@pytest.mark.parametrize(
    ("profile", "duration_ms", "accepted"),
    [
        ("short_highlight", 44_999, False),
        ("short_highlight", 45_000, True),
        ("short_highlight", 90_000, True),
        ("short_highlight", 90_001, False),
        ("mini_lesson", 90_000, False),
        ("mini_lesson", 90_001, True),
        ("mini_lesson", 300_000, True),
        ("mini_lesson", 300_001, False),
    ],
)
def test_evaluator_duration_gate_follows_benchmark_profiles(
    profile: str, duration_ms: int, accepted: bool
) -> None:
    assert duration_allowed(BENCHMARK, profile, duration_ms) is accepted


def _flag(buckets: Buckets, *candidate_ids: str) -> None:
    manual = buckets[CandidateDisposition.MANUAL_REVIEW]
    buckets[CandidateDisposition.MANUAL_REVIEW] = [
        value.model_copy(update={"quality_flags": (DualQualityFlag.MATERIAL_INTERRUPTION,)})
        if value.candidate_id in candidate_ids
        else value
        for value in manual
    ]


def test_score_exactly_85_passes() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.SHORT_HIGHLIGHT], "s01")
    _remove(buckets[ClipProfile.MINI_LESSON], "l04")
    _flag(buckets[ClipProfile.SHORT_HIGHLIGHT], "s02", "s03", "s04", "s05", "s06", "s07")
    report = _evaluate(buckets)
    # 15 + 20*7/8 + 30*5/6 + 15*6/12 + 10 + 10
    assert report["score"] == 85.0
    assert not report["hard_failures"]
    assert not report["pass_blockers"]
    assert report["status"] == "PASS"


def test_score_between_84_and_85_fails_under_literal_conditional() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.MINI_LESSON], "l04")
    _flag(buckets[ClipProfile.SHORT_HIGHLIGHT], *(f"s0{index}" for index in range(1, 9)))
    _flag(buckets[ClipProfile.MINI_LESSON], "l01")
    report = _evaluate(buckets)
    # 15 + 20 + 30*5/6 + 15*4/13 + 10 + 10 = 84.615...; no integer-count fixture
    # yields 84.64 exactly, and any 84 < score < 85 is FAIL (Controller decision D3).
    assert report["score"] == 84.62
    assert report["pass_blockers"] == ["score_below_pass_threshold"]
    assert report["conditional_criteria_met"] is False
    assert report["status"] == "FAIL"


def test_score_at_least_85_with_six_shorts_fails() -> None:
    buckets = _passing_buckets()
    _remove(buckets[ClipProfile.SHORT_HIGHLIGHT], "s01", "s02")
    report = _evaluate(buckets)
    assert report["score"] == 95
    assert report["pass_blockers"] == ["short_recall_below_threshold"]
    assert report["status"] == "FAIL"


def test_matching_uses_augmenting_paths_not_greedy_assignment() -> None:
    synthetic = {
        "matching": {"short_boundary_tolerance_ms": 3_000, "long_boundary_tolerance_ms": 5_000},
        "profiles": BENCHMARK["profiles"],
        "gold_short": [
            {"id": "A1", "start_ms": 100_000, "end_ms": 150_000, "cue_start": 10, "cue_end": 20},
            {"id": "A2", "start_ms": 101_000, "end_ms": 151_000, "cue_start": 11, "cue_end": 21},
        ],
        "gold_mini_lesson": [],
        "negative_anchors": [],
    }
    # c1 is the cheapest exact match for A1 and the only one for A2; c2 matches only A1.
    # A greedy matcher gives A1 -> c1 and leaves A2 unmatched.
    c1 = CandidateView("c1", "short_highlight", "manual_review", 100_000, 150_000, 10, 21, 90)
    c2 = CandidateView("c2", "short_highlight", "manual_review", 97_500, 147_500, 9, 20, 90)
    matching = match_profile(
        synthetic, "short_highlight", (c1, c2), decision_allowed=lambda *_: True
    )
    assert {(value.anchor_id, value.candidate_id) for value in matching.matches} == {
        ("A1", "c2"),
        ("A2", "c1"),
    }


def test_risk_candidate_missing_anchor_risk_tags_is_not_matched() -> None:
    buckets = _passing_buckets()
    r01 = _anchor("R01")
    _remove(buckets[ClipProfile.MINI_LESSON], "r01")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.BLOCKED].append(
        _candidate(
            r01,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.BLOCKED,
            risk_tags=(DualRiskTag.MEDICAL_CLAIM,),
        )
    )
    report = _evaluate(buckets)
    [missing] = report["risk_findings"]["R01"]["missing_risk_tags"]
    assert missing["candidate_id"] == "r01"
    assert missing["missing_risk_tags"] == ["absolute_claim", "health_advice"]
    assert "risk_suppressed_or_misrouted" in report["hard_failures"]
    assert report["status"] == "FAIL"


def test_human_required_lists_source_faithfulness_without_changing_status() -> None:
    report = _evaluate(_passing_buckets())
    checks = {value["check"] for value in report["human_required"]}
    assert "title_hook_summary_must_be_source_faithful" in checks
    assert report["status"] == "PASS"


def test_rgr03_bad_opening_is_reported_as_finding_only() -> None:
    rgr03 = next(value for value in BENCHMARK["regressions"] if value["id"] == "RGR-03")
    buckets = _passing_buckets()
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
        _custom(
            "rgr03_short",
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(rgr03["current_bad_start_ms"]),
            end_ms=int(rgr03["current_bad_start_ms"]) + 46_000,
            start_cue_id=975,
            end_cue_id=991,
        )
    )
    report = _evaluate(buckets)
    assert report["regression_findings"] == [
        {
            "regression_id": "RGR-03",
            "candidate_id": "rgr03_short",
            "profile": "short_highlight",
            "decision": "manual_review",
            "start_delta_ms": 0,
            "forbidden": False,
        }
    ]
    assert not report["hard_failures"]
    assert report["status"] == "PASS"


# Operator decision A (2026-10-21): an exact boundary hit is tolerance-only.
# S03 (73.88 s) and L04 (142.04 s) stay legal after moving inward by the tolerance.
@pytest.mark.parametrize("anchor_id", ["S03", "L04"])
@pytest.mark.parametrize(
    ("start_shift", "end_shift", "cue_shift", "exact"),
    [
        (0.5, -0.5, 1, True),  # inward within tolerance, fewer cues: exact
        (1.0, -1.0, 1, True),  # inward exactly at tolerance: exact
        (-1.0, 1.0, 0, True),  # outward exactly at tolerance: exact
        ("tol+1", 0, 0, False),  # inward 1 ms beyond tolerance
        (0, "-tol-1", 0, False),  # inward end 1 ms beyond tolerance
        ("-tol-1", 0, 0, False),  # outward 1 ms beyond tolerance
    ],
)
def test_exact_boundary_is_tolerance_only_inward_or_outward(
    anchor_id: str, start_shift: Any, end_shift: Any, cue_shift: int, exact: bool
) -> None:
    anchor = _anchor(anchor_id)
    profile = "short_highlight" if anchor_id.startswith("S") else "mini_lesson"
    tolerance = tolerance_ms(BENCHMARK, profile)
    assert tolerance == (3_000 if profile == "short_highlight" else 5_000)

    def shift(value: Any) -> int:
        named = {"tol+1": tolerance + 1, "-tol-1": -tolerance - 1}
        return named[value] if isinstance(value, str) else int(value * tolerance)

    view = CandidateView(
        candidate_id="probe",
        profile=profile,
        decision="manual_review",
        start_ms=int(anchor["start_ms"]) + shift(start_shift),
        end_ms=int(anchor["end_ms"]) + shift(end_shift),
        start_cue_id=int(anchor["cue_start"]) + cue_shift,
        end_cue_id=int(anchor["cue_end"]) - cue_shift,
        score=90,
    )
    assert is_exact_boundary(anchor, view, tolerance) is exact
    matching = match_profile(BENCHMARK, profile, [view], decision_allowed=lambda *_: True)
    assert [value.anchor_id for value in matching.matches] == ([anchor_id] if exact else [])


@pytest.mark.parametrize(
    ("profile", "anchor_id", "section"),
    [
        (ClipProfile.SHORT_HIGHLIGHT, "S03", "short_matches"),
        (ClipProfile.MINI_LESSON, "L04", "mini_lesson_matches"),
    ],
)
def test_inward_candidate_within_tolerance_is_a_qualified_hit(
    profile: ClipProfile, anchor_id: str, section: str
) -> None:
    buckets = _passing_buckets()
    anchor = _anchor(anchor_id)
    tolerance = tolerance_ms(BENCHMARK, profile.value)
    _remove(buckets[profile], anchor_id.lower())
    buckets[profile][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            anchor,
            profile=profile,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(anchor["start_ms"]) + tolerance,
            end_ms=int(anchor["end_ms"]) - tolerance,
            start_cue_id=int(anchor["cue_start"]) + 1,
            end_cue_id=int(anchor["cue_end"]) - 1,
        )
    )
    report = _evaluate(buckets)
    assert anchor_id in {value["anchor_id"] for value in report[section]}
    assert report["qualified_boundary_hits"] == report["short_hits"] + report["mini_lesson_hits"]
    assert report["status"] == "PASS"


def test_inward_semantic_only_candidate_still_needs_manual_adjudication() -> None:
    buckets = _passing_buckets()
    l02 = _anchor("L02")
    _remove(buckets[ClipProfile.MINI_LESSON], "l02")
    buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            l02,
            profile=ClipProfile.MINI_LESSON,
            status=CandidateDisposition.MANUAL_REVIEW,
            start_ms=int(l02["start_ms"]) + 6_000,
            start_cue_id=int(l02["cue_start"]) + 1,
        )
    )
    report = _evaluate(buckets)
    assert "L02" not in {value["anchor_id"] for value in report["mini_lesson_matches"]}
    [entry] = report["manual_adjudication_required"]
    assert (entry["anchor_id"], entry["start_delta_ms"]) == ("L02", 6_000)
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]


# Operator decision B (2026-10-21): negative-only outputs, per-anchor MD section 7 policy.
def _negative_only(
    anchor_id: str,
    status: CandidateDisposition,
    profile: ClipProfile = ClipProfile.MINI_LESSON,
    *,
    offset_ms: int = 60_000,
) -> FinalProfileCandidate:
    negative = _anchor(anchor_id)
    duration = 60_000 if profile == ClipProfile.SHORT_HIGHLIGHT else 120_000
    start = int(negative["start_ms"]) + offset_ms
    assert start + duration <= int(negative["end_ms"])
    return _custom(
        f"{anchor_id.lower()}_{status.value}",
        profile=profile,
        status=status,
        start_ms=start,
        end_ms=start + duration,
        start_cue_id=5000,
        end_cue_id=5020,
    )


def _with(candidate: FinalProfileCandidate) -> dict[str, Any]:
    buckets = _passing_buckets()
    buckets[candidate.profile].setdefault(candidate.review_status, []).append(candidate)
    return _evaluate(buckets)


def test_n08_manual_review_negative_only_is_human_required_not_a_hard_failure() -> None:
    report = _with(_negative_only("N08", CandidateDisposition.MANUAL_REVIEW))
    [finding] = report["negative_anchor_output_findings"]
    assert finding["negative_anchor_id"] == "N08"
    assert finding["hard_failure"] is False
    assert "不得自动作为教学片" in str(finding["policy"])
    assert "negative_anchor_output" not in report["hard_failures"]
    assert report["padding_findings"] == []
    [check] = [
        value
        for value in report["human_required"]
        if value["check"] == "negative_anchor_output_manual_review"
    ]
    assert check["candidate_ids"] == ["n08_manual_review"]
    assert check["negative_anchor_ids"] == ["N08"]
    assert report["status"] == "PASS"


@pytest.mark.parametrize("profile", [ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON])
def test_n08_selected_negative_only_is_a_hard_failure(profile: ClipProfile) -> None:
    report = _with(_negative_only("N08", CandidateDisposition.SELECTED, profile))
    [finding] = report["negative_anchor_output_findings"]
    assert (finding["negative_anchor_id"], finding["hard_failure"]) == ("N08", True)
    assert "negative_anchor_output" in report["hard_failures"]
    assert report["status"] == "FAIL"


@pytest.mark.parametrize("anchor_id", ["N05", "N09"])
def test_default_and_n09_manual_review_negative_only_are_hard_failures(anchor_id: str) -> None:
    profile = ClipProfile.SHORT_HIGHLIGHT
    # N09: 8 s after S08 ends, so the output holds no S08 content.
    offset = 30_000 if anchor_id == "N05" else 75_000
    report = _with(
        _negative_only(anchor_id, CandidateDisposition.MANUAL_REVIEW, profile, offset_ms=offset)
    )
    [finding] = report["negative_anchor_output_findings"]
    assert (finding["negative_anchor_id"], finding["hard_failure"]) == (anchor_id, True)
    assert "negative_anchor_output" in report["hard_failures"]
    assert "irrelevant_padding" not in report["hard_failures"]
    assert report["status"] == "FAIL"


def test_s08_clean_subinterval_inside_n09_is_allowed() -> None:
    buckets = _passing_buckets()
    s08 = _anchor("S08")
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            s08,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            candidate_id="s08_clean_subinterval",
            # Inward by 1 s at the start only: S08 (46.8 s) keeps a legal duration.
            start_ms=int(s08["start_ms"]) + 1_000,
            start_cue_id=int(s08["cue_start"]) + 1,
        )
    )
    report = _evaluate(buckets)
    assert report["negative_anchor_output_findings"] == []
    assert report["padding_findings"] == []
    assert report["status"] == "PASS"


def test_partial_gold_with_negative_overlap_stays_irrelevant_padding() -> None:
    buckets = _passing_buckets()
    s05 = _anchor("S05")
    # S05 extended 20 s into N06: gold content plus negative overlap beyond allowance.
    buckets[ClipProfile.SHORT_HIGHLIGHT][CandidateDisposition.MANUAL_REVIEW].append(
        _candidate(
            s05,
            profile=ClipProfile.SHORT_HIGHLIGHT,
            status=CandidateDisposition.MANUAL_REVIEW,
            candidate_id="s05_into_n06",
            end_ms=int(s05["end_ms"]) + 20_000,
            end_cue_id=int(s05["cue_end"]) + 8,
        )
    )
    report = _evaluate(buckets)
    assert report["negative_anchor_output_findings"] == []
    [finding] = report["padding_findings"]
    assert (finding["candidate_id"], finding["negative_anchor_id"]) == ("s05_into_n06", "N06")
    assert finding["outside_allowed_overlap_ms"] == 20_000
    assert "irrelevant_padding" in report["hard_failures"]
    assert "negative_anchor_output" not in report["hard_failures"]


def test_policy_table_matches_every_benchmark_negative_anchor() -> None:
    resolved = negative_anchor_policies(BENCHMARK)
    assert resolved.mismatches == ()
    assert set(NEGATIVE_ANCHOR_POLICIES) == {value["id"] for value in BENCHMARK["negative_anchors"]}
    for anchor in BENCHMARK["negative_anchors"]:
        policy = resolved.policies[anchor["id"]]
        assert policy.reason == anchor["reason"]
        assert policy.md_section_7_row.startswith("MD §7 line ")


@pytest.mark.parametrize(
    ("mutation", "mismatch"),
    [
        ("reason", "reason"),
        ("benchmark_id", "benchmark_id"),
        ("s08_outside_n09", "clean_subinterval_anchor"),
        ("unknown_anchor", "no_policy_entry"),
    ],
)
def test_policy_table_mismatch_fails_closed(mutation: str, mismatch: str) -> None:
    benchmark = json.loads(json.dumps(BENCHMARK))
    n08 = next(value for value in benchmark["negative_anchors"] if value["id"] == "N08")
    target = "N08"
    if mutation == "reason":
        n08["reason"] = "edited_reason"
    elif mutation == "benchmark_id":
        benchmark["benchmark_id"] = "another-benchmark"
    elif mutation == "s08_outside_n09":
        target = "N09"
        s08 = next(value for value in benchmark["gold_short"] if value["id"] == "S08")
        s08["start_ms"] = int(benchmark["negative_anchors"][8]["start_ms"]) - 1
    else:
        target = "N99"
        benchmark["negative_anchors"].append(
            {"id": "N99", "start_ms": 1, "end_ms": 2, "reason": "unlisted"}
        )
    resolved = negative_anchor_policies(benchmark)
    assert {"negative_anchor_id": target, "mismatch": mismatch} in resolved.mismatches
    # The strictest policy: every output decision is a hard failure.
    assert resolved.policies[target].hard_fail_decisions >= {"selected", "manual_review"}
    if mutation in {"reason", "benchmark_id"}:
        buckets = _passing_buckets()
        candidate = _negative_only("N08", CandidateDisposition.MANUAL_REVIEW)
        buckets[ClipProfile.MINI_LESSON][CandidateDisposition.MANUAL_REVIEW].append(candidate)
        result, manifest = _build(buckets)
        report = evaluate(benchmark, result, manifest)
        [finding] = report["negative_anchor_output_findings"]
        assert finding["hard_failure"] is True
        assert "negative_anchor_output" in report["hard_failures"]
        assert report["negative_anchor_policy_mismatches"]
