from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from liveclip.agent_runtime.models import AgentModelResponse, AgentToolResult, AgentTurn
from liveclip.agent_runtime.skills import LoadedAgentSkill
from liveclip.agent_tools.subtitle_calibration import (
    CalibrationChunkEvidence,
    CalibrationTranscriptSegment,
    SubtitleCalibrationEvidence,
)
from liveclip.cli.app import app
from liveclip.config.settings import Settings
from liveclip.media.models import AudioChunk, AudioChunkManifest
from liveclip.media.secure_files import SecureFileError
from liveclip.services.agent_clipping import run_agent_clipping_v2, write_agent_run_result
from liveclip.services.subtitle_calibration import configured_subtitle_calibration_backend


class _TranscriptDrivenModel:
    provider_name = "mock-agent"
    model_name = "mock-agent-v1"

    def __init__(self) -> None:
        self._turn = 0
        self.payloads: list[dict[str, object]] = []

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
        del run_id, turn_number, instructions
        assert not cancel_requested()
        self.payloads.append(payload)
        assert any(value.get("name") == "finish" for value in tool_definitions)
        self._turn += 1
        turns = (
            AgentTurn(
                action="call_tool",
                tool="inspect_transcript",
                arguments_json=json.dumps({"start_ms": 0, "end_ms": 70_000}),
                summary="读取字幕证据",
            ),
            AgentTurn(
                action="call_tool",
                tool="save_clip_candidate",
                arguments_json=json.dumps(
                    {
                        "artifact_id": "candidate_low_score",
                        "profile": "short_highlight",
                        "variant_group_id": "",
                        "source_candidate_ids": [],
                        "start_cue_id": 1,
                        "end_cue_id": 3,
                        "score": 35,
                        "score_reason": "测试方法完整但吸引力一般",
                        "score_dimensions": [],
                        "evidence_cue_ids": [1, 2, 3],
                    },
                    ensure_ascii=False,
                ),
                summary="低分候选仍保存",
            ),
            AgentTurn(
                action="call_tool",
                tool="validate_clip_artifact",
                arguments_json=json.dumps({"artifact_id": "candidate_low_score"}),
                summary="验证时长和字幕边界",
            ),
            AgentTurn(
                action="finish",
                artifact_ids=("candidate_low_score",),
                summary="评分完成, 不进行自动审批",
            ),
        )
        return AgentModelResponse(
            call_id=f"mock_call_{self._turn:04d}",
            turn=turns[self._turn - 1],
        )


def test_prompt_first_agent_service_keeps_low_score_candidate(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        """1
00:00:00,000 --> 00:00:10,000
先提出问题

2
00:00:10,000 --> 00:00:30,000
解释一个普通人能使用的方法

3
00:00:30,000 --> 00:00:50,000
最后给出完整结论

4
00:00:50,000 --> 00:01:10,000
进入下一个话题
""",
        encoding="utf-8",
    )
    model = _TranscriptDrivenModel()

    result = run_agent_clipping_v2(
        transcript_path=transcript,
        run_id="agent_vertical_slice",
        task="发现、评分并保留所有技术有效候选, 不做内容审核",
        model_factory=lambda skill: _same_model(skill, model),
        initial_context={"title_preferences": {"audience": "初学者"}},
    )

    assert result.skill_version == "agent_clipping_v2"
    assert result.artifacts[0].data["score"] == 35
    assert result.summary == "评分完成, 不进行自动审批"
    source = model.payloads[0]["initial_context"]
    assert isinstance(source, dict)
    assert source["source"]["cue_count"] == 4  # type: ignore[index]
    configuration = model.payloads[0]["skill_configuration"]
    assert isinstance(configuration, dict)
    assert "full_lesson" in configuration["profiles"]  # type: ignore[operator]

    output = tmp_path / "agent-result.json"
    digest = write_agent_run_result(output, result)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert len(digest) == 64
    assert persisted["skill_sha256"] == result.skill_sha256
    assert persisted["artifacts"][0]["data"]["score"] == 35
    assert write_agent_run_result(output, result) == digest
    with pytest.raises(SecureFileError, match="conflicts"):
        write_agent_run_result(output, result.model_copy(update={"summary": "different"}))


def test_agent_clipping_cli_is_exposed_without_running_a_model() -> None:
    command = CliRunner().invoke(app, ["agent-clipping-eval", "--help"])

    assert command.exit_code == 0
    assert "configured native-function-calling Agent" in command.stdout
    assert "--transcript" in command.stdout
    assert "--output" in command.stdout
    assert "--audio-manifest" in command.stdout
    assert "--max-turns" in command.stdout
    assert "--resume-extra-turns" in command.stdout


def test_agent_service_can_publish_audio_grounded_subtitle_revision(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        """1
00:00:00,000 --> 00:00:10,000
先提出问题

2
00:00:10,000 --> 00:00:30,000
解释一个普通人能使用的方发

3
00:00:30,000 --> 00:00:50,000
最后给出完整结论
""",
        encoding="utf-8",
    )
    model = _SubtitleRevisionModel()

    result = run_agent_clipping_v2(
        transcript_path=transcript,
        run_id="agent_subtitle_fixture",
        task="评分候选并用音频证据校准字幕",
        model_factory=lambda skill: _same_model(skill, model),
        subtitle_calibration=_CalibrationFixture(),
    )

    assert [artifact.artifact_type for artifact in result.artifacts] == [
        "clip_candidate",
        "subtitle_audio_evidence",
        "subtitle_revision",
    ]
    revision = result.artifacts[-1]
    assert revision.data["changes"] == [
        {
            "cue_id": 2,
            "original_text": "解释一个普通人能使用的方发",
            "corrected_text": "解释一个普通人能使用的方法",
        }
    ]


