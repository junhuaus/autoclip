from __future__ import annotations

import hashlib
import json

import pytest

from liveclip.application.pipeline import PipelineRunConfig, load_persisted_pipeline_config
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.pipeline.semantic_global import (
    BoundaryCompactness,
    CandidateStatus,
    CueRange,
    DiscoveryCandidate,
    DiscoveryOutput,
    DiscoveryTopicUnit,
    NoCandidateReasonCode,
    OpeningRelevance,
    SemanticGlobalConfig,
    SemanticInputMode,
    build_global_review_payload,
    plan_semantic_input,
    semantic_request_tokens,
    validate_discovery_output,
)

_V3_FIELDS = (
    "clipping_algorithm",
    "semantic_skill_version",
    "semantic_skill_sha256",
    "semantic_score_threshold",
)
_V4_FIELDS = (
    "semantic_target_clip_ms",
    "semantic_continuous_merge_enabled",
    "semantic_consolidation_skill_version",
    "semantic_consolidation_skill_sha256",
)
_V5_FIELDS = (
    "semantic_profile",
    "semantic_discovery_skill_version",
    "semantic_discovery_skill_sha256",
    "semantic_global_review_skill_version",
    "semantic_global_review_skill_sha256",
    "semantic_full_context_budget_ratio",
    "semantic_model_context_tokens",
    "semantic_tokenizer_name",
    "semantic_output_reserve_tokens",
    "semantic_safety_margin_tokens",
    "semantic_fallback_target_ms",
    "semantic_fallback_minimum_ms",
    "semantic_fallback_maximum_ms",
    "semantic_fallback_context_guard_ms",
    "semantic_global_context_ms",
    "semantic_no_render",
    "semantic_prompt_debug",
)


def _pipeline_config() -> PipelineRunConfig:
    return PipelineRunConfig(
        provider="mock",
        top_n=15,
        minimum_clip_ms=45_000,
        maximum_clip_ms=90_000,
        chunk_duration_ms=120_000,
        chunk_overlap_ms=10_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=540,
        preview_height=960,
        video_encoder="libx264",
    )


@pytest.mark.parametrize(
    ("version", "removed_fields"),
    (
        ("2", _V3_FIELDS + _V4_FIELDS + _V5_FIELDS),
        ("3", _V4_FIELDS + _V5_FIELDS),
        ("4", _V5_FIELDS),
    ),
)
def test_historical_configs_upgrade_to_provider_aligned_context_reserves(
    version: str,
    removed_fields: tuple[str, ...],
) -> None:
    payload = _pipeline_config().model_dump(mode="json")
    payload["schema_version"] = version
    for field in removed_fields:
        del payload[field]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = load_persisted_pipeline_config(
        payload,
        hashlib.sha256(serialized.encode()).hexdigest(),
    )

    assert restored.semantic_output_reserve_tokens == 16_000
    assert restored.semantic_safety_margin_tokens == 1_000


def test_default_context_reserves_match_provider_output_limit() -> None:
    semantic = SemanticGlobalConfig()
    pipeline = _pipeline_config()

    assert semantic.output_reserve_tokens == 16_000
    assert semantic.safety_margin_tokens == 1_000
    assert pipeline.semantic_output_reserve_tokens == 16_000
    assert pipeline.semantic_safety_margin_tokens == 1_000
    assert semantic.output_reserve_tokens + semantic.safety_margin_tokens == 17_000


def test_rich_global_review_package_uses_compact_semantic_context_at_128k() -> None:
    transcript = _rich_transcript()
    discovery = _rich_discovery(transcript)
    config = SemanticGlobalConfig(model_context_tokens=128_000)
    discovery_prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")
    global_prompt = load_semantic_global_prompt("global_review", "vocal_coach_live")

    plan = plan_semantic_input(
        transcript,
        prompt=discovery_prompt.instructions,
        config=config,
    )
    validated_discovery = validate_discovery_output(
        discovery,
        unit=plan.units[0],
        config=config,
    )
    payload = build_global_review_payload(
        transcript,
        input_plan=plan,
        discovery_outputs=(validated_discovery,),
        config=config,
        prompt=global_prompt.instructions,
    )
    request_tokens = semantic_request_tokens(
        global_prompt.instructions,
        payload,
        config=config,
    )

    assert plan.mode is SemanticInputMode.FULL_CONTEXT
    assert payload["mode"] == "semantic_context"
    assert len(discovery.topic_units) == 60
    assert len(discovery.candidates) == 15
    contexts = payload["evidence"]["semantic_contexts"]
    assert isinstance(contexts, list)
    transported_topics = {topic_id for context in contexts for topic_id in context["topic_ids"]}
    expected_topics = {
        topic.topic_id
        for topic in discovery.topic_units
        if topic.value_density in {"medium", "high"}
    }
    assert transported_topics == expected_topics
    assert request_tokens <= int(config.model_context_tokens * config.full_context_budget_ratio)


