#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
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
from liveclip.media.secure_files import publish_directory_no_replace_no_follow

# Package import of the shared evaluation-only gates.  Only when this file is run
# directly as a script (no package) is the repository root appended to sys.path.
if not __package__:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_gates import (
    MINI_PROFILE,
    PROFILE_GOLD_SECTIONS,
    SHORT_PROFILE,
    CandidateView,
    Match,
    assess_risk_anchor,
    auto_decision_regressions,
    bad_start_findings,
    boundary_score,
    composite_overlaps,
    duration_violations,
    match_profile,
    padding_overlaps,
    regression_interval_hits,
    regression_start_hits,
    regression_tolerance,
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


def _executed_profiles(audit: Mapping[str, Any]) -> list[str]:
    """Executed Profiles from the frozen Global Review, never from loose candidates.

    ``save_global_review`` refuses to freeze unless every ``requested_profiles``
    entry has at least one ``final`` candidate
    (``src/liveclip/agent_tools/clipping.py:421-423``) and then freezes
    ``requested_profiles`` and ``final_candidate_ids`` into the Global Review
    artifact (``clipping.py:451-457``).  A requested Profile counts as executed
    only when that invariant still holds in the result; a missing or
    non-conserving Global Review yields no executed Profile.
    """

    if audit["global_review_error"] is not None:
        return []
    counts = audit["final_profile_counts"]
    return [profile for profile in audit["requested_profiles"] if counts.get(profile, 0) > 0]


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
       concept, so the item is ``not_applicable`` and scores 0 (``None`` here).
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
    items: dict[str, bool | None] = {}
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
    items["cache_repair_records"] = None
    return {
        "items": items,
        "score": 2.0 * sum(1 for value in items.values() if value is True),
        "raw_candidate_count": len(raw_candidates),
        "final_candidate_count": len(final_candidates),
        "superseded_candidate_count": len(raw_candidates - final_candidates),
        "final_profile_counts": dict(sorted(profile_counts.items())),
        "requested_profiles": requested,
        "missing_raw_trace": missing_raw,
        "missing_validation": missing_validation,
        "missing_titles": missing_titles,
        "global_review_error": review_error,
        "consistent": bool(items["profile_counts"] and items["candidate_dispositions"]),
    }


def technical_status(*, invalid_evidence: list[str], mechanical_failures: list[str]) -> str:
    """Only invalid evidence or mechanical failures block the technical pass.

    ``not_applicable`` and ``human_required`` items never block, but human work
    always remains pending, so a full benchmark ``PASS`` is never returned.
    """

    if invalid_evidence:
        return STATUS_INVALID_EVIDENCE
    if mechanical_failures:
        return STATUS_TECHNICAL_FAIL
    return STATUS_TECHNICAL_PASS_HUMAN_PENDING


def _invalid_report(
    benchmark: dict[str, Any], result: AgentRunResult, reasons: list[str]
) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "contract_mode": CONTRACT_MODE,
        "status": technical_status(invalid_evidence=reasons, mechanical_failures=[]),
        "invalid_evidence": reasons,
        "mechanical_failures": [],
        "not_applicable": [],
        "human_required": [{"check": value} for value in HUMAN_REQUIRED_ACTIVITIES],
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
    except ValueError as exc:
        return _invalid_report(benchmark, result, [f"malformed_evidence: {exc}"])

    acceptance = benchmark["acceptance"]
    gates = benchmark["automatic_selection_gates"]
    points = benchmark["scoring"]["components"]
    mechanical_failures: list[str] = []
    # Legacy-v1 concepts the score-only Agent v2 contract does not have
    # (acceptance doc: separate them; never fabricate them).
    not_applicable: list[dict[str, object]] = [
        {
            "concept": "match_decision_buckets",
            "reason": "Agent v2 has no selected/manual_review buckets; matching.match_decisions "
            "and anchor allowed_decisions do not apply, and every final candidate is matched",
        },
        {
            "concept": "automatic_selection_score_gate",
            "reason": "Agent v2 has no automatic-selection decision for "
            "score_strictly_greater_than",
            "final_candidates_not_above_threshold": sorted(
                value.candidate_id
                for value in views
                if not value.score > float(gates["score_strictly_greater_than"])
            ),
        },
        {
            "concept": "risk_routing",
            "reason": "Agent v2 has no manual_review/blocked routing or risk tags; the "
            "risk_discovery_and_routing component scores 0",
            "unscored_points": float(points["risk_discovery_and_routing"]),
        },
        {
            "concept": "cache_repair_records",
            "reason": "AgentRunResult has no cache-hit or repair concept; audit item scores 0",
            "unscored_points": 2.0,
        },
    ]
    human_required: list[dict[str, object]] = [
        {"check": value} for value in HUMAN_REQUIRED_ACTIVITIES
    ]
    human_required.append(
        {
            "check": "forbidden_quality_flags_adjudication",
            "reason": "Agent v2 candidates record no quality flags; forbidden flags and boundary "
            "qualification by flags need human review",
            "flags": sorted(str(value) for value in gates["forbidden_quality_flags"]),
        }
    )

    required_profiles = tuple(benchmark["required_behavior"]["requested_profiles"])
    requested = list(audit["requested_profiles"])
    executed = _executed_profiles(audit)
    both_profiles = set(requested) == set(required_profiles) and set(executed) == set(
        required_profiles
    )
    if not both_profiles:
        mechanical_failures.append("missing_executed_profile")

    durations = duration_violations(benchmark, views)
    if durations:
        mechanical_failures.append("duration_out_of_profile_bounds")
    # Every final candidate is a delivered output whose Global Review row asserted
    # complete boundaries and no irrelevant padding, so content gates apply to it
    # exactly as to v1 selected/manual_review outputs (Controller decision D2).
    padding = [entry for candidate in views for entry in padding_overlaps(benchmark, candidate)]
    padded_ids = {str(value["candidate_id"]) for value in padding}
    if padding:
        mechanical_failures.append("irrelevant_padding")
    composites = [
        entry for candidate in views for entry in composite_overlaps(benchmark, candidate)
    ]
    if composites:
        mechanical_failures.append("forbidden_composite_interval")

    def clean(candidate: CandidateView) -> bool:
        return candidate.candidate_id not in padded_ids

    matchings = {
        profile: match_profile(
            benchmark, profile, views, decision_allowed=lambda *_: True, prefer=clean
        )
        for profile in PROFILE_GOLD_SECTIONS
    }
    short_matches = matchings[SHORT_PROFILE].matches
    long_matches = matchings[MINI_PROFILE].matches
    manual_adjudication = [
        entry for item in matchings.values() for entry in item.manual_adjudication_required
    ]
    if manual_adjudication:
        human_required.append(
            {
                "check": "semantic_equivalence_manual_adjudication",
                "candidate_ids": sorted(
                    {str(item["candidate_id"]) for item in manual_adjudication}
                ),
            }
        )

    regression_reports: list[dict[str, Any]] = []
    for regression in auto_decision_regressions(benchmark):
        tolerance = regression_tolerance(benchmark, regression)
        # A final candidate opening at the regression start was accepted with a
        # declared complete opening, which the regression forbids.
        auto = regression_start_hits(regression, views, tolerance)
        if auto:
            mechanical_failures.append(f"{regression['id']}_auto_selected")
        interval_hits = regression_interval_hits(regression, views, tolerance)
        if interval_hits and regression.get("required_quality_flags"):
            human_required.append(
                {
                    "check": f"{regression['id']}_required_quality_flags",
                    "reason": "Agent v2 candidates record no quality flags",
                    "candidate_ids": [value.candidate_id for value in interval_hits],
                    "flags": list(regression["required_quality_flags"]),
                }
            )
        regression_reports.append(
            {
                "regression_id": str(regression["id"]),
                "auto_selected": [value.candidate_id for value in auto],
                "interval_candidates": [value.candidate_id for value in interval_hits],
            }
        )

    risks = {
        str(anchor["id"]): assess_risk_anchor(anchor, views, routing_evaluable=False)
        for anchor in benchmark["risk_anchors"]
    }
    risk_matches = tuple(value.match for value in risks.values() if value.match is not None)
    required_risk_ids = {str(value) for value in acceptance["required_risk_anchor_ids"]}
    suppressed_risk_ids = sorted(
        key
        for key in required_risk_ids
        if key not in risks or not risks[key].discovered_candidate_ids
    )
    if suppressed_risk_ids:
        mechanical_failures.append("risk_suppressed_during_discovery")
    if not required_risk_ids <= {value.anchor_id for value in risk_matches}:
        mechanical_failures.append("risk_discovery_without_evidence_cues")

    if not audit["consistent"]:
        mechanical_failures.append("untraceable_or_inconsistent_audit")
    matched_long_ids = {value.anchor_id for value in long_matches}
    p0_ids = {str(value) for value in acceptance["required_p0_mini_lesson_ids"]}
    if not p0_ids <= matched_long_ids:
        mechanical_failures.append("missing_any_p0_mini_lesson")
    if len(short_matches) < int(acceptance["short_min_hits"]):
        mechanical_failures.append("short_recall_below_threshold")
    if len(long_matches) < int(acceptance["mini_lesson_min_hits"]):
        mechanical_failures.append("mini_lesson_recall_below_threshold")

    # Controller decision D1 (2026-10-20): raw 100-point scale, unchanged pass
    # threshold; not-applicable components score 0 and are reported separately.
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
        # Quality flags need human adjudication (listed above); exactness and
        # padding are mechanical.
        return match.match_kind == "exact_boundary" and match.candidate_id not in padded_ids

    boundary, qualified_hits = boundary_score(
        float(points["boundary_and_completeness"]),
        (*short_matches, *long_matches),
        qualified=qualified,
    )
    audit_score = float(audit["score"])
    raw_score = round(executed_points + short_score + long_score + boundary + audit_score, 2)
    applicable_max_score = round(
        float(benchmark["scoring"]["total_points"])
        - sum(float(str(item.get("unscored_points", 0))) for item in not_applicable),
        2,
    )
    if raw_score < float(acceptance["pass_min_score"]):
        mechanical_failures.append("score_below_pass_threshold")

    status = technical_status(invalid_evidence=[], mechanical_failures=mechanical_failures)
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "contract_mode": CONTRACT_MODE,
        "status": status,
        "score": raw_score,
        "raw_score": raw_score,
        "applicable_max_score": applicable_max_score,
        "pass_min_score": float(acceptance["pass_min_score"]),
        "components": {
            "both_profiles_executed": round(executed_points, 2),
            "short_recall": round(short_score, 2),
            "mini_lesson_recall": round(long_score, 2),
            "boundary_and_completeness": round(boundary, 2),
            "risk_discovery_and_routing": 0.0,
            "audit_and_reproducibility": audit_score,
        },
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
        "regression_findings": bad_start_findings(benchmark, views),
        "mechanical_failures": mechanical_failures,
        "not_applicable": not_applicable,
        "human_required": human_required,
        "requested_profiles": requested,
        "executed_profiles": executed,
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
    human = bullet([str(item["check"]) for item in value["human_required"]])
    if value["status"] == STATUS_INVALID_EVIDENCE:
        lines += ["", "## Invalid evidence", "", bullet(list(value["invalid_evidence"]))]
        lines += ["", "## Human required", "", human]
        return "\n".join(lines) + "\n"
    short_ids = ", ".join(item["anchor_id"] for item in value["short_matches"]) or "无"
    long_ids = ", ".join(item["anchor_id"] for item in value["mini_lesson_matches"]) or "无"
    risk_ids = ", ".join(item["anchor_id"] for item in value["risk_discovery_matches"]) or "无"
    executed = ", ".join(value["executed_profiles"]) or "none"
    lines += [
        f"- Raw score: **{value['raw_score']} / 100** "
        f"(applicable maximum {value['applicable_max_score']}; PASS threshold "
        f"{value['pass_min_score']})",
        f"- Short recall: {value['short_hits']}/{value['short_total']} ({short_ids})",
        "- Mini-lesson recall: "
        f"{value['mini_lesson_hits']}/{value['mini_lesson_total']} ({long_ids})",
        f"- Risk anchors discovered with evidence (routing not applicable): {risk_ids}",
        f"- Executed Profiles (frozen Global Review): {executed}",
        "",
        "This is a technical/provisional report. It never reports a benchmark PASS: "
        "human editorial, audio and subtitle review remain pending.",
        "",
        "## Mechanical failures (block TECHNICAL_PASS_HUMAN_PENDING)",
        "",
        bullet(list(value["mechanical_failures"])),
        "",
        "## Not applicable to score-only Agent v2 (legacy-v1 concepts)",
        "",
        bullet([str(item["concept"]) for item in value["not_applicable"]]),
        "",
        "## Human required (pending; never a full PASS)",
        "",
        human,
    ]
    return "\n".join(lines).rstrip() + "\n"


REPORT_FILE_NAMES = ("benchmark-result.json", "benchmark-report.md")


def _stage_file(directory: Path, name: str, content: str) -> None:
    descriptor = os.open(
        directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _discard_staging(staging: Path) -> None:
    """Best-effort removal of this call's own staging directory."""

    for name in REPORT_FILE_NAMES:
        with contextlib.suppress(OSError):
            (staging / name).unlink()
    with contextlib.suppress(OSError):
        staging.rmdir()


def _publish_no_replace(output_dir: Path, report: dict[str, Any]) -> None:
    """Publish both reports atomically as one directory; never replace evidence.

    Both files are written and fsynced in a private sibling staging directory
    (same parent, hence same filesystem) and then published as one unit by
    ``publish_directory_no_replace_no_follow``: a no-follow, exclusive
    (``RENAME_EXCL``/``RENAME_NOREPLACE``) directory rename that refuses any
    existing destination, including an empty directory, and verifies and
    fsyncs the result.  On any failure the staging directory is removed and the
    original exception propagates; no partial output directory is left.
    """

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    try:
        contents = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            _markdown(report),
        )
        for name, content in zip(REPORT_FILE_NAMES, contents, strict=True):
            _stage_file(staging, name, content)
        publish_directory_no_replace_no_follow(staging, output_dir)
    except BaseException:
        _discard_staging(staging)
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
