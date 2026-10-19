from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from liveclip.agent_runtime import (
    AgentArtifact,
    AgentEvent,
    AgentHarness,
    AgentModelResponse,
    AgentObservation,
    AgentRunCancelled,
    AgentRunJournal,
    AgentRunLimitError,
    AgentRunLimits,
    AgentToolResult,
    AgentTurn,
    ArtifactStore,
    ToolRegistry,
    ToolSpec,
    load_agent_skill_directory,
    load_packaged_agent_skill,
)
from liveclip.agent_runtime.context import build_agent_payload
from liveclip.agent_tools.clipping import (
    ClippingTechnicalConfig,
    build_clipping_tool_registry,
    validate_clip_artifact,
    validate_clipping_artifacts,
)
from liveclip.agent_tools.subtitle_calibration import (
    ASRSubtitleCalibrationBackend,
    SubtitleCalibrationError,
)
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.media.models import AudioChunk
from liveclip.providers.asr.base import (
    ASRChunkResult,
    AudioChunkLike,
    LocalASRSegment,
    open_validated_audio_chunk,
)
from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment


class _ScriptedModel:
    provider_name = "scripted"
    model_name = "scripted-agent"

    def __init__(
        self,
        turns: tuple[AgentTurn, ...],
        *,
        variant: str = "default",
    ) -> None:
        self._turns = list(turns)
        self.payloads: list[dict[str, object]] = []
        self.identity_settings = {"script_variant": variant}

    def generate_turn(
        self,
        *,
        run_id: str,
        turn_number: int,
        instructions: str,
        payload: dict[str, object],
        tool_definitions: tuple[dict[str, object], ...],
        previous_tool_result: AgentToolResult | None,
        cancel_requested: Callable[[], bool],
    ) -> AgentModelResponse:
        assert run_id
        assert turn_number >= 1
        assert "LiveClip prompt-first clipping Agent" in instructions
        assert not cancel_requested()
        self.payloads.append(payload)
        assert any(value.get("name") == "finish" for value in tool_definitions)
        return AgentModelResponse(
            call_id=f"script_{turn_number:04d}",
            turn=self._turns.pop(0),
            metadata={"scripted_turn": turn_number},
        )


def _args(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _transcript() -> TranscriptDocument:
    return TranscriptDocument(
        source_duration_ms=70_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=(
            TranscriptSegment(segment_id="cue_1", start_ms=0, end_ms=10_000, text="开头"),
            TranscriptSegment(segment_id="cue_2", start_ms=10_000, end_ms=30_000, text="解释方法"),
            TranscriptSegment(segment_id="cue_3", start_ms=30_000, end_ms=50_000, text="完成结论"),
            TranscriptSegment(
                segment_id="cue_4", start_ms=50_000, end_ms=70_000, text="下一个话题"
            ),
        ),
    )


def _config() -> ClippingTechnicalConfig:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    return ClippingTechnicalConfig.model_validate(dict(skill.configuration))


def test_packaged_skill_owns_systematic_discovery_and_global_boundary_review() -> None:
    instructions = load_packaged_agent_skill("agent_clipping_v2").instructions

    assert "advance by at most half that width" in instructions
    assert "Discover each requested Profile independently" in instructions
    assert "unresolved backward reference" in instructions
    assert "A first improvement is not necessarily the end" in instructions
    assert "Never deduplicate across Profiles" in instructions
    assert "Do not include superseded drafts" in instructions
    assert "Do not treat a backward reference as resolved" in instructions
    assert "test at least one tighter inner interval" in instructions
    assert "Prefer `save_title_batch`" in instructions
    assert "per-candidate technical validator for every final clip" in instructions


def _turns() -> tuple[AgentTurn, ...]:
    return (
        AgentTurn(
            action="call_tool",
            tool="inspect_transcript",
            arguments_json=_args({"start_ms": 0, "end_ms": 70_000}),
            summary="查看完整测试上下文",
        ),
        AgentTurn(
            action="call_tool",
            tool="save_clip_candidate",
            arguments_json=_args(
                {
                    "artifact_id": "clip_1",
                    "profile": "short_highlight",
                    "variant_group_id": "",
                    "source_candidate_ids": [],
                    "start_cue_id": 1,
                    "end_cue_id": 3,
                    "score": 42,
                    "score_reason": "完整但价值一般; 低分仍保留",
                    "score_dimensions": [],
                    "evidence_cue_ids": [1, 2, 3],
                }
            ),
            summary="保存评分候选, 不做审批",
        ),
        AgentTurn(
            action="call_tool",
            tool="validate_clip_artifact",
            arguments_json=_args({"artifact_id": "clip_1"}),
            summary="只校验技术事实",
        ),
        AgentTurn(
            action="finish",
            artifact_ids=("clip_1",),
            summary="完成一个有评分的技术有效候选",
        ),
    )


def test_harness_runs_bounded_action_observation_loop() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    transcript = _transcript()
    config = _config()
    store = ArtifactStore()
    model = _ScriptedModel(_turns())
    harness = AgentHarness(
        skill=skill,
        model=model,
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=store,
        ),
        artifacts=store,
        artifact_validator=lambda artifacts: validate_clipping_artifacts(
            artifacts,
            transcript=transcript,
            config=config,
        ),
    )

    result = harness.run(
        run_id="agent_test_1",
        task="找出并评分所有技术有效候选",
        initial_context={"user_preferences": {"approval_required": False}},
    )

    assert result.status == "completed"
    assert result.artifacts[0].data["score"] == 42
    assert len(result.events) == 4
    assert [event.function_call_id for event in result.events] == [
        "script_0001",
        "script_0002",
        "script_0003",
        "script_0004",
    ]
    assert [event.observation.status for event in result.events[:-1]] == ["ok", "ok", "ok"]
    assert model.payloads[0]["history"] == []
    assert model.payloads[-1]["artifacts"] == [result.artifacts[0].model_dump(mode="json")]


