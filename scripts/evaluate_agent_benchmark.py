#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from liveclip.agent_runtime.models import AgentArtifact, AgentRunResult

# The shared evaluation-only gates live beside this script.  Resolve them the same
# way whether this file runs directly or is imported as ``scripts.evaluate_agent_benchmark``.
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

__all__ = [
    "STATUS_INVALID_EVIDENCE",
    "STATUS_TECHNICAL_FAIL",
    "STATUS_TECHNICAL_PASS_HUMAN_PENDING",
    "Match",
    "evaluate_agent",
    "technical_status",
]

# docs/requirements/liveclip-agent-runtime-v2-acceptance.md: the only
# checkpoint-level technical statuses.  A plain benchmark PASS is never emitted.
STATUS_TECHNICAL_PASS_HUMAN_PENDING = "TECHNICAL_PASS_HUMAN_PENDING"
STATUS_TECHNICAL_FAIL = "TECHNICAL_FAIL"
STATUS_INVALID_EVIDENCE = "INVALID_EVIDENCE"
CONTRACT_MODE = "agent_v2_technical_provisional"
# Agent v2 has no selected/manual_review/blocked/rejected buckets.  Every saved
# clip candidate retained in the result is a Global Review ``final`` candidate.
AGENT_FINAL_DECISION = "final"
# Human-only acceptance activities that no mechanical evaluator can close.
HUMAN_REQUIRED_ACTIVITIES = (
    "semantic_and_editorial_review",
    "audio_quality_listening",
    "audio_grounded_subtitle_calibration",
    "title_hook_summary_source_faithfulness",
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _required_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Agent candidate {key} must be an integer")
    return value


def _required_str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Agent candidate {key} must be a non-empty string")
    return value


def _evidence_cues(artifact: AgentArtifact) -> frozenset[int] | None:
    cues: set[int] = set()
    recorded = False
    for item in artifact.evidence:
        values = item.get("cue_ids")
        if values is None:
            continue
        if not isinstance(values, list) or not all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            raise ValueError("Agent candidate evidence cue_ids must be integers")
        recorded = True
        cues.update(values)
    return frozenset(cues) if recorded else None


def _view(artifact: AgentArtifact) -> CandidateView:
    data = artifact.data
    return CandidateView(
        candidate_id=artifact.artifact_id,
        profile=_required_str(data, "profile"),
        decision=AGENT_FINAL_DECISION,
        start_ms=_required_int(data, "start_ms"),
        end_ms=_required_int(data, "end_ms"),
        start_cue_id=_required_int(data, "start_cue_id"),
        end_cue_id=_required_int(data, "end_cue_id"),
        score=float(_required_int(data, "score")),
        # Agent v2 records neither quality flags nor risk tags.
        quality_flags=None,
        risk_tags=None,
        evidence_cue_ids=_evidence_cues(artifact),
    )


def _global_review(result: AgentRunResult) -> AgentArtifact | None:
    reviews = [value for value in result.artifacts if value.artifact_type == "global_review"]
    return reviews[0] if len(reviews) == 1 else None


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _explicit_executed_profiles(result: AgentRunResult) -> list[str] | None:
    """Return an explicit executed-Profile record; candidates are never proof of execution."""

    review = _global_review(result)
    for record in (review.data if review is not None else {}, result.initial_context):
        if "executed_profiles" in record:
            values = _string_list(record["executed_profiles"])
            if values is None:
                raise ValueError("executed_profiles record must be a list of strings")
            return values
    return None


def _audit(result: AgentRunResult, views: tuple[CandidateView, ...]) -> dict[str, Any]:
    """Audit and reproducibility: five items x 2 points (MD section 10).

    Agent v2 field mapping (an empty or missing item scores 0):

    1. ``profile_counts``: exactly one Global Review exists; its
       ``final_candidate_ids`` equal the result's ``clip_candidate`` artifacts;
       per-Profile counts recomputed from those artifacts cover every Global
       Review ``requested_profiles`` entry and no other Profile.
    2. ``candidate_dispositions``: at least one successful ``save_clip_candidate``
       event exists; Global Review ``reviews`` rows equal those raw IDs exactly
       once each; every final candidate has a raw save event, a successful
       ``validate_clip_artifact`` event and a ``title_options`` artifact.
    3. ``version_hash``: ``run_identity_sha256``, ``skill_version``,
       ``skill_sha256``, ``provider``, ``model`` and
       ``initial_context.source.transcript_sha256`` are present.
    4. ``call_data``: events exist; every event's ``model_metadata`` carries a
       non-empty ``prompt_sha256`` and a non-empty ``call_records`` list; at least
       one token-usage record exists (``call_records[].usage_json`` or
       ``session_usage``/``final_session_usage``).
    5. ``cache_repair_records``: ``AgentRunResult`` has no cache-hit or repair
       counter field, so this item is missing and always scores 0.
    """

    final_candidates = {value.candidate_id for value in views}
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
    review = _global_review(result)
    review_error: str | None = None
    reviewed_rows: list[str] = []
    reviewed_final: set[str] = set()
    requested: list[str] = []
    if review is None:
        review_error = "final result must contain exactly one Global Review Artifact"
    else:
        raw_reviews = review.data.get("reviews")
        raw_final = _string_list(review.data.get("final_candidate_ids"))
        raw_requested = _string_list(review.data.get("requested_profiles"))
        if not isinstance(raw_reviews, list) or raw_final is None or raw_requested is None:
            review_error = "Global Review Artifact data is malformed"
        else:
            reviewed_rows = [
                str(value.get("candidate_artifact_id"))
                for value in raw_reviews
                if isinstance(value, dict) and isinstance(value.get("candidate_artifact_id"), str)
            ]
            reviewed_final = set(raw_final)
            requested = raw_requested
            if set(reviewed_rows) != raw_candidates or reviewed_final != final_candidates:
                review_error = "Global Review does not conserve raw and final candidate arrays"
    profile_counts = Counter(value.profile for value in views)
    missing_raw = sorted(final_candidates - raw_candidates)
    missing_validation = sorted(final_candidates - validated)
    missing_titles = sorted(final_candidates - title_candidates)
    items: dict[str, bool] = {}
    items["profile_counts"] = (
        review_error is None
        and bool(requested)
        and set(profile_counts) == set(requested)
        and all(profile_counts[profile] > 0 for profile in requested)
    )
    items["candidate_dispositions"] = (
        review_error is None
        and bool(raw_candidates)
        and len(reviewed_rows) == len(set(reviewed_rows))
        and not missing_raw
        and not missing_validation
        and not missing_titles
    )
    source = result.initial_context.get("source")
    items["version_hash"] = bool(
        result.run_identity_sha256
        and result.skill_version
        and result.skill_sha256
        and result.provider
        and result.model
        and isinstance(source, dict)
        and source.get("transcript_sha256")
    )
    token_records = 0
    call_metadata_complete = bool(result.events)
    for event in result.events:
        metadata = event.model_metadata
        records = metadata.get("call_records")
        if not metadata.get("prompt_sha256") or not isinstance(records, list) or not records:
            call_metadata_complete = False
            continue
        token_records += sum(
            1 for record in records if isinstance(record, dict) and record.get("usage_json")
        )
        token_records += sum(
            1
            for key in ("session_usage", "final_session_usage")
            if isinstance(metadata.get(key), dict) and metadata.get(key)
        )
    items["call_data"] = call_metadata_complete and token_records > 0
    items["cache_repair_records"] = False
    return {
        "items": items,
        "score": 2.0 * sum(1 for value in items.values() if value),
        "raw_candidate_count": len(raw_candidates),
        "final_candidate_count": len(final_candidates),
        "superseded_candidate_count": len(raw_candidates - final_candidates),
        "final_profile_counts": dict(sorted(profile_counts.items())),
        "requested_profiles": requested,
        "missing_raw_trace": missing_raw,
        "missing_validation": missing_validation,
        "missing_titles": missing_titles,
        "global_review_error": review_error,
        "consistent": items["profile_counts"] and items["candidate_dispositions"],
    }


def technical_status(
    *,
    invalid_evidence: list[str],
    hard_failures: list[str],
    not_evaluable: list[dict[str, object]],
) -> str:
    """Invalid evidence dominates; any failure or not-evaluable gate blocks the pass."""

    if invalid_evidence:
        return STATUS_INVALID_EVIDENCE
    if hard_failures or not_evaluable:
        return STATUS_TECHNICAL_FAIL
    return STATUS_TECHNICAL_PASS_HUMAN_PENDING


def _invalid_report(
    benchmark: dict[str, Any], result: AgentRunResult, reasons: list[str]
) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "contract_mode": CONTRACT_MODE,
        "status": technical_status(invalid_evidence=reasons, hard_failures=[], not_evaluable=[]),
        "invalid_evidence": reasons,
        "hard_failures": [],
        "not_evaluable": [],
        "human_required": list(HUMAN_REQUIRED_ACTIVITIES),
        "provider": result.provider,
        "model": result.model,
        "skill_sha256": result.skill_sha256,
    }