def test_configured_subtitle_backend_uses_manifest_local_verified_chunks(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    chunk_path = audio_dir / "chunk-000000.m4a"
    payload = b"bounded mock audio fixture"
    chunk_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    chunk = AudioChunk(
        index=0,
        chunk_id="chunk_000000",
        source_start_ms=0,
        source_end_ms=50_000,
        duration_ms=50_000,
        overlap_before_ms=0,
        overlap_after_ms=0,
        path=chunk_path.resolve(),
        size_bytes=len(payload),
        sha256=digest,
        cache_key=digest,
    )
    manifest = AudioChunkManifest(
        source_sha256="b" * 64,
        source_duration_ms=50_000,
        source_audio_stream_index=1,
        chunk_duration_ms=50_000,
        chunk_overlap_ms=0,
        sample_rate_hz=16_000,
        bitrate="48k",
        silence_noise_db=-35,
        silence_min_duration_ms=500,
        max_chunk_bytes=24_000_000,
        expected_chunk_count=1,
        chunks=(chunk,),
        complete=True,
    )
    manifest_path = audio_dir / "chunk-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")

    backend = configured_subtitle_calibration_backend(
        Settings(ai_provider="mock", transcription_model="mock-asr-v1"),
        audio_manifest_path=manifest_path,
    )
    evidence = backend.inspect_interval(
        start_ms=0,
        end_ms=50_000,
        cancel_requested=lambda: False,
    )

    assert evidence.evidence_kind == "mock_fixture"
    assert evidence.chunks[0].sha256 == digest


def _same_model(skill: LoadedAgentSkill, model: _TranscriptDrivenModel) -> _TranscriptDrivenModel:
    assert "do not approve, block, reject" in skill.instructions
    assert "Title behavior" in skill.instructions
    assert "Subtitle calibration behavior" in skill.instructions
    return model


class _SubtitleRevisionModel(_TranscriptDrivenModel):
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
        del run_id, turn_number, instructions
        assert not cancel_requested()
        self.payloads.append(payload)
        assert any(value.get("name") == "finish" for value in tool_definitions)
        self._turn += 1
        turns = (
            AgentTurn(
                action="call_tool",
                tool="save_clip_candidate",
                arguments_json=json.dumps(
                    {
                        "artifact_id": "candidate_audio",
                        "profile": "short_highlight",
                        "variant_group_id": "",
                        "source_candidate_ids": [],
                        "start_cue_id": 1,
                        "end_cue_id": 3,
                        "score": 61,
                        "score_reason": "方法说明完整",
                        "score_dimensions": [],
                        "evidence_cue_ids": [1, 2, 3],
                    }
                ),
                summary="保存候选",
            ),
            AgentTurn(
                action="call_tool",
                tool="inspect_candidate_audio",
                arguments_json=json.dumps(
                    {
                        "candidate_artifact_id": "candidate_audio",
                        "evidence_artifact_id": "audio_observation",
                    }
                ),
                summary="取得音频二次转写证据",
            ),
            AgentTurn(
                action="call_tool",
                tool="save_subtitle_revision",
                arguments_json=json.dumps(
                    {
                        "artifact_id": "subtitle_revision_1",
                        "candidate_artifact_id": "candidate_audio",
                        "audio_evidence_artifact_id": "audio_observation",
                        "corrected_cues": [
                            {"cue_id": 1, "text": "先提出问题"},
                            {"cue_id": 2, "text": "解释一个普通人能使用的方法"},
                            {"cue_id": 3, "text": "最后给出完整结论"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                summary="保存音频证据支持的字幕修正",
            ),
            AgentTurn(
                action="finish",
                artifact_ids=("candidate_audio", "audio_observation", "subtitle_revision_1"),
                summary="候选评分和字幕校准完成",
            ),
        )
        return AgentModelResponse(
            call_id=f"subtitle_call_{self._turn:04d}",
            turn=turns[self._turn - 1],
        )


class _CalibrationFixture:
    def inspect_interval(
        self,
        *,
        start_ms: int,
        end_ms: int,
        cancel_requested: Callable[[], bool],
    ) -> SubtitleCalibrationEvidence:
        assert not cancel_requested()
        return SubtitleCalibrationEvidence(
            evidence_kind="verified_audio_asr",
            provider="fixture",
            model="fixture-asr",
            contract_version="fixture-asr-v1",
            requested_start_ms=start_ms,
            requested_end_ms=end_ms,
            language="zh",
            chunks=(
                CalibrationChunkEvidence(
                    chunk_id="chunk_000000",
                    source_start_ms=0,
                    source_end_ms=50_000,
                    size_bytes=123,
                    sha256="a" * 64,
                ),
            ),
            segments=(
                CalibrationTranscriptSegment(
                    segment_id="calibration_1",
                    start_ms=10_000,
                    end_ms=30_000,
                    text="解释一个普通人能使用的方法",
                    source_chunk_ids=("chunk_000000",),
                ),
            ),
        )
