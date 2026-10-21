#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
)

# The shared evaluation-only gates live beside this script.  Resolve them the same
# way whether this file runs directly or is imported as ``scripts.evaluate_benchmark``.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parent))

from benchmark_gates import (
    MINI_PROFILE,
    PROFILE_GOLD_SECTIONS,
    SHORT_PROFILE,
    CandidateView,
    Match,
    assess_risk_anchor,
    auto_decision_regressions,
    boundary_score,
    composite_overlaps,
    duration_violations,
    match_profile,
    padding_overlaps,
    regression_interval_hits,
    regression_start_hits,
    regression_tolerance,
    tolerance_ms,
)

__all__ = ["Match", "evaluate"]

STATUS_PASS = "PASS"
STATUS_CONDITIONAL = "CONDITIONAL"
STATUS_FAIL = "FAIL"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _groups(
    value: FinalProfileResult,
) -> dict[CandidateDisposition, tuple[FinalProfileCandidate, ...]]:
    return {
        CandidateDisposition.SELECTED: value.selected,
        CandidateDisposition.MANUAL_REVIEW: value.manual_review,
        CandidateDisposition.BLOCKED: value.blocked,
        CandidateDisposition.REJECTED: value.rejected,
    }


def _view(candidate: FinalProfileCandidate, decision: CandidateDisposition) -> CandidateView:
    # The decision is the terminal array that holds the candidate; the audit
    # separately verifies that it equals ``review_status``.
    return CandidateView(
        candidate_id=candidate.candidate_id,
        profile=candidate.profile.value,
        decision=decision.value,
        start_ms=candidate.start_ms,
        end_ms=candidate.end_ms,
        start_cue_id=candidate.start_cue_id,
        end_cue_id=candidate.end_cue_id,
        score=float(candidate.score),
        quality_flags=frozenset(flag.value for flag in candidate.quality_flags),
        risk_tags=frozenset(tag.value for tag in candidate.risk_tags),
        evidence_cue_ids=frozenset(candidate.evidence_cue_ids),
    )


def _views(result: DualProfileFinalResult) -> tuple[CandidateView, ...]:
    return tuple(
        _view(candidate, decision)
        for value in result.profiles.values()
        for decision, candidates in _groups(value).items()
        for candidate in candidates
    )


