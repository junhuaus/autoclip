#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from liveclip.agent_runtime.models import AgentArtifact, AgentRunResult


@dataclass(frozen=True, slots=True)
class AgentMatch:
    anchor_id: str
    candidate_id: str
    profile: str
    start_delta_ms: int
    end_delta_ms: int
    match_kind: str


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _required_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Agent candidate {key} must be an integer")
    return value


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Agent candidate {key} must be a non-empty string")
    return value


def _candidates(result: AgentRunResult, profile: str) -> tuple[AgentArtifact, ...]:
    return tuple(
        artifact
        for artifact in result.artifacts
        if artifact.artifact_type == "clip_candidate" and artifact.data.get("profile") == profile
    )


def _match_anchor(
    anchor: dict[str, Any],
    candidates: tuple[AgentArtifact, ...],
    *,
    tolerance_ms: int,
) -> AgentMatch | None:
    ranked: list[tuple[int, int, int, str, AgentArtifact]] = []
    for candidate in candidates:
        data = candidate.data
        start_ms = _required_int(data, "start_ms")
        end_ms = _required_int(data, "end_ms")
        start_cue = _required_int(data, "start_cue_id")
        end_cue = _required_int(data, "end_cue_id")
        start_delta = abs(start_ms - int(anchor["start_ms"]))
        end_delta = abs(end_ms - int(anchor["end_ms"]))
        cue_start = int(anchor["cue_start"])
        cue_end = int(anchor["cue_end"])
        exact = (
            start_delta <= tolerance_ms
            and end_delta <= tolerance_ms
            and start_cue <= cue_start
            and end_cue >= cue_end
        )
        overlap_ms = max(
            0,
            min(end_ms, int(anchor["end_ms"])) - max(start_ms, int(anchor["start_ms"])),
        )
        gold_duration_ms = int(anchor["end_ms"]) - int(anchor["start_ms"])
        overlap_cues = max(0, min(end_cue, cue_end) - max(start_cue, cue_start) + 1)
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
        score = _required_int(data, "score")
        ranked.append(
            (
                0 if exact else 1,
                start_delta + end_delta,
                -score,
                candidate.artifact_id,
                candidate,
            )
        )
    if not ranked:
        return None
    match_rank, _, _, _, candidate = min(ranked)
    data = candidate.data
    start_ms = _required_int(data, "start_ms")
    end_ms = _required_int(data, "end_ms")
    return AgentMatch(
        anchor_id=str(anchor["id"]),
        candidate_id=candidate.artifact_id,
        profile=_required_str(data, "profile"),
        start_delta_ms=start_ms - int(anchor["start_ms"]),
        end_delta_ms=end_ms - int(anchor["end_ms"]),
        match_kind=("exact_boundary" if match_rank == 0 else "cue_time_semantic_equivalent"),
    )


def _match_topic_anchor(
    anchor: dict[str, Any], candidates: tuple[AgentArtifact, ...]
) -> AgentMatch | None:
    ranked: list[tuple[int, str, AgentArtifact]] = []
    for candidate in candidates:
        data = candidate.data
        start_ms = _required_int(data, "start_ms")
        end_ms = _required_int(data, "end_ms")
        start_cue = _required_int(data, "start_cue_id")
        end_cue = _required_int(data, "end_cue_id")
        overlap = min(end_ms, int(anchor["end_ms"])) - max(start_ms, int(anchor["start_ms"]))
        if overlap <= 0 or start_cue > int(anchor["cue_start"]) or end_cue < int(anchor["cue_end"]):
            continue
        ranked.append((-overlap, candidate.artifact_id, candidate))
    if not ranked:
        return None
    _, _, candidate = min(ranked)
    data = candidate.data
    return AgentMatch(
        anchor_id=str(anchor["id"]),
        candidate_id=candidate.artifact_id,
        profile=_required_str(data, "profile"),
        start_delta_ms=_required_int(data, "start_ms") - int(anchor["start_ms"]),
        end_delta_ms=_required_int(data, "end_ms") - int(anchor["end_ms"]),
        match_kind="ordinary_topic_full_cue_coverage",
    )


