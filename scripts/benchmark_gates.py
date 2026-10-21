"""Evaluation-only gates shared by the dual-profile benchmark evaluators.

Every rule here is derived from fields of ``liveclip_dual_profile_benchmark_v1.json``.
The only structural constants are the JSON section/field names that bind a Profile
to its gold list and boundary tolerance, and the per-anchor output policy of MD
section 7 (``NEGATIVE_ANCHOR_POLICIES``), which the JSON carries only as ``reason``
strings and which is validated against the JSON before use.  No timestamp or hash
is hard-coded; production code must never import this module.
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
# Anchor sections whose exact-boundary intervals are legitimate content for the
# negative-anchor padding allowance (required gold plus supplemental lessons).
PADDING_ALLOWANCE_SECTIONS: Final = (*PROFILE_GOLD_SECTIONS.values(), "supplemental_mini_lesson")
# ``forbidden_composite_intervals`` forbid continuous long outputs; their JSON
# reasons explicitly allow clean short subclips, so only this Profile is gated.
COMPOSITE_GATED_PROFILE: Final = MINI_PROFILE
# Operator decision B (2026-10-21): an output lying only on negative-anchor
# content is its own direct-FAIL class, distinct from ``irrelevant_padding``.
# The benchmark JSON cannot be edited, so both evaluators add this name to the
# JSON ``direct_fail_conditions``.
NEGATIVE_ANCHOR_OUTPUT: Final = "negative_anchor_output"
EXTRA_DIRECT_FAIL_CONDITIONS: Final = (NEGATIVE_ANCHOR_OUTPUT,)
# Decisions that put a candidate out without a human routing step: v1
# ``selected`` and every Agent v2 Global Review ``final`` candidate.
AUTOMATIC_OUTPUT_DECISIONS: Final = frozenset({"selected", "final"})
# Every output decision, v1 (``matching.match_decisions``) and Agent v2.
ALL_OUTPUT_DECISIONS: Final = frozenset({"selected", "manual_review", "final"})


@dataclass(frozen=True, slots=True)
class NegativeAnchorPolicy:
    """How MD section 7 ("禁止作为成片或补时的区间") treats an output on one anchor.

    ``hard_fail_decisions`` are the output decisions for which a negative-only
    output is a direct FAIL; any other output decision is reported as an
    informational finding that needs human review.  ``clean_subinterval_anchor``
    names the only gold anchor whose clean sub-interval may be cut from the
    negative interval; that exception is the exact-match padding allowance.
    """

    anchor_id: str
    reason: str
    start_ms: int
    end_ms: int
    md_section_7_row: str
    hard_fail_decisions: frozenset[str]
    clean_subinterval_anchor: str | None = None


# The table binds to this benchmark only; ``negative_anchor_policies`` checks
# the ID, every anchor ``reason`` and interval, and any clean sub-interval
# anchor before use.
NEGATIVE_POLICY_BENCHMARK_ID: Final = "liveclip-dual-profile-transcript-v1"
# MD section 7 interval of each row (HH:MM:SS.mmm converted to milliseconds).
_MD_SECTION_7_INTERVALS: Final[Mapping[str, tuple[int, int]]] = {
    "N01": (0, 530_000),  # 00:00:00.000-00:08:50.000
    "N02": (700_260, 715_620),  # 00:11:40.260-00:11:55.620
    "N03": (772_960, 805_000),  # 00:12:52.960-00:13:25.000
    "N04": (950_280, 993_980),  # 00:15:50.280-00:16:33.980
    "N05": (1_425_760, 1_548_080),  # 00:23:45.760-00:25:48.080
    "N06": (1_742_560, 1_889_160),  # 00:29:02.560-00:31:29.160
    "N07": (2_284_100, 2_404_200),  # 00:38:04.100-00:40:04.200
    "N08": (2_984_180, 3_916_960),  # 00:49:44.180-01:05:16.960
    "N09": (5_226_540, 5_423_560),  # 01:27:06.540-01:30:23.560
    "N10": (5_481_300, 5_571_800),  # 01:31:21.300-01:32:51.800
    "N11": (6_604_880, 6_630_860),  # 01:50:04.880-01:50:30.860
}


def _policy(
    anchor_id: str,
    reason: str,
    row: str,
    hard_fail_decisions: frozenset[str],
    clean_subinterval_anchor: str | None = None,
) -> NegativeAnchorPolicy:
    start_ms, end_ms = _MD_SECTION_7_INTERVALS[anchor_id]
    return NegativeAnchorPolicy(
        anchor_id,
        reason,
        start_ms,
        end_ms,
        row,
        hard_fail_decisions,
        clean_subinterval_anchor,
    )


def _default_policy(anchor_id: str, reason: str, row: str) -> NegativeAnchorPolicy:
    # Controller interpretation pending operator confirmation: "禁止作为成片"
    # together with confirmed D2 makes every output on these anchors a FAIL,
    # whether it was selected or routed to manual review.
    return _policy(anchor_id, reason, row, ALL_OUTPUT_DECISIONS)


NEGATIVE_ANCHOR_POLICIES: Final[Mapping[str, NegativeAnchorPolicy]] = {
    value.anchor_id: value
    for value in (
        _default_policy(
            "N01",
            "setup_chat_device_and_fragmented_singing",
            "MD §7 line 93 (N01): 开场准备、碎片演唱、聊天、设备调整",
        ),
        _default_policy(
            "N02",
            "follow_and_fan_cta",
            "MD §7 line 94 (N02): 关注/粉丝 CTA",
        ),
        _default_policy(
            "N03",
            "schedule_and_off_topic_chat",
            "MD §7 line 95 (N03): 排期、网球等离题聊天",
        ),
        _default_policy(
            "N04",
            "cta_and_device_adjustment",
            "MD §7 line 96 (N04): CTA 与设备调整",
        ),
        _default_policy(
            "N05",
            "likes_course_promo_and_device_interruption",
            "MD §7 line 97 (N05): 点赞、课程推广、设备/白板中断",
        ),
        _default_policy(
            "N06",
            "cta_waiting_and_unfinished_setup",
            "MD §7 line 98 (N06): CTA、等待及未完成铺垫",
        ),
        _default_policy(
            "N07",
            "chat_device_and_fragments",
            "MD §7 line 99 (N07): 聊天、设备及碎片内容 / 不得给 L03 补时",
        ),
        # "不得自动作为教学片": only an automatic output is forbidden; a
        # manual_review output is a finding for the human reviewer.
        _policy(
            "N08",
            "extended_sales_pricing_scheduling_and_credentials",
            "MD §7 line 100 (N08): 大段价格、课程销售、排期与资历说明 / 不得自动作为教学片",
            AUTOMATIC_OUTPUT_DECISIONS,
        ),
        # "只允许抽取 S08 的干净子区间": everything else on N09 fails for every
        # output decision; the S08 exception is its exact-match padding allowance.
        _policy(
            "N09",
            "device_network_and_phone_playback_chaos_with_S08_exception",
            "MD §7 line 101 (N09): 设备、网络和手机播放混乱 / 只允许抽取 S08 的干净子区间",
            ALL_OUTPUT_DECISIONS,
            clean_subinterval_anchor="S08",
        ),
        _default_policy(
            "N10",
            "connection_troubleshooting",
            "MD §7 line 102 (N10): 连线故障排查",
        ),
        _default_policy(
            "N11",
            "outro_cta_and_farewell",
            "MD §7 line 103 (N11): 结束 CTA 与告别",
        ),
    )
}


@dataclass(frozen=True, slots=True)
class ResolvedNegativePolicies:
    policies: Mapping[str, NegativeAnchorPolicy]
    mismatches: tuple[dict[str, str], ...]


def negative_anchor_policies(benchmark: Mapping[str, Any]) -> ResolvedNegativePolicies:
    """Bind the MD section 7 table to the loaded benchmark, failing closed.

    Each negative anchor uses its table entry only when the benchmark ID, the
    anchor ``reason``, its ``start_ms``/``end_ms`` (the MD section 7 interval)
    and (for N09) the clean sub-interval gold anchor lying inside the negative
    interval all match.  Any mismatch, or an anchor with no
    entry, gets the strictest policy: a FAIL for every output decision.  This
    can only tighten the result, so the evaluator stays usable on a mismatched
    benchmark while every relaxation is withheld; the mismatches are reported.
    """

    benchmark_id = str(benchmark.get("benchmark_id"))
    golds = {
        str(anchor["id"]): anchor
        for section in PADDING_ALLOWANCE_SECTIONS
        for anchor in benchmark.get(section, ())
    }
    resolved: dict[str, NegativeAnchorPolicy] = {}
    mismatches: list[dict[str, str]] = []
    for anchor in benchmark["negative_anchors"]:
        anchor_id = str(anchor["id"])
        reason = str(anchor.get("reason"))
        entry = NEGATIVE_ANCHOR_POLICIES.get(anchor_id)
        problem: str | None = None
        if benchmark_id != NEGATIVE_POLICY_BENCHMARK_ID:
            problem = "benchmark_id"
        elif entry is None:
            problem = "no_policy_entry"
        elif entry.reason != reason:
            problem = "reason"
        elif (entry.start_ms, entry.end_ms) != (int(anchor["start_ms"]), int(anchor["end_ms"])):
            problem = "interval"
        elif entry.clean_subinterval_anchor is not None:
            gold = golds.get(entry.clean_subinterval_anchor)
            if gold is None or not (
                int(anchor["start_ms"]) <= int(gold["start_ms"])
                and int(gold["end_ms"]) <= int(anchor["end_ms"])
            ):
                problem = "clean_subinterval_anchor"
        if problem is None and entry is not None:
            resolved[anchor_id] = entry
        else:
            mismatches.append({"negative_anchor_id": anchor_id, "mismatch": str(problem)})
            resolved[anchor_id] = NegativeAnchorPolicy(
                anchor_id,
                reason,
                int(anchor["start_ms"]),
                int(anchor["end_ms"]),
                "strictest default (policy table mismatch)",
                ALL_OUTPUT_DECISIONS,
            )
    return ResolvedNegativePolicies(policies=resolved, mismatches=tuple(mismatches))


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
    manual_adjudication_required: tuple[dict[str, object], ...]


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
    """Both edges within the Profile tolerance, inward or outward (inclusive).

    Operator decision A (2026-10-21): an exact boundary hit is tolerance-only;
    full gold cue coverage is no longer required.  MD basis: section 4 line 41
    and section 5 line 58 ("允许在自然 cue 边界前后调整约 3 秒 / 5 秒": the
    boundary may move about 3 s / 5 s in either direction) and section 9 rules 3
    and 4 (core topic/evidence coverage, edges "通常在参考边界 ±3 秒 / ±5 秒").
    Beyond the tolerance a semantically equivalent candidate still goes to
    manual adjudication only (``is_semantic_equivalent``).
    """

    metrics = _pair_metrics(anchor, candidate)
    return abs(metrics["start_delta_ms"]) <= tolerance and abs(metrics["end_delta_ms"]) <= tolerance


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


def padding_allowance(
    benchmark: Mapping[str, Any], candidate: CandidateView
) -> tuple[tuple[int, int], ...]:
    """Union members of the candidate's allowed interval.

    Every gold or supplemental anchor that the candidate matches at the exact
    boundary contributes its interval widened by the candidate's Profile
    tolerance, independent of the one-to-one assignment and of the decision.
    A candidate matching no anchor has the empty allowance.
    """

    tolerance = tolerance_ms(benchmark, candidate.profile)
    return tuple(
        allowed_interval(anchor, tolerance)
        for section in PADDING_ALLOWANCE_SECTIONS
        for anchor in benchmark.get(section, ())
        if is_exact_boundary(anchor, candidate, tolerance)
    )


def _covered_ms(start: int, end: int, intervals: Iterable[tuple[int, int]]) -> int:
    """Length of [start, end) covered by the union of ``intervals``."""

    clipped = sorted(
        (max(start, low), min(end, high))
        for low, high in intervals
        if min(end, high) > max(start, low)
    )
    covered = 0
    cursor = start
    for low, high in clipped:
        low = max(low, cursor)
        if high > low:
            covered += high - low
            cursor = high
    return covered


def _nearest_gold_anchor(
    benchmark: Mapping[str, Any], candidate: CandidateView
) -> Mapping[str, Any] | None:
    """Gold anchor of the candidate's Profile with the smallest summed edge delta."""

    anchors = benchmark.get(PROFILE_GOLD_SECTIONS.get(candidate.profile, ""), ())
    ranked = sorted(
        (
            abs(candidate.start_ms - int(anchor["start_ms"]))
            + abs(candidate.end_ms - int(anchor["end_ms"])),
            str(anchor["id"]),
            index,
        )
        for index, anchor in enumerate(anchors)
    )
    return anchors[ranked[0][2]] if ranked else None