def evaluate_agent(benchmark: dict[str, Any], result: AgentRunResult) -> dict[str, Any]:
    source = result.initial_context.get("source")
    source_hash = source.get("transcript_sha256") if isinstance(source, dict) else None
    if source_hash != benchmark["source"]["sha256"]:
        return _invalid_report(benchmark, result, ["source_hash_mismatch"])
    try:
        views = tuple(
            _view(artifact)
            for artifact in result.artifacts
            if artifact.artifact_type == "clip_candidate"
        )
        audit = _audit(result, views)
        executed_record = _explicit_executed_profiles(result)
    except ValueError as exc:
        return _invalid_report(benchmark, result, [f"malformed_evidence: {exc}"])

    acceptance = benchmark["acceptance"]
    gates = benchmark["automatic_selection_gates"]
    hard_failures: list[str] = []
    not_evaluable: list[dict[str, object]] = []

    def unevaluable(gate: str, category: str, reason: str, **extra: object) -> None:
        not_evaluable.append({"gate": gate, "category": category, "reason": reason, **extra})

    required_profiles = tuple(benchmark["required_behavior"]["requested_profiles"])
    requested = list(audit["requested_profiles"])
    executed: list[str] = []
    both_profiles = False
    if executed_record is None:
        unevaluable(
            "executed_profiles",
            "missing_record",
            "the Agent v2 result has no explicit executed-Profile record; "
            "saved candidates are not proof that a Profile was executed",
        )
    else:
        executed = executed_record
        both_profiles = set(requested) == set(required_profiles) and set(executed) == set(
            required_profiles
        )
        if not both_profiles:
            hard_failures.append("missing_executed_profile")

    unevaluable(
        "match_decision_buckets",
        "legacy_v1_decision_concept",
        "Agent v2 has no selected/manual_review buckets, so matching.match_decisions and "
        "anchor allowed_decisions cannot be checked; every final candidate is matched",
    )
    matchings = {
        profile: match_profile(benchmark, profile, views, decision_allowed=lambda *_: True)
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

    durations = duration_violations(benchmark, views)
    if durations:
        hard_failures.append("duration_out_of_profile_bounds")

    # Every final candidate is a delivered output whose Global Review row asserted
    # complete boundaries and no irrelevant padding, so content gates apply to it.
    padding = [
        entry
        for candidate in views
        for entry in padding_overlaps(
            benchmark,
            candidate,
            allowed=allowed_intervals.get(candidate.candidate_id),
            tolerance=tolerance_ms(benchmark, candidate.profile),
        )
    ]
    padded_ids = {str(value["candidate_id"]) for value in padding}
    if padding:
        hard_failures.append("irrelevant_padding")
    composites = [
        entry for candidate in views for entry in composite_overlaps(benchmark, candidate)
    ]
    if composites:
        hard_failures.append("forbidden_composite_interval")

    regression_reports: list[dict[str, Any]] = []
    for regression in auto_decision_regressions(benchmark):
        tolerance = regression_tolerance(benchmark, regression)
        # A final candidate opening at the regression start was accepted with a
        # declared complete opening, which the regression forbids.
        auto = regression_start_hits(regression, views, tolerance)
        if auto:
            hard_failures.append(f"{regression['id']}_auto_selected")
        interval_hits = regression_interval_hits(regression, views, tolerance)
        if interval_hits and regression.get("required_quality_flags"):
            unevaluable(
                f"{regression['id']}_required_quality_flags",
                "missing_record",
                "Agent v2 candidates record no quality flags",
                candidate_ids=[value.candidate_id for value in interval_hits],
            )
        regression_reports.append(
            {
                "regression_id": str(regression["id"]),
                "auto_selected": [value.candidate_id for value in auto],
                "interval_candidates": [value.candidate_id for value in interval_hits],
            }
        )

    score_threshold = float(gates["score_strictly_greater_than"])
    unevaluable(
        "automatic_selection_score_gate",
        "legacy_v1_decision_concept",
        "Agent v2 has no automatic-selection decision to which score_strictly_greater_than applies",
        final_candidates_not_above_threshold=sorted(
            value.candidate_id for value in views if not value.score > score_threshold
        ),
    )
    unevaluable(
        "forbidden_quality_flags",
        "missing_record",
        "Agent v2 candidates record no quality flags; forbidden flags cannot be checked for "
        "automatic selection or boundary qualification",
    )

    risks = {
        str(anchor["id"]): assess_risk_anchor(anchor, views, routing_evaluable=False)
        for anchor in benchmark["risk_anchors"]
    }
    unevaluable(
        "risk_routing",
        "legacy_v1_decision_concept",
        "Agent v2 has no manual_review/blocked routing and no risk tags",
        anchor_ids=sorted(risks),
    )
    risk_matches = tuple(value.match for value in risks.values() if value.match is not None)
    required_risk_ids = {str(value) for value in acceptance["required_risk_anchor_ids"]}
    suppressed_risk_ids = sorted(
        key
        for key in required_risk_ids
        if key not in risks or not risks[key].discovered_candidate_ids
    )
    if suppressed_risk_ids:
        hard_failures.append("risk_suppressed_during_discovery")
    if not required_risk_ids <= {value.anchor_id for value in risk_matches}:
        hard_failures.append("risk_discovery_without_evidence_cues")

    if not audit["consistent"]:
        hard_failures.append("untraceable_or_inconsistent_audit")
    matched_long_ids = {value.anchor_id for value in long_matches}
    p0_ids = {str(value) for value in acceptance["required_p0_mini_lesson_ids"]}
    if not p0_ids <= matched_long_ids:
        hard_failures.append("missing_any_p0_mini_lesson")
    if len(short_matches) < int(acceptance["short_min_hits"]):
        hard_failures.append("short_recall_below_threshold")
    if len(long_matches) < int(acceptance["mini_lesson_min_hits"]):
        hard_failures.append("mini_lesson_recall_below_threshold")

    # Components that cannot be proven mechanically score 0 (never fabricated).
    points = benchmark["scoring"]["components"]
    executed_points = (
        float(points["both_profiles_executed"])
        * len(set(executed) & set(required_profiles))
        / len(required_profiles)
    )
    short_score = (
        float(points["short_recall"]) * len(short_matches) / int(acceptance["short_total"])
    )
    long_score = (
        float(points["mini_lesson_recall"])
        * len(long_matches)
        / int(acceptance["mini_lesson_total"])
    )

    def qualified(match: Match) -> bool:
        # Quality flags are not evaluable (listed above); exactness and padding are.
        return match.match_kind == "exact_boundary" and match.candidate_id not in padded_ids

    boundary, qualified_hits = boundary_score(
        float(points["boundary_and_completeness"]),
        (*short_matches, *long_matches),
        qualified=qualified,
    )
    audit_score = float(audit["score"])
    score = round(executed_points + short_score + long_score + boundary + audit_score, 2)
    if score < float(acceptance["pass_min_score"]):
        hard_failures.append("score_below_pass_threshold")

    status = technical_status(
        invalid_evidence=[], hard_failures=hard_failures, not_evaluable=not_evaluable
    )
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "contract_mode": CONTRACT_MODE,
        "status": status,
        "score": score,
        "components": {
            "both_profiles_executed": round(executed_points, 2),
            "short_recall": round(short_score, 2),
            "mini_lesson_recall": round(long_score, 2),
            "boundary_and_completeness": round(boundary, 2),
            "risk_discovery_and_routing": 0.0,
            "audit_and_reproducibility": audit_score,
        },
        "unscored_components": ["risk_discovery_and_routing"],
        "invalid_evidence": [],
        "short_hits": len(short_matches),
        "short_total": int(acceptance["short_total"]),
        "mini_lesson_hits": len(long_matches),
        "mini_lesson_total": int(acceptance["mini_lesson_total"]),
        "qualified_boundary_hits": qualified_hits,
        "short_matches": [asdict(value) for value in short_matches],
        "mini_lesson_matches": [asdict(value) for value in long_matches],
        "manual_adjudication_required": manual_adjudication,
        "padding_findings": padding,
        "forbidden_composite_findings": composites,
        "duration_violations": durations,
        "risk_discovery_matches": [asdict(value) for value in risk_matches],
        "risk_suppressed_during_discovery": suppressed_risk_ids,
        "risk_findings": {
            key: {
                "discovered_candidate_ids": list(value.discovered_candidate_ids),
                "missing_evidence_cues": list(value.missing_evidence_cues),
            }
            for key, value in risks.items()
        },
        "required_p0": sorted(p0_ids),
        "matched_p0": sorted(p0_ids & matched_long_ids),
        "regressions": regression_reports,
        "hard_failures": hard_failures,
        "not_evaluable": not_evaluable,
        "human_required": list(HUMAN_REQUIRED_ACTIVITIES),
        "requested_profiles": requested,
        "executed_profiles": executed,
        "executed_profiles_recorded": executed_record is not None,
        "audit": audit,
        "provider": result.provider,
        "model": result.model,
        "skill_sha256": result.skill_sha256,
    }