def _rich_transcript() -> TranscriptDocument:
    segments = tuple(
        TranscriptSegment(
            segment_id=f"cue_{index:03d}",
            start_ms=(index - 1) * 6_500,
            end_ms=index * 6_500,
            text=_cue_text(index),
        )
        for index in range(1, 721)
    )
    return TranscriptDocument(
        source_duration_ms=segments[-1].end_ms,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=segments,
    )


def _rich_discovery(transcript: TranscriptDocument) -> DiscoveryOutput:
    topics: list[DiscoveryTopicUnit] = []
    candidates: list[DiscoveryCandidate] = []
    for topic_index in range(1, 61):
        topic_start = (topic_index - 1) * 12 + 1
        topic_end = topic_index * 12
        candidate_ids: tuple[str, ...] = ()
        status = CandidateStatus.NO_CANDIDATE
        reason: NoCandidateReasonCode | None = NoCandidateReasonCode.NO_GENERAL_VALUE
        if topic_index <= 15:
            candidate_id = f"candidate_{topic_index:03d}"
            candidate_start = topic_start + 1
            candidate_end = candidate_start + 9
            candidate_ids = (candidate_id,)
            status = CandidateStatus.FOUND
            reason = None
            candidates.append(
                DiscoveryCandidate(
                    candidate_id=candidate_id,
                    parent_topic=f"声乐教学主题{topic_index}: 动作、原因与听感验证",
                    viewer_promise=(
                        f"让陌生观众理解第{topic_index}个常见发声问题, 并掌握可复现的修正步骤"
                    ),
                    content_type="teaching_demonstration",
                    start_cue_id=candidate_start,
                    end_cue_id=candidate_end,
                    hook="同一个音为什么换一个发声动作, 声音就会立刻变得更稳定?",
                    payoff="观众获得错误表现、产生原因、正确动作和自行验证方法的完整答案。",
                    standalone_context=(
                        "片段内部先呈现学员问题, 再由老师完成对比示范、原因解释、练习步骤和"
                        "适用边界, 不依赖直播前文。"
                    ),
                    evidence_cue_ids=(candidate_start, candidate_start + 4, candidate_end),
                    boundary_notes="开始处包含真实问题, 结束处完成总结, 区间连续且没有直播噪声。",
                    source_opening_quote=_cue_text(candidate_start),
                    source_closing_quote=_cue_text(candidate_end),
                    opening_relevance=OpeningRelevance.DIRECT,
                    ending_complete=True,
                    first_complete_payoff_cue_id=candidate_end,
                    minimum_duration_extension_cue_ids=(),
                    boundary_compactness=BoundaryCompactness.SHORTEST_COMPLETE,
                    topic_core_start_cue_id=candidate_start,
                    topic_core_end_cue_id=candidate_end,
                )
            )
        topics.append(
            DiscoveryTopicUnit(
                topic_id=f"topic_{topic_index:03d}",
                start_cue_id=topic_start,
                end_cue_id=topic_end,
                summary=f"第{topic_index}个完整直播话题及其教学展开",
                value_density="high" if topic_index <= 15 else "medium",
                candidate_ids=candidate_ids,
                candidate_status=status,
                no_candidate_reason_code=reason,
            )
        )
    return DiscoveryOutput(
        source_id="rich_128k_regression",
        source_range=CueRange(start_cue_id=1, end_cue_id=len(transcript.segments)),
        topic_units=tuple(topics),
        candidates=tuple(candidates),
    )


def _cue_text(index: int) -> str:
    return f"第{index}句 老师讲发声动作、原因、练习、条件和结论。"