def test_harness_resumes_turns_artifacts_and_completed_result(tmp_path: Path) -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    transcript = _transcript()
    config = _config()
    journal_root = tmp_path / "agent-state"

    interrupted_store = ArtifactStore()
    interrupted = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[:2]),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=interrupted_store,
        ),
        artifacts=interrupted_store,
        artifact_validator=lambda artifacts: validate_clipping_artifacts(
            artifacts,
            transcript=transcript,
            config=config,
        ),
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(IndexError):
        interrupted.run(
            run_id="agent_resumable",
            task="resume exact run",
            initial_context={"mode": "fixture"},
        )

    resumed_store = ArtifactStore()
    resumed_model = _ScriptedModel(_turns()[2:])
    resumed = AgentHarness(
        skill=skill,
        model=resumed_model,
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=resumed_store,
        ),
        artifacts=resumed_store,
        artifact_validator=lambda artifacts: validate_clipping_artifacts(
            artifacts,
            transcript=transcript,
            config=config,
        ),
        journal=AgentRunJournal(journal_root),
    ).run(
        run_id="agent_resumable",
        task="resume exact run",
        initial_context={"mode": "fixture"},
    )

    assert len(resumed.events) == 4
    assert resumed.artifacts[0].artifact_id == "clip_1"
    assert len(resumed_model.payloads) == 2
    assert len(resumed_model.payloads[0]["history"]) == 2  # type: ignore[arg-type]

    completed_model = _ScriptedModel(())
    completed_store = ArtifactStore()
    completed = AgentHarness(
        skill=skill,
        model=completed_model,
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=completed_store,
        ),
        artifacts=completed_store,
        artifact_validator=lambda artifacts: validate_clipping_artifacts(
            artifacts,
            transcript=transcript,
            config=config,
        ),
        journal=AgentRunJournal(journal_root),
    ).run(
        run_id="agent_resumable",
        task="resume exact run",
        initial_context={"mode": "fixture"},
    )
    assert completed == resumed
    assert completed_model.payloads == []


def test_harness_resume_rejects_changed_identity(tmp_path: Path) -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    transcript = _transcript()
    config = _config()
    journal_root = tmp_path / "agent-state"
    first_store = ArtifactStore()
    first = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[:1]),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=first_store,
        ),
        artifacts=first_store,
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(IndexError):
        first.run(run_id="agent_identity", task="original", initial_context={})

    second_store = ArtifactStore()
    second = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[1:]),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=second_store,
        ),
        artifacts=second_store,
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(ValueError, match="identity conflicts"):
        second.run(run_id="agent_identity", task="changed", initial_context={})