def padding_overlaps(
    benchmark: Mapping[str, Any], candidate: CandidateView
) -> list[dict[str, object]]:
    """Negative-anchor overlap outside the candidate's allowance, above its Profile tolerance.

    Only exact-boundary matches earn an allowance; a semantic-equivalent-only
    candidate gets none (confirmed by the operator on 2026-10-21).  For human
    inspection each finding also reports the overlap measured outside the
    candidate's nearest gold anchor interval (unwidened).  Negative-only outputs
    are classified by ``negative_anchor_outputs`` instead and never reach here.
    """

    tolerance = tolerance_ms(benchmark, candidate.profile)
    allowance = padding_allowance(benchmark, candidate)
    nearest = _nearest_gold_anchor(benchmark, candidate)
    nearest_interval = (
        ((int(nearest["start_ms"]), int(nearest["end_ms"])),) if nearest is not None else ()
    )
    findings: list[dict[str, object]] = []
    for negative in benchmark["negative_anchors"]:
        start = max(candidate.start_ms, int(negative["start_ms"]))
        end = min(candidate.end_ms, int(negative["end_ms"]))
        if end <= start:
            continue
        outside = end - start - _covered_ms(start, end, allowance)
        if outside > tolerance:
            findings.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "profile": candidate.profile,
                    "decision": candidate.decision,
                    "negative_anchor_id": str(negative["id"]),
                    "outside_allowed_overlap_ms": outside,
                    "nearest_anchor_id": None if nearest is None else str(nearest["id"]),
                    "outside_nearest_anchor_ms": end
                    - start
                    - _covered_ms(start, end, nearest_interval),
                }
            )
    return findings


