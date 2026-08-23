from __future__ import annotations

from collections.abc import Callable

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.pipeline.semantic_clipping import (
    KEEP_SEPARATE_RISK,
    NOT_MEANINGFUL_RISK,
    generate_semantic_analysis_windows,
    select_semantic_clips,
)
from liveclip.providers.llm.base import LLMDisposition, LLMProviderResult


def _transcript() -> TranscriptDocument:
    return TranscriptDocument(
        source_duration_ms=240_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"s{index}",
                start_ms=index * 10_000,
                end_ms=(index + 1) * 10_000,
                text=f"第{index}段有时间证据的内容",
            )
            for index in range(24)
        ),
    )


class _SemanticProvider:
    provider_name = "test-agent"
    model_name = "test-model"
    prompt_version = "semantic_window_v1"
    prompt_sha256 = "1" * 64
    contract_version = "test-contract-v1"

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        ordinal = int(candidate.reasons[2].split(":")[1])
        if candidate.source_start_ms >= 180_000:
            score = 0.0
            risk_flags = (NOT_MEANINGFUL_RISK,)
            start_ms, end_ms = candidate.source_start_ms, candidate.source_start_ms + 10_000
        elif candidate.source_start_ms >= 120_000:
            score = 75.0
            risk_flags = ()
            start_ms, end_ms = 120_000, 160_000
        elif candidate.source_start_ms >= 60_000:
            score = 91.0
            risk_flags = ()
            start_ms, end_ms = 70_000, 110_000
        else:
            score = 92.0
            risk_flags = ()
            start_ms, end_ms = 60_000, 110_000
        plan = EditPlan(
            candidate_id=candidate.candidate_id,
            source_start_ms=start_ms,
            source_end_ms=end_ms,
            score=score,
            title=f"语义片段{ordinal}",
            hook="对其他观众也有用的完整观点",
            reason="内容可以独立理解且具有可迁移价值。",
            layout=Layout.CENTER_CROP,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=risk_flags,
            prompt_version=self.prompt_version,
            model=self.model_name,
            degraded=False,
        )
        return LLMProviderResult(plan=plan, disposition=LLMDisposition.SUCCEEDED)


class _ContinuousDiscoveryProvider:
    provider_name = "test-discovery-agent"
    model_name = "test-model"
    prompt_version = "semantic_window_v2"
    prompt_sha256 = "2" * 64
    contract_version = "test-contract-v1"

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        if candidate.allowed_start_ms == 0:
            start_ms, end_ms, score = 90_000, 130_000, 84.0
            risks: tuple[str, ...] = ()
        elif candidate.allowed_start_ms == 60_000:
            start_ms, end_ms, score = 120_000, 170_000, 83.0
            risks = ()
        else:
            start_ms = candidate.allowed_start_ms
            end_ms = candidate.allowed_start_ms + 10_000
            score = 0.0
            risks = (NOT_MEANINGFUL_RISK,)
        return LLMProviderResult(
            plan=EditPlan(
                candidate_id=candidate.candidate_id,
                source_start_ms=start_ms,
                source_end_ms=end_ms,
                score=score,
                title="腹部呼吸连续讲解",
                hook="吸气和呼气时腹部如何运动?",
                reason="回答同一个观众问题, 但内容跨越相邻窗口。",
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=risks,
                prompt_version=self.prompt_version,
                model=self.model_name,
                degraded=False,
            ),
            disposition=LLMDisposition.SUCCEEDED,
        )


class _ContinuousConsolidationProvider:
    provider_name = "test-consolidation-agent"
    model_name = "test-model"
    prompt_version = "semantic_continuous_v1"
    prompt_sha256 = "3" * 64
    contract_version = "test-contract-v1"

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        assert candidate.candidate_id.startswith("merge_b_")
        assert "proposal 1" in candidate.context_before
        assert "proposal 2" in candidate.context_before
        return LLMProviderResult(
            plan=EditPlan(
                candidate_id=candidate.candidate_id,
                source_start_ms=90_000,
                source_end_ms=170_000,
                score=85.0,
                title="吸气与呼气时腹部如何运动",
                hook="吸气外撑、呼气回收, 一次讲清楚。",
                reason="两个候选属于同一连续话题, 重新定界并重新评分。",
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=(),
                prompt_version=self.prompt_version,
                model=self.model_name,
                degraded=False,
            ),
            disposition=LLMDisposition.SUCCEEDED,
        )