def test_harness_resume_rejects_changed_model_settings(tmp_path: Path) -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    transcript = _transcript()
    config = _config()
    journal_root = tmp_path / "agent-state"
    first_store = ArtifactStore()
    first = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[:1], variant="reasoning-high"),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=first_store,
        ),
        artifacts=first_store,
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(IndexError):
        first.run(run_id="agent_settings", task="same", initial_context={})

    second_store = ArtifactStore()
    second = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[1:], variant="reasoning-medium"),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=second_store,
        ),
        artifacts=second_store,
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(ValueError, match="identity conflicts"):
        second.run(run_id="agent_settings", task="same", initial_context={})


def test_harness_stops_repeated_identical_actions() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    repeated = AgentTurn(
        action="call_tool",
        tool="list_artifacts",
        arguments_json=_args({"artifact_type": None}),
        summary="重复查看",
    )
    model = _ScriptedModel((repeated, repeated, repeated))
    store = ArtifactStore()
    harness = AgentHarness(
        skill=skill,
        model=model,
        tools=build_clipping_tool_registry(
            transcript=_transcript(),
            config=_config(),
            artifacts=store,
        ),
        artifacts=store,
        limits=AgentRunLimits(max_turns=4, max_repeated_action=2),
    )

    with pytest.raises(AgentRunLimitError, match="repeated") as raised:
        harness.run(run_id="agent_repeat", task="测试循环", initial_context={})

    assert len(raised.value.events) == 2


def test_harness_cancellation_retains_prior_events() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    model = _ScriptedModel(_turns())
    store = ArtifactStore()
    harness = AgentHarness(
        skill=skill,
        model=model,
        tools=build_clipping_tool_registry(
            transcript=_transcript(),
            config=_config(),
            artifacts=store,
        ),
        artifacts=store,
    )

    with pytest.raises(AgentRunCancelled) as raised:
        harness.run(
            run_id="agent_cancelled",
            task="不应启动",
            initial_context={},
            cancel_requested=lambda: True,
        )

    assert raised.value.events == ()
    assert model.payloads == []


def test_harness_stops_at_max_turns() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    turns = (
        AgentTurn(
            action="call_tool",
            tool="list_artifacts",
            arguments_json=_args({"artifact_type": None}),
            summary="第一次查看",
        ),
        AgentTurn(
            action="call_tool",
            tool="list_artifacts",
            arguments_json=_args({"artifact_type": "clip_candidate"}),
            summary="第二次查看",
        ),
    )
    store = ArtifactStore()
    harness = AgentHarness(
        skill=skill,
        model=_ScriptedModel(turns),
        tools=build_clipping_tool_registry(
            transcript=_transcript(),
            config=_config(),
            artifacts=store,
        ),
        artifacts=store,
        limits=AgentRunLimits(max_turns=2),
    )

    with pytest.raises(AgentRunLimitError, match="turn budget") as raised:
        harness.run(run_id="agent_turn_limit", task="测试上限", initial_context={})

    assert len(raised.value.events) == 2


def test_harness_can_extend_only_an_existing_checkpoint_turn_budget(tmp_path: Path) -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    transcript = _transcript()
    config = _config()
    journal_root = tmp_path / "agent-state"
    limits = AgentRunLimits(max_turns=2)

    first_store = ArtifactStore()
    first = AgentHarness(
        skill=skill,
        model=_ScriptedModel(_turns()[:2]),
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=first_store,
        ),
        artifacts=first_store,
        limits=limits,
        journal=AgentRunJournal(journal_root),
    )
    with pytest.raises(AgentRunLimitError, match="turn budget"):
        first.run(run_id="agent_extended", task="resume budget", initial_context={})

    resumed_store = ArtifactStore()
    resumed_model = _ScriptedModel(_turns()[2:])
    result = AgentHarness(
        skill=skill,
        model=resumed_model,
        tools=build_clipping_tool_registry(
            transcript=transcript,
            config=config,
            artifacts=resumed_store,
        ),
        artifacts=resumed_store,
        limits=limits,
        artifact_validator=lambda artifacts: validate_clipping_artifacts(
            artifacts,
            transcript=transcript,
            config=config,
        ),
        journal=AgentRunJournal(journal_root),
    ).run(
        run_id="agent_extended",
        task="resume budget",
        initial_context={},
        resume_extra_turns=2,
    )

    assert result.status == "completed"
    assert [event.turn_number for event in result.events] == [1, 2, 3, 4]
    assert len(resumed_model.payloads) == 2

    empty_store = ArtifactStore()
    with pytest.raises(ValueError, match="requires an existing Agent checkpoint"):
        AgentHarness(
            skill=skill,
            model=_ScriptedModel(_turns()),
            tools=build_clipping_tool_registry(
                transcript=transcript,
                config=config,
                artifacts=empty_store,
            ),
            artifacts=empty_store,
            limits=limits,
            journal=AgentRunJournal(tmp_path / "empty-state"),
        ).run(
            run_id="agent_not_started",
            task="resume budget",
            initial_context={},
            resume_extra_turns=1,
        )


