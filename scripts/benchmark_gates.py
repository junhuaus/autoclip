"""Evaluation-only gates shared by the dual-profile benchmark evaluators.

Every rule here is derived from fields of ``liveclip_dual_profile_benchmark_v1.json``.
The only structural constants are the JSON section/field names that bind a Profile
to its gold list and boundary tolerance.  No anchor ID, timestamp or hash is
hard-coded; production code must never import this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

SHORT_PROFILE: Final = "short_highlight"
MINI_PROFILE: Final = "mini_lesson"
# Benchmark JSON section holding each Profile's required gold anchors.
PROFILE_GOLD_SECTIONS: Final[Mapping[str, str]] = {
    SHORT_PROFILE: "gold_short",
    MINI_PROFILE: "gold_mini_lesson",
}
# ``matching`` field holding each Profile's boundary tolerance.
PROFILE_TOLERANCE_FIELDS: Final[Mapping[str, str]] = {
    SHORT_PROFILE: "short_boundary_tolerance_ms",
    MINI_PROFILE: "long_boundary_tolerance_ms",
}
# ``forbidden_composite_intervals`` forbid continuous long outputs; their JSON
# reasons explicitly allow clean short subclips, so only this Profile is gated.
COMPOSITE_GATED_PROFILE: Final = MINI_PROFILE


@dataclass(frozen=True, slots=True)
class CandidateView:
    """Model-neutral projection of one final candidate.

    ``None`` means the source result model does not record that field, which
    makes every gate depending on it not evaluable rather than vacuously true.
    """

    candidate_id: str
    profile: str
    decision: str
    start_ms: int
    end_ms: int
    start_cue_id: int
    end_cue_id: int
    score: float
    quality_flags: frozenset[str] | None = None
    risk_tags: frozenset[str] | None = None
    evidence_cue_ids: frozenset[int] | None = None


@dataclass(frozen=True, slots=True)
class Match:
    anchor_id: str
    candidate_id: str
    profile: str
    start_delta_ms: int
    end_delta_ms: int
    decision: str
    match_kind: str


@dataclass(frozen=True, slots=True)
class ProfileMatching:
    matches: tuple[Match, ...]
    # matched candidate ID -> its allowed (start, end) interval
    allowed_intervals: Mapping[str, tuple[int, int]]
    manual_adjudication_required: tuple[dict[str, object], ...]
    padding_excluded_hits: tuple[dict[str, object], ...]


def tolerance_ms(benchmark: Mapping[str, Any], profile: str) -> int:
    return int(benchmark["matching"][PROFILE_TOLERANCE_FIELDS[profile]])


def gold_anchors(benchmark: Mapping[str, Any], profile: str) -> tuple[dict[str, Any], ...]:
    return tuple(benchmark[PROFILE_GOLD_SECTIONS[profile]])


def duration_allowed(benchmark: Mapping[str, Any], profile: str, duration_ms: int) -> bool:
    contract = benchmark["profiles"].get(profile)
    if not isinstance(contract, Mapping):
        return False
    minimum = int(contract["min_duration_ms"])
    maximum = int(contract["max_duration_ms"])
    minimum_ok = duration_ms >= minimum if contract["min_inclusive"] else duration_ms > minimum
    maximum_ok = duration_ms <= maximum if contract["max_inclusive"] else duration_ms < maximum
    return bool(minimum_ok and maximum_ok)


def duration_violations(
    benchmark: Mapping[str, Any], candidates: Iterable[CandidateView]
) -> list[dict[str, object]]:
    return [
        {
            "candidate_id": value.candidate_id,
            "profile": value.profile,
            "decision": value.decision,
            "duration_ms": value.end_ms - value.start_ms,
        }
        for value in candidates
        if not duration_allowed(benchmark, value.profile, value.end_ms - value.start_ms)
    ]


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _pair_metrics(anchor: Mapping[str, Any], candidate: CandidateView) -> dict[str, int]:
    anchor_start = int(anchor["start_ms"])
    anchor_end = int(anchor["end_ms"])
    cue_start = int(anchor["cue_start"])
    cue_end = int(anchor["cue_end"])
    return {
        "start_delta_ms": candidate.start_ms - anchor_start,
        "end_delta_ms": candidate.end_ms - anchor_end,
        "time_overlap_ms": overlap_ms(
            candidate.start_ms, candidate.end_ms, anchor_start, anchor_end
        ),
        "gold_duration_ms": anchor_end - anchor_start,
        "cue_overlap": max(
            0, min(candidate.end_cue_id, cue_end) - max(candidate.start_cue_id, cue_start) + 1
        ),
        "gold_cues": cue_end - cue_start + 1,
    }


def is_exact_boundary(anchor: Mapping[str, Any], candidate: CandidateView, tolerance: int) -> bool:
    """MD section 9 rule 4: both edges within the Profile tolerance with full cue coverage."""

    metrics = _pair_metrics(anchor, candidate)
    return (
        abs(metrics["start_delta_ms"]) <= tolerance
        and abs(metrics["end_delta_ms"]) <= tolerance
        and candidate.start_cue_id <= int(anchor["cue_start"])
        and candidate.end_cue_id >= int(anchor["cue_end"])
    )


def is_semantic_equivalent(
    anchor: Mapping[str, Any], candidate: CandidateView, tolerance: int
) -> bool:
    """The former automatic cue/time semantic-equivalence rule.

    The benchmark allows semantic equivalence only by manual adjudication
    (``matching.semantic_equivalence_manual_adjudication_allowed``), so this
    rule never creates a hit; it only routes a candidate to manual adjudication.
    """

    metrics = _pair_metrics(anchor, candidate)
    edge_limit = max(tolerance * 2, metrics["gold_duration_ms"] // 10)
    return (
        metrics["time_overlap_ms"] * 100 >= metrics["gold_duration_ms"] * 90
        and metrics["cue_overlap"] * 100 >= metrics["gold_cues"] * 90
        and abs(metrics["start_delta_ms"]) <= edge_limit
        and abs(metrics["end_delta_ms"]) <= edge_limit
    )


def allowed_interval(anchor: Mapping[str, Any], tolerance: int) -> tuple[int, int]:
    return int(anchor["start_ms"]) - tolerance, int(anchor["end_ms"]) + tolerance


def padding_overlaps(
    benchmark: Mapping[str, Any],
    candidate: CandidateView,
    *,
    allowed: tuple[int, int] | None,
    tolerance: int,
) -> list[dict[str, object]]:
    """Negative-anchor overlap outside the candidate's allowed interval above tolerance.

    ``allowed`` is the matched gold interval widened by the Profile tolerance for a
    counted hit, and ``None`` (the empty interval) otherwise.
    """

    findings: list[dict[str, object]] = []
    for negative in benchmark["negative_anchors"]:
        start = max(candidate.start_ms, int(negative["start_ms"]))
        end = min(candidate.end_ms, int(negative["end_ms"]))
        inside = max(0, end - start)
        if inside and allowed is not None:
            inside -= overlap_ms(start, end, allowed[0], allowed[1])
        if inside > tolerance:
            findings.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "profile": candidate.profile,
                    "decision": candidate.decision,
                    "negative_anchor_id": str(negative["id"]),
                    "outside_allowed_overlap_ms": inside,
                }
            )
    return findings


def composite_overlaps(
    benchmark: Mapping[str, Any], candidate: CandidateView
) -> list[dict[str, object]]:
    if candidate.profile != COMPOSITE_GATED_PROFILE:
        return []
    tolerance = tolerance_ms(benchmark, candidate.profile)
    findings: list[dict[str, object]] = []
    for interval in benchmark["forbidden_composite_intervals"]:
        overlap = overlap_ms(
            candidate.start_ms,
            candidate.end_ms,
            int(interval["start_ms"]),
            int(interval["end_ms"]),
        )
        if overlap > tolerance:
            findings.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "profile": candidate.profile,
                    "decision": candidate.decision,
                    "composite_start_ms": int(interval["start_ms"]),
                    "composite_end_ms": int(interval["end_ms"]),
                    "overlap_ms": overlap,
                }
            )
    return findings


def _maximum_matching(edges: Sequence[Sequence[int]]) -> dict[int, int]:
    """Deterministic augmenting-path bipartite matching: candidate index -> anchor index."""

    owner: dict[int, int] = {}

    def assign(anchor_index: int, seen: set[int]) -> bool:
        for candidate_index in edges[anchor_index]:
            if candidate_index in seen:
                continue
            seen.add(candidate_index)
            current = owner.get(candidate_index)
            if current is None or assign(current, seen):
                owner[candidate_index] = anchor_index
                return True
        return False

    for anchor_index in range(len(edges)):
        assign(anchor_index, set())
    return owner


def match_profile(
    benchmark: Mapping[str, Any],
    profile: str,
    candidates: Sequence[CandidateView],
    *,
    decision_allowed: Callable[[Mapping[str, Any], CandidateView], bool],
) -> ProfileMatching:
    """One-to-one exact-boundary matching within one Profile.

    Each anchor and each candidate contributes at most one hit.  Semantic-only
    candidates are reported for manual adjudication and never counted.
    """

    anchors = gold_anchors(benchmark, profile)
    tolerance = tolerance_ms(benchmark, profile)
    pool = [value for value in candidates if value.profile == profile]
    edges: list[list[int]] = []
    manual: list[dict[str, object]] = []
    padding_excluded: list[dict[str, object]] = []
    for anchor in anchors:
        ranked: list[tuple[int, float, str, int]] = []
        for index, candidate in enumerate(pool):
            if not decision_allowed(anchor, candidate):
                continue
            if not duration_allowed(benchmark, profile, candidate.end_ms - candidate.start_ms):
                continue
            metrics = _pair_metrics(anchor, candidate)
            if is_exact_boundary(anchor, candidate, tolerance):
                padding = padding_overlaps(
                    benchmark,
                    candidate,
                    allowed=allowed_interval(anchor, tolerance),
                    tolerance=tolerance,
                )
                if padding:
                    padding_excluded.append(
                        {
                            "anchor_id": str(anchor["id"]),
                            "candidate_id": candidate.candidate_id,
                            "decision": candidate.decision,
                            "padding": padding,
                            **metrics,
                        }
                    )
                    continue
                cost = abs(metrics["start_delta_ms"]) + abs(metrics["end_delta_ms"])
                ranked.append((cost, -candidate.score, candidate.candidate_id, index))
            elif is_semantic_equivalent(anchor, candidate, tolerance):
                manual.append(
                    {
                        "anchor_id": str(anchor["id"]),
                        "candidate_id": candidate.candidate_id,
                        "profile": profile,
                        "decision": candidate.decision,
                        "start_delta_ms": metrics["start_delta_ms"],
                        "end_delta_ms": metrics["end_delta_ms"],
                        "cue_coverage_percent": round(
                            100 * metrics["cue_overlap"] / metrics["gold_cues"], 2
                        ),
                        "time_coverage_percent": round(
                            100 * metrics["time_overlap_ms"] / metrics["gold_duration_ms"], 2
                        ),
                        "padding": padding_overlaps(
                            benchmark, candidate, allowed=None, tolerance=tolerance
                        ),
                    }
                )
        edges.append([index for *_, index in sorted(ranked)])
    owner = _maximum_matching(edges)
    matches: list[Match] = []
    allowed: dict[str, tuple[int, int]] = {}
    for candidate_index, anchor_index in sorted(owner.items(), key=lambda item: item[1]):
        anchor = anchors[anchor_index]
        candidate = pool[candidate_index]
        matches.append(
            Match(
                anchor_id=str(anchor["id"]),
                candidate_id=candidate.candidate_id,
                profile=profile,
                start_delta_ms=candidate.start_ms - int(anchor["start_ms"]),
                end_delta_ms=candidate.end_ms - int(anchor["end_ms"]),
                decision=candidate.decision,
                match_kind="exact_boundary",
            )
        )
        allowed[candidate.candidate_id] = allowed_interval(anchor, tolerance)
    return ProfileMatching(
        matches=tuple(matches),
        allowed_intervals=allowed,
        manual_adjudication_required=tuple(manual),
        padding_excluded_hits=tuple(padding_excluded),
    )


def auto_decision_regressions(benchmark: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Regressions whose interval may never be automatically decided."""

    return tuple(
        value
        for value in benchmark["regressions"]
        if value.get("forbidden_auto_decision") is True
        and "start_ms" in value
        and "end_ms" in value
    )