def _audit(result: AgentRunResult) -> dict[str, object]:
    final_candidates = {
        value.artifact_id for value in result.artifacts if value.artifact_type == "clip_candidate"
    }
    title_candidates = {
        str(value.data.get("source_candidate_id"))
        for value in result.artifacts
        if value.artifact_type == "title_options"
    }
    raw_candidates: set[str] = set()
    validated: set[str] = set()
    for event in result.events:
        if event.action.action != "call_tool" or event.observation is None:
            continue
        arguments = event.action.parsed_arguments()
        if event.action.tool == "save_clip_candidate" and event.observation.status == "ok":
            artifact = event.observation.data.get("artifact")
            if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact_id"), str):
                raise ValueError("successful candidate event lacks its raw Artifact")
            raw_candidates.add(str(artifact["artifact_id"]))
        elif event.action.tool == "validate_clip_artifact" and event.observation.status == "ok":
            artifact_id = arguments.get("artifact_id")
            if isinstance(artifact_id, str):
                validated.add(artifact_id)
    global_reviews = [value for value in result.artifacts if value.artifact_type == "global_review"]
    review_error: str | None = None
    reviewed_candidates: set[str] = set()
    reviewed_final: set[str] = set()
    if len(global_reviews) != 1:
        review_error = "final result must contain exactly one Global Review Artifact"
    else:
        raw_reviews = global_reviews[0].data.get("reviews")
        raw_final = global_reviews[0].data.get("final_candidate_ids")
        if not isinstance(raw_reviews, list) or not isinstance(raw_final, list):
            review_error = "Global Review Artifact data is malformed"
        else:
            reviewed_candidates = {
                str(value.get("candidate_artifact_id"))
                for value in raw_reviews
                if isinstance(value, dict) and isinstance(value.get("candidate_artifact_id"), str)
            }
            reviewed_final = {str(value) for value in raw_final if isinstance(value, str)}
            if reviewed_candidates != raw_candidates or reviewed_final != final_candidates:
                review_error = "Global Review does not conserve raw and final candidate arrays"
    missing_raw = sorted(final_candidates - raw_candidates)
    missing_validation = sorted(final_candidates - validated)
    missing_titles = sorted(final_candidates - title_candidates)
    return {
        "raw_candidate_count": len(raw_candidates),
        "final_candidate_count": len(final_candidates),
        "superseded_candidate_count": len(raw_candidates - final_candidates),
        "missing_raw_trace": missing_raw,
        "missing_validation": missing_validation,
        "missing_titles": missing_titles,
        "global_review_error": review_error,
        "consistent": not (
            missing_raw or missing_validation or missing_titles or review_error is not None
        ),
    }