def test_context_drops_oldest_history_before_exceeding_limit() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    event = AgentEvent(
        turn_number=1,
        function_call_id="context_call_0001",
        action=AgentTurn(
            action="call_tool",
            tool="inspect_transcript",
            arguments_json=_args({"start_ms": 0, "end_ms": 1}),
            summary="large observation",
        ),
        observation=AgentObservation(
            observation_id="obs_0001",
            tool="inspect_transcript",
            status="ok",
            data={"blob": "x" * 24_000},
        ),
    )

    payload = build_agent_payload(
        task="bounded context",
        turn_number=2,
        skill=skill,
        initial_context={},
        tool_descriptions=(),
        events=(event,),
        artifacts=(),
        limits=AgentRunLimits(max_context_bytes=16 * 1024),
    )

    assert payload["history"] == []
    assert payload["omitted_oldest_history_events"] == 1


def test_tool_registry_rejects_unknown_and_invalid_arguments() -> None:
    registry = ToolRegistry()

    class _Arguments(BaseModel):
        value: int

    registry.register(
        ToolSpec(
            name="echo",
            description="Return one integer.",
            arguments_model=_Arguments,
            handler=lambda value: value.model_dump(),
        )
    )

    unknown = registry.invoke(observation_number=1, tool_name="shell", arguments={})
    invalid = registry.invoke(
        observation_number=2,
        tool_name="echo",
        arguments={"value": "not-an-integer"},
    )

    assert unknown.status == "error"
    assert unknown.tool == "tool_registry"
    assert invalid.status == "error"
    assert invalid.data["errors"]


def test_clipping_registry_exposes_closed_native_function_schemas() -> None:
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=ArtifactStore(),
    )

    definitions = registry.function_definitions()
    names = {str(value["name"]) for value in definitions}

    assert "save_clip_candidate" in names
    assert "save_global_review" in names
    assert "save_title_options" in names
    assert "save_artifact" not in names
    assert all(value["type"] == "function" for value in definitions)
    assert all(value["strict"] is True for value in definitions)
    for definition in definitions:
        _assert_strict_object_schemas(definition["parameters"])