def regression_tolerance(benchmark: Mapping[str, Any], regression: Mapping[str, Any]) -> int:
    """Tolerance of the Profile whose duration contract contains the regression interval."""

    duration = int(regression["end_ms"]) - int(regression["start_ms"])
    for profile in PROFILE_TOLERANCE_FIELDS:
        if duration_allowed(benchmark, profile, duration):
            return tolerance_ms(benchmark, profile)
    raise ValueError(f"regression {regression['id']} fits no benchmark Profile")


def regression_start_hits(
    regression: Mapping[str, Any], candidates: Iterable[CandidateView], tolerance: int
) -> list[CandidateView]:
    """Candidates starting at the regression opening, regardless of where they end."""

    return [
        value
        for value in candidates
        if abs(value.start_ms - int(regression["start_ms"])) <= tolerance
    ]


def regression_interval_hits(
    regression: Mapping[str, Any], candidates: Iterable[CandidateView], tolerance: int
) -> list[CandidateView]:
    return [
        value
        for value in candidates
        if abs(value.start_ms - int(regression["start_ms"])) <= tolerance
        and abs(value.end_ms - int(regression["end_ms"])) <= tolerance
    ]


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    match: Match | None
    discovered_candidate_ids: tuple[str, ...]
    misrouted: tuple[dict[str, object], ...]
    missing_risk_tags: tuple[dict[str, object], ...]
    missing_evidence_cues: tuple[dict[str, object], ...]