class _KeepSeparateProvider(_ContinuousConsolidationProvider):
    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        return LLMProviderResult(
            plan=EditPlan(
                candidate_id=candidate.candidate_id,
                source_start_ms=90_000,
                source_end_ms=130_000,
                score=0.0,
                title="两个独立话题",
                hook="分别保留",
                reason="两个候选各自回答不同的观众问题.",
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=(KEEP_SEPARATE_RISK,),
                prompt_version=self.prompt_version,
                model=self.model_name,
                degraded=False,
            ),
            disposition=LLMDisposition.SUCCEEDED,
        )


def test_algorithm_b_builds_two_length_windows_with_one_length_stride() -> None:
    windows = generate_semantic_analysis_windows(
        _transcript(),
        maximum_clip_ms=60_000,
        minimum_clip_ms=8_000,
    )

    assert [(item.allowed_start_ms, item.allowed_end_ms) for item in windows] == [
        (0, 120_000),
        (60_000, 180_000),
        (120_000, 240_000),
        (180_000, 240_000),
    ]
    assert windows[0].text.startswith("[0,10000]")
    assert "analysis_span_ms:120000" in windows[0].reasons
    assert "analysis_stride_ms:60000" in windows[0].reasons


def test_algorithm_b_v2_uses_target_plus_maximum_windows() -> None:
    windows = generate_semantic_analysis_windows(
        _transcript(),
        maximum_clip_ms=90_000,
        target_clip_ms=60_000,
        minimum_clip_ms=8_000,
    )

    assert [(item.allowed_start_ms, item.allowed_end_ms) for item in windows] == [
        (0, 150_000),
        (60_000, 210_000),
        (120_000, 240_000),
        (180_000, 240_000),
    ]
    assert "target_clip_ms:60000" in windows[0].reasons
    assert "maximum_clip_ms:90000" in windows[0].reasons


def test_algorithm_b_discards_no_value_and_deduplicates_overlap(tmp_path) -> None:
    transcript = _transcript()
    windows = generate_semantic_analysis_windows(
        transcript,
        maximum_clip_ms=60_000,
        minimum_clip_ms=8_000,
    )

    result = select_semantic_clips(
        _SemanticProvider(),
        windows,
        transcript=transcript,
        source_duration_ms=transcript.source_duration_ms,
        minimum_duration_ms=8_000,
        maximum_duration_ms=60_000,
        top_n=15,
        score_threshold=75,
        cache_dir=tmp_path,
    )

    assert len(result.selected) == 1
    assert result.selected[0].result.plan.source_start_ms == 60_000
    assert result.selected[0].result.plan.source_end_ms == 110_000
    assert result.rejected_count == 3


def test_algorithm_b_v2_consolidates_overlapping_continuous_topics(tmp_path) -> None:
    transcript = _transcript()
    windows = generate_semantic_analysis_windows(
        transcript,
        maximum_clip_ms=90_000,
        target_clip_ms=60_000,
        minimum_clip_ms=8_000,
    )

    result = select_semantic_clips(
        _ContinuousDiscoveryProvider(),
        windows,
        transcript=transcript,
        source_duration_ms=transcript.source_duration_ms,
        minimum_duration_ms=8_000,
        maximum_duration_ms=90_000,
        target_duration_ms=60_000,
        top_n=15,
        score_threshold=75,
        cache_dir=tmp_path / "discovery",
        continuous_merge_enabled=True,
        consolidation_provider=_ContinuousConsolidationProvider(),
        consolidation_cache_dir=tmp_path / "continuous",
    )

    assert len(result.selected) == 1
    plan = result.selected[0].result.plan
    assert (plan.source_start_ms, plan.source_end_ms) == (90_000, 170_000)
    assert plan.prompt_version == "semantic_continuous_v1"
    assert result.selected[0].candidate.allowed_start_ms == 60_000
    assert result.rejected_count == 3


def test_algorithm_b_v2_keeps_distinct_continuous_proposals_separate(tmp_path) -> None:
    transcript = _transcript()
    windows = generate_semantic_analysis_windows(
        transcript,
        maximum_clip_ms=90_000,
        target_clip_ms=60_000,
        minimum_clip_ms=8_000,
    )

    result = select_semantic_clips(
        _ContinuousDiscoveryProvider(),
        windows,
        transcript=transcript,
        source_duration_ms=transcript.source_duration_ms,
        minimum_duration_ms=8_000,
        maximum_duration_ms=90_000,
        target_duration_ms=60_000,
        top_n=15,
        score_threshold=75,
        cache_dir=tmp_path / "discovery",
        continuous_merge_enabled=True,
        consolidation_provider=_KeepSeparateProvider(),
        consolidation_cache_dir=tmp_path / "continuous",
    )

    assert [
        (item.result.plan.source_start_ms, item.result.plan.source_end_ms)
        for item in result.selected
    ] == [(90_000, 130_000), (120_000, 170_000)]