def _assert_strict_object_schemas(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            properties = value.get("properties")
            assert isinstance(properties, dict)
            assert value.get("additionalProperties") is False
            assert set(value.get("required", [])) == set(properties)
        for nested in value.values():
            _assert_strict_object_schemas(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_strict_object_schemas(nested)


def test_profile_names_and_bounds_come_from_skill_configuration() -> None:
    config = ClippingTechnicalConfig.model_validate(
        {
            "schema_version": "1",
            "transcript_context_max_ms": 900_000,
            "transcript_search_max_results": 10,
            "profiles": {
                "podcast_chapter": {
                    "min_duration_ms": 120_000,
                    "max_duration_ms": 600_000,
                    "min_inclusive": True,
                    "max_inclusive": True,
                    "context_window_ms": 900_000,
                }
            },
        }
    )

    assert tuple(config.profiles) == ("podcast_chapter",)
    assert config.profiles["podcast_chapter"].accepts(300_000)


def test_clip_validation_is_technical_and_rejects_non_cue_boundary() -> None:
    artifact = AgentArtifact(
        artifact_id="clip_bad_boundary",
        artifact_type="clip_candidate",
        data={
            "profile": "short_highlight",
            "start_ms": 1,
            "end_ms": 50_000,
            "score": 99,
        },
    )

    errors = validate_clip_artifact(artifact, transcript=_transcript(), config=_config())

    assert any("start_ms is not cue-exact" in error for error in errors)
    assert all("score" not in error for error in errors)


def test_subtitle_audio_tool_labels_mock_and_refuses_fake_revision(tmp_path: Path) -> None:
    chunk = _audio_chunk(tmp_path)
    backend = ASRSubtitleCalibrationBackend(
        provider=MockASRProvider(
            (
                MockScriptSegment(
                    script_id="calibration",
                    source_start_ms=0,
                    source_end_ms=70_000,
                    text="音频测试转写",
                ),
            )
        ),
        chunks=(chunk,),
        source_duration_ms=70_000,
    )
    store = ArtifactStore()
    store.add(_candidate_artifact())
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
        subtitle_calibration=backend,
    )

    observation = registry.invoke(
        observation_number=1,
        tool_name="inspect_candidate_audio",
        arguments={
            "candidate_artifact_id": "clip_audio",
            "evidence_artifact_id": "audio_evidence",
        },
    )
    evidence = store.get("audio_evidence")
    blocked = registry.invoke(
        observation_number=2,
        tool_name="save_subtitle_revision",
        arguments={
            "artifact_id": "subtitle_fake",
            "candidate_artifact_id": "clip_audio",
            "audio_evidence_artifact_id": "audio_evidence",
            "corrected_cues": [
                {"cue_id": index, "text": segment.text}
                for index, segment in enumerate(_transcript().segments, start=1)
            ],
        },
    )
    generic_bypass = registry.invoke(
        observation_number=3,
        tool_name="save_artifact",
        arguments={
            "artifact_id": "subtitle_bypass",
            "artifact_type": "subtitle_revision",
        },
    )

    assert observation.status == "ok"
    assert evidence.data["calibration"]["evidence_kind"] == "mock_fixture"  # type: ignore[index]
    assert blocked.status == "error"
    assert "mock subtitle evidence" in blocked.message
    assert generic_bypass.status == "error"


def test_verified_audio_evidence_creates_timeline_preserving_revision(tmp_path: Path) -> None:
    backend = ASRSubtitleCalibrationBackend(
        provider=_VerifiedFixtureASR(),
        chunks=(_audio_chunk(tmp_path),),
        source_duration_ms=70_000,
    )
    store = ArtifactStore()
    candidate = store.add(_candidate_artifact())
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
        subtitle_calibration=backend,
    )
    inspected = registry.invoke(
        observation_number=1,
        tool_name="inspect_candidate_audio",
        arguments={
            "candidate_artifact_id": candidate.artifact_id,
            "evidence_artifact_id": "audio_verified",
        },
    )
    saved = registry.invoke(
        observation_number=2,
        tool_name="save_subtitle_revision",
        arguments={
            "artifact_id": "subtitle_verified",
            "candidate_artifact_id": candidate.artifact_id,
            "audio_evidence_artifact_id": "audio_verified",
            "corrected_cues": [
                {"cue_id": 1, "text": "开头"},
                {"cue_id": 2, "text": "解释正确方法"},
                {"cue_id": 3, "text": "完成结论"},
            ],
        },
    )
    evidence = store.get("audio_verified")
    revision = store.get("subtitle_verified")

    assert inspected.status == "ok"
    assert saved.status == "ok"
    assert revision.data["changes"] == [
        {
            "cue_id": 2,
            "original_text": "解释方法",
            "corrected_text": "解释正确方法",
        }
    ]
    corrected = revision.data["corrected_cues"]
    assert isinstance(corrected, list)
    assert [(item["start_ms"], item["end_ms"]) for item in corrected] == [  # type: ignore[index]
        (0, 10_000),
        (10_000, 30_000),
        (30_000, 50_000),
    ]
    assert (
        validate_clipping_artifacts(
            (candidate, evidence, revision),
            transcript=_transcript(),
            config=_config(),
        )
        == ()
    )


def test_subtitle_calibration_requires_complete_audio_coverage(tmp_path: Path) -> None:
    chunk = _audio_chunk(tmp_path, end_ms=20_000)
    backend = ASRSubtitleCalibrationBackend(
        provider=MockASRProvider(),
        chunks=(chunk,),
        source_duration_ms=70_000,
    )

    with pytest.raises(SubtitleCalibrationError, match="do not cover"):
        backend.inspect_interval(
            start_ms=0,
            end_ms=50_000,
            cancel_requested=lambda: False,
        )