def _audit(result: DualProfileFinalResult, manifest: DualProfileRunManifest) -> dict[str, Any]:
    """Audit and reproducibility: five items x 2 points (MD section 10).

    Field mapping (an empty or missing item scores 0):

    1. ``profile_counts``: per executed Profile, ``discovered`` equals
       ``len(raw_candidate_ids)`` and each disposition count equals the length of
       its terminal array; ``FinalProfileResult.statistics`` and
       ``DualProfileRunManifest.profiles`` both equal that recount, and the
       manifest's requested/executed Profiles equal the result's.
    2. ``candidate_dispositions``: at least one raw candidate exists; every
       ``raw_candidate_ids`` entry is the source of some final candidate and every
       final ``source_candidate_ids`` entry is a raw ID; candidate IDs are unique
       across terminal arrays; every candidate's ``review_status`` equals its
       array.
    3. ``version_hash``: result/manifest ``schema_version`` and
       ``algorithm_version`` are present and equal, ``source_hash`` is present
       and equal in both, and the manifest names ``provider`` and ``model``.
    4. ``call_data``: ``calls`` is non-empty with a positive total,
       ``prompt_hashes`` is non-empty with no empty value, and
       ``input_tokens + output_tokens`` is positive.
    5. ``cache_repair_records``: the manifest explicitly records ``cache_hits``
       and ``repair_count`` (``model_fields_set``).
    """

    items: dict[str, bool] = {}
    details: dict[str, Any] = {}
    recounted: dict[str, ProfileManifestStats] = {}
    for profile, value in result.profiles.items():
        groups = _groups(value)
        recounted[profile.value] = ProfileManifestStats(
            discovered=len(value.raw_candidate_ids),
            selected=len(groups[CandidateDisposition.SELECTED]),
            manual_review=len(groups[CandidateDisposition.MANUAL_REVIEW]),
            blocked=len(groups[CandidateDisposition.BLOCKED]),
            rejected=len(groups[CandidateDisposition.REJECTED]),
        )
    result_stats = {
        profile.value: ProfileManifestStats(**value.statistics.model_dump())
        for profile, value in result.profiles.items()
    }
    manifest_stats = {profile.value: value for profile, value in manifest.profiles.items()}
    identity_consistent = (
        manifest.requested_profiles == result.requested_profiles
        and manifest.executed_profiles == result.executed_profiles
    )
    items["profile_counts"] = (
        bool(recounted)
        and result_stats == recounted
        and manifest_stats == recounted
        and identity_consistent
    )
    details["recounted_profile_counts"] = {
        key: value.model_dump() for key, value in sorted(recounted.items())
    }

    raw_ids: list[str] = []
    traced: set[str] = set()
    final_ids: list[str] = []
    wrong_array: list[str] = []
    for value in result.profiles.values():
        raw_ids.extend(value.raw_candidate_ids)
        for decision, candidates in _groups(value).items():
            for candidate in candidates:
                final_ids.append(candidate.candidate_id)
                traced.update(candidate.source_candidate_ids)
                if candidate.review_status != decision:
                    wrong_array.append(candidate.candidate_id)
    untraced_raw = sorted(set(raw_ids) - traced)
    unknown_sources = sorted(traced - set(raw_ids))
    items["candidate_dispositions"] = (
        bool(raw_ids)
        and not untraced_raw
        and not unknown_sources
        and not wrong_array
        and len(final_ids) == len(set(final_ids))
    )
    details["untraced_raw_candidate_ids"] = untraced_raw
    details["unknown_source_candidate_ids"] = unknown_sources
    details["candidates_in_wrong_array"] = sorted(wrong_array)

    items["version_hash"] = bool(
        result.schema_version
        and result.algorithm_version
        and result.source_hash
        and manifest.schema_version == result.schema_version
        and manifest.algorithm_version == result.algorithm_version
        and manifest.source_hash == result.source_hash
        and manifest.provider
        and manifest.model
    )
    items["call_data"] = bool(
        manifest.calls
        and sum(manifest.calls.values()) > 0
        and manifest.prompt_hashes
        and all(manifest.prompt_hashes.values())
        and manifest.input_tokens + manifest.output_tokens > 0
    )
    items["cache_repair_records"] = {"cache_hits", "repair_count"} <= manifest.model_fields_set
    score = 2.0 * sum(1 for value in items.values() if value)
    return {
        "items": items,
        "score": score,
        "identity_consistent": identity_consistent and manifest.source_hash == result.source_hash,
        "traceable_and_consistent": (
            items["profile_counts"]
            and items["candidate_dispositions"]
            and manifest.source_hash == result.source_hash
        ),
        **details,
    }