def _markdown(value: dict[str, Any]) -> str:
    def bullet(items: list[str]) -> str:
        return "\n".join(f"- `{item}`" for item in items) or "- 无"

    lines = [
        "# LiveClip Agent v2 technical/provisional benchmark result\n",
        f"- Contract: `{value['contract_mode']}`",
        f"- Status: **{value['status']}**",
    ]
    if value["status"] == STATUS_INVALID_EVIDENCE:
        lines += ["", "## Invalid evidence", "", bullet(list(value["invalid_evidence"]))]
        return "\n".join(lines) + "\n"
    short_ids = ", ".join(item["anchor_id"] for item in value["short_matches"]) or "无"
    long_ids = ", ".join(item["anchor_id"] for item in value["mini_lesson_matches"]) or "无"
    risk_ids = ", ".join(item["anchor_id"] for item in value["risk_discovery_matches"]) or "无"
    executed = ", ".join(value["executed_profiles"]) or "not recorded"
    lines += [
        f"- Mechanical score: **{value['score']} / 100** (unproven components score 0)",
        f"- Short recall: {value['short_hits']}/{value['short_total']} ({short_ids})",
        "- Mini-lesson recall: "
        f"{value['mini_lesson_hits']}/{value['mini_lesson_total']} ({long_ids})",
        f"- Risk anchors discovered with evidence (routing not evaluable): {risk_ids}",
        f"- Executed Profiles: {executed}",
        "",
        "This is a technical/provisional report. It never reports a benchmark PASS: "
        "human editorial, audio and subtitle review remain pending.",
        "",
        "## Mechanical hard failures",
        "",
        bullet(list(value["hard_failures"])),
        "",
        "## Not evaluable (blocks TECHNICAL_PASS_HUMAN_PENDING)",
        "",
        bullet([f"{item['gate']} ({item['category']})" for item in value["not_evaluable"]]),
        "",
        "## Human required",
        "",
        bullet(list(value["human_required"])),
        bullet(
            [
                f"manual adjudication {item['anchor_id']} <- {item['candidate_id']}"
                for item in value["manual_adjudication_required"]
            ]
        )
        if value["manual_adjudication_required"]
        else "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _publish_no_replace(output_dir: Path, report: dict[str, Any]) -> None:
    """Publish both reports atomically into a new directory; never replace evidence."""

    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        (staging / "benchmark-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "benchmark-report.md").write_text(_markdown(report), encoding="utf-8")
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError(f"output directory already exists: {output_dir}")
        os.rename(staging, output_dir)
    except BaseException:
        for child in staging.iterdir() if staging.exists() else ():
            child.unlink()
        if staging.exists():
            staging.rmdir()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a score-only Agent v2 run (technical/provisional status only)"
    )
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("agent_run_result", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        benchmark = _load_object(args.benchmark)
        result = AgentRunResult.model_validate_json(
            args.agent_run_result.read_text(encoding="utf-8")
        )
        report = evaluate_agent(benchmark, result)
        _publish_no_replace(args.output_dir, report)
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == STATUS_TECHNICAL_PASS_HUMAN_PENDING else 1


if __name__ == "__main__":
    raise SystemExit(main())