def test_dedicated_title_tool_keeps_title_score_separate_from_clip_score() -> None:
    store = ArtifactStore()
    candidate = store.add(_candidate_artifact())
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
    )

    reviewed = registry.invoke(
        observation_number=1,
        tool_name="save_global_review",
        arguments={
            "artifact_id": "review_1",
            "requested_profiles": ["short_highlight"],
            "reviews": [
                {
                    "candidate_artifact_id": candidate.artifact_id,
                    "decision": "final",
                    "replacement_candidate_ids": [],
                    "cross_profile_variant_candidate_ids": [],
                    "opening_complete": True,
                    "ending_complete": True,
                    "irrelevant_padding": False,
                    "backward_references_resolved": True,
                    "minimal_complete_boundary": True,
                    "opening_dependency_analysis": "开头不依赖片外内容",
                    "boundary_minimality_analysis": "已是满足时长的最短完整边界",
                    "rationale": "候选边界完整且无需替换",
                    "cross_profile_analysis": "本测试只请求一个短片 Profile",
                }
            ],
            "profile_coverage_notes": ["short_highlight 已逐条复核"],
            "summary": "完成显式全局复核",
        },
    )

    saved = registry.invoke(
        observation_number=2,
        tool_name="save_title_options",
        arguments={
            "artifact_id": "titles_1",
            "candidate_artifact_id": candidate.artifact_id,
            "primary_index": 1,
            "options": [
                {
                    "title": "讲方法总讲不清? 先补这一环",
                    "style_label": "问题",
                    "title_score": 76,
                    "grounding_cue_ids": [1, 2],
                    "rationale": "对应开头和方法解释",
                },
                {
                    "title": "普通人也能讲明白的方法",
                    "style_label": "结果",
                    "title_score": 88,
                    "grounding_cue_ids": [2, 3],
                    "rationale": "方法和结论都有原文依据",
                },
                {
                    "title": "别急着讲结论, 先把方法说明白",
                    "style_label": "反差",
                    "title_score": 81,
                    "grounding_cue_ids": [1, 3],
                    "rationale": "由问题到结论",
                },
            ],
        },
    )
    titles = store.get("titles_1")

    assert reviewed.status == "ok"
    assert saved.status == "ok"
    assert titles.data["primary_title"] == "普通人也能讲明白的方法"
    assert titles.data["options"][1]["title_score"] == 88  # type: ignore[index]
    assert candidate.data["score"] == 50
    assert (
        validate_clipping_artifacts(
            (candidate, store.get("review_1"), titles),
            transcript=_transcript(),
            config=_config(),
        )
        == ()
    )


def test_global_review_refuses_a_declared_defective_final_boundary() -> None:
    store = ArtifactStore()
    candidate = store.add(_candidate_artifact())
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
    )

    observation = registry.invoke(
        observation_number=1,
        tool_name="save_global_review",
        arguments={
            "artifact_id": "review_bad_final",
            "requested_profiles": ["short_highlight"],
            "reviews": [
                {
                    "candidate_artifact_id": candidate.artifact_id,
                    "decision": "final",
                    "replacement_candidate_ids": [],
                    "cross_profile_variant_candidate_ids": [],
                    "opening_complete": True,
                    "ending_complete": True,
                    "irrelevant_padding": True,
                    "backward_references_resolved": True,
                    "minimal_complete_boundary": False,
                    "opening_dependency_analysis": "开头无需片外信息",
                    "boundary_minimality_analysis": "仍含与主题无关的补时内容",
                    "rationale": "不应作为 final",
                    "cross_profile_analysis": "本测试只请求一个 Profile",
                }
            ],
            "profile_coverage_notes": ["测试声明缺陷的候选"],
            "summary": "不合法的最终边界",
        },
    )

    assert observation.status == "error"
    assert observation.message == "tool arguments failed validation"


