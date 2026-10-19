#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
)


@dataclass(frozen=True, slots=True)
class Match:
    anchor_id: str
    candidate_id: str
    profile: str
    start_delta_ms: int
    end_delta_ms: int
    decision: str
    match_kind: str


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _candidates(
    result: DualProfileFinalResult,
    profile: ClipProfile,
    decisions: set[CandidateDisposition],
) -> tuple[FinalProfileCandidate, ...]:
    value = result.profiles[profile]
    groups = {
        CandidateDisposition.SELECTED: value.selected,
        CandidateDisposition.MANUAL_REVIEW: value.manual_review,
        CandidateDisposition.BLOCKED: value.blocked,
        CandidateDisposition.REJECTED: value.rejected,
    }
    return tuple(item for decision in decisions for item in groups[decision])


def _match_anchor(
    anchor: dict[str, Any],
    candidates: tuple[FinalProfileCandidate, ...],
    *,
    tolerance_ms: int,
) -> Match | None:
    allowed = {str(value) for value in anchor.get("allowed_decisions", ())}
    ranked: list[tuple[int, int, FinalProfileCandidate, str]] = []
    for candidate in candidates:
        if candidate.review_status.value not in allowed:
            continue
        start_delta = abs(candidate.start_ms - int(anchor["start_ms"]))
        end_delta = abs(candidate.end_ms - int(anchor["end_ms"]))
        cue_start = int(anchor["cue_start"])
        cue_end = int(anchor["cue_end"])
        exact = (
            start_delta <= tolerance_ms
            and end_delta <= tolerance_ms
            and candidate.start_cue_id <= cue_start
            and candidate.end_cue_id >= cue_end
        )
        overlap_ms = max(
            0,
            min(candidate.end_ms, int(anchor["end_ms"]))
            - max(candidate.start_ms, int(anchor["start_ms"])),
        )
        gold_duration_ms = int(anchor["end_ms"]) - int(anchor["start_ms"])
        overlap_cues = max(
            0,
            min(candidate.end_cue_id, cue_end) - max(candidate.start_cue_id, cue_start) + 1,
        )
        gold_cues = cue_end - cue_start + 1
        semantic_edge_limit = max(tolerance_ms * 2, gold_duration_ms // 10)
        semantic_equivalent = (
            overlap_ms * 100 >= gold_duration_ms * 90
            and overlap_cues * 100 >= gold_cues * 90
            and start_delta <= semantic_edge_limit
            and end_delta <= semantic_edge_limit
        )
        if not exact and not semantic_equivalent:
            continue
        match_kind = "exact_boundary" if exact else "cue_time_semantic_equivalent"
        ranked.append((0 if exact else 1, start_delta + end_delta, candidate, match_kind))
    if not ranked:
        return None
    _, _, candidate, match_kind = min(
        ranked,
        key=lambda value: (value[0], value[1], -value[2].score, value[2].candidate_id),
    )
    return Match(
        anchor_id=str(anchor["id"]),
        candidate_id=candidate.candidate_id,
        profile=candidate.profile.value,
        start_delta_ms=candidate.start_ms - int(anchor["start_ms"]),
        end_delta_ms=candidate.end_ms - int(anchor["end_ms"]),
        decision=candidate.review_status.value,
        match_kind=match_kind,
    )


def _match_risk_anchor(
    anchor: dict[str, Any], candidates: tuple[FinalProfileCandidate, ...]
) -> Match | None:
    required_routes = {str(value) for value in anchor["required_routing"]}
    required_risks = {str(value) for value in anchor["risk_tags"]}
    ranked: list[tuple[int, FinalProfileCandidate]] = []
    for candidate in candidates:
        if candidate.review_status.value not in required_routes:
            continue
        if not required_risks <= {value.value for value in candidate.risk_tags}:
            continue
        overlap = min(candidate.end_ms, int(anchor["end_ms"])) - max(
            candidate.start_ms, int(anchor["start_ms"])
        )
        if overlap <= 0:
            continue
        if candidate.start_cue_id > int(anchor["cue_start"]) or candidate.end_cue_id < int(
            anchor["cue_end"]
        ):
            continue
        ranked.append((-overlap, candidate))
    if not ranked:
        return None
    candidate = min(ranked, key=lambda value: (value[0], value[1].candidate_id))[1]
    return Match(
        anchor_id=str(anchor["id"]),
        candidate_id=candidate.candidate_id,
        profile=candidate.profile.value,
        start_delta_ms=candidate.start_ms - int(anchor["start_ms"]),
        end_delta_ms=candidate.end_ms - int(anchor["end_ms"]),
        decision=candidate.review_status.value,
        match_kind="risk_full_cue_coverage",
    )


def evaluate(
    benchmark: dict[str, Any],
    result: DualProfileFinalResult,
    manifest: DualProfileRunManifest,
) -> dict[str, Any]:
    manifest.validate_against(result)
    required_profiles = tuple(benchmark["required_behavior"]["requested_profiles"])
    executed = tuple(value.value for value in result.executed_profiles)
    requested = tuple(value.value for value in result.requested_profiles)
    both_profiles = requested == required_profiles and set(executed) == set(required_profiles)
    short_candidates = _candidates(
        result,
        ClipProfile.SHORT_HIGHLIGHT,
        {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW},
    )
    long_candidates = _candidates(
        result,
        ClipProfile.MINI_LESSON,
        {CandidateDisposition.SELECTED, CandidateDisposition.MANUAL_REVIEW},
    )
    short_tolerance = int(benchmark["matching"]["short_boundary_tolerance_ms"])
    long_tolerance = int(benchmark["matching"]["long_boundary_tolerance_ms"])
    short_matches = tuple(
        match
        for anchor in benchmark["gold_short"]
        if (match := _match_anchor(anchor, short_candidates, tolerance_ms=short_tolerance))
        is not None
    )
    long_matches = tuple(
        match
        for anchor in benchmark["gold_mini_lesson"]
        if (match := _match_anchor(anchor, long_candidates, tolerance_ms=long_tolerance))
        is not None
    )
    all_mini = _candidates(
        result,
        ClipProfile.MINI_LESSON,
        {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
            CandidateDisposition.BLOCKED,
        },
    )
    risk_matches = tuple(
        match
        for anchor in benchmark["risk_anchors"]
        if (match := _match_risk_anchor(anchor, all_mini)) is not None
    )
    selected = tuple(value for profile in result.profiles.values() for value in profile.selected)
    forbidden_quality = set(benchmark["automatic_selection_gates"]["forbidden_quality_flags"])
    automatic_quality_failures = [
        value.candidate_id
        for value in selected
        if set(flag.value for flag in value.quality_flags) & forbidden_quality
    ]
    rgr02 = next(value for value in benchmark["regressions"] if value["id"] == "RGR-02")
    rgr02_auto = [
        value.candidate_id
        for value in selected
        if abs(value.start_ms - int(rgr02["start_ms"])) <= short_tolerance
        and abs(value.end_ms - int(rgr02["end_ms"])) <= short_tolerance
    ]
    matched_long_ids = {value.anchor_id for value in long_matches}
    matched_risk_ids = {value.anchor_id for value in risk_matches}
    p0_ids = set(benchmark["acceptance"]["required_p0_mini_lesson_ids"])
    required_risk_ids = set(benchmark["acceptance"]["required_risk_anchor_ids"])
    short_score = 20 * len(short_matches) / int(benchmark["acceptance"]["short_total"])
    long_score = 30 * len(long_matches) / int(benchmark["acceptance"]["mini_lesson_total"])
    total_gold = int(benchmark["acceptance"]["short_total"]) + int(
        benchmark["acceptance"]["mini_lesson_total"]
    )
    boundary_score = 15 * (len(short_matches) + len(long_matches)) / total_gold
    risk_score = 10 * len(risk_matches) / len(benchmark["risk_anchors"])
    audit_score = 10.0
    score = round(
        (15 if both_profiles else 0)
        + short_score
        + long_score
        + boundary_score
        + risk_score
        + audit_score,
        2,
    )
    hard_failures: list[str] = []
    acceptance = benchmark["acceptance"]
    if not both_profiles:
        hard_failures.append("missing_executed_profile")
    if len(short_matches) < int(acceptance["short_min_hits"]):
        hard_failures.append("short_recall_below_threshold")
    if len(long_matches) < int(acceptance["mini_lesson_min_hits"]):
        hard_failures.append("mini_lesson_recall_below_threshold")
    if not p0_ids <= matched_long_ids:
        hard_failures.append("missing_any_p0_mini_lesson")
    if not required_risk_ids <= matched_risk_ids:
        hard_failures.append("risk_suppressed_or_misrouted")
    if automatic_quality_failures:
        hard_failures.append("automatic_hard_quality_failure")
    if rgr02_auto:
        hard_failures.append("RGR-02_auto_selected")
    if score < float(acceptance["pass_min_score"]):
        hard_failures.append("score_below_pass_threshold")
    status = "PASS" if not hard_failures else "FAIL"
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "status": status,
        "score": score,
        "components": {
            "both_profiles_executed": 15 if both_profiles else 0,
            "short_recall": round(short_score, 2),
            "mini_lesson_recall": round(long_score, 2),
            "boundary_and_completeness": round(boundary_score, 2),
            "risk_discovery_and_routing": round(risk_score, 2),
            "audit_and_reproducibility": audit_score,
        },
        "short_hits": len(short_matches),
        "short_total": int(acceptance["short_total"]),
        "mini_lesson_hits": len(long_matches),
        "mini_lesson_total": int(acceptance["mini_lesson_total"]),
        "short_matches": [asdict(value) for value in short_matches],
        "mini_lesson_matches": [asdict(value) for value in long_matches],
        "risk_matches": [asdict(value) for value in risk_matches],
        "required_p0": sorted(p0_ids),
        "matched_p0": sorted(p0_ids & matched_long_ids),
        "automatic_quality_failures": automatic_quality_failures,
        "rgr02_auto_selected": rgr02_auto,
        "hard_failures": hard_failures,
        "requested_profiles": list(requested),
        "executed_profiles": list(executed),
    }


def _markdown(value: dict[str, Any]) -> str:
    short_ids = ", ".join(item["anchor_id"] for item in value["short_matches"]) or "无"
    long_ids = ", ".join(item["anchor_id"] for item in value["mini_lesson_matches"]) or "无"
    risk_ids = ", ".join(item["anchor_id"] for item in value["risk_matches"]) or "无"
    failures = "\n".join(f"- `{item}`" for item in value["hard_failures"]) or "- 无"
    return (
        "# LiveClip dual-profile benchmark result\n\n"
        f"- Status: **{value['status']}**\n"
        f"- Score: **{value['score']} / 100**\n"
        f"- Short recall: {value['short_hits']}/{value['short_total']} ({short_ids})\n"
        "- Mini-lesson recall: "
        f"{value['mini_lesson_hits']}/{value['mini_lesson_total']} ({long_ids})\n"
        f"- Risk anchors: {risk_ids}\n"
        f"- Requested Profiles: {', '.join(value['requested_profiles'])}\n"
        f"- Executed Profiles: {', '.join(value['executed_profiles'])}\n\n"
        "## Hard failures\n\n"
        f"{failures}\n"
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
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
