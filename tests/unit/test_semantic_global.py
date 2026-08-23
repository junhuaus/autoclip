# ruff: noqa: RUF001
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, cast

import pytest

import liveclip.services.semantic_evaluation as semantic_evaluation
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)
from liveclip.config.settings import Settings
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.pipeline.semantic_cache import (
    load_semantic_stage_cache,
    semantic_stage_cache_key,
    write_semantic_stage_cache,
)
from liveclip.pipeline.semantic_global import (
    BoundaryAlternativeAudit,
    BoundaryAlternativeCompleteness,
    BoundaryCompactness,
    BoundarySide,
    BoundaryTopicReport,
    CandidateStatus,
    ClipOrigin,
    CoverageDecision,
    CoverageDecisionValue,
    CoverageReasonCode,
    CueRange,
    DiscoveryCandidate,
    DiscoveryOutput,
    DiscoveryTopicUnit,
    EditorialDecision,
    EndCueFunction,
    EndCueSpeakerRole,
    FollowingCueRelation,
    GlobalReviewClip,
    GlobalReviewOutput,
    GlobalReviewSummary,
    NoCandidateReasonCode,
    OpeningRelevance,
    QualityFlag,
    RejectedCandidateGroup,
    ReviewDecision,
    ReviewStatus,
    RiskAssessment,
    RiskSeverity,
    RiskType,
    ScoreDimensions,
    SemanticGlobalConfig,
    SemanticInputMode,
    SourceFidelity,
    TokenEstimator,
    build_global_review_payload,
    discovery_request_payload,
    namespace_discovery_output,
    plan_boundary_bridge_units,
    plan_semantic_input,
    plan_semantic_windowed_input,
    semantic_repair_payload,
    semantic_request_tokens,
    validate_discovery_output,
    validate_global_review,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.providers.llm.structured import (
    MockStructuredLLMProvider,
    StructuredCallResult,
    StructuredProviderError,
    _record,
    _schema_repair_payload,
    _strict_codex_schema,
    _with_codex_reasoning_effort,
)
from liveclip.providers.telemetry import ProviderCallStatus
from liveclip.services.semantic_evaluation import run_semantic_evaluation

ROOT = Path(__file__).resolve().parents[2]
REAL_TRANSCRIPT = ROOT / "tests/fixtures/8-16-3-full-transcript.txt"
REAL_CUES = load_srt_transcript(REAL_TRANSCRIPT).segments


def _from_srt(path: Path = REAL_TRANSCRIPT) -> TranscriptDocument:
    pattern = re.compile(
        r"(?ms)^(\d+)\n(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})\n"
        r"(.*?)(?=\n\n\d+\n|\Z)"
    )
    segments = []
    for cue_id, start, end, text in pattern.findall(path.read_text(encoding="utf-8")):
        segments.append(
            TranscriptSegment(
                segment_id=f"cue_{cue_id}",
                start_ms=_srt_ms(start),
                end_ms=_srt_ms(end),
                text=" ".join(text.strip().splitlines()),
            )
        )
    return TranscriptDocument(
        source_duration_ms=4_660_205,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(segments),
    )


def _srt_ms(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(milliseconds)


def _discovery_candidate(
    *,
    candidate_id: str = "candidate_001",
    start_cue_id: int = 179,
    end_cue_id: int = 193,
    risks: tuple[RiskAssessment, ...] = (),
    opening_relevance: OpeningRelevance = OpeningRelevance.DIRECT,
    topic_core_start_cue_id: int | None = None,
    topic_core_end_cue_id: int | None = None,
    irrelevant_intro_cue_ids: tuple[int, ...] = (),
    irrelevant_outro_cue_ids: tuple[int, ...] = (),
    quality_flags: tuple[QualityFlag, ...] = (),
    source_opening_quote: str = "老师我不知道我这个唱歌的时候肚子到底是往外还是往里的",
    source_closing_quote: str | None = None,
    ending_complete: bool = True,
    first_complete_payoff_cue_id: int | None = None,
    minimum_duration_extension_cue_ids: tuple[int, ...] = (),
    boundary_compactness: BoundaryCompactness = BoundaryCompactness.SHORTEST_COMPLETE,
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        candidate_id=candidate_id,
        parent_topic="唱歌时的呼吸和腹部运动",
        viewer_promise="解释吸气和发声时腹部的运动方向",
        content_type="teaching_demonstration",
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        hook="唱歌时肚子到底往外还是往里",
        payoff="吸气外撑, 呼气和发声时逐渐向内",
        standalone_context="候选包含问题、解释和结论",
        evidence_cue_ids=(start_cue_id, end_cue_id),
        boundary_notes="一个连续话题",
        source_opening_quote=source_opening_quote,
        source_closing_quote=(
            source_closing_quote
            or (
                REAL_CUES[end_cue_id - 1].text
                if 1 <= end_cue_id <= len(REAL_CUES)
                else "不存在的结束 cue"
            )
        ),
        opening_relevance=opening_relevance,
        ending_complete=ending_complete,
        first_complete_payoff_cue_id=(first_complete_payoff_cue_id or end_cue_id),
        minimum_duration_extension_cue_ids=minimum_duration_extension_cue_ids,
        boundary_compactness=boundary_compactness,
        topic_core_start_cue_id=(topic_core_start_cue_id or start_cue_id),
        topic_core_end_cue_id=(topic_core_end_cue_id or end_cue_id),
        irrelevant_intro_cue_ids=irrelevant_intro_cue_ids,
        irrelevant_outro_cue_ids=irrelevant_outro_cue_ids,
        quality_flags=quality_flags,
        risks=risks,
    )


def _discovery(
    transcript: TranscriptDocument,
    candidates: tuple[DiscoveryCandidate, ...] | None = None,
) -> DiscoveryOutput:
    resolved = candidates if candidates is not None else (_discovery_candidate(),)
    return DiscoveryOutput(
        source_id="source_8163",
        source_range=CueRange(start_cue_id=1, end_cue_id=len(transcript.segments)),
        topic_units=(
            DiscoveryTopicUnit(
                topic_id="topic_before_breathing",
                start_cue_id=1,
                end_cue_id=178,
                summary="呼吸教学前的其他直播内容",
                value_density="low",
                candidate_ids=(),
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_breathing",
                start_cue_id=179,
                end_cue_id=193,
                summary="腹部呼吸方向",
                value_density="high",
                candidate_ids=tuple(value.candidate_id for value in resolved),
                candidate_status=(
                    CandidateStatus.FOUND if resolved else CandidateStatus.NO_CANDIDATE
                ),
                no_candidate_reason_code=(
                    None if resolved else NoCandidateReasonCode.NO_GENERAL_VALUE
                ),
            ),
            DiscoveryTopicUnit(
                topic_id="topic_after_breathing",
                start_cue_id=194,
                end_cue_id=len(transcript.segments),
                summary="呼吸教学后的其他直播内容",
                value_density="low",
                candidate_ids=(),
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
        ),
        candidates=resolved,
    )


def _review_clip(
    *,
    clip_id: str = "clip_001",
    start_cue_id: int = 179,
    end_cue_id: int = 193,
    score: ScoreDimensions | None = None,
    decision: ReviewDecision = ReviewDecision.SELECTED,
    risks: tuple[RiskAssessment, ...] = (),
    manual: bool = False,
    source_candidate_ids: tuple[str, ...] = ("candidate_001",),
    source_topic_ids: tuple[str, ...] = ("topic_breathing",),
    origin: ClipOrigin = ClipOrigin.DISCOVERY,
    opening_relevance: OpeningRelevance = OpeningRelevance.DIRECT,
    topic_core_start_cue_id: int | None = None,
    topic_core_end_cue_id: int | None = None,
    irrelevant_intro_cue_ids: tuple[int, ...] = (),
    irrelevant_outro_cue_ids: tuple[int, ...] = (),
    quality_flags: tuple[QualityFlag, ...] = (),
    source_opening_quote: str = "老师我不知道我这个唱歌的时候肚子到底是往外还是往里的",
    viewer_promise_matches_source_opening: bool = True,
    source_closing_quote: str | None = None,
    end_cue_speaker_role: EndCueSpeakerRole = EndCueSpeakerRole.ANSWERER,
    end_cue_function: EndCueFunction = EndCueFunction.SUBSTANTIVE_PAYOFF,
    following_cue_relation: FollowingCueRelation = FollowingCueRelation.OPTIONAL_OR_REDUNDANT,
    ending_complete: bool = True,
    first_complete_payoff_cue_id: int | None = None,
    minimum_duration_extension_cue_ids: tuple[int, ...] = (),
    boundary_compactness: BoundaryCompactness = BoundaryCompactness.SHORTEST_COMPLETE,
    source_fidelity: SourceFidelity = SourceFidelity.FAITHFUL,
) -> GlobalReviewClip:
    return GlobalReviewClip(
        clip_id=clip_id,
        source_candidate_ids=source_candidate_ids,
        source_topic_ids=source_topic_ids,
        origin=origin,
        editorial_decision=(
            EditorialDecision.DROP
            if decision == ReviewDecision.REJECTED
            else EditorialDecision.KEEP
        ),
        review_status=(
            ReviewStatus.MANUAL
            if manual or decision == ReviewDecision.MANUAL_REVIEW
            else ReviewStatus.CLEAR
        ),
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        parent_topic="唱歌时的呼吸和腹部运动",
        viewer_promise="吸气外撑, 呼气和发声时逐渐向内",
        title="唱歌时肚子到底往哪边动",
        content_type="teaching_demonstration",
        hook="唱歌时肚子到底往外还是往里",
        payoff="吸气外撑, 呼气和发声时逐渐向内",
        source_opening_quote=source_opening_quote,
        source_opening_promise="回答唱歌时腹部在不同阶段如何运动",
        viewer_promise_matches_source_opening=viewer_promise_matches_source_opening,
        source_closing_quote=(
            source_closing_quote
            or (
                REAL_CUES[end_cue_id - 1].text
                if 1 <= end_cue_id <= len(REAL_CUES)
                else "不存在的结束 cue"
            )
        ),
        end_cue_speaker_role=end_cue_speaker_role,
        end_cue_function=end_cue_function,
        following_cue_id=(end_cue_id + 1 if end_cue_id < len(REAL_CUES) else None),
        following_cue_quote=(REAL_CUES[end_cue_id].text if end_cue_id < len(REAL_CUES) else None),
        following_cue_relation=(
            following_cue_relation
            if end_cue_id < len(REAL_CUES)
            else FollowingCueRelation.SOURCE_END
        ),
        end_boundary_reason="The following cue is not required to fulfil this promise.",
        opening_relevance=opening_relevance,
        ending_complete=ending_complete,
        first_complete_payoff_cue_id=(first_complete_payoff_cue_id or end_cue_id),
        minimum_duration_extension_cue_ids=minimum_duration_extension_cue_ids,
        boundary_compactness=boundary_compactness,
        source_fidelity=source_fidelity,
        source_fidelity_notes="标题、hook 和 payoff 忠实概括原片立场",
        topic_core_start_cue_id=(topic_core_start_cue_id or start_cue_id),
        topic_core_end_cue_id=(topic_core_end_cue_id or end_cue_id),
        irrelevant_intro_cue_ids=irrelevant_intro_cue_ids,
        irrelevant_outro_cue_ids=irrelevant_outro_cue_ids,
        quality_flags=quality_flags,
        score_dimensions=score
        or ScoreDimensions(
            standalone=19,
            general_value=18,
            interest=17,
            completeness=19,
            evidence=9,
            edit_cleanliness=9,
        ),
        risks=risks,
        review_reason="全局评审保留一个完整连续版本",
    )


def _review(
    *clips: GlobalReviewClip,
    rejected_candidates: tuple[RejectedCandidateGroup, ...] = (),
    coverage_decisions: tuple[CoverageDecision, ...] | None = None,
) -> GlobalReviewOutput:
    resolved_coverage: tuple[CoverageDecision, ...]
    if coverage_decisions is None:
        reference = next((clip for clip in clips if clip.editorial_decision == "keep"), None)
        if reference is None:
            resolved_coverage = (
                CoverageDecision(
                    topic_id="topic_breathing",
                    decision=CoverageDecisionValue.REJECTED,
                    reason_code=CoverageReasonCode.NO_GENERAL_VALUE,
                    reason="全局评审拒绝该话题",
                ),
            )
        else:
            is_manual = reference.review_status == ReviewStatus.MANUAL
            resolved_coverage = (
                CoverageDecision(
                    topic_id="topic_breathing",
                    decision=(
                        CoverageDecisionValue.MANUAL_REVIEW
                        if is_manual
                        else CoverageDecisionValue.REPRESENTED
                    ),
                    clip_ids=(reference.clip_id,),
                    reason_code=(
                        CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW
                        if is_manual
                        else CoverageReasonCode.REPRESENTED_BY_CLIP
                    ),
                    reason="全局评审已覆盖该话题",
                ),
            )
    else:
        resolved_coverage = coverage_decisions
    return GlobalReviewOutput(
        review_summary=GlobalReviewSummary(
            global_notes=(),
        ),
        clips=clips,
        rejected_candidates=rejected_candidates,
        coverage_decisions=resolved_coverage,
        coverage_notes=(),
    )


def _risk(
    risk_type: RiskType,
    *,
    severity: RiskSeverity,
    cue_id: int = 179,
) -> RiskAssessment:
    return RiskAssessment(
        type=risk_type,
        severity=severity,
        reason="测试风险事实",
        source_cue_ids=(cue_id,),
    )


def _topic_discovery(
    transcript: TranscriptDocument,
    *,
    topic_id: str,
    start_cue_id: int,
    end_cue_id: int,
    summary: str,
    value_density: Literal["low", "medium", "high"],
    candidates: tuple[DiscoveryCandidate, ...] = (),
) -> DiscoveryOutput:
    return DiscoveryOutput(
        source_id="source_8163",
        source_range=CueRange(start_cue_id=1, end_cue_id=len(transcript.segments)),
        topic_units=(
            DiscoveryTopicUnit(
                topic_id=topic_id,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                summary=summary,
                value_density=value_density,
                candidate_ids=tuple(value.candidate_id for value in candidates),
                candidate_status=(
                    CandidateStatus.FOUND if candidates else CandidateStatus.NO_CANDIDATE
                ),
                no_candidate_reason_code=(
                    None if candidates else NoCandidateReasonCode.INCOMPLETE_TOPIC
                ),
            ),
        ),
        candidates=candidates,
    )


def test_prompt_bundle_loads_stable_layers_without_eval() -> None:
    discovery = load_semantic_global_prompt("discovery", "vocal_coach_live")
    general = load_semantic_global_prompt("discovery", "general")
    review = load_semantic_global_prompt("global_review", "vocal_coach_live")

    assert discovery.loaded_files == (
        "main.md",
        "common_rules.md",
        "stages/discovery.md",
        "profiles/vocal_coach_live.md",
    )
    assert "evals/8-16-3.md" not in discovery.loaded_files
    assert discovery.sha256 == load_semantic_global_prompt("discovery", "vocal_coach_live").sha256
    assert discovery.sha256 != general.sha256
    assert discovery.sha256 != review.sha256
    assert discovery.instructions.index("# Stable rules") < discovery.instructions.index(
        "# Vocal coach live profile"
    )
    assert "topic unit 是全局目录索引，不是候选的硬边界" in discovery.instructions
    assert "semantic_contexts 已机械合并" in review.instructions
    assert "上位问题反证" in review.instructions
    assert "最短自然范围" in review.instructions
    assert "不能用窄化" in review.instructions
    assert "Python 求和" in review.instructions
    assert "不要返回\nfinal_score" in review.instructions
    assert "不得为了过线抬高分项" in review.repair
    assert "first_complete_payoff_cue_id" in review.instructions
    assert "answerer 与 listener" in review.instructions
    assert "padded_with_irrelevant_content" in review.instructions
    assert "boundary_alternatives" in review.instructions
    assert "following_cue_relation" in review.instructions
    fixture_specific_markers = (
        "8-16-3",
        "clip_008",
        "00:57:54",
        "气球变扁",
        "唱歌时气是不是就走了",
        "第一步找通道、第二步加强通道",
        "前两步很简单",
        "录播收益/规模",
    )
    for marker in fixture_specific_markers:
        assert marker not in discovery.instructions
        assert marker not in review.instructions
        assert marker not in discovery.repair
        assert marker not in review.repair
    with pytest.raises(RuntimeError, match="not installed"):
        load_semantic_global_prompt("discovery", "unknown")


def test_windowed_prompt_bundle_is_compact_versioned_and_profile_specific() -> None:
    vocal = load_semantic_windowed_discovery_prompt("vocal_coach_live")
    general = load_semantic_windowed_discovery_prompt("general")
    full = load_semantic_global_prompt("discovery", "vocal_coach_live")

    assert vocal.version == "semantic_windowed_v1"
    assert vocal.loaded_files == (
        "main.md",
        "common_rules.md",
        "stages/discovery.md",
        "profiles/vocal_coach_live.md",
    )
    assert vocal.sha256 == load_semantic_windowed_discovery_prompt("vocal_coach_live").sha256
    assert vocal.sha256 != general.sha256
    assert len(vocal.instructions) < len(full.instructions)
    assert "120秒" in vocal.instructions
    assert "60秒" in vocal.instructions
    assert "180秒" in vocal.instructions
    assert "最终评分" in vocal.instructions
    assert "ownership_interval_ms" in vocal.instructions
    with pytest.raises(RuntimeError, match="not installed"):
        load_semantic_windowed_discovery_prompt("unknown")  # type: ignore[arg-type]


def test_checked_in_json_schemas_match_runtime_models() -> None:
    schema_root = ROOT / "src/liveclip/schemas/clipping"
    assert json.loads((schema_root / "discovery.schema.json").read_text()) == (
        DiscoveryOutput.model_json_schema(mode="validation")
    )
    assert json.loads((schema_root / "global_review.schema.json").read_text()) == (
        GlobalReviewOutput.model_json_schema(mode="validation")
    )
    candidate_properties = DiscoveryOutput.model_json_schema()["$defs"]["DiscoveryCandidate"][
        "properties"
    ]
    assert "final_score" not in candidate_properties
    assert "score_dimensions" not in candidate_properties
    assert "minimum_duration_extension_cue_ids" in candidate_properties
    review_schema = GlobalReviewOutput.model_json_schema()
    assert set(review_schema["$defs"]["GlobalReviewSummary"]["properties"]) == {"global_notes"}
    assert (
        "minimum_duration_extension_cue_ids"
        in review_schema["$defs"]["GlobalReviewClip"]["properties"]
    )
    assert "following_cue_relation" in review_schema["$defs"]["GlobalReviewClip"]["properties"]
    assert "boundary_alternatives" in review_schema["$defs"]["CoverageDecision"]["properties"]
    assert "final_score" not in review_schema["$defs"]["GlobalReviewClip"]["properties"]
    assert "topic_summary" not in review_schema["$defs"]["CoverageDecision"]["properties"]
    assert "value_density" not in review_schema["$defs"]["CoverageDecision"]["properties"]


def test_codex_schema_adapter_requires_all_properties_and_uses_nullable_values() -> None:
    schema = _strict_codex_schema(DiscoveryOutput.model_json_schema(mode="validation"))
    assert isinstance(schema, dict)

    def assert_strict(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                assert_strict(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert value["additionalProperties"] is False
            assert value["required"] == list(properties)
        assert "default" not in value
        for item in value.values():
            assert_strict(item)

    assert_strict(schema)


def test_semantic_codex_uses_explicit_high_reasoning_without_mutating_base_argv() -> None:
    base = ["codex", "exec", "--strict-config", "--model", "gpt-5.6-sol", "-"]

    configured = _with_codex_reasoning_effort(base, "high")

    assert base == ["codex", "exec", "--strict-config", "--model", "gpt-5.6-sol", "-"]
    assert configured[configured.index("--model") - 2 : configured.index("--model")] == [
        "-c",
        'model_reasoning_effort="high"',
    ]


def test_provider_schema_repair_receives_invalid_output_and_precise_errors() -> None:
    invalid_output = {
        "source_id": "source_8163",
        "topic_units": [{"topic_id": "topic_001"}],
        "candidates": [{"candidate_id": "candidate_001"}],
    }
    error = StructuredProviderError(
        "STRUCTURED_OUTPUT_INVALID",
        (),
        repair_attempts=(
            {
                "phase": "initial",
                "validation_errors": ["topic_units.0.start_cue_id: Field required [missing]"],
                "invalid_output": invalid_output,
            },
        ),
    )
    payload: dict[str, object] = {
        "schema_version": "2",
        "source_id": "source_8163",
        "input_mode": "full_context",
        "input_unit_id": "full_context",
        "source_range": {"start_cue_id": 1, "end_cue_id": 2},
        "runtime": {"minimum_duration_sec": 45, "maximum_duration_sec": 90},
        "cues": [{"cue_id": 1, "original_text": "开始"}, {"cue_id": 2, "original_text": "结束"}],
    }

    repair = _schema_repair_payload(payload, error)

    assert repair["invalid_output"] == invalid_output
    assert "topic_units.0.start_cue_id: Field required [missing]" in cast(
        list[str], repair["validation_errors"]
    )
    assert repair["valid_cue_ids"] == [1, 2]
    assert "cues" not in cast(dict[str, object], repair["immutable_transport_facts"])
    assert "Never return empty arrays" in str(repair["repair_scope"])


def test_real_8163_uses_full_context_with_128k_o200k_budget() -> None:
    transcript = load_srt_transcript(REAL_TRANSCRIPT)
    prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")

    plan = plan_semantic_input(
        transcript,
        prompt=prompt.instructions,
        config=SemanticGlobalConfig(),
    )

    assert len(transcript.segments) == 701
    assert plan.mode == SemanticInputMode.FULL_CONTEXT
    assert len(plan.units) == 1
    assert plan.units[0].source_range == CueRange(start_cue_id=1, end_cue_id=701)
    assert plan.prompt_tokens + plan.transcript_tokens + 17_000 <= plan.budget_tokens


def test_mock_semantic_eval_writes_reproducible_offline_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "semantic-eval"

    result = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=output_dir,
        settings=Settings(ai_provider="mock"),
        provider_mode="mock",
    )

    assert result["input_mode"] == ("discovery_full_context__global_review_semantic_context")
    assert result["cue_count"] == 701
    assert result["agent_call_count"] == 2
    assert result["selected_count"] == 1
    assert result["model_settings"]["reasoning_effort"] == "provider_default"
    assert result["model_settings"]["discovery_reasoning_effort"] == "provider_default"
    assert result["model_settings"]["global_review_reasoning_effort"] == "provider_default"
    assert {path.name for path in output_dir.iterdir()} == {
        "before-after-report.md",
        "discovery-manifest.json",
        "discovery-raw.json",
        "evaluation-ready.md",
        "global-review-agent-raw.json",
        "prompt-debug.json",
        "global-review-raw.json",
        "final-validated.json",
        "run-manifest.json",
        "run-metadata.json",
    }
    final = json.loads((output_dir / "final-validated.json").read_text())
    normalized_review = json.loads((output_dir / "global-review-raw.json").read_text())
    assert final["algorithm"] == "semantic_global"
    assert final["schema_version"] == "3"
    assert final["selected"][0]["final_score"] == 80
    assert final["selected"][0]["start_time"].count(":") == 2
    assert final["selected"][0]["end_time"].count(":") == 2
    assert final["validation_summary"]["rejected_audit"] == {
        "candidate_groups": 0,
        "clips": 0,
        "topics": 0,
    }
    assert final["validation_summary"]["statistics_source"] == "python_final_arrays"
    assert normalized_review["review_summary"] == final["global_review_summary"]
    assert normalized_review["review_summary"] == {
        "discovery_candidate_count": 1,
        "globally_recovered_clip_count": 0,
        "kept_clip_count": 1,
        "selected_clip_count": 1,
        "manual_review_clip_count": 0,
        "rejected_candidate_group_count": 0,
        "rejected_clip_count": 0,
        "rejected_topic_count": 0,
        "global_notes": ["Mock output is not a semantic quality claim."],
    }
    evaluation_ready = (output_dir / "evaluation-ready.md").read_text()
    assert "# semantic_global 可评估切片结果" in evaluation_ready
    assert "## 切片总表" in evaluation_ready
    assert "## 完整源字幕（用于独立检查漏选）" in evaluation_ready
    assert "00:00:00.000" in evaluation_ready
    assert "[cue 701 |" in evaluation_ready
    assert "Agent 调用" in evaluation_ready
    assert "输入 tokens" in evaluation_ready
    assert "话题拒绝" in evaluation_ready


def test_mock_windowed_eval_uses_twenty_batches_and_local_global_context(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "semantic-windowed-eval"

    result = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=output_dir,
        settings=Settings(ai_provider="mock"),
        provider_mode="mock",
        algorithm="semantic_windowed",
    )

    assert result["algorithm"] == "semantic_windowed"
    assert result["discovery_context_mode"] == "windowed"
    assert result["discovery_unit_count"] == 20
    assert result["logical_window_count"] == 78
    assert result["boundary_bridge_call_count"] == 0
    assert result["discovery_call_count"] == 20
    assert result["global_review_call_count"] == 1
    assert result["agent_call_count"] == 21
    assert cast(dict[str, object], result["runtime"])["window_duration_ms"] == 120_000
    assert cast(dict[str, object], result["runtime"])["window_overlap_ms"] == 60_000
    final = json.loads((output_dir / "final-validated.json").read_text())
    assert final["algorithm"] == "semantic_windowed"
    assert final["run_metadata"]["context_mode"] == (
        "discovery_windowed__global_review_semantic_context"
    )
    assert "完整源字幕（用于独立检查漏选）" in (output_dir / "evaluation-ready.md").read_text()

    resumed_dir = tmp_path / "semantic-windowed-resumed"
    resumed = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=resumed_dir,
        settings=Settings(ai_provider="mock"),
        provider_mode="mock",
        algorithm="semantic_windowed",
        discovery_cache_dir=output_dir,
    )
    assert resumed["discovery_reused"] is True
    assert resumed["discovery_call_count"] == 0
    assert resumed["global_review_call_count"] == 1
    assert resumed["agent_call_count"] == 1
    assert cast(dict[str, object], resumed["discovery_reuse"])["reused_batch_count"] == 20


def test_semantic_eval_can_reuse_compatible_discovery_and_rerun_only_global(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "semantic-first"
    second_dir = tmp_path / "semantic-global-only"
    settings = Settings(ai_provider="mock")
    first = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=first_dir,
        settings=settings,
        provider_mode="mock",
    )

    second = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=second_dir,
        settings=settings,
        provider_mode="mock",
        discovery_cache_dir=first_dir,
    )

    assert first["agent_call_count"] == 2
    assert second["discovery_reused"] is True
    assert second["discovery_call_count"] == 0
    assert second["global_review_call_count"] == 1
    assert second["agent_call_count"] == 1
    assert second["discovery_candidate_count"] == first["discovery_candidate_count"]
    assert (second_dir / "discovery-raw.json").read_bytes() == (
        first_dir / "discovery-raw.json"
    ).read_bytes()
    assert "Discovery 复用：`true`" in (second_dir / "evaluation-ready.md").read_text()


def test_semantic_eval_repairs_false_duration_rejection_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    false_duration_review = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(
            global_notes=("模型误称完整呼吸片段超过最长时长",),
        ),
        clips=(),
        rejected_candidates=(
            RejectedCandidateGroup(
                candidate_ids=("candidate_001",),
                topic_ids=("topic_breathing",),
                reason_code=CoverageReasonCode.DURATION_TOO_LONG,
                reason="完整表达预计超过最大时长",
                ideal_start_cue_id=179,
                ideal_end_cue_id=193,
                model_claimed_duration_sec=95,
            ),
        ),
        coverage_decisions=(
            CoverageDecision(
                topic_id="topic_breathing",
                decision=CoverageDecisionValue.REJECTED,
                ideal_start_cue_id=179,
                ideal_end_cue_id=193,
                model_claimed_duration_sec=95,
                reason_code=CoverageReasonCode.DURATION_TOO_LONG,
                reason="完整表达预计超过最大时长",
            ),
        ),
        coverage_notes=(),
    )
    repaired_review = _review(_review_clip())
    providers: list[_FalseDurationProvider] = []

    def provider_factory(
        settings: Settings,
        *,
        prompts: Any,
        mode: str,
        reasoning_effort: str,
    ) -> _FalseDurationProvider:
        del settings, mode, reasoning_effort
        provider = _FalseDurationProvider(
            prompts=prompts,
            discovery=discovery,
            false_duration_review=false_duration_review,
            repaired_review=repaired_review,
        )
        providers.append(provider)
        return provider

    monkeypatch.setattr(semantic_evaluation, "_provider", provider_factory)
    output_dir = tmp_path / "semantic-duration-repair"

    result = run_semantic_evaluation(
        transcript_path=REAL_TRANSCRIPT,
        output_dir=output_dir,
        settings=Settings(ai_provider="mock"),
        provider_mode="configured",
    )

    assert sum(value.repair_calls for value in providers) == 1
    assert result["repair_call_count"] == 1
    assert result["agent_call_count"] == 3
    final = json.loads((output_dir / "final-validated.json").read_text())
    assert final["selected"][0]["start_time_ms"] == 932_500
    assert final["selected"][0]["end_time_ms"] == 1_000_950
    assert final["selected"][0]["duration_sec"] == 68.45
    attempts = json.loads((output_dir / "repair-attempts.json").read_text())
    assert attempts["attempts"][0]["phase"] == "invalid_initial"
    assert attempts["attempts"][1]["phase"] == "repair"


class _FalseDurationProvider:
    provider_name = "test_structured"
    model_name = "test-model"
    contract_version = "test-structured-v1"

    def __init__(
        self,
        *,
        prompts: Any,
        discovery: DiscoveryOutput,
        false_duration_review: GlobalReviewOutput,
        repaired_review: GlobalReviewOutput,
    ) -> None:
        self._prompts = prompts
        self._discovery = discovery
        self._false_duration_review = false_duration_review
        self._repaired_review = repaired_review
        self.repair_calls = 0

    @property
    def prompt_version(self) -> str:
        return self._prompts.version

    @property
    def prompt_sha256(self) -> str:
        return self._prompts.sha256

    def generate(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[Any],
        cancel_requested: Any = lambda: False,
    ) -> StructuredCallResult[Any]:
        del cancel_requested
        output = (
            self._discovery if response_model is DiscoveryOutput else self._false_duration_review
        )
        return StructuredCallResult(
            output=output,
            call_records=(self._call(subject_id, payload, "initial"),),
            repaired=False,
        )

    def repair(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[Any],
        validation_errors: tuple[str, ...],
        cancel_requested: Any = lambda: False,
    ) -> StructuredCallResult[Any]:
        del response_model, validation_errors, cancel_requested
        self.repair_calls += 1
        return StructuredCallResult(
            output=self._repaired_review,
            call_records=(self._call(subject_id, payload, "repair"),),
            repaired=True,
        )

    def _call(
        self,
        subject_id: str,
        payload: dict[str, object],
        phase: str,
    ) -> Any:
        return _record(
            provider=self.provider_name,
            model=self.model_name,
            contract=self.contract_version,
            prompts=self._prompts,
            subject_id=subject_id,
            phase=phase,
            payload=payload,
            status=ProviderCallStatus.SUCCEEDED,
            latency_ms=0,
        )


def test_full_context_ratio_can_select_token_bounded_fallback() -> None:
    transcript = _from_srt()
    prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")
    config = SemanticGlobalConfig(
        model_context_tokens=64_000,
        full_context_budget_ratio=0.30,
        output_reserve_tokens=4_000,
        safety_margin_tokens=2_000,
    )

    plan = plan_semantic_input(transcript, prompt=prompt.instructions, config=config)

    assert plan.mode == SemanticInputMode.FALLBACK
    assert len(plan.units) > 1
    for previous, current in zip(plan.units, plan.units[1:], strict=False):
        assert previous.cues[-1].end_ms - current.cues[0].start_ms >= 115_000
        assert current.cues[0].cue_id < previous.cues[-1].cue_id
        assert (
            previous.cues[-1].end_ms - previous.cues[0].start_ms
            <= config.fallback_maximum_duration_ms
        )
    assert all(unit.estimated_tokens + 6_000 <= plan.budget_tokens for unit in plan.units)
    assert config.fallback_overlap_ms == 120_000


def test_windowed_plan_batches_four_overlapping_logical_windows() -> None:
    transcript = TranscriptDocument(
        source_duration_ms=600_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"cue_{index}",
                start_ms=(index - 1) * 1_000,
                end_ms=index * 1_000,
                text=f"字幕{index}",
            )
            for index in range(1, 601)
        ),
    )
    config = SemanticGlobalConfig()
    plan = plan_semantic_windowed_input(transcript, prompt="短窗口", config=config)

    assert plan.mode == SemanticInputMode.WINDOWED
    assert len(plan.units) == 3
    first, second, last = plan.units
    assert first.context_range_ms.model_dump() == {"start_ms": 0, "end_ms": 300_000}
    assert first.ownership_range_ms.model_dump() == {"start_ms": 0, "end_ms": 240_000}
    assert [value.model_dump() for value in first.logical_windows_ms] == [
        {"start_ms": 0, "end_ms": 120_000},
        {"start_ms": 60_000, "end_ms": 180_000},
        {"start_ms": 120_000, "end_ms": 240_000},
        {"start_ms": 180_000, "end_ms": 300_000},
    ]
    assert second.context_range_ms.start_ms == 240_000
    assert second.ownership_range_ms.start_ms == first.ownership_range_ms.end_ms
    assert last.ownership_range_ms.end_ms == transcript.source_duration_ms
    payload = discovery_request_payload(
        first,
        source_id="source_001",
        mode=plan.mode,
        config=config,
    )
    assert payload["input_mode"] == "windowed"
    assert len(payload["logical_windows_ms"]) == 4