def test_title_batch_saves_multiple_independent_title_artifacts() -> None:
    store = ArtifactStore()
    first = store.add(_candidate_artifact())
    second = store.add(first.model_copy(update={"artifact_id": "clip_audio_2"}))
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
    )
    review_rows = []
    for candidate in (first, second):
        review_rows.append(
            {
                "candidate_artifact_id": candidate.artifact_id,
                "decision": "final",
                "replacement_candidate_ids": [],
                "cross_profile_variant_candidate_ids": [],
                "opening_complete": True,
                "ending_complete": True,
                "irrelevant_padding": False,
                "backward_references_resolved": True,
                "minimal_complete_boundary": True,
                "opening_dependency_analysis": "开头无需片外信息",
                "boundary_minimality_analysis": "已是最短完整边界",
                "rationale": "保留独立候选",
                "cross_profile_analysis": "本测试只请求一个 Profile",
            }
        )
    reviewed = registry.invoke(
        observation_number=1,
        tool_name="save_global_review",
        arguments={
            "artifact_id": "review_batch_titles",
            "requested_profiles": ["short_highlight"],
            "reviews": review_rows,
            "profile_coverage_notes": ["两条候选均已复核"],
            "summary": "批量标题测试总账",
        },
    )
    assert reviewed.status == "ok"

    items = []
    for index, candidate in enumerate((first, second), start=1):
        items.append(
            {
                "artifact_id": f"titles_batch_{index}",
                "candidate_artifact_id": candidate.artifact_id,
                "primary_index": 0,
                "options": [
                    {
                        "title": f"小白先学这一招{index}",
                        "style_label": "结果",
                        "title_score": 88,
                        "grounding_cue_ids": [1, 2],
                        "rationale": "对应问题和方法",
                    },
                    {
                        "title": f"这个常见错误怎么改{index}",
                        "style_label": "问题",
                        "title_score": 84,
                        "grounding_cue_ids": [1, 3],
                        "rationale": "对应开头和结论",
                    },
                    {
                        "title": f"方法讲清楚其实很简单{index}",
                        "style_label": "反差",
                        "title_score": 82,
                        "grounding_cue_ids": [2, 3],
                        "rationale": "对应方法和结论",
                    },
                ],
            }
        )
    saved = registry.invoke(
        observation_number=2,
        tool_name="save_title_batch",
        arguments={"items": items},
    )

    assert saved.status == "ok"
    assert saved.data["count"] == 2
    assert saved.data["artifact_ids"] == ["titles_batch_1", "titles_batch_2"]
    assert store.get("titles_batch_1").data["source_candidate_id"] == first.artifact_id
    assert store.get("titles_batch_2").data["source_candidate_id"] == second.artifact_id


def test_global_review_is_exhaustive_and_freezes_candidates_before_titles() -> None:
    store = ArtifactStore()
    candidate = store.add(_candidate_artifact())
    duplicate = store.add(candidate.model_copy(update={"artifact_id": "clip_duplicate"}))
    registry = build_clipping_tool_registry(
        transcript=_transcript(),
        config=_config(),
        artifacts=store,
    )
    incomplete = registry.invoke(
        observation_number=1,
        tool_name="save_global_review",
        arguments={
            "artifact_id": "review_incomplete",
            "requested_profiles": ["short_highlight"],
            "reviews": [
                {
                    "candidate_artifact_id": candidate.artifact_id,
                    "decision": "final",
                    "replacement_candidate_ids": [],
                    "cross_profile_variant_candidate_ids": [],
                    "opening_complete": True,
                    "ending_complete": True,
                    "irrelevant_padding": False,
                    "backward_references_resolved": True,
                    "minimal_complete_boundary": True,
                    "opening_dependency_analysis": "开头不依赖片外内容",
                    "boundary_minimality_analysis": "已是满足时长的最短完整边界",
                    "rationale": "只复核了一条",
                    "cross_profile_analysis": "没有请求长片",
                }
            ],
            "profile_coverage_notes": ["尚不完整"],
            "summary": "错误的不完整复核",
        },
    )
    assert incomplete.status == "error"
    assert "every saved clip candidate" in incomplete.message

    reviewed = registry.invoke(
        observation_number=2,
        tool_name="save_global_review",
        arguments={
            "artifact_id": "review_complete",
            "requested_profiles": ["short_highlight"],
            "reviews": [
                {
                    "candidate_artifact_id": candidate.artifact_id,
                    "decision": "final",
                    "replacement_candidate_ids": [],
                    "cross_profile_variant_candidate_ids": [],
                    "opening_complete": True,
                    "ending_complete": True,
                    "irrelevant_padding": False,
                    "backward_references_resolved": True,
                    "minimal_complete_boundary": True,
                    "opening_dependency_analysis": "开头不依赖片外内容",
                    "boundary_minimality_analysis": "已是满足时长的最短完整边界",
                    "rationale": "保留边界更完整版本",
                    "cross_profile_analysis": "没有请求长片",
                },
                {
                    "candidate_artifact_id": duplicate.artifact_id,
                    "decision": "duplicate",
                    "replacement_candidate_ids": [candidate.artifact_id],
                    "cross_profile_variant_candidate_ids": [],
                    "opening_complete": True,
                    "ending_complete": True,
                    "irrelevant_padding": False,
                    "backward_references_resolved": True,
                    "minimal_complete_boundary": True,
                    "opening_dependency_analysis": "重复稿开头本身完整",
                    "boundary_minimality_analysis": "边界完整但与保留稿重复",
                    "rationale": "与保留版本语义相同",
                    "cross_profile_analysis": "没有请求长片",
                },
            ],
            "profile_coverage_notes": ["全部短片逐条复核"],
            "summary": "完整复核并完成同 Profile 去重",
        },
    )
    frozen = registry.invoke(
        observation_number=3,
        tool_name="save_clip_candidate",
        arguments={
            "artifact_id": "clip_after_review",
            "profile": "short_highlight",
            "variant_group_id": "",
            "source_candidate_ids": [],
            "start_cue_id": 1,
            "end_cue_id": 3,
            "score": 50,
            "score_reason": "不应在复核冻结后保存",
            "score_dimensions": [],
            "evidence_cue_ids": [1, 2, 3],
        },
    )

    assert reviewed.status == "ok"
    assert frozen.status == "error"
    assert "frozen" in frozen.message