def assess_risk_anchor(
    anchor: Mapping[str, Any],
    candidates: Iterable[CandidateView],
    *,
    routing_evaluable: bool,
) -> RiskAssessment:
    """Discovery requires full cue coverage; a match also requires evidence and routing.

    A candidate's evidence cue IDs must intersect the anchor's cue range.  When
    ``routing_evaluable`` is false (no decision buckets / risk tags exist in the
    model), routing and risk-tag checks are skipped and must be reported as not
    evaluable by the caller.
    """

    cue_start = int(anchor["cue_start"])
    cue_end = int(anchor["cue_end"])
    required_routes = {str(value) for value in anchor["required_routing"]}
    required_risks = {str(value) for value in anchor["risk_tags"]}
    discovered: list[CandidateView] = []
    misrouted: list[dict[str, object]] = []
    missing_tags: list[dict[str, object]] = []
    missing_evidence: list[dict[str, object]] = []
    ranked: list[tuple[int, str, CandidateView]] = []
    for candidate in candidates:
        overlap = overlap_ms(
            candidate.start_ms, candidate.end_ms, int(anchor["start_ms"]), int(anchor["end_ms"])
        )
        if overlap <= 0 or candidate.start_cue_id > cue_start or candidate.end_cue_id < cue_end:
            continue
        discovered.append(candidate)
        row: dict[str, object] = {
            "anchor_id": str(anchor["id"]),
            "candidate_id": candidate.candidate_id,
            "decision": candidate.decision,
        }
        ok = True
        evidence = candidate.evidence_cue_ids
        if evidence is None or not any(cue_start <= cue <= cue_end for cue in evidence):
            missing_evidence.append({**row, "evidence_cue_ids": sorted(evidence or ())})
            ok = False
        if routing_evaluable:
            if candidate.decision not in required_routes:
                misrouted.append({**row, "required_routing": sorted(required_routes)})
                ok = False
            tags = candidate.risk_tags or frozenset()
            if not required_risks <= tags:
                missing_tags.append({**row, "missing_risk_tags": sorted(required_risks - tags)})
                ok = False
        if ok:
            ranked.append((-overlap, candidate.candidate_id, candidate))
    match: Match | None = None
    if ranked:
        candidate = min(ranked, key=lambda value: (value[0], value[1]))[2]
        match = Match(
            anchor_id=str(anchor["id"]),
            candidate_id=candidate.candidate_id,
            profile=candidate.profile,
            start_delta_ms=candidate.start_ms - int(anchor["start_ms"]),
            end_delta_ms=candidate.end_ms - int(anchor["end_ms"]),
            decision=candidate.decision,
            match_kind=(
                "risk_full_cue_coverage_routed_with_evidence"
                if routing_evaluable
                else "risk_full_cue_coverage_with_evidence"
            ),
        )
    return RiskAssessment(
        match=match,
        discovered_candidate_ids=tuple(value.candidate_id for value in discovered),
        misrouted=tuple(misrouted),
        missing_risk_tags=tuple(missing_tags),
        missing_evidence_cues=tuple(missing_evidence),
    )


def boundary_score(
    points: float,
    matches: Sequence[Match],
    *,
    qualified: Callable[[Match], bool],
) -> tuple[float, int]:
    """MD section 10: points x qualified hits / hits, and zero without hits."""

    if not matches:
        return 0.0, 0
    count = sum(1 for value in matches if qualified(value))
    return points * count / len(matches), count