def test_windowed_global_review_uses_candidate_context_not_full_livestream() -> None:
    transcript = load_srt_transcript(REAL_TRANSCRIPT)
    config = SemanticGlobalConfig()
    discovery_prompt = load_semantic_windowed_discovery_prompt("vocal_coach_live")
    plan = plan_semantic_windowed_input(
        transcript,
        prompt=discovery_prompt.instructions,
        config=config,
    )
    provider = MockStructuredLLMProvider(
        prompts=discovery_prompt,
        model_name="mock-llm-v1",
    )
    outputs: list[DiscoveryOutput] = []
    for unit in plan.units:
        payload = discovery_request_payload(
            unit,
            source_id="source_001",
            mode=plan.mode,
            config=config,
        )
        result = provider.generate(
            subject_id=unit.unit_id,
            payload=payload,
            response_model=DiscoveryOutput,
        )
        outputs.append(validate_discovery_output(result.output, unit=unit, config=config))
    first = outputs[0]
    transport_only_topic = DiscoveryTopicUnit(
        topic_id="window_batch_001_transport_only",
        start_cue_id=first.source_range.start_cue_id,
        end_cue_id=first.source_range.start_cue_id,
        summary="仅用于确认候选级审核会移除的低价值运输话题",
        value_density="low",
        candidate_ids=(),
        candidate_status=CandidateStatus.NO_CANDIDATE,
        no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
    )
    outputs[0] = first.model_copy(
        update={"topic_units": (*first.topic_units, transport_only_topic)}
    )

    review_payload = build_global_review_payload(
        transcript,
        input_plan=plan,
        discovery_outputs=tuple(outputs),
        config=config,
        prompt=load_semantic_global_prompt("global_review", "vocal_coach_live").instructions,
    )
    evidence = cast(dict[str, object], review_payload["evidence"])
    discovery = cast(dict[str, object], review_payload["discovery"])

    assert review_payload["mode"] == "semantic_context"
    assert "full_transcript_rows" not in evidence
    assert cast(list[object], evidence["semantic_contexts"])
    assert discovery["review_scope"] == "candidate_topics_and_boundary_bridges"
    review_topics = cast(list[dict[str, object]], discovery["topic_units"])
    assert review_topics
    assert all(
        topic["candidate_ids"]
        or (str(topic["topic_id"]).startswith("bridge_") and topic["value_density"] == "high")
        for topic in review_topics
    )
    assert len(review_topics) == sum(len(output.topic_units) for output in outputs) - 1