def test_skill_behavior_can_change_without_runtime_code(tmp_path: Path) -> None:
    first = _write_test_skill(tmp_path / "first", behavior="标题要清楚")
    second = _write_test_skill(tmp_path / "second", behavior="标题要让小白一眼看懂")

    loaded_first = load_agent_skill_directory(first)
    loaded_second = load_agent_skill_directory(second)

    assert loaded_first.sha256 != loaded_second.sha256
    assert "标题要清楚" in loaded_first.instructions
    assert "标题要让小白一眼看懂" in loaded_second.instructions
    assert dict(loaded_first.configuration) == dict(loaded_second.configuration)


def _write_test_skill(root: Path, *, behavior: str) -> Path:
    root.mkdir()
    (root / "manifest.yaml").write_text(
        """schema_version: "1"
version: test_skill
entrypoint: SKILL.md
includes:
  - behavior.md
repair: REPAIR.md
profiles: profiles.yaml
""",
        encoding="utf-8",
    )
    (root / "SKILL.md").write_text("执行测试任务。", encoding="utf-8")
    (root / "behavior.md").write_text(behavior, encoding="utf-8")
    (root / "REPAIR.md").write_text("修复结构。", encoding="utf-8")
    (root / "profiles.yaml").write_text(
        """schema_version: "1"
transcript_context_max_ms: 120000
transcript_search_max_results: 10
profiles:
  any_profile:
    min_duration_ms: 1000
    max_duration_ms: 60000
    min_inclusive: true
    max_inclusive: true
    context_window_ms: 120000
""",
        encoding="utf-8",
    )
    return root


def _candidate_artifact() -> AgentArtifact:
    return AgentArtifact(
        artifact_id="clip_audio",
        artifact_type="clip_candidate",
        data={
            "profile": "short_highlight",
            "start_ms": 0,
            "end_ms": 50_000,
            "start_cue_id": 1,
            "end_cue_id": 3,
            "score": 50,
        },
    )


def _audio_chunk(tmp_path: Path, *, end_ms: int = 70_000) -> AudioChunk:
    path = tmp_path / f"chunk-{end_ms}.m4a"
    payload = b"verified test audio bytes"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return AudioChunk(
        index=0,
        chunk_id="chunk_000000",
        source_start_ms=0,
        source_end_ms=end_ms,
        duration_ms=end_ms,
        overlap_before_ms=0,
        overlap_after_ms=0,
        path=path.resolve(),
        size_bytes=len(payload),
        sha256=digest,
        cache_key=digest,
    )


class _VerifiedFixtureASR:
    provider_name = "fixture"
    model_name = "fixture-asr"
    contract_version = "fixture-asr-v1"

    def transcribe(
        self,
        chunk: AudioChunkLike,
        *,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> ASRChunkResult:
        del vocabulary_prompt
        assert not cancel_requested()
        with open_validated_audio_chunk(chunk) as handle:
            assert handle.read() == b"verified test audio bytes"
        return ASRChunkResult(
            chunk_id=chunk.chunk_id,
            chunk_duration_ms=chunk.source_end_ms - chunk.source_start_ms,
            language=language,
            provider=self.provider_name,
            model=self.model_name,
            word_timing_status=WordTimingStatus.UNAVAILABLE,
            segments=(
                LocalASRSegment(
                    segment_id="fixture_1",
                    start_ms=0,
                    end_ms=chunk.source_end_ms - chunk.source_start_ms,
                    text="通过已校验音频字节得到的测试转写",
                ),
            ),
        )