def negative_anchor_outputs(
    benchmark: Mapping[str, Any],
    candidate: CandidateView,
    policies: ResolvedNegativePolicies,
) -> list[dict[str, object]]:
    """Operator decision B (2026-10-21): an output lying only on negative content.

    A candidate is negative-only when it is entirely negative: the part of it
    not covered by the union of negative-anchor intervals is at most its Profile
    tolerance.  It must also have no time overlap with any gold or supplemental
    anchor of either Profile, and neither an exact nor a semantic match.  Each
    negative anchor it overlaps by more than the tolerance (the padding
    threshold) yields one finding whose ``hard_failure`` follows that anchor's
    MD section 7 policy; no nearest-gold diagnostic is reported.

    Anything else, including un-anchored content or risk-anchor content mixed
    with a negative interval, is not "negative-only" and returns no finding
    here, so ``padding_overlaps`` judges its negative overlap as padding.  Risk
    anchors need no special case: their content is not covered by a negative
    interval, so beyond the tolerance it counts toward the uncovered remainder.
    """

    tolerance = tolerance_ms(benchmark, candidate.profile)
    negative_intervals = tuple(
        (int(value["start_ms"]), int(value["end_ms"])) for value in benchmark["negative_anchors"]
    )
    duration = candidate.end_ms - candidate.start_ms
    if duration - _covered_ms(candidate.start_ms, candidate.end_ms, negative_intervals) > tolerance:
        return []
    for section in PADDING_ALLOWANCE_SECTIONS:
        for anchor in benchmark.get(section, ()):
            if overlap_ms(
                candidate.start_ms, candidate.end_ms, int(anchor["start_ms"]), int(anchor["end_ms"])
            ):
                return []
            if is_exact_boundary(anchor, candidate, tolerance) or is_semantic_equivalent(
                anchor, candidate, tolerance
            ):
                return []
    findings: list[dict[str, object]] = []
    for negative in benchmark["negative_anchors"]:
        overlap = overlap_ms(
            candidate.start_ms, candidate.end_ms, int(negative["start_ms"]), int(negative["end_ms"])
        )
        if overlap <= tolerance:
            continue
        policy = policies.policies[str(negative["id"])]
        findings.append(
            {
                "candidate_id": candidate.candidate_id,
                "profile": candidate.profile,
                "decision": candidate.decision,
                "negative_anchor_id": str(negative["id"]),
                "overlap_ms": overlap,
                "hard_failure": candidate.decision in policy.hard_fail_decisions,
                "policy": policy.md_section_7_row,
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
    prefer: Callable[[CandidateView], bool] | None = None,
) -> ProfileMatching:
    """One-to-one exact-boundary matching within one Profile.

    Each anchor and each candidate contributes at most one hit; augmenting paths
    maximize the number of hits.  Within that, each anchor tries candidates in
    the order: candidates accepted by ``prefer`` (qualified) first, then smallest edge delta, then
    higher score, then candidate ID.  The preference steers which duplicate is
    assigned but does not guarantee a globally optimal set of qualified hits.
    Semantic-only candidates are reported for manual adjudication and never
    counted.
    """

    anchors = gold_anchors(benchmark, profile)
    tolerance = tolerance_ms(benchmark, profile)
    pool = [value for value in candidates if value.profile == profile]
    edges: list[list[int]] = []
    manual: list[dict[str, object]] = []
    for anchor in anchors:
        ranked: list[tuple[int, int, float, str, int]] = []
        for index, candidate in enumerate(pool):
            if not decision_allowed(anchor, candidate):
                continue
            if not duration_allowed(benchmark, profile, candidate.end_ms - candidate.start_ms):
                continue
            metrics = _pair_metrics(anchor, candidate)
            if is_exact_boundary(anchor, candidate, tolerance):
                preferred = 0 if prefer is None or prefer(candidate) else 1
                cost = abs(metrics["start_delta_ms"]) + abs(metrics["end_delta_ms"])
                ranked.append((preferred, cost, -candidate.score, candidate.candidate_id, index))
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
                        "padding": padding_overlaps(benchmark, candidate),
                    }
                )
        edges.append([index for *_, index in sorted(ranked)])
    owner = _maximum_matching(edges)
    matches: list[Match] = []
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
    return ProfileMatching(matches=tuple(matches), manual_adjudication_required=tuple(manual))


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


