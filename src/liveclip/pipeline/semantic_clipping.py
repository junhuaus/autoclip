from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment
from liveclip.pipeline.editing import CallRecordsCallback, EditedCandidate, edit_and_rank_candidates
from liveclip.providers.llm.base import LLMDisposition, LLMProvider
from liveclip.providers.telemetry import ProviderCancelled

SEMANTIC_WINDOW_REASON = "algorithm_b_analysis_window"
NOT_MEANINGFUL_RISK = "not_meaningful"
KEEP_SEPARATE_RISK = "keep_separate"
CONTINUOUS_CLUSTER_GAP_MS = 5_000


@dataclass(frozen=True, slots=True)
class SemanticSelection:
    selected: tuple[EditedCandidate, ...]
    rejected_count: int


def generate_semantic_analysis_windows(
    transcript: TranscriptDocument,
    *,
    maximum_clip_ms: int,
    minimum_clip_ms: int,
    target_clip_ms: int | None = None,
) -> tuple[CandidateClip, ...]:
    """Build target+maximum windows at target stride; v1 defaults remain 2L/L."""

    if maximum_clip_ms <= 0 or minimum_clip_ms <= 0:
        raise ValueError("semantic clip durations must be positive")
    if minimum_clip_ms > maximum_clip_ms:
        raise ValueError("semantic minimum clip duration cannot exceed maximum")
    resolved_target_ms = target_clip_ms or maximum_clip_ms
    if not minimum_clip_ms <= resolved_target_ms <= maximum_clip_ms:
        raise ValueError("semantic target duration must be between minimum and maximum")
    window_span_ms = maximum_clip_ms + resolved_target_ms
    windows: list[CandidateClip] = []
    seen_segment_sets: set[tuple[str, ...]] = set()
    schedule_start_ms = 0
    while schedule_start_ms < transcript.source_duration_ms:
        schedule_end_ms = min(
            transcript.source_duration_ms,
            schedule_start_ms + window_span_ms,
        )
        segments = tuple(
            segment
            for segment in transcript.segments
            if segment.start_ms >= schedule_start_ms and segment.end_ms <= schedule_end_ms
        )
        segment_ids = tuple(segment.segment_id for segment in segments)
        if (
            segments
            and segments[-1].end_ms - segments[0].start_ms >= minimum_clip_ms
            and segment_ids not in seen_segment_sets
        ):
            seen_segment_sets.add(segment_ids)
            allowed_start_ms = segments[0].start_ms
            allowed_end_ms = segments[-1].end_ms
            identity = hashlib.sha256(
                (f"b\0{schedule_start_ms}\0{schedule_end_ms}\0" + "\0".join(segment_ids)).encode()
            ).hexdigest()[:24]
            reasons: tuple[str, ...] = (
                SEMANTIC_WINDOW_REASON,
                f"analysis_span_ms:{window_span_ms}",
                f"analysis_stride_ms:{resolved_target_ms}",
            )
            if target_clip_ms is not None:
                reasons += (
                    f"target_clip_ms:{resolved_target_ms}",
                    f"maximum_clip_ms:{maximum_clip_ms}",
                )
            windows.append(
                CandidateClip(
                    candidate_id=f"window_b_{identity}",
                    source_start_ms=allowed_start_ms,
                    source_end_ms=allowed_end_ms,
                    allowed_start_ms=allowed_start_ms,
                    allowed_end_ms=allowed_end_ms,
                    text="\n".join(_timestamped_segment(segment) for segment in segments),
                    context_before="",
                    context_after="",
                    rule_score=80.0,
                    reasons=reasons,
                    segment_ids=segment_ids,
                )
            )
        schedule_start_ms += resolved_target_ms
    return tuple(windows)