def test_window_batch_accepts_cross_window_topic_and_enforces_single_owner() -> None:
    transcript = TranscriptDocument(
        source_duration_ms=600_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"cue_{index}",
                start_ms=(index - 1) * 1_000,
                end_ms=index * 1_000,
                text=f"字幕{index}",
            )
            for index in range(1, 601)
        ),
    )
    config = SemanticGlobalConfig()
    prompt = load_semantic_windowed_discovery_prompt("general")
    plan = plan_semantic_windowed_input(
        transcript,
        prompt=prompt.instructions,
        config=config,
    )
    unit = plan.units[0]
    provider = MockStructuredLLMProvider(prompts=prompt, model_name="mock-llm-v1")
    payload = discovery_request_payload(
        unit,
        source_id="source_001",
        mode=plan.mode,
        config=config,
    )
    original = provider.generate(
        subject_id=unit.unit_id,
        payload=payload,
        response_model=DiscoveryOutput,
    ).output
    candidate = original.candidates[0]
    crossing_candidate = candidate.model_copy(
        update={
            "start_cue_id": 51,
            "end_cue_id": 140,
            "evidence_cue_ids": (51, 140),
            "source_opening_quote": "字幕51",
            "source_closing_quote": "字幕140",
            "first_complete_payoff_cue_id": 140,
            "topic_core_start_cue_id": 51,
            "topic_core_end_cue_id": 140,
        }
    )
    crossing_output = original.model_copy(update={"candidates": (crossing_candidate,)})

    validated = validate_discovery_output(crossing_output, unit=unit, config=config)
    assert validated.candidates[0].start_cue_id == 51
    assert validated.candidates[0].end_cue_id == 140

    non_owner_candidate = crossing_candidate.model_copy(
        update={
            "start_cue_id": 251,
            "end_cue_id": 296,
            "evidence_cue_ids": (251, 296),
            "source_opening_quote": "字幕251",
            "source_closing_quote": "字幕296",
            "first_complete_payoff_cue_id": 296,
            "topic_core_start_cue_id": 251,
            "topic_core_end_cue_id": 296,
        }
    )
    non_owner_output = original.model_copy(update={"candidates": (non_owner_candidate,)})
    with pytest.raises(ValueError, match="outside the batch ownership interval"):
        validate_discovery_output(non_owner_output, unit=unit, config=config)