def evaluate(
    benchmark: dict[str, Any],
    result: DualProfileFinalResult,
    manifest: DualProfileRunManifest,
) -> dict[str, Any]:
    acceptance = benchmark["acceptance"]
    gates = benchmark["automatic_selection_gates"]
    hard_failures: list[str] = []
    source_hash_matches = result.source_hash == benchmark["source"]["sha256"]
    if not source_hash_matches:
        hard_failures.append("source_hash_mismatch")

    # RGR-01 / Profile execution comes from the explicit executed_profiles record.
    required_profiles = tuple(benchmark["required_behavior"]["requested_profiles"])
    executed = tuple(value.value for value in result.executed_profiles)
    requested = tuple(value.value for value in result.requested_profiles)
    both_profiles = requested == required_profiles and set(executed) == set(required_profiles)
    if not both_profiles:
        hard_failures.append("missing_executed_profile")

    views = _views(result)
    match_decisions = {str(value) for value in benchmark["matching"]["match_decisions"]}
    outputs = tuple(value for value in views if value.decision in match_decisions)
    selected = tuple(
        value for value in views if value.decision == CandidateDisposition.SELECTED.value
    )

    def decision_allowed(anchor: Mapping[str, Any], candidate: CandidateView) -> bool:
        allowed = {str(value) for value in anchor.get("allowed_decisions", ())}
        return candidate.decision in match_decisions and candidate.decision in allowed

    matchings = {
        profile: match_profile(benchmark, profile, outputs, decision_allowed=decision_allowed)
        for profile in PROFILE_GOLD_SECTIONS
    }
    short_matches = matchings[SHORT_PROFILE].matches
    long_matches = matchings[MINI_PROFILE].matches
    allowed_intervals = {
        key: value for item in matchings.values() for key, value in item.allowed_intervals.items()
    }
    manual_adjudication = [
        entry for item in matchings.values() for entry in item.manual_adjudication_required
    ]
    padding_excluded = [
        entry for item in matchings.values() for entry in item.padding_excluded_hits
    ]

    durations = duration_violations(benchmark, views)
    if durations:
        hard_failures.append("duration_out_of_profile_bounds")

    padding: list[dict[str, object]] = []
    for candidate in outputs:
        padding.extend(
            padding_overlaps(
                benchmark,
                candidate,
                allowed=allowed_intervals.get(candidate.candidate_id),
                tolerance=tolerance_ms(benchmark, candidate.profile),
            )
        )
    padded_ids = {str(value["candidate_id"]) for value in padding}
    if any(value["decision"] == CandidateDisposition.SELECTED.value for value in padding):
        hard_failures.append("irrelevant_padding")

    composites = [
        entry for candidate in outputs for entry in composite_overlaps(benchmark, candidate)
    ]
    if any(value["decision"] == CandidateDisposition.SELECTED.value for value in composites):
        hard_failures.append("forbidden_composite_interval")

    forbidden_quality = {str(value) for value in gates["forbidden_quality_flags"]}
    automatic_quality_failures = [
        value.candidate_id
        for value in selected
        if (value.quality_flags or set()) & forbidden_quality
    ]
    if automatic_quality_failures:
        hard_failures.append("automatic_hard_quality_failure")
    score_threshold = float(gates["score_strictly_greater_than"])
    automatic_score_failures = [
        value.candidate_id for value in selected if not value.score > score_threshold
    ]
    if automatic_score_failures:
        hard_failures.append("automatic_score_not_above_threshold")

    regression_reports: list[dict[str, Any]] = []
    for regression in auto_decision_regressions(benchmark):
        tolerance = regression_tolerance(benchmark, regression)
        auto = regression_start_hits(regression, selected, tolerance)
        required_flags = {str(value) for value in regression.get("required_quality_flags", ())}
        missing_flags = [
            {
                "candidate_id": value.candidate_id,
                "decision": value.decision,
                "missing_quality_flags": sorted(required_flags - (value.quality_flags or set())),
            }
            for value in regression_interval_hits(regression, views, tolerance)
            if not required_flags <= (value.quality_flags or set())
        ]
        if auto:
            hard_failures.append(f"{regression['id']}_auto_selected")
        if missing_flags:
            hard_failures.append(f"{regression['id']}_required_flags_missing")
        regression_reports.append(
            {
                "regression_id": str(regression["id"]),
                "auto_selected": [value.candidate_id for value in auto],
                "required_flags_missing": missing_flags,
            }
        )

    risks = {
        str(anchor["id"]): assess_risk_anchor(anchor, views, routing_evaluable=True)
        for anchor in benchmark["risk_anchors"]
    }
    risk_matches = tuple(value.match for value in risks.values() if value.match is not None)
    required_risk_ids = {str(value) for value in acceptance["required_risk_anchor_ids"]}
    matched_risk_ids = {value.anchor_id for value in risk_matches}
    suppressed_risk_ids = sorted(
        key
        for key in required_risk_ids
        if key not in risks or not risks[key].discovered_candidate_ids
    )
    if suppressed_risk_ids:
        hard_failures.append("risk_suppressed_during_discovery")
    if not required_risk_ids <= matched_risk_ids:
        hard_failures.append("risk_suppressed_or_misrouted")

    audit = _audit(result, manifest)
    if not audit["traceable_and_consistent"]:
        hard_failures.append("untraceable_or_inconsistent_audit")

    matched_long_ids = {value.anchor_id for value in long_matches}
    p0_ids = {str(value) for value in acceptance["required_p0_mini_lesson_ids"]}
    if not p0_ids <= matched_long_ids:
        hard_failures.append("missing_any_p0_mini_lesson")

    components_points = benchmark["scoring"]["components"]
    profile_points = float(components_points["both_profiles_executed"])
    executed_points = (
        profile_points * len(set(executed) & set(required_profiles)) / len(required_profiles)
    )
    short_score = (
        float(components_points["short_recall"])
        * len(short_matches)
        / int(acceptance["short_total"])
    )
    long_score = (
        float(components_points["mini_lesson_recall"])
        * len(long_matches)
        / int(acceptance["mini_lesson_total"])
    )
    views_by_id = {value.candidate_id: value for value in views}

    def qualified(match: Match) -> bool:
        candidate = views_by_id[match.candidate_id]
        return (
            match.match_kind == "exact_boundary"
            and not (candidate.quality_flags or set()) & forbidden_quality
            and candidate.candidate_id not in padded_ids
        )

    all_hits = (*short_matches, *long_matches)
    boundary, qualified_hits = boundary_score(
        float(components_points["boundary_and_completeness"]), all_hits, qualified=qualified
    )
    risk_score = (
        float(components_points["risk_discovery_and_routing"])
        * len(risk_matches)
        / len(benchmark["risk_anchors"])
    )
    audit_score = float(audit["score"])
    score = round(
        executed_points + short_score + long_score + boundary + risk_score + audit_score, 2
    )

    pass_blockers: list[str] = []
    if len(short_matches) < int(acceptance["short_min_hits"]):
        pass_blockers.append("short_recall_below_threshold")
    if len(long_matches) < int(acceptance["mini_lesson_min_hits"]):
        pass_blockers.append("mini_lesson_recall_below_threshold")
    if score < float(acceptance["pass_min_score"]):
        pass_blockers.append("score_below_pass_threshold")

    conditional = acceptance["conditional"]
    conditional_met = (
        (not conditional["requires_both_profiles"] or both_profiles)
        and (not conditional["requires_all_p0_mini_lessons"] or p0_ids <= matched_long_ids)
        and len(short_matches) >= int(conditional["short_min_hits"])
        and len(long_matches) >= int(conditional["mini_lesson_min_hits"])
        and len(hard_failures) <= int(conditional["max_hard_quality_failures"])
        and float(conditional["min_score"]) <= score <= float(conditional["max_score"])
    )
    if hard_failures:
        status = STATUS_FAIL
    elif not pass_blockers:
        status = STATUS_PASS
    elif conditional_met:
        status = STATUS_CONDITIONAL
    else:
        status = STATUS_FAIL

    direct_fail_conditions = {str(value) for value in acceptance["direct_fail_conditions"]}
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "status": status,
        "score": score,
        "components": {
            "both_profiles_executed": round(executed_points, 2),
            "short_recall": round(short_score, 2),
            "mini_lesson_recall": round(long_score, 2),
            "boundary_and_completeness": round(boundary, 2),
            "risk_discovery_and_routing": round(risk_score, 2),
            "audit_and_reproducibility": audit_score,
        },
        "source_hash": result.source_hash,
        "source_hash_matches": source_hash_matches,
        "short_hits": len(short_matches),
        "short_total": int(acceptance["short_total"]),
        "mini_lesson_hits": len(long_matches),
        "mini_lesson_total": int(acceptance["mini_lesson_total"]),
        "qualified_boundary_hits": qualified_hits,
        "short_matches": [asdict(value) for value in short_matches],
        "mini_lesson_matches": [asdict(value) for value in long_matches],
        "manual_adjudication_required": manual_adjudication,
        "padding_findings": padding,
        "padding_excluded_hits": padding_excluded,
        "forbidden_composite_findings": composites,
        "duration_violations": durations,
        "risk_matches": [asdict(value) for value in risk_matches],
        "risk_suppressed_during_discovery": suppressed_risk_ids,
        "risk_findings": {
            key: {
                "discovered_candidate_ids": list(value.discovered_candidate_ids),
                "misrouted": list(value.misrouted),
                "missing_risk_tags": list(value.missing_risk_tags),
                "missing_evidence_cues": list(value.missing_evidence_cues),
            }
            for key, value in risks.items()
        },
        "required_p0": sorted(p0_ids),
        "matched_p0": sorted(p0_ids & matched_long_ids),
        "automatic_quality_failures": automatic_quality_failures,
        "automatic_score_failures": automatic_score_failures,
        "regressions": regression_reports,
        "hard_failures": hard_failures,
        "direct_fail_conditions_hit": sorted(set(hard_failures) & direct_fail_conditions),
        "pass_blockers": pass_blockers,
        "conditional_criteria_met": conditional_met,
        "audit": audit,
        "requested_profiles": list(requested),
        "executed_profiles": list(executed),
    }