def bad_start_findings(
    benchmark: Mapping[str, Any], candidates: Iterable[CandidateView]
) -> list[dict[str, object]]:
    """Regressions recording a known-bad opening (``current_bad_start_ms``).

    The candidate Profile is the one whose gold section holds the regression's
    ``preferred_short_anchor``; candidates of that Profile opening within its
    tolerance of the bad start are findings.  ``forbidden`` mirrors the JSON
    ``forbidden_auto_decision`` flag (absent means a finding only).
    """

    findings: list[dict[str, object]] = []
    views = tuple(candidates)
    for regression in benchmark["regressions"]:
        if "current_bad_start_ms" not in regression:
            continue
        preferred = regression.get("preferred_short_anchor")
        profiles = [
            profile
            for profile, section in PROFILE_GOLD_SECTIONS.items()
            if any(anchor["id"] == preferred for anchor in benchmark[section])
        ]
        for profile in profiles:
            tolerance = tolerance_ms(benchmark, profile)
            for value in views:
                if value.profile == profile and (
                    abs(value.start_ms - int(regression["current_bad_start_ms"])) <= tolerance
                ):
                    findings.append(
                        {
                            "regression_id": str(regression["id"]),
                            "candidate_id": value.candidate_id,
                            "profile": value.profile,
                            "decision": value.decision,
                            "start_delta_ms": value.start_ms
                            - int(regression["current_bad_start_ms"]),
                            "forbidden": regression.get("forbidden_auto_decision") is True,
                        }
                    )
    return findings


def manual_or_blocking_risk_tags(benchmark: Mapping[str, Any]) -> frozenset[str]:
    """Risk tags that the benchmark routes only to manual review or blocking.

    Derived from the JSON: tags on risk anchors whose ``required_routing``
    excludes ``selected``, plus tags on gold/supplemental anchors whose
    ``allowed_decisions`` exclude ``selected``, minus any tag that also appears
    on an anchor allowing ``selected``.
    """

    restricted: set[str] = set()
    selectable: set[str] = set()
    for anchor in benchmark["risk_anchors"]:
        if "selected" not in anchor.get("required_routing", ()):
            restricted.update(str(value) for value in anchor.get("risk_tags", ()))
    for section in PADDING_ALLOWANCE_SECTIONS:
        for anchor in benchmark.get(section, ()):
            tags = {str(value) for value in anchor.get("risk_tags", ())}
            if "selected" in anchor.get("allowed_decisions", ()):
                selectable.update(tags)
            else:
                restricted.update(tags)
    return frozenset(restricted - selectable)


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