def test_window_discovery_local_ids_are_namespaced_without_semantic_changes() -> None:
    transcript = load_srt_transcript(REAL_TRANSCRIPT)
    config = SemanticGlobalConfig()
    prompt = load_semantic_windowed_discovery_prompt("general")
    plan = plan_semantic_windowed_input(
        transcript,
        prompt=prompt.instructions,
        config=config,
    )
    unit = plan.units[0]
    provider = MockStructuredLLMProvider(prompts=prompt, model_name="mock-llm-v1")
    payload = discovery_request_payload(
        unit,
        source_id="source_001",
        mode=plan.mode,
        config=config,
    )
    prefixed = provider.generate(
        subject_id=unit.unit_id,
        payload=payload,
        response_model=DiscoveryOutput,
    ).output
    local_candidate_id = "candidate_001"
    local_topic_id = "topic_001"
    local = prefixed.model_copy(
        update={
            "candidates": (
                prefixed.candidates[0].model_copy(update={"candidate_id": local_candidate_id}),
            ),
            "topic_units": (
                prefixed.topic_units[0].model_copy(
                    update={
                        "topic_id": local_topic_id,
                        "candidate_ids": (local_candidate_id,),
                    }
                ),
            ),
        }
    )

    normalized, notes = namespace_discovery_output(local, unit=unit)

    assert notes == (f"namespaced_discovery_ids:{unit.unit_id}",)
    assert normalized.candidates[0].candidate_id == (f"{unit.unit_id}_{local_candidate_id}")
    assert normalized.topic_units[0].topic_id == f"{unit.unit_id}_{local_topic_id}"
    assert normalized.candidates[0].start_cue_id == local.candidates[0].start_cue_id
    assert validate_discovery_output(normalized, unit=unit, config=config) == normalized


def test_namespacing_removes_only_impossible_topic_candidate_reference() -> None:
    transcript = load_srt_transcript(REAL_TRANSCRIPT)
    config = SemanticGlobalConfig()
    prompt = load_semantic_windowed_discovery_prompt("general")
    unit = plan_semantic_windowed_input(
        transcript,
        prompt=prompt.instructions,
        config=config,
    ).units[0]
    provider = MockStructuredLLMProvider(prompts=prompt, model_name="mock-llm-v1")
    output = provider.generate(
        subject_id=unit.unit_id,
        payload=discovery_request_payload(
            unit,
            source_id="source_001",
            mode=SemanticInputMode.WINDOWED,
            config=config,
        ),
        response_model=DiscoveryOutput,
    ).output
    candidate = output.candidates[0]
    impossible = output.topic_units[0].model_copy(
        update={
            "topic_id": "transport_tail",
            "start_cue_id": candidate.end_cue_id + 1,
            "end_cue_id": candidate.end_cue_id + 1,
            "candidate_ids": (candidate.candidate_id,),
        }
    )
    malformed = output.model_copy(update={"topic_units": (*output.topic_units, impossible)})

    normalized, notes = namespace_discovery_output(malformed, unit=unit)

    tail = next(
        topic for topic in normalized.topic_units if topic.topic_id.endswith("transport_tail")
    )
    assert tail.candidate_ids == ()
    assert tail.candidate_status == CandidateStatus.NO_CANDIDATE
    assert tail.no_candidate_reason_code == NoCandidateReasonCode.INVALID_REFERENCE_REMOVED
    assert any(note.startswith("removed_nonoverlapping_candidate_reference:") for note in notes)


def test_one_open_batch_edge_creates_fixed_180_second_bridge() -> None:
    transcript = TranscriptDocument(
        source_duration_ms=600_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"cue_{index}",
                start_ms=(index - 1) * 1_000,
                end_ms=index * 1_000,
                text=f"字幕{index}",
            )
            for index in range(1, 601)
        ),
    )
    config = SemanticGlobalConfig()
    plan = plan_semantic_windowed_input(transcript, prompt="短窗口", config=config)

    outputs: list[DiscoveryOutput] = []
    for index, unit in enumerate(plan.units, start=1):
        right_open = index == 1
        outputs.append(
            DiscoveryOutput(
                source_id="source_001",
                source_range=unit.source_range,
                starts_inside_open_topic=False,
                ends_inside_open_topic=right_open,
                boundary_topics=(
                    BoundaryTopicReport(
                        side=BoundarySide.RIGHT,
                        topic_summary="跨越batch边界的话题",
                        viewer_promise="解释跨边界的完整方法",
                        evidence_cue_ids=(unit.source_range.end_cue_id,),
                        continuation_expected=True,
                        related_candidate_ids=(),
                    ),
                )
                if right_open
                else (),
                topic_units=(
                    DiscoveryTopicUnit(
                        topic_id=f"{unit.unit_id}_topic_001",
                        start_cue_id=unit.source_range.start_cue_id,
                        end_cue_id=unit.source_range.end_cue_id,
                        summary="当前batch内容",
                        value_density="medium" if right_open else "low",
                        candidate_ids=(),
                        candidate_status=CandidateStatus.NO_CANDIDATE,
                        no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
                        ideal_start_cue_id=None,
                        ideal_end_cue_id=None,
                        model_claimed_duration_sec=None,
                    ),
                ),
                candidates=(),
            )
        )
    validated = tuple(
        validate_discovery_output(output, unit=unit, config=config)
        for output, unit in zip(outputs, plan.units, strict=True)
    )
    bridges = plan_boundary_bridge_units(
        transcript,
        input_plan=plan,
        discovery_outputs=validated,
        config=config,
    )

    assert len(bridges) == 1
    bridge = bridges[0]
    assert bridge.bridge_boundary_ms == 240_000
    assert bridge.context_range_ms.model_dump() == {
        "start_ms": 180_000,
        "end_ms": 360_000,
    }
    assert bridge.context_range_ms.end_ms - bridge.context_range_ms.start_ms == 180_000
    assert len(bridge.triggering_boundary_topics) == 1

    prompt = load_semantic_windowed_discovery_prompt("general")
    provider = MockStructuredLLMProvider(prompts=prompt, model_name="mock-llm-v1")
    bridge_payload = discovery_request_payload(
        bridge,
        source_id="source_001",
        mode=SemanticInputMode.BOUNDARY_BRIDGE,
        config=config,
    )
    original = provider.generate(
        subject_id=bridge.unit_id,
        payload=bridge_payload,
        response_model=DiscoveryOutput,
    ).output
    candidate = original.candidates[0].model_copy(
        update={
            "start_cue_id": 201,
            "end_cue_id": 270,
            "evidence_cue_ids": (201, 270),
            "source_opening_quote": "字幕201",
            "source_closing_quote": "字幕270",
            "first_complete_payoff_cue_id": 270,
            "topic_core_start_cue_id": 201,
            "topic_core_end_cue_id": 270,
        }
    )
    crossing = original.model_copy(update={"candidates": (candidate,)})
    assert validate_discovery_output(crossing, unit=bridge, config=config).candidates

    not_crossing_candidate = candidate.model_copy(
        update={
            "start_cue_id": 241,
            "end_cue_id": 300,
            "evidence_cue_ids": (241, 300),
            "source_opening_quote": "字幕241",
            "source_closing_quote": "字幕300",
            "first_complete_payoff_cue_id": 300,
            "topic_core_start_cue_id": 241,
            "topic_core_end_cue_id": 300,
        }
    )
    not_crossing = original.model_copy(update={"candidates": (not_crossing_candidate,)})
    with pytest.raises(ValueError, match="must cross its boundary"):
        validate_discovery_output(not_crossing, unit=bridge, config=config)


def test_discovery_accepts_zero_or_multiple_without_final_score() -> None:
    transcript = _from_srt()
    plan = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
        estimator=TokenEstimator("o200k_base"),
    )
    unit = plan.units[0]
    empty = _discovery(transcript, ())
    multiple = _discovery(
        transcript,
        (
            _discovery_candidate(candidate_id="candidate_001"),
            _discovery_candidate(
                candidate_id="candidate_002",
                start_cue_id=181,
                end_cue_id=193,
                source_opening_quote="你就把我们的小腹想象成一个气球",
            ),
        ),
    )

    assert validate_discovery_output(empty, unit=unit, config=SemanticGlobalConfig()) == empty
    assert (
        len(
            validate_discovery_output(multiple, unit=unit, config=SemanticGlobalConfig()).candidates
        )
        == 2
    )


@pytest.mark.parametrize(
    ("start_cue_id", "end_cue_id", "error"),
    [
        (193, 179, "reversed or empty cue interval"),
        (179, 999, "outside the supplied evidence"),
    ],
)
def test_discovery_rejects_reversed_or_unknown_cue_ids(
    start_cue_id: int,
    end_cue_id: int,
    error: str,
) -> None:
    transcript = _from_srt()
    unit = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    ).units[0]
    output = _discovery(
        transcript,
        (
            _discovery_candidate(
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
            ),
        ),
    )

    with pytest.raises(ValueError, match=error):
        validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig())


def test_discovery_source_range_is_an_exact_transport_fact() -> None:
    transcript = _from_srt()
    unit = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    ).units[0]
    output = _discovery(transcript).model_copy(
        update={"source_range": CueRange(start_cue_id=2, end_cue_id=701)}
    )

    with pytest.raises(ValueError, match=r"expected=\(1, 701\), actual=\(2, 701\)"):
        validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig())


def test_discovery_reports_all_topic_map_gaps_in_one_repair_error() -> None:
    transcript = _from_srt()
    unit = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    ).units[0]
    original = _discovery(transcript)
    output = original.model_copy(
        update={
            "topic_units": (
                original.topic_units[0].model_copy(update={"end_cue_id": 177}),
                original.topic_units[1],
                original.topic_units[2].model_copy(update={"start_cue_id": 195}),
            )
        }
    )

    with pytest.raises(ValueError) as captured:
        validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig())

    assert "(178, 178)" in str(captured.value)
    assert "(194, 194)" in str(captured.value)