def _markdown(value: dict[str, Any]) -> str:
    short_ids = ", ".join(item["anchor_id"] for item in value["short_matches"]) or "无"
    long_ids = ", ".join(item["anchor_id"] for item in value["mini_lesson_matches"]) or "无"
    risk_ids = ", ".join(item["anchor_id"] for item in value["risk_matches"]) or "无"
    failures = "\n".join(f"- `{item}`" for item in value["hard_failures"]) or "- 无"
    blockers = "\n".join(f"- `{item}`" for item in value["pass_blockers"]) or "- 无"
    manual = (
        "\n".join(
            f"- {item['anchor_id']} ← `{item['candidate_id']}` ({item['decision']}, "
            f"Δstart {item['start_delta_ms']} ms, Δend {item['end_delta_ms']} ms)"
            for item in value["manual_adjudication_required"]
        )
        or "- 无"
    )
    return (
        "# LiveClip dual-profile benchmark result\n\n"
        f"- Status: **{value['status']}**\n"
        f"- Score: **{value['score']} / 100**\n"
        f"- Source hash matches benchmark: {value['source_hash_matches']}\n"
        f"- Short recall: {value['short_hits']}/{value['short_total']} ({short_ids})\n"
        "- Mini-lesson recall: "
        f"{value['mini_lesson_hits']}/{value['mini_lesson_total']} ({long_ids})\n"
        f"- Risk anchors: {risk_ids}\n"
        f"- Requested Profiles: {', '.join(value['requested_profiles'])}\n"
        f"- Executed Profiles: {', '.join(value['executed_profiles'])}\n\n"
        "## Hard failures\n\n"
        f"{failures}\n\n"
        "## PASS blockers\n\n"
        f"{blockers}\n\n"
        "## Manual adjudication required (never counted as hits)\n\n"
        f"{manual}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate LiveClip dual-profile benchmark output")
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("final_validated", type=Path)
    parser.add_argument("run_manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        benchmark = _load_object(args.benchmark)
        result = DualProfileFinalResult.model_validate_json(
            args.final_validated.read_text(encoding="utf-8")
        )
        manifest = DualProfileRunManifest.model_validate_json(
            args.run_manifest.read_text(encoding="utf-8")
        )
        report = evaluate(benchmark, result, manifest)
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "benchmark-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "benchmark-report.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