def select_semantic_clips(
    provider: LLMProvider,
    windows: Sequence[CandidateClip],
    *,
    transcript: TranscriptDocument,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
    top_n: int,
    score_threshold: float,
    cache_dir: Path,
    target_duration_ms: int | None = None,
    continuous_merge_enabled: bool = False,
    consolidation_provider: LLMProvider | None = None,
    consolidation_cache_dir: Path | None = None,
    cancel_requested: Callable[[], bool] = lambda: False,
    on_call_records: CallRecordsCallback | None = None,
) -> SemanticSelection:
    """Discover semantic clips, optionally consolidate continuous conflicts, then rank."""

    if not windows:
        return SemanticSelection(selected=(), rejected_count=0)
    if cancel_requested():
        raise ProviderCancelled()
    edited = edit_and_rank_candidates(
        provider,
        windows,
        source_duration_ms=source_duration_ms,
        minimum_duration_ms=minimum_duration_ms,
        maximum_duration_ms=maximum_duration_ms,
        top_n=len(windows),
        cache_dir=cache_dir,
        cancel_requested=cancel_requested,
        on_call_records=on_call_records,
    )
    starts = {segment.start_ms for segment in transcript.segments}
    ends = {segment.end_ms for segment in transcript.segments}
    if continuous_merge_enabled:
        if consolidation_provider is None or consolidation_cache_dir is None:
            raise ValueError("continuous semantic merge requires its versioned Agent Skill")
        return _select_with_continuous_merge(
            edited.selected,
            windows=windows,
            transcript=transcript,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            target_duration_ms=target_duration_ms or maximum_duration_ms,
            top_n=top_n,
            score_threshold=score_threshold,
            starts=starts,
            ends=ends,
            provider=consolidation_provider,
            cache_dir=consolidation_cache_dir,
            cancel_requested=cancel_requested,
            on_call_records=on_call_records,
        )
    accepted: list[EditedCandidate] = []
    rejected = 0
    for item in edited.selected:
        plan = item.result.plan
        if (
            item.result.disposition not in {LLMDisposition.SUCCEEDED, LLMDisposition.REPAIRED}
            or plan.degraded
            or plan.score <= score_threshold
            or NOT_MEANINGFUL_RISK in plan.risk_flags
            or plan.source_start_ms not in starts
            or plan.source_end_ms not in ends
            or any(_interval_overlap_ratio(item, existing) >= 0.55 for existing in accepted)
        ):
            rejected += 1
            continue
        accepted.append(item)
        if len(accepted) == top_n:
            break
    rejected += max(0, len(edited.selected) - rejected - len(accepted))
    return SemanticSelection(selected=tuple(accepted), rejected_count=rejected)


def _select_with_continuous_merge(
    discovered: Sequence[EditedCandidate],
    *,
    windows: Sequence[CandidateClip],
    transcript: TranscriptDocument,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
    target_duration_ms: int,
    top_n: int,
    score_threshold: float,
    starts: set[int],
    ends: set[int],
    provider: LLMProvider,
    cache_dir: Path,
    cancel_requested: Callable[[], bool],
    on_call_records: CallRecordsCallback | None,
) -> SemanticSelection:
    qualifying = tuple(
        item
        for item in discovered
        if _is_qualifying(
            item,
            score_threshold=score_threshold,
            starts=starts,
            ends=ends,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
        )
    )
    clusters = _continuous_clusters(
        qualifying,
        maximum_cluster_span_ms=target_duration_ms + maximum_duration_ms,
    )
    final_items: list[EditedCandidate] = []
    merge_candidates: list[CandidateClip] = []
    cluster_by_id: dict[str, tuple[EditedCandidate, ...]] = {}
    for cluster in clusters:
        if len(cluster) == 1:
            final_items.append(cluster[0])
            continue
        candidate = _continuous_cluster_candidate(
            cluster,
            transcript=transcript,
            target_duration_ms=target_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
        )
        merge_candidates.append(candidate)
        cluster_by_id[candidate.candidate_id] = cluster
    if merge_candidates:
        consolidated = edit_and_rank_candidates(
            provider,
            merge_candidates,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            top_n=len(merge_candidates),
            cache_dir=cache_dir,
            cancel_requested=cancel_requested,
            on_call_records=on_call_records,
        )
        for item in consolidated.selected:
            originals = cluster_by_id[item.candidate.candidate_id]
            plan = item.result.plan
            if KEEP_SEPARATE_RISK in plan.risk_flags:
                final_items.extend(originals)
                continue
            if not _is_qualifying(
                item,
                score_threshold=score_threshold,
                starts=starts,
                ends=ends,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
            ):
                continue
            remapped = _remap_consolidated_candidate(item, windows=windows)
            if remapped is not None:
                final_items.append(remapped)
    ranked = sorted(
        final_items,
        key=lambda item: (
            -item.result.plan.score,
            item.result.plan.source_start_ms,
            item.candidate.candidate_id,
        ),
    )
    selected: list[EditedCandidate] = []
    used_candidate_ids: set[str] = set()
    for item in ranked:
        if item.candidate.candidate_id in used_candidate_ids:
            continue
        used_candidate_ids.add(item.candidate.candidate_id)
        selected.append(item)
        if len(selected) == top_n:
            break
    return SemanticSelection(
        selected=tuple(selected),
        rejected_count=max(0, len(discovered) - len(selected)),
    )


def _is_qualifying(
    item: EditedCandidate,
    *,
    score_threshold: float,
    starts: set[int],
    ends: set[int],
    minimum_duration_ms: int,
    maximum_duration_ms: int,
) -> bool:
    plan = item.result.plan
    duration_ms = plan.source_end_ms - plan.source_start_ms
    return (
        item.result.disposition in {LLMDisposition.SUCCEEDED, LLMDisposition.REPAIRED}
        and not plan.degraded
        and plan.score > score_threshold
        and NOT_MEANINGFUL_RISK not in plan.risk_flags
        and KEEP_SEPARATE_RISK not in plan.risk_flags
        and plan.source_start_ms in starts
        and plan.source_end_ms in ends
        and minimum_duration_ms <= duration_ms <= maximum_duration_ms
    )