def test_provider_schema_preflight_reports_gap_without_audit_only_duration_repair() -> None:
    transcript = _from_srt()
    plan = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    )
    payload = {
        "schema_version": "2",
        "source_id": "source_8163",
        "input_mode": "full_context",
        "input_unit_id": "full_context",
        "source_range": {"start_cue_id": 1, "end_cue_id": 701},
        "runtime": {"minimum_duration_sec": 45, "maximum_duration_sec": 90},
        "cues": [value.model_dump(mode="json") for value in plan.units[0].cues],
    }
    invalid_output = {
        "source_id": "source_8163",
        "source_range": {"start_cue_id": 1, "end_cue_id": 701},
        "topic_units": [
            {
                "topic_id": "topic_before",
                "start_cue_id": 1,
                "end_cue_id": 177,
                "no_candidate_reason_code": "no_general_value",
            },
            {
                "topic_id": "topic_breathing",
                "start_cue_id": 179,
                "end_cue_id": 193,
                "no_candidate_reason_code": "duration_too_long",
                "ideal_start_cue_id": 179,
                "ideal_end_cue_id": 193,
            },
            {
                "topic_id": "topic_after",
                "start_cue_id": 194,
                "end_cue_id": 701,
                "no_candidate_reason_code": "no_general_value",
            },
        ],
        "candidates": [],
    }
    error = StructuredProviderError(
        "STRUCTURED_OUTPUT_INVALID",
        (),
        repair_attempts=(
            {
                "phase": "initial",
                "validation_errors": ["topic_units.1.model_claimed_duration_sec: missing"],
                "invalid_output": invalid_output,
            },
        ),
    )

    repair = _schema_repair_payload(payload, error)
    messages = "\n".join(cast(list[str], repair["validation_errors"]))

    assert "uncovered cue gaps [(178, 178)]" in messages
    assert "duration_too_long conflicts" not in messages


def test_semantic_repair_receives_invalid_output_and_only_bounded_facts() -> None:
    transcript = _from_srt()
    plan = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    )
    request: dict[str, object] = {
        "source_id": "source_8163",
        "input_mode": "full_context",
        "input_unit_id": "full_context",
        "source_range": {"start_cue_id": 1, "end_cue_id": 701},
        "runtime": {"minimum_duration_sec": 45},
        "cues": [cue.model_dump(mode="json") for cue in plan.units[0].cues],
    }
    invalid = _discovery(transcript).model_copy(
        update={"source_range": CueRange(start_cue_id=2, end_cue_id=701)}
    )

    repair = semantic_repair_payload(request, invalid)

    assert repair["repair_only"] is True
    assert repair["valid_cue_ids"] == list(range(1, 702))
    invalid_payload = cast(dict[str, object], repair["invalid_output"])
    invalid_candidates = cast(list[dict[str, object]], invalid_payload["candidates"])
    assert invalid_candidates[0]["candidate_id"] == "candidate_001"
    assert "cues" not in repair
    immutable_facts = cast(dict[str, object], repair["immutable_transport_facts"])
    assert immutable_facts["source_range"] == {
        "start_cue_id": 1,
        "end_cue_id": 701,
    }
    quote_options = cast(list[dict[str, object]], repair["authoritative_boundary_quote_options"])
    first = quote_options[0]
    assert first["item_id"] == "candidate_001"
    assert first["start_cue_id"] == 179
    assert first["end_cue_id"] == 193
    assert REAL_CUES[178].text in cast(list[str], first["exact_opening_quote_options"])
    assert REAL_CUES[192].text in cast(list[str], first["exact_closing_quote_options"])
    assert first["immediate_following_cue_id"] == 194
    assert first["exact_following_cue_quote"] == REAL_CUES[193].text


@pytest.mark.parametrize(
    ("end_ms", "valid"),
    [(45_000, True), (90_000, True), (44_999, False), (90_001, False)],
)
def test_exact_runtime_duration_edges(end_ms: int, valid: bool) -> None:
    transcript = TranscriptDocument(
        source_duration_ms=100_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=(
            TranscriptSegment(segment_id="cue_1", start_ms=0, end_ms=1_000, text="开始"),
            TranscriptSegment(
                segment_id="cue_2",
                start_ms=end_ms - 1_000,
                end_ms=end_ms,
                text="结束",
            ),
        ),
    )
    unit = plan_semantic_input(
        transcript,
        prompt="bounded",
        config=SemanticGlobalConfig(),
    ).units[0]
    candidate = DiscoveryCandidate(
        candidate_id="candidate_edge",
        parent_topic="边界",
        viewer_promise="边界校验",
        content_type="teaching",
        start_cue_id=1,
        end_cue_id=2,
        hook="边界",
        payoff="边界",
        standalone_context="完整",
        evidence_cue_ids=(1, 2),
        boundary_notes="边界",
        source_opening_quote="开始",
        source_closing_quote="结束",
        opening_relevance=OpeningRelevance.DIRECT,
        ending_complete=True,
        first_complete_payoff_cue_id=2,
        minimum_duration_extension_cue_ids=(),
        boundary_compactness=BoundaryCompactness.SHORTEST_COMPLETE,
        topic_core_start_cue_id=1,
        topic_core_end_cue_id=2,
        risks=(),
    )
    output = DiscoveryOutput(
        source_id="edge",
        source_range=CueRange(start_cue_id=1, end_cue_id=2),
        topic_units=(
            DiscoveryTopicUnit(
                topic_id="topic_edge",
                start_cue_id=1,
                end_cue_id=2,
                summary="边界",
                value_density="high",
                candidate_ids=(candidate.candidate_id,),
                candidate_status=CandidateStatus.FOUND,
                no_candidate_reason_code=None,
            ),
        ),
        candidates=(candidate,),
    )
    if valid:
        validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig())
    else:
        with pytest.raises(ValueError, match="duration"):
            validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig())


def test_global_review_recomputes_score_and_uses_exclusive_threshold() -> None:
    transcript = _from_srt()
    discovery = _discovery(
        transcript,
        (
            _discovery_candidate(candidate_id="candidate_075"),
            _discovery_candidate(candidate_id="candidate_076"),
        ),
    )
    score_75 = ScoreDimensions(
        standalone=15,
        general_value=15,
        interest=15,
        completeness=15,
        evidence=8,
        edit_cleanliness=7,
    )
    score_76 = score_75.model_copy(update={"edit_cleanliness": 8})
    output = _review(
        _review_clip(
            clip_id="clip_75",
            score=score_75,
            source_candidate_ids=("candidate_075",),
        ),
        _review_clip(
            clip_id="clip_76",
            score=score_76,
            source_candidate_ids=("candidate_076",),
        ),
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert [value.clip.clip_id for value in result.selected] == ["clip_76"]
    assert [value.clip.clip_id for value in result.rejected] == ["clip_75"]
    assert result.selected[0].final_score == 76
    assert "exclusive_score_gate" in " ".join(result.validation_notes)


def test_global_review_risk_gate_excludes_high_medical_diagnosis_from_selected() -> None:
    transcript = _from_srt()
    medical = _risk(
        RiskType.MEDICAL_DIAGNOSIS_HIGH,
        severity=RiskSeverity.HIGH,
    )
    discovery_candidate = _discovery_candidate(risks=(medical,))
    discovery = _discovery(transcript, (discovery_candidate,))
    output = _review(
        _review_clip(
            risks=(),
            manual=False,
            decision=ReviewDecision.SELECTED,
        )
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert result.selected == ()
    assert len(result.manual_review) == 1
    assert result.manual_review[0].clip.risks == (medical,)


def test_top_n_is_a_stable_ceiling_and_never_pads() -> None:
    transcript = _from_srt()
    candidates = tuple(
        _discovery_candidate(candidate_id=f"candidate_{index:03d}") for index in range(20)
    )
    discovery = _discovery(transcript, candidates)
    clips = tuple(
        _review_clip(
            clip_id=f"clip_{index:03d}",
            source_candidate_ids=(f"candidate_{index:03d}",),
        )
        for index in range(20)
    )

    limited = validate_global_review(
        _review(*clips),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(max_clips=15),
    )
    short = validate_global_review(
        _review(*clips[:7]),
        transcript=transcript,
        discovery_outputs=(_discovery(transcript, candidates[:7]),),
        config=SemanticGlobalConfig(max_clips=15),
    )

    assert len(limited.selected) == 15
    assert [value.clip.clip_id for value in limited.selected] == [
        f"clip_{index:03d}" for index in range(15)
    ]
    assert len(limited.rejected) == 5
    assert all(
        "top_n_ceiling_changed_selected_to_rejected" in value.validation_notes
        for value in limited.rejected
    )
    assert len(short.selected) == 7
    assert short.rejected == ()


def test_breathing_duplicate_regression_keeps_one_global_clip() -> None:
    transcript = _from_srt()
    discovery = _discovery(
        transcript,
        (
            _discovery_candidate(candidate_id="breathing_long", start_cue_id=179),
            _discovery_candidate(candidate_id="breathing_overlap", start_cue_id=181),
        ),
    )
    output = _review(_review_clip(source_candidate_ids=("breathing_long", "breathing_overlap")))

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert len(result.selected) == 1
    assert (result.selected[0].start_ms, result.selected[0].end_ms) == (932_500, 1_000_950)
    assert result.selected[0].duration_ms == 68_450


def test_long_global_review_payload_uses_all_semantic_contexts_and_candidates() -> None:
    transcript = _from_srt()
    discovery_prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")
    review_prompt = load_semantic_global_prompt("global_review", "vocal_coach_live")
    config = SemanticGlobalConfig()
    plan = plan_semantic_input(
        transcript,
        prompt=discovery_prompt.instructions,
        config=config,
    )
    discovery = _discovery(transcript)

    payload = build_global_review_payload(
        transcript,
        input_plan=plan,
        discovery_outputs=(discovery,),
        config=config,
        prompt=review_prompt.instructions,
    )

    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    contexts = cast(list[dict[str, object]], evidence["semantic_contexts"])
    assert 0 < sum(len(cast(list[object], value["cue_rows"])) for value in contexts) < 701
    assert any("candidate_001" in value["candidate_ids"] for value in contexts)
    assert any("topic_breathing" in value["topic_ids"] for value in contexts)
    assert list(payload).index("evidence") < list(payload).index("discovery")
    discovery_payload = cast(dict[str, object], payload["discovery"])
    assert discovery_payload["discovery_candidate_count"] == 1
    candidate = cast(list[dict[str, object]], discovery_payload["candidates"])[0]
    topics = cast(list[dict[str, object]], discovery_payload["topic_units"])
    topic = next(value for value in topics if value["topic_id"] == "topic_breathing")
    assert "candidate_status" not in topic
    assert "no_candidate_reason_code" not in topic
    assert "ideal_start_cue_id" not in topic
    assert candidate["calculated_start_time_ms"] == 932_500
    assert candidate["calculated_end_time_ms"] == 1_000_950
    assert candidate["calculated_duration_sec"] == 68.45
    assert "standalone_context" not in candidate
    assert "boundary_notes" not in candidate
    assert "source_opening_quote" not in candidate
    assert topic["topic_start_time_ms"] == 932_500
    assert topic["topic_end_time_ms"] == 1_000_950
    assert topic["topic_total_duration_sec"] == 68.45
    assert payload["mode"] == "semantic_context"
    assert (
        semantic_request_tokens(review_prompt.instructions, payload, config=config)
        <= config.model_context_tokens * config.full_context_budget_ratio
    )


def test_real_8163_global_review_uses_compact_context_with_fifteen_candidates() -> None:
    transcript = _from_srt()
    discovery_prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")
    review_prompt = load_semantic_global_prompt("global_review", "vocal_coach_live")
    config = SemanticGlobalConfig()
    plan = plan_semantic_input(
        transcript,
        prompt=discovery_prompt.instructions,
        config=config,
    )
    candidates = tuple(
        _discovery_candidate(candidate_id=f"candidate_{index:03d}") for index in range(1, 16)
    )

    payload = build_global_review_payload(
        transcript,
        input_plan=plan,
        discovery_outputs=(_discovery(transcript, candidates),),
        config=config,
        prompt=review_prompt.instructions,
    )

    assert payload["mode"] == "semantic_context"
    contexts = cast(
        list[dict[str, object]],
        cast(dict[str, object], payload["evidence"])["semantic_contexts"],
    )
    transported_candidates = {
        str(candidate_id)
        for context in contexts
        for candidate_id in cast(list[object], context["candidate_ids"])
    }
    assert transported_candidates == {f"candidate_{index:03d}" for index in range(1, 16)}
    assert (
        semantic_request_tokens(review_prompt.instructions, payload, config=config)
        <= config.model_context_tokens * config.full_context_budget_ratio
    )


def test_windowed_global_review_adapts_context_guard_without_dropping_candidates() -> None:
    class GuardBudgetEstimator:
        def count(self, value: str) -> int:
            if '"candidate_context_guard_ms":30000' in value:
                return 10_000
            if '"candidate_context_guard_ms":25000' in value:
                return 9_000
            return 0

    transcript = _from_srt()
    config = SemanticGlobalConfig(
        model_context_tokens=16_000,
        full_context_budget_ratio=0.8,
        output_reserve_tokens=2_000,
        safety_margin_tokens=1_000,
    )
    plan = plan_semantic_windowed_input(transcript, prompt="Discovery", config=config)
    candidates = tuple(
        _discovery_candidate(candidate_id=f"candidate_{index:03d}") for index in range(1, 16)
    )

    payload = build_global_review_payload(
        transcript,
        input_plan=plan,
        discovery_outputs=(_discovery(transcript, candidates),),
        config=config,
        prompt="Global Review",
        estimator=cast(TokenEstimator, GuardBudgetEstimator()),
    )

    evidence = cast(dict[str, object], payload["evidence"])
    assert evidence["candidate_context_guard_ms"] == 25_000
    contexts = cast(list[dict[str, object]], evidence["semantic_contexts"])
    transported_candidates = {
        str(candidate_id)
        for context in contexts
        for candidate_id in cast(list[object], context["candidate_ids"])
    }
    assert transported_candidates == {f"candidate_{index:03d}" for index in range(1, 16)}


def test_false_duration_rejection_for_breathing_uses_python_6845_seconds() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    rejection = RejectedCandidateGroup(
        candidate_ids=("candidate_001",),
        topic_ids=("topic_breathing",),
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="模型错误声称完整呼吸对照超过90秒",
        ideal_start_cue_id=179,
        ideal_end_cue_id=193,
        model_claimed_duration_sec=120,
    )
    coverage = CoverageDecision(
        topic_id="topic_breathing",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="模型错误声称完整呼吸对照超过90秒",
        ideal_start_cue_id=179,
        ideal_end_cue_id=193,
        model_claimed_duration_sec=120,
    )

    with pytest.raises(ValueError, match=r"duration_claim_conflict.*68\.450"):
        validate_global_review(
            _review(
                rejected_candidates=(rejection,),
                coverage_decisions=(coverage,),
            ),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


def test_cross_topic_breathing_duration_claim_uses_the_complete_global_range() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_breathing_answer",
        start_cue_id=181,
        end_cue_id=208,
        summary="呼吸与发声时腹部运动方向",
        value_density="high",
    )
    output = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(),
        clips=(),
        rejected_candidates=(),
        coverage_decisions=(
            CoverageDecision(
                topic_id="topic_breathing_answer",
                decision=CoverageDecisionValue.REJECTED,
                reason_code=CoverageReasonCode.DURATION_TOO_LONG,
                reason="错误地从目录边界开始计算完整对照",
                ideal_start_cue_id=179,
                ideal_end_cue_id=193,
                model_claimed_duration_sec=120,
            ),
        ),
        coverage_notes=(),
    )

    with pytest.raises(ValueError, match=r"duration_claim_conflict.*68\.450"):
        validate_global_review(
            output,
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


def test_overlong_rejection_does_not_require_synthetic_boundary_alternative() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_long",
        start_cue_id=179,
        end_cue_id=198,
        summary="一个超过最长时长的完整话题",
        value_density="high",
    )
    coverage = CoverageDecision(
        topic_id="topic_long",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="完整范围超过运行时上限",
        ideal_start_cue_id=179,
        ideal_end_cue_id=198,
        model_claimed_duration_sec=92.5,
    )
    output = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(),
        clips=(),
        rejected_candidates=(),
        coverage_decisions=(coverage,),
        coverage_notes=(),
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )
    assert result.coverage_decisions[0].reason_code == CoverageReasonCode.DURATION_TOO_LONG