def evaluate_agent(benchmark: dict[str, Any], result: AgentRunResult) -> dict[str, Any]:
    source = result.initial_context.get("source")
    if (
        not isinstance(source, dict)
        or source.get("transcript_sha256") != benchmark["source"]["sha256"]
    ):
        raise ValueError("Agent result source hash differs from benchmark")
    short = _candidates(result, "short_highlight")
    long = _candidates(result, "mini_lesson")
    executed = sorted(
        profile for profile, values in (("short_highlight", short), ("mini_lesson", long)) if values
    )
    required_profiles = tuple(benchmark["required_behavior"]["requested_profiles"])
    both_profiles = set(executed) == set(required_profiles)
    short_tolerance = int(benchmark["matching"]["short_boundary_tolerance_ms"])
    long_tolerance = int(benchmark["matching"]["long_boundary_tolerance_ms"])
    short_matches = tuple(
        match
        for anchor in benchmark["gold_short"]
        if (match := _match_anchor(anchor, short, tolerance_ms=short_tolerance)) is not None
    )
    long_matches = tuple(
        match
        for anchor in benchmark["gold_mini_lesson"]
        if (match := _match_anchor(anchor, long, tolerance_ms=long_tolerance)) is not None
    )
    topic_matches = tuple(
        match
        for anchor in benchmark["risk_anchors"]
        if (match := _match_topic_anchor(anchor, long)) is not None
    )
    audit = _audit(result)
    acceptance = benchmark["acceptance"]
    matched_long_ids = {value.anchor_id for value in long_matches}
    p0_ids = set(acceptance["required_p0_mini_lesson_ids"])
    required_topic_ids = set(acceptance["required_risk_anchor_ids"])
    matched_topic_ids = {value.anchor_id for value in topic_matches}
    short_score = 20 * len(short_matches) / int(acceptance["short_total"])
    long_score = 30 * len(long_matches) / int(acceptance["mini_lesson_total"])
    total_gold = int(acceptance["short_total"]) + int(acceptance["mini_lesson_total"])
    boundary_score = 15 * (len(short_matches) + len(long_matches)) / total_gold
    topic_score = 10 * len(topic_matches) / len(benchmark["risk_anchors"])
    audit_score = 10.0 if audit["consistent"] else 0.0
    score = round(
        (15 if both_profiles else 0)
        + short_score
        + long_score
        + boundary_score
        + topic_score
        + audit_score,
        2,
    )
    hard_failures: list[str] = []
    if not both_profiles:
        hard_failures.append("missing_executed_profile")
    if len(short_matches) < int(acceptance["short_min_hits"]):
        hard_failures.append("short_recall_below_threshold")
    if len(long_matches) < int(acceptance["mini_lesson_min_hits"]):
        hard_failures.append("mini_lesson_recall_below_threshold")
    if not p0_ids <= matched_long_ids:
        hard_failures.append("missing_any_p0_mini_lesson")
    if not required_topic_ids <= matched_topic_ids:
        hard_failures.append("required_topic_anchor_not_discovered")
    if not audit["consistent"]:
        hard_failures.append("untraceable_or_inconsistent_audit")
    if score < float(acceptance["pass_min_score"]):
        hard_failures.append("score_below_pass_threshold")
    rgr02 = next(value for value in benchmark["regressions"] if value["id"] == "RGR-02")
    rgr02_candidates = [
        {
            "candidate_id": value.artifact_id,
            "score": _required_int(value.data, "score"),
            "start_ms": _required_int(value.data, "start_ms"),
            "end_ms": _required_int(value.data, "end_ms"),
        }
        for value in short
        if abs(_required_int(value.data, "start_ms") - int(rgr02["start_ms"])) <= short_tolerance
    ]
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "contract_mode": "agent_v2_score_only_no_risk_routing",
        "status": "PASS" if not hard_failures else "FAIL",
        "score": score,
        "components": {
            "both_profiles_executed": 15 if both_profiles else 0,
            "short_recall": round(short_score, 2),
            "mini_lesson_recall": round(long_score, 2),
            "boundary_and_completeness": round(boundary_score, 2),
            "ordinary_topic_coverage": round(topic_score, 2),
            "audit_and_reproducibility": audit_score,
        },
        "short_hits": len(short_matches),
        "short_total": int(acceptance["short_total"]),
        "mini_lesson_hits": len(long_matches),
        "mini_lesson_total": int(acceptance["mini_lesson_total"]),
        "short_matches": [asdict(value) for value in short_matches],
        "mini_lesson_matches": [asdict(value) for value in long_matches],
        "ordinary_topic_matches": [asdict(value) for value in topic_matches],
        "required_p0": sorted(p0_ids),
        "matched_p0": sorted(p0_ids & matched_long_ids),
        "rgr02_scored_candidates": rgr02_candidates,
        "hard_failures": hard_failures,
        "requested_profiles": list(required_profiles),
        "executed_profiles": executed,
        "audit": audit,
        "legacy_v1_contract_changes": [
            "Agent v2 has scores but no automatic selected/manual/blocked/rejected decision",
            "legacy risk anchors are evaluated only as ordinary topic discovery",
        ],
        "provider": result.provider,
        "model": result.model,
        "skill_sha256": result.skill_sha256,
    }


def _markdown(value: dict[str, Any]) -> str:
    short_ids = ", ".join(item["anchor_id"] for item in value["short_matches"]) or "无"
    long_ids = ", ".join(item["anchor_id"] for item in value["mini_lesson_matches"]) or "无"
    topic_ids = ", ".join(item["anchor_id"] for item in value["ordinary_topic_matches"]) or "无"
    failures = "\n".join(f"- `{item}`" for item in value["hard_failures"]) or "- 无"
    return (
        "# LiveClip Agent v2 benchmark result\n\n"
        f"- Contract: `{value['contract_mode']}`\n"
        f"- Status: **{value['status']}**\n"
        f"- Score: **{value['score']} / 100**\n"
        f"- Short recall: {value['short_hits']}/{value['short_total']} ({short_ids})\n"
        "- Mini-lesson recall: "
        f"{value['mini_lesson_hits']}/{value['mini_lesson_total']} ({long_ids})\n"
        f"- Ordinary topic anchors (legacy risk anchors): {topic_ids}\n"
        f"- Executed Profiles: {', '.join(value['executed_profiles'])}\n\n"
        "Agent v2 intentionally has no automatic approval or content-risk routing. "
        "Those legacy v1 fields are not fabricated; the two old risk anchors are "
        "measured only as ordinary topic discovery.\n\n"
        "## Hard failures\n\n"
        f"{failures}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a score-only Agent v2 run")
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("agent_run_result", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        benchmark = _load_object(args.benchmark)
        result = AgentRunResult.model_validate_json(
            args.agent_run_result.read_text(encoding="utf-8")
        )
        report = evaluate_agent(benchmark, result)
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