def _continuous_clusters(
    items: Sequence[EditedCandidate],
    *,
    maximum_cluster_span_ms: int,
) -> tuple[tuple[EditedCandidate, ...], ...]:
    ordered = sorted(
        items,
        key=lambda item: (
            item.result.plan.source_start_ms,
            item.result.plan.source_end_ms,
            item.candidate.candidate_id,
        ),
    )
    clusters: list[list[EditedCandidate]] = []
    for item in ordered:
        plan = item.result.plan
        if not clusters:
            clusters.append([item])
            continue
        current = clusters[-1]
        cluster_start = min(member.result.plan.source_start_ms for member in current)
        cluster_end = max(member.result.plan.source_end_ms for member in current)
        prospective_end = max(cluster_end, plan.source_end_ms)
        if (
            plan.source_start_ms <= cluster_end + CONTINUOUS_CLUSTER_GAP_MS
            and prospective_end - cluster_start <= maximum_cluster_span_ms
        ):
            current.append(item)
        else:
            clusters.append([item])
    return tuple(tuple(cluster) for cluster in clusters)


def _continuous_cluster_candidate(
    cluster: Sequence[EditedCandidate],
    *,
    transcript: TranscriptDocument,
    target_duration_ms: int,
    maximum_duration_ms: int,
) -> CandidateClip:
    union_start = min(item.result.plan.source_start_ms for item in cluster)
    union_end = max(item.result.plan.source_end_ms for item in cluster)
    analysis_span_ms = target_duration_ms + maximum_duration_ms
    context_start = max(0, union_start - max(0, analysis_span_ms - (union_end - union_start)) // 2)
    context_end = min(transcript.source_duration_ms, context_start + analysis_span_ms)
    context_start = max(0, context_end - analysis_span_ms)
    segments = tuple(
        segment
        for segment in transcript.segments
        if segment.start_ms >= context_start and segment.end_ms <= context_end
    )
    if not segments:
        raise ValueError("continuous semantic cluster has no transcript evidence")
    text = "\n".join(_timestamped_segment(segment) for segment in segments)
    if len(text) > 24_000:
        raise ValueError("continuous semantic cluster transcript exceeds its bounded input")
    proposal_summary = "\n".join(
        (
            f"proposal {index}: [{item.result.plan.source_start_ms},"
            f"{item.result.plan.source_end_ms}] score={item.result.plan.score:.1f}; "
            f"title={item.result.plan.title}; reason={item.result.plan.reason}"
        )
        for index, item in enumerate(cluster, start=1)
    )[:4_000]
    identity = hashlib.sha256(
        "\0".join(item.candidate.candidate_id for item in cluster).encode()
    ).hexdigest()[:24]
    return CandidateClip(
        candidate_id=f"merge_b_{identity}",
        source_start_ms=union_start,
        source_end_ms=union_end,
        allowed_start_ms=segments[0].start_ms,
        allowed_end_ms=segments[-1].end_ms,
        text=text,
        context_before=proposal_summary,
        context_after="",
        rule_score=max(item.result.plan.score for item in cluster),
        reasons=(
            "algorithm_b_continuous_cluster",
            f"target_clip_ms:{target_duration_ms}",
            f"maximum_clip_ms:{maximum_duration_ms}",
            f"proposal_count:{len(cluster)}",
        ),
        segment_ids=tuple(segment.segment_id for segment in segments),
    )


def _remap_consolidated_candidate(
    item: EditedCandidate,
    *,
    windows: Sequence[CandidateClip],
) -> EditedCandidate | None:
    plan = item.result.plan
    owners = tuple(
        window
        for window in windows
        if window.allowed_start_ms <= plan.source_start_ms
        and plan.source_end_ms <= window.allowed_end_ms
    )
    if not owners:
        return None
    owner = min(owners, key=lambda value: (value.duration_ms, value.candidate_id))
    remapped_plan = plan.model_copy(update={"candidate_id": owner.candidate_id})
    return EditedCandidate(
        candidate=owner,
        result=item.result.model_copy(update={"plan": remapped_plan}),
        cache_hit=item.cache_hit,
    )


def _timestamped_segment(segment: TranscriptSegment) -> str:
    return f"[{segment.start_ms},{segment.end_ms}] {segment.text}"


def _interval_overlap_ratio(left: EditedCandidate, right: EditedCandidate) -> float:
    left_plan = left.result.plan
    right_plan = right.result.plan
    overlap = max(
        0,
        min(left_plan.source_end_ms, right_plan.source_end_ms)
        - max(left_plan.source_start_ms, right_plan.source_start_ms),
    )
    shorter = min(
        left_plan.source_end_ms - left_plan.source_start_ms,
        right_plan.source_end_ms - right_plan.source_start_ms,
    )
    return overlap / shorter if shorter > 0 else 0.0