def test_complete_legal_boundary_challenge_remains_optional_audit_evidence() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_long",
        start_cue_id=179,
        end_cue_id=198,
        summary="一个超过最长时长的完整话题",
        value_density="high",
    )
    alternative = BoundaryAlternativeAudit(
        start_cue_id=179,
        end_cue_id=193,
        viewer_promise="用一个更窄但独立的承诺形成完整回答",
        completeness=BoundaryAlternativeCompleteness.COMPLETE,
        reason="这个连续范围已经包含问题、解释和结论",
    )
    coverage = CoverageDecision(
        topic_id="topic_long",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="完整范围超过运行时上限",
        ideal_start_cue_id=179,
        ideal_end_cue_id=198,
        model_claimed_duration_sec=92.5,
        boundary_alternatives=(alternative,),
    )
    output = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(),
        clips=(),
        rejected_candidates=(),
        coverage_decisions=(coverage,),
        coverage_notes=(),
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )
    assert result.coverage_decisions[0].boundary_alternatives == (alternative,)


def test_complete_adjacent_extension_remains_optional_audit_evidence() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_incomplete",
        start_cue_id=179,
        end_cue_id=193,
        summary="一个结尾需要检查紧邻后续字幕的话题",
        value_density="high",
    )
    alternative = BoundaryAlternativeAudit(
        start_cue_id=179,
        end_cue_id=193,
        viewer_promise="延伸到紧邻回答后形成完整承诺",
        completeness=BoundaryAlternativeCompleteness.COMPLETE,
        reason="紧邻的下一条字幕闭合了当前问题",
    )
    coverage = CoverageDecision(
        topic_id="topic_incomplete",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.INCOMPLETE_TOPIC,
        reason="原尝试边界停在未完成的问题",
        ideal_start_cue_id=179,
        ideal_end_cue_id=192,
        model_claimed_duration_sec=55.35,
        boundary_alternatives=(alternative,),
    )
    output = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(),
        clips=(),
        rejected_candidates=(),
        coverage_decisions=(coverage,),
        coverage_notes=(),
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )
    assert result.coverage_decisions[0].boundary_alternatives == (alternative,)


def test_incomplete_rejection_does_not_require_mechanical_adjacent_extension() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_incomplete",
        start_cue_id=179,
        end_cue_id=193,
        summary="一个结尾需要检查紧邻后续字幕的话题",
        value_density="high",
    )
    shorter_only = BoundaryAlternativeAudit(
        start_cue_id=180,
        end_cue_id=191,
        viewer_promise="只检查了原尝试范围的更短前半段",
        completeness=BoundaryAlternativeCompleteness.INCOMPLETE,
        reason="前半段仍然没有结论",
    )
    coverage = CoverageDecision(
        topic_id="topic_incomplete",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
        reason="尝试范围的最后一句没有说完",
        ideal_start_cue_id=179,
        ideal_end_cue_id=192,
        model_claimed_duration_sec=66.35,
        boundary_alternatives=(shorter_only,),
    )

    result = validate_global_review(
        GlobalReviewOutput(
            review_summary=GlobalReviewSummary(),
            clips=(),
            rejected_candidates=(),
            coverage_decisions=(coverage,),
            coverage_notes=(),
        ),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )
    assert result.coverage_decisions[0].boundary_alternatives == (shorter_only,)


