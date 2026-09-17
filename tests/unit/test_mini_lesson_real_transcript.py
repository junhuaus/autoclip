from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from pathlib import Path

from liveclip.clipping_skills.semantic_topic_chain_v1 import (
    load_semantic_topic_chain_prompt,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.semantic_global import (
    SemanticGlobalConfig,
    plan_semantic_windowed_input,
    transcript_cues,
)
from liveclip.pipeline.semantic_profiles import (
    BoundaryEvidenceV4,
    BoundaryReviewV4,
    CandidateGlobalReviewV4,
    ChainCandidateV4,
    ContentDecisionV4,
    DiscoveryCandidateV4,
    GlobalReviewOutputV4,
    LinkRelationshipV4,
    LinkReviewV4,
    MiniLessonScoresV4,
    PublishStatusV4,
    RiskFlagV4,
    TopicChainReviewV4,
    TopicChainStatusV4,
    TopicFragmentV4,
    assemble_topic_chains_v4,
    validate_boundary_review_v4,
    validate_profile_global_review_v4,
    validate_topic_chain_review_v4,
)
from liveclip.pipeline.srt import load_srt_transcript

ROOT = Path(__file__).parents[2]
TRANSCRIPT_PATH = ROOT / "tests/fixtures/8-30-full-transcript.srt"
ANCHORS_PATH = ROOT / "tests/fixtures/8-30-mini-lesson-anchors.json"


def _anchor_cue_range(start_ms: int, end_ms: int) -> tuple[int, int]:
    cues = transcript_cues(load_srt_transcript(TRANSCRIPT_PATH))
    start = min(cues, key=lambda value: (abs(value.start_ms - start_ms), value.cue_id))
    end = min(cues, key=lambda value: (abs(value.end_ms - end_ms), value.cue_id))
    return start.cue_id, end.cue_id


def _fixture_fragments(anchor: dict[str, object]) -> tuple[TopicFragmentV4, ...]:
    transcript = load_srt_transcript(TRANSCRIPT_PATH)
    cues = transcript_cues(transcript)
    start_ms = int(anchor["start_ms"])
    end_ms = int(anchor["end_ms"])
    boundaries = [start_ms]
    while boundaries[-1] + 60_000 < end_ms:
        boundaries.append(boundaries[-1] + 60_000)
    boundaries.append(end_ms)
    values: list[TopicFragmentV4] = []
    for index, (part_start, part_end) in enumerate(pairwise(boundaries), start=1):
        selected = [
            value for value in cues if value.end_ms > part_start and value.start_ms < part_end
        ]
        assert selected
        anchor_id = str(anchor["anchor_id"])
        values.append(
            TopicFragmentV4(
                topic_fragment_id=f"{anchor_id}_fragment_{index:02d}",
                logical_window_id=f"{anchor_id}_window_{index:02d}",
                topic_summary=f"{anchor_id} teaching part {index}",
                central_question=f"What is the central objective of {anchor_id}?",
                learning_outcome=f"Apply the complete lesson for {anchor_id}.",
                start_cue_id=selected[0].cue_id,
                end_cue_id=selected[-1].cue_id,
                touches_left_boundary=index > 1,
                touches_right_boundary=index < len(boundaries) - 1,
                left_complete=index == 1,
                right_complete=index == len(boundaries) - 1,
                evidence_cue_ids=(selected[0].cue_id, selected[-1].cue_id),
                possible_profiles=(ClipProfile.MINI_LESSON,),
                source_batch_id=f"fixture_batch_{start_ms // 240_000:02d}",
            )
        )
    return tuple(values)


def _fixture_link(
    left: TopicFragmentV4,
    right: TopicFragmentV4,
    index: int,
) -> LinkReviewV4:
    return LinkReviewV4(
        link_review_id=f"link_{left.topic_fragment_id}_{index:02d}",
        left_fragment_id=left.topic_fragment_id,
        right_fragment_id=right.topic_fragment_id,
        same_topic=True,
        same_central_objective=True,
        relationship=LinkRelationshipV4.NEXT_STEP_SAME_LESSON,
        merged_topic_summary=left.topic_summary,
        central_question=left.central_question,
        learning_outcome=left.learning_outcome,
        topic_closed_on_right=right.right_complete,
        needs_next_boundary=not right.right_complete,
        evidence_cue_ids=(left.end_cue_id, right.start_cue_id),
        confidence=0.95,
    )


def test_real_transcript_hash_and_multi_batch_window_plan() -> None:
    fixture = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(TRANSCRIPT_PATH.read_bytes()).hexdigest() == fixture["transcript_sha256"]
    transcript = load_srt_transcript(TRANSCRIPT_PATH)
    prompt = load_semantic_topic_chain_prompt(
        "discovery", "vocal_coach_live", ClipProfile.MINI_LESSON
    )
    plan = plan_semantic_windowed_input(
        transcript,
        prompt=prompt.instructions,
        config=SemanticGlobalConfig(
            minimum_duration_ms=90_000,
            target_duration_ms=180_000,
            maximum_duration_ms=300_000,
        ),
    )
    learning_order = fixture["anchors"][1]
    touched_batches = [
        unit
        for unit in plan.units
        if unit.context_range_ms is not None
        and unit.context_range_ms.end_ms > learning_order["start_ms"]
        and unit.context_range_ms.start_ms < learning_order["end_ms"]
    ]
    assert len(touched_batches) >= 2
    assert sum(len(value.logical_windows_ms) for value in touched_batches) >= 4


def test_six_real_anchors_form_complete_audited_profile_results() -> None:
    transcript = load_srt_transcript(TRANSCRIPT_PATH)
    fixture = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    anchors = fixture["anchors"]
    all_fragments: list[TopicFragmentV4] = []
    all_links: list[LinkReviewV4] = []
    discoveries: list[DiscoveryCandidateV4] = []
    for anchor in anchors:
        fragments = _fixture_fragments(anchor)
        all_fragments.extend(fragments)
        all_links.extend(
            _fixture_link(left, right, index)
            for index, (left, right) in enumerate(pairwise(fragments), start=1)
        )
        start_cue_id, end_cue_id = _anchor_cue_range(int(anchor["start_ms"]), int(anchor["end_ms"]))
        discoveries.append(
            DiscoveryCandidateV4(
                candidate_id=f"{anchor['anchor_id']}_discovery",
                source_topic_id=f"{anchor['anchor_id']}_topic",
                topic_fragment_ids=tuple(value.topic_fragment_id for value in fragments),
                topic_summary=str(anchor["anchor_id"]),
                central_question=fragments[0].central_question,
                learning_outcome=fragments[0].learning_outcome,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                evidence_cue_ids=(start_cue_id, end_cue_id),
                possible_profiles=(ClipProfile.MINI_LESSON,),
                risk_flags=tuple(str(value) for value in anchor["risk_flags"]),
                source_window_ids=tuple(value.logical_window_id for value in fragments),
                source_batch_id=fragments[0].source_batch_id,
            )
        )
    assert len(discoveries) == 6
    assert all(value.possible_profiles == (ClipProfile.MINI_LESSON,) for value in discoveries)
    chains = assemble_topic_chains_v4(tuple(all_fragments), tuple(all_links))
    assert len(chains) == 6
    chain_by_prefix = {
        value.fragment_ids[0].split("_fragment_", maxsplit=1)[0]: value for value in chains
    }
    candidates: list[ChainCandidateV4] = []
    boundaries: list[BoundaryReviewV4] = []
    reviews: list[CandidateGlobalReviewV4] = []
    for anchor in anchors:
        anchor_id = str(anchor["anchor_id"])
        chain = chain_by_prefix[anchor_id]
        start_cue_id, end_cue_id = _anchor_cue_range(int(anchor["start_ms"]), int(anchor["end_ms"]))
        candidate = ChainCandidateV4(
            candidate_id=f"{anchor_id}_mini",
            clip_profile=ClipProfile.MINI_LESSON,
            source_topic_id=f"{anchor_id}_topic",
            topic_chain_id=chain.topic_chain_id,
            source_fragment_ids=chain.fragment_ids,
            start_cue_id=start_cue_id,
            end_cue_id=end_cue_id,
            central_question=chain.central_question,
            learning_outcome=chain.learning_outcome,
            title=anchor_id[:40],
            summary=f"Complete fixture lesson for {anchor_id}.",
            evidence_cue_ids=(start_cue_id, end_cue_id),
        )
        chain_review = TopicChainReviewV4(
            topic_chain_id=chain.topic_chain_id,
            central_question=chain.central_question,
            learning_outcome=chain.learning_outcome,
            topic_outline=chain.topic_outline,
            left_closed=True,
            right_closed=True,
            chain_status=TopicChainStatusV4.CLOSED,
            candidates=(candidate,),
            evidence_cue_ids=(start_cue_id, end_cue_id),
        )
        validate_topic_chain_review_v4(chain_review, chain=chain, transcript=transcript)
        boundary = BoundaryReviewV4(
            candidate_id=candidate.candidate_id,
            clip_profile=ClipProfile.MINI_LESSON,
            content_decision=ContentDecisionV4.KEEP,
            proposed_start_cue_id=start_cue_id,
            proposed_end_cue_id=end_cue_id,
            opening_complete=True,
            ending_complete=True,
            central_objective_complete=True,
            boundary_compactness="shortest_complete",
            opening_relevance="necessary_context",
            ending_relevance="necessary_conclusion",
            internal_topic_switch=False,
            contains_padding=False,
            interruption_review=(),
            quality_flags=(),
            risk_flags=tuple(RiskFlagV4(value) for value in anchor["risk_flags"]),
            evidence=BoundaryEvidenceV4(
                opening_cue_ids=(start_cue_id,),
                core_cue_ids=(start_cue_id, end_cue_id),
                ending_cue_ids=(end_cue_id,),
            ),
            review_reason="Fixture Agent found a shortest complete continuous teaching unit.",
        )
        validate_boundary_review_v4(boundary, candidate=candidate, transcript=transcript)
        scores = MiniLessonScoresV4(
            central_objective_clarity=17,
            completeness_and_closure=17,
            teaching_structure=13,
            standalone_understanding=13,
            information_density=9,
            edit_cleanliness=8,
            title_summary_fidelity=8,
        )
        reviews.append(
            CandidateGlobalReviewV4(
                candidate_id=candidate.candidate_id,
                clip_profile=ClipProfile.MINI_LESSON,
                source_topic_id=candidate.source_topic_id,
                topic_chain_id=candidate.topic_chain_id,
                source_fragment_ids=candidate.source_fragment_ids,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                central_question=candidate.central_question,
                learning_outcome=candidate.learning_outcome,
                title=candidate.title,
                summary=candidate.summary,
                content_decision=ContentDecisionV4.KEEP,
                publish_status=PublishStatusV4.AUTO,
                risk_flags=boundary.risk_flags,
                scores=scores,
                total_score=scores.total,
                evidence_cue_ids=(start_cue_id, end_cue_id),
                review_reason="Fixture score tests deterministic Profile gates.",
            )
        )
        candidates.append(candidate)
        boundaries.append(boundary)
    result = validate_profile_global_review_v4(
        GlobalReviewOutputV4(
            clip_profile=ClipProfile.MINI_LESSON,
            reviews=tuple(reviews),
        ),
        candidates=tuple(candidates),
        boundary_reviews=tuple(boundaries),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert [value.review.candidate_id for value in result.selected] == [
        f"{value['anchor_id']}_mini" for value in anchors[:3]
    ]
    assert {value.review.candidate_id for value in result.manual_review} == {
        f"{value['anchor_id']}_mini" for value in anchors[3:]
    }
    assert result.statistics.selected_count == 3
    assert result.statistics.manual_count == 3
    assert not result.rejected