def test_rejected_adjacent_topic_does_not_trigger_python_semantic_adjacency_rule() -> None:
    transcript = _from_srt()
    candidate = _discovery_candidate(
        candidate_id="candidate_stage_one",
        start_cue_id=169,
        end_cue_id=180,
        source_opening_quote=REAL_CUES[168].text,
        source_closing_quote=REAL_CUES[179].text,
    )
    discovery = DiscoveryOutput(
        source_id="source_adjacent_stages",
        source_range=CueRange(start_cue_id=1, end_cue_id=len(transcript.segments)),
        topic_units=(
            DiscoveryTopicUnit(
                topic_id="topic_before",
                start_cue_id=1,
                end_cue_id=168,
                summary="之前的其他内容",
                value_density="low",
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_stage_one",
                start_cue_id=169,
                end_cue_id=181,
                summary="同一操作的第一阶段",
                value_density="high",
                candidate_ids=(candidate.candidate_id,),
                candidate_status=CandidateStatus.FOUND,
                no_candidate_reason_code=None,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_stage_two",
                start_cue_id=182,
                end_cue_id=210,
                summary="同一操作的相邻第二阶段",
                value_density="medium",
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_after",
                start_cue_id=211,
                end_cue_id=len(transcript.segments),
                summary="之后的其他内容",
                value_density="low",
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
        ),
        candidates=(candidate,),
    )
    kept = _review_clip(
        clip_id="clip_stage_one",
        start_cue_id=169,
        end_cue_id=180,
        source_candidate_ids=(candidate.candidate_id,),
        source_topic_ids=("topic_stage_one",),
        source_opening_quote=REAL_CUES[168].text,
        source_closing_quote=REAL_CUES[179].text,
    )
    represented = CoverageDecision(
        topic_id="topic_stage_one",
        decision=CoverageDecisionValue.REPRESENTED,
        clip_ids=(kept.clip_id,),
        reason_code=CoverageReasonCode.REPRESENTED_BY_CLIP,
        reason="第一阶段由当前片段表示",
    )
    adjacent_only = BoundaryAlternativeAudit(
        start_cue_id=196,
        end_cue_id=208,
        viewer_promise="只从第二阶段内部检查连续结尾",
        completeness=BoundaryAlternativeCompleteness.INCOMPLETE,
        reason="该范围仍不能形成干净结论",
    )
    rejected = CoverageDecision(
        topic_id="topic_stage_two",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.CANNOT_FORM_CONTINUOUS_CLIP,
        reason="第二阶段被认为无法独立成片",
        ideal_start_cue_id=196,
        ideal_end_cue_id=207,
        model_claimed_duration_sec=79.36,
        boundary_alternatives=(adjacent_only,),
    )

    result = validate_global_review(
        _review(kept, coverage_decisions=(represented, rejected)),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert len(result.selected) == 1
    assert result.coverage_decisions[1].boundary_alternatives == (adjacent_only,)


def test_discovery_candidate_can_span_adjacent_referencing_topics() -> None:
    transcript = _from_srt()
    unit = plan_semantic_input(
        transcript,
        prompt="cross-topic",
        config=SemanticGlobalConfig(),
    ).units[0]
    candidate = _discovery_candidate()
    output = DiscoveryOutput(
        source_id="source_8163",
        source_range=CueRange(start_cue_id=1, end_cue_id=701),
        topic_units=(
            DiscoveryTopicUnit(
                topic_id="topic_before",
                start_cue_id=1,
                end_cue_id=178,
                summary="之前内容",
                value_density="low",
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_question",
                start_cue_id=179,
                end_cue_id=180,
                summary="提出吸气与唱歌腹部方向问题",
                value_density="high",
                candidate_ids=(candidate.candidate_id,),
                candidate_status=CandidateStatus.FOUND,
                no_candidate_reason_code=None,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_answer",
                start_cue_id=181,
                end_cue_id=193,
                summary="完成呼气与发声时内收的答案",
                value_density="high",
                candidate_ids=(candidate.candidate_id,),
                candidate_status=CandidateStatus.FOUND,
                no_candidate_reason_code=None,
            ),
            DiscoveryTopicUnit(
                topic_id="topic_after",
                start_cue_id=194,
                end_cue_id=701,
                summary="之后内容",
                value_density="low",
                candidate_status=CandidateStatus.NO_CANDIDATE,
                no_candidate_reason_code=NoCandidateReasonCode.NO_GENERAL_VALUE,
            ),
        ),
        candidates=(candidate,),
    )

    assert validate_discovery_output(output, unit=unit, config=SemanticGlobalConfig()) == output


def test_false_duration_rejection_for_four_steps_uses_python_8849_seconds() -> None:
    transcript = _from_srt()
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_four_steps",
        start_cue_id=208,
        end_cue_id=244,
        summary="气息使用四步法",
        value_density="high",
    )
    output = GlobalReviewOutput(
        review_summary=GlobalReviewSummary(),
        clips=(),
        rejected_candidates=(),
        coverage_decisions=(
            CoverageDecision(
                topic_id="topic_four_steps",
                decision=CoverageDecisionValue.REJECTED,
                reason_code=CoverageReasonCode.DURATION_TOO_LONG,
                reason="模型错误声称四步法超过90秒",
                ideal_start_cue_id=224,
                ideal_end_cue_id=231,
                model_claimed_duration_sec=120,
            ),
        ),
        coverage_notes=(),
    )

    with pytest.raises(ValueError, match=r"duration_claim_conflict.*88\.490"):
        validate_global_review(
            output,
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


def test_medium_high_coverage_is_mandatory_and_duplicate_requires_target() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    with pytest.raises(ValueError, match="coverage is incomplete"):
        validate_global_review(
            _review(_review_clip(), coverage_decisions=()),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )

    invalid_duplicate = CoverageDecision(
        topic_id="topic_breathing",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.DUPLICATE_OF_OTHER_TOPIC,
        reason="重复话题却没有给出目标",
    )
    with pytest.raises(ValueError, match="duplicate reason requires"):
        validate_global_review(
            _review(_review_clip(), coverage_decisions=(invalid_duplicate,)),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


def test_cue_664_live_intro_cannot_pad_4224_second_topic_core() -> None:
    transcript = _from_srt()
    candidate = _discovery_candidate(
        candidate_id="candidate_noisy",
        start_cue_id=664,
        end_cue_id=667,
        topic_core_start_cue_id=665,
        topic_core_end_cue_id=667,
        irrelevant_intro_cue_ids=(664,),
        quality_flags=(QualityFlag.IRRELEVANT_INTRO,),
        opening_relevance=OpeningRelevance.NECESSARY_CONTEXT,
        source_opening_quote="你怎么小助理怎么不摆在那里呢 拜拜 拜拜",
    )
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_noisy",
        start_cue_id=664,
        end_cue_id=667,
        summary="三种唱法通道重述",
        value_density="medium",
        candidates=(candidate,),
    )
    clip = _review_clip(
        clip_id="clip_007",
        start_cue_id=664,
        end_cue_id=667,
        source_candidate_ids=("candidate_noisy",),
        source_topic_ids=("topic_noisy",),
        topic_core_start_cue_id=665,
        topic_core_end_cue_id=667,
        irrelevant_intro_cue_ids=(664,),
        quality_flags=(QualityFlag.IRRELEVANT_INTRO,),
        opening_relevance=OpeningRelevance.NECESSARY_CONTEXT,
        manual=True,
        source_opening_quote="你怎么小助理怎么不摆在那里呢 拜拜 拜拜",
        score=ScoreDimensions(
            standalone=15,
            general_value=18,
            interest=16,
            completeness=18,
            evidence=8,
            edit_cleanliness=5,
        ),
    )
    coverage = CoverageDecision(
        topic_id="topic_noisy",
        decision=CoverageDecisionValue.REPRESENTED,
        clip_ids=("clip_007",),
        reason_code=CoverageReasonCode.REPRESENTED_BY_CLIP,
        reason="错误地使用直播引入补足时长",
    )

    with pytest.raises(ValueError, match="irrelevant intro cue IDs must precede the selected clip"):
        validate_global_review(
            _review(clip, coverage_decisions=(coverage,)),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


@pytest.mark.parametrize(
    ("flags", "intro_ids", "score", "error"),
    [
        (
            (QualityFlag.IRRELEVANT_INTRO,),
            (179,),
            ScoreDimensions(
                standalone=18,
                general_value=18,
                interest=18,
                completeness=18,
                evidence=9,
                edit_cleanliness=10,
            ),
            "irrelevant intro cue IDs must precede the selected clip",
        ),
        (
            (QualityFlag.CONTEXT_DEPENDENT_OPENING,),
            (),
            ScoreDimensions(
                standalone=13,
                general_value=18,
                interest=18,
                completeness=18,
                evidence=9,
                edit_cleanliness=8,
            ),
            "standalone <= 12",
        ),
        (
            (QualityFlag.TOPIC_NOT_CLOSED,),
            (),
            ScoreDimensions(
                standalone=10,
                general_value=18,
                interest=18,
                completeness=11,
                evidence=9,
                edit_cleanliness=8,
            ),
            "completeness <= 10",
        ),
        (
            (QualityFlag.PADDED_WITH_IRRELEVANT_CONTENT,),
            (),
            ScoreDimensions(
                standalone=18,
                general_value=18,
                interest=18,
                completeness=18,
                evidence=9,
                edit_cleanliness=8,
            ),
            "irrelevant padding cannot be kept",
        ),
    ],
)
def test_quality_flags_constrain_scores_and_keep_decision(
    flags: tuple[QualityFlag, ...],
    intro_ids: tuple[int, ...],
    score: ScoreDimensions,
    error: str,
) -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    clip = _review_clip(
        quality_flags=flags,
        irrelevant_intro_cue_ids=intro_ids,
        topic_core_start_cue_id=180 if intro_ids else 179,
        score=score,
    )

    with pytest.raises(ValueError, match=error):
        validate_global_review(
            _review(clip),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


@pytest.mark.parametrize(
    ("clip", "error"),
    [
        (
            _review_clip(first_complete_payoff_cue_id=192),
            "first payoff already forms a legal",
        ),
        (
            _review_clip(boundary_compactness=BoundaryCompactness.CONTAINS_REMOVABLE_CONTEXT),
            "must use the shortest complete boundary",
        ),
        (
            _review_clip(
                ending_complete=False,
                quality_flags=(QualityFlag.INCOMPLETE_ENDING,),
                score=ScoreDimensions(
                    standalone=10,
                    general_value=18,
                    interest=18,
                    completeness=10,
                    evidence=9,
                    edit_cleanliness=8,
                ),
            ),
            "incomplete ending cannot be kept",
        ),
        (
            _review_clip(
                source_fidelity=SourceFidelity.UNSUPPORTED_REFRAME,
                quality_flags=(QualityFlag.SOURCE_TITLE_MISMATCH,),
            ),
            "unsupported source reframe cannot be kept",
        ),
        (
            _review_clip(
                end_cue_speaker_role=EndCueSpeakerRole.LISTENER,
                end_cue_function=EndCueFunction.LISTENER_RESPONSE,
            ),
            "kept clip must end on payoff",
        ),
        (
            _review_clip(end_cue_speaker_role=EndCueSpeakerRole.UNKNOWN),
            "automatic selection requires an answerer-owned end cue",
        ),
        (
            _review_clip(viewer_promise_matches_source_opening=False),
            "viewer promise must cover the actual source-opening question",
        ),
        (
            _review_clip(
                following_cue_relation=FollowingCueRelation.CONTINUES_SAME_UTTERANCE,
            ),
            "followed by required continuation",
        ),
    ],
)
def test_kept_clip_requires_shortest_complete_and_source_faithful_boundary(
    clip: GlobalReviewClip,
    error: str,
) -> None:
    transcript = _from_srt()

    with pytest.raises(ValueError, match=error):
        validate_global_review(
            _review(clip),
            transcript=transcript,
            discovery_outputs=(_discovery(transcript),),
            config=SemanticGlobalConfig(),
        )


def test_dropped_padded_clip_keeps_invalid_extension_as_audit_evidence() -> None:
    transcript = _from_srt()
    dropped = _review_clip(
        decision=ReviewDecision.REJECTED,
        first_complete_payoff_cue_id=192,
        minimum_duration_extension_cue_ids=(193,),
        topic_core_end_cue_id=192,
        irrelevant_outro_cue_ids=(193,),
        quality_flags=(
            QualityFlag.IRRELEVANT_OUTRO,
            QualityFlag.PADDED_WITH_IRRELEVANT_CONTENT,
        ),
        boundary_compactness=BoundaryCompactness.CONTAINS_REMOVABLE_CONTEXT,
        score=ScoreDimensions(
            standalone=14,
            general_value=12,
            interest=10,
            completeness=10,
            evidence=6,
            edit_cleanliness=3,
        ),
    )

    result = validate_global_review(
        _review(dropped),
        transcript=transcript,
        discovery_outputs=(_discovery(transcript),),
        config=SemanticGlobalConfig(),
    )

    assert result.selected == ()
    assert result.manual_review == ()
    assert len(result.rejected) == 1
    assert result.rejected[0].clip.minimum_duration_extension_cue_ids == (193,)


def test_dropped_clip_may_preserve_out_of_bounds_duration_as_audit_evidence() -> None:
    transcript = _from_srt()
    dropped = _review_clip(
        decision=ReviewDecision.REJECTED,
        end_cue_id=184,
        score=ScoreDimensions(
            standalone=8,
            general_value=8,
            interest=8,
            completeness=6,
            evidence=4,
            edit_cleanliness=5,
        ),
    )

    result = validate_global_review(
        _review(dropped),
        transcript=transcript,
        discovery_outputs=(_discovery(transcript),),
        config=SemanticGlobalConfig(),
    )

    assert result.selected == ()
    assert result.manual_review == ()
    assert len(result.rejected) == 1
    assert result.rejected[0].duration_ms < SemanticGlobalConfig().minimum_duration_ms


def test_repeated_live_cta_blocks_automatic_selection() -> None:
    transcript = _from_srt()
    result = validate_global_review(
        _review(_review_clip(quality_flags=(QualityFlag.REPEATED_LIVE_CTA,))),
        transcript=transcript,
        discovery_outputs=(_discovery(transcript),),
        config=SemanticGlobalConfig(),
    )

    assert result.selected == ()
    assert len(result.manual_review) == 1
    assert "quality_gate_changed_selected_to_manual_review" in (
        result.manual_review[0].validation_notes
    )


def test_rnb_regression_prefers_49_second_direct_question_suffix() -> None:
    transcript = _from_srt()
    discovery_candidate = _discovery_candidate(
        candidate_id="candidate_rnb",
        start_cue_id=505,
        end_cue_id=516,
        topic_core_start_cue_id=505,
        topic_core_end_cue_id=516,
        source_opening_quote=REAL_CUES[504].text,
        source_closing_quote=REAL_CUES[515].text,
    )
    discovery = _topic_discovery(
        transcript,
        topic_id="topic_rnb",
        start_cue_id=503,
        end_cue_id=518,
        summary="R&B风格定位",
        value_density="high",
        candidates=(discovery_candidate,),
    )
    old_context_dependent = _review_clip(
        clip_id="clip_rnb_old",
        start_cue_id=505,
        end_cue_id=516,
        source_candidate_ids=("candidate_rnb",),
        source_topic_ids=("topic_rnb",),
        opening_relevance=OpeningRelevance.NECESSARY_CONTEXT,
        topic_core_start_cue_id=505,
        topic_core_end_cue_id=516,
        source_opening_quote=REAL_CUES[504].text,
        source_closing_quote=REAL_CUES[515].text,
    )
    coverage = CoverageDecision(
        topic_id="topic_rnb",
        decision=CoverageDecisionValue.REPRESENTED,
        clip_ids=("clip_rnb_old",),
        reason_code=CoverageReasonCode.REPRESENTED_BY_CLIP,
        reason="旧边界错误地保留片段外承接内容",
    )

    with pytest.raises(ValueError, match="automatic selection requires a direct source opening"):
        validate_global_review(
            _review(old_context_dependent, coverage_decisions=(coverage,)),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )

    corrected = _review_clip(
        clip_id="clip_rnb_direct",
        start_cue_id=509,
        end_cue_id=517,
        source_candidate_ids=("candidate_rnb",),
        source_topic_ids=("topic_rnb",),
        opening_relevance=OpeningRelevance.DIRECT,
        topic_core_start_cue_id=509,
        topic_core_end_cue_id=517,
        source_opening_quote=REAL_CUES[508].text,
        source_closing_quote=REAL_CUES[516].text,
        first_complete_payoff_cue_id=516,
        minimum_duration_extension_cue_ids=(517,),
    )
    corrected_coverage = coverage.model_copy(update={"clip_ids": ("clip_rnb_direct",)})
    result = validate_global_review(
        _review(corrected, coverage_decisions=(corrected_coverage,)),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert len(result.selected) == 1
    assert result.selected[0].start_ms == 3_474_550
    assert result.selected[0].end_ms == 3_523_550
    assert result.selected[0].duration_ms == 49_000


def test_global_risk_evidence_outside_rebound_clip_names_the_clip_for_repair() -> None:
    transcript = _from_srt()
    outside = RiskAssessment(
        type=RiskType.ABSOLUTE_CLAIM,
        severity=RiskSeverity.HIGH,
        reason="边界移动前的风险证据",
        source_cue_ids=(178,),
    )

    with pytest.raises(
        ValueError,
        match=r"clip_id=clip_001: risk source cue IDs must stay inside",
    ):
        validate_global_review(
            _review(_review_clip(risks=(outside,))),
            transcript=transcript,
            discovery_outputs=(_discovery(transcript),),
            config=SemanticGlobalConfig(),
        )


def test_final_validation_deduplicates_same_risk_fact_from_both_stages() -> None:
    transcript = _from_srt()
    discovery_risk = RiskAssessment(
        type=RiskType.GENERAL_HEALTH_WARNING,
        severity=RiskSeverity.LOW,
        reason="唱法不当可能使声带疲劳",
        source_cue_ids=(179,),
    )
    review_risk = discovery_risk.model_copy(update={"reason": "不当发声可能使声带疲劳"})
    discovery = _discovery(
        transcript,
        (_discovery_candidate(risks=(discovery_risk,)),),
    )
    result = validate_global_review(
        _review(_review_clip(risks=(review_risk,))),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert len(result.selected) == 1
    assert len(result.selected[0].clip.risks) == 1
    assert result.selected[0].clip.risks[0].source_cue_ids == (179,)
    assert "不当发声可能使声带疲劳" in result.selected[0].clip.risks[0].reason
    assert "唱法不当可能使声带疲劳" in result.selected[0].clip.risks[0].reason
    assert "duplicate_risks_removed" in result.selected[0].validation_notes


def test_final_validation_merges_same_risk_type_at_highest_severity() -> None:
    transcript = _from_srt()
    discovery_risk = RiskAssessment(
        type=RiskType.SENSITIVITY_REVIEW,
        severity=RiskSeverity.LOW,
        reason="涉及地域音色",
        source_cue_ids=(179,),
    )
    review_risk = RiskAssessment(
        type=RiskType.SENSITIVITY_REVIEW,
        severity=RiskSeverity.HIGH,
        reason="标题可能强化地域归因",
        source_cue_ids=(180,),
    )
    discovery = _discovery(
        transcript,
        (_discovery_candidate(risks=(discovery_risk,)),),
    )

    result = validate_global_review(
        _review(_review_clip(risks=(review_risk,))),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert result.selected == ()
    merged = result.manual_review[0].clip.risks
    assert len(merged) == 1
    assert merged[0].type == RiskType.SENSITIVITY_REVIEW
    assert merged[0].severity == RiskSeverity.HIGH
    assert merged[0].source_cue_ids == (179, 180)
    assert "涉及地域音色" in merged[0].reason
    assert "标题可能强化地域归因" in merged[0].reason


@pytest.mark.parametrize(
    ("risk_type", "severity", "expected_decision"),
    [
        (RiskType.GENERAL_HEALTH_WARNING, RiskSeverity.LOW, ReviewDecision.SELECTED),
        (RiskType.GENERAL_HEALTH_WARNING, RiskSeverity.MEDIUM, ReviewDecision.MANUAL_REVIEW),
        (RiskType.MEDICAL_DIAGNOSIS_HIGH, RiskSeverity.HIGH, ReviewDecision.MANUAL_REVIEW),
        (RiskType.MUSIC_RIGHTS_REVIEW, RiskSeverity.LOW, ReviewDecision.MANUAL_REVIEW),
    ],
)
def test_structured_risk_policy_distinguishes_low_warning_and_manual_risks(
    risk_type: RiskType,
    severity: RiskSeverity,
    expected_decision: ReviewDecision,
) -> None:
    transcript = _from_srt()
    risk = _risk(risk_type, severity=severity)
    discovery = _discovery(
        transcript,
        (_discovery_candidate(risks=(risk,)),),
    )
    result = validate_global_review(
        _review(_review_clip()),
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )
    actual = (
        ReviewDecision.SELECTED
        if result.selected
        else ReviewDecision.MANUAL_REVIEW
        if result.manual_review
        else ReviewDecision.REJECTED
    )
    assert actual == expected_decision
    preserved = (result.selected or result.manual_review)[0]
    assert preserved.clip.risks == (risk,)


def test_raw_rejection_and_coverage_are_preserved_for_final_assembly() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    incomplete_alternative = BoundaryAlternativeAudit(
        start_cue_id=179,
        end_cue_id=193,
        viewer_promise="审计不同的合法连续边界",
        completeness=BoundaryAlternativeCompleteness.INCOMPLETE,
        reason="结构测试中的Agent判断仍缺少必要上下文",
    )
    rejection = RejectedCandidateGroup(
        candidate_ids=("candidate_001",),
        topic_ids=("topic_breathing",),
        reason_code=CoverageReasonCode.INCOMPLETE_TOPIC,
        reason="候选只有前半段,没有完整结论",
        ideal_start_cue_id=179,
        ideal_end_cue_id=192,
        model_claimed_duration_sec=66.35,
        boundary_alternatives=(incomplete_alternative,),
    )
    coverage = CoverageDecision(
        topic_id="topic_breathing",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.INCOMPLETE_TOPIC,
        reason="候选只有前半段,没有完整结论",
        ideal_start_cue_id=179,
        ideal_end_cue_id=192,
        model_claimed_duration_sec=66.35,
        boundary_alternatives=(incomplete_alternative,),
    )
    output = _review(
        rejected_candidates=(rejection,),
        coverage_decisions=(coverage,),
    )

    result = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert result.rejected_candidates == (rejection,)
    assert result.coverage_decisions[0].topic_id == coverage.topic_id
    assert result.coverage_decisions[0].topic_summary == "腹部呼吸方向"
    assert result.coverage_decisions[0].value_density == "high"
    assert result.coverage_decisions[0].actual_duration_sec == 66.35
    assert result.global_review_summary.rejected_candidate_group_count == 1
    assert result.global_review_summary.discovery_candidate_count == 1
    assert result.global_review_summary.kept_clip_count == 0


def test_risk_review_reason_cannot_drop_editorial_value() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    rejection = RejectedCandidateGroup(
        candidate_ids=("candidate_001",),
        topic_ids=("topic_breathing",),
        reason_code=CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW,
        reason="内容有价值但需要人工审核",
    )
    coverage = CoverageDecision(
        topic_id="topic_breathing",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.RISK_REQUIRES_MANUAL_REVIEW,
        reason="内容有价值但需要人工审核",
    )

    with pytest.raises(ValueError, match="risk requiring review cannot"):
        validate_global_review(
            _review(rejected_candidates=(rejection,), coverage_decisions=(coverage,)),
            transcript=transcript,
            discovery_outputs=(discovery,),
            config=SemanticGlobalConfig(),
        )


def test_summary_statistics_are_derived_from_final_arrays_not_agent_counts() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    output = _review(
        _review_clip(decision=ReviewDecision.MANUAL_REVIEW),
        _review_clip(
            clip_id="clip_recovered",
            decision=ReviewDecision.MANUAL_REVIEW,
            source_candidate_ids=(),
            origin=ClipOrigin.GLOBAL_REVIEW_RECOVERY,
        ),
    )

    validated = validate_global_review(
        output,
        transcript=transcript,
        discovery_outputs=(discovery,),
        config=SemanticGlobalConfig(),
    )

    assert len(validated.manual_review) == 2
    assert validated.global_review_summary.discovery_candidate_count == 1
    assert validated.global_review_summary.globally_recovered_clip_count == 1
    assert validated.global_review_summary.kept_clip_count == 2
    assert validated.global_review_summary.selected_clip_count == 0
    assert validated.global_review_summary.manual_review_clip_count == 2
    assert validated.global_review_summary.rejected_candidate_group_count == 0


def test_repair_payload_reads_fallback_candidate_contexts_and_keeps_error_facts() -> None:
    transcript = _from_srt()
    discovery = _discovery(transcript)
    rejection = RejectedCandidateGroup(
        candidate_ids=("candidate_001",),
        topic_ids=("topic_breathing",),
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="模型错误声称超时",
        ideal_start_cue_id=179,
        ideal_end_cue_id=193,
        model_claimed_duration_sec=120,
    )
    coverage = CoverageDecision(
        topic_id="topic_breathing",
        decision=CoverageDecisionValue.REJECTED,
        reason_code=CoverageReasonCode.DURATION_TOO_LONG,
        reason="模型错误声称超时",
        ideal_start_cue_id=179,
        ideal_end_cue_id=193,
        model_claimed_duration_sec=120,
    )
    invalid = _review(
        rejected_candidates=(rejection,),
        coverage_decisions=(coverage,),
    )
    cues = [
        {
            "cue_id": index,
            "start_ms": transcript.segments[index - 1].start_ms,
            "end_ms": transcript.segments[index - 1].end_ms,
            "original_text": transcript.segments[index - 1].text,
        }
        for index in range(176, 197)
    ]
    payload: dict[str, object] = {
        "mode": "fallback",
        "runtime": {"minimum_duration_sec": 45, "maximum_duration_sec": 90},
        "discovery": {
            "topic_units": [value.model_dump(mode="json") for value in discovery.topic_units],
            "candidates": [value.model_dump(mode="json") for value in discovery.candidates],
        },
        "evidence": {
            "candidate_contexts": [
                {
                    "context_id": "context_001",
                    "candidate_ids": ["candidate_001"],
                    "cues": cues,
                }
            ]
        },
    }
    error = (
        "duration_claim_conflict topic_id=topic_breathing "
        "actual_duration_sec=68.450; Python is authoritative"
    )

    repair = semantic_repair_payload(payload, invalid, validation_errors=(error,))

    assert repair["validation_errors"] == [error]
    assert repair["valid_cue_ids"] == list(range(176, 197))
    assert repair["valid_discovery_candidate_ids"] == ["candidate_001"]
    affected = cast(list[dict[str, object]], repair["affected_evidence"])
    assert {value["cue_id"] for value in affected} >= {179, 193}
    authoritative = cast(dict[str, object], repair["authoritative_discovery"])
    candidates = cast(list[dict[str, object]], authoritative["candidates"])
    assert candidates[0]["candidate_id"] == "candidate_001"


def test_semantic_stage_cache_is_stage_prompt_and_input_scoped(tmp_path: Path) -> None:
    transcript = _from_srt()
    output = _discovery(transcript)
    prompt = load_semantic_global_prompt("discovery", "vocal_coach_live")
    provider = MockStructuredLLMProvider(prompts=prompt, model_name="mock-llm-v1")
    payload: dict[str, object] = {
        "source_hash": "a" * 64,
        "algorithm": "semantic_global",
        "mode": "full_context",
        "source_range": {"start_cue_id": 1, "end_cue_id": 701},
    }
    settings: dict[str, object] = {"context_tokens": 128_000, "temperature": 0}
    key = semantic_stage_cache_key(
        stage="discovery",
        payload=payload,
        provider=provider,
        model_settings=settings,
        output_model=DiscoveryOutput,
    )

    write_semantic_stage_cache(
        cache_dir=tmp_path,
        cache_key=key,
        stage="discovery",
        payload=payload,
        provider=provider,
        model_settings=settings,
        output=output,
    )

    assert (
        load_semantic_stage_cache(
            cache_dirs=(tmp_path,),
            cache_key=key,
            stage="discovery",
            payload=payload,
            provider=provider,
            model_settings=settings,
            output_model=DiscoveryOutput,
        )
        == output
    )
    changed_payload = {**payload, "mode": "fallback"}
    assert (
        semantic_stage_cache_key(
            stage="discovery",
            payload=changed_payload,
            provider=provider,
            model_settings=settings,
            output_model=DiscoveryOutput,
        )
        != key
    )
