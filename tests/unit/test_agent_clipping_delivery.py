from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.agent_runtime.models import AgentArtifact, AgentRunResult
from liveclip.agent_runtime.skills import load_packaged_agent_skill
from liveclip.agent_tools.clipping import (
    SubtitleAudioEvidenceData,
    SubtitleCueRecord,
    SubtitleRevisionData,
)
from liveclip.agent_tools.subtitle_calibration import (
    CalibrationChunkEvidence,
    SubtitleCalibrationEvidence,
)
from liveclip.agent_tools.titles import (
    SaveTitleOptionsArguments,
    build_title_options_artifact,
)
from liveclip.services.agent_clipping_delivery import (
    AgentClippingDeliveryError,
    export_agent_clipping_review_package,
    render_agent_clipping_result,
)


def test_agent_render_and_review_package_preserve_agent_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, transcript, result_path = _run_evidence(tmp_path)
    _install_fake_media(monkeypatch)

    render = render_agent_clipping_result(
        source_video=source,
        transcript_path=transcript,
        run_result_path=result_path,
        output_dir=tmp_path / "render",
        encoder="fixture",
    )

    assert render.clip_count == 1
    rendered = render.clips[0]
    assert rendered.primary_title == "这一步做对了, 新手也能讲清楚"
    assert len(rendered.title_options) == 3
    subtitle = rendered.subtitle_path.read_text(encoding="utf-8")
    assert "正确术语" in subtitle
    assert "错误术语" not in subtitle
    assert rendered.subtitle_evidence_kind == "verified_audio_asr"

    package = export_agent_clipping_review_package(
        transcript_path=transcript,
        run_result_path=result_path,
        render_manifest_path=tmp_path / "render" / "render-manifest.json",
        output_dir=tmp_path / "review-package",
    )

    assert package.clip_count == 1
    assert package.profile_counts == {"short_highlight": 1}
    assert package.zip_path is not None and package.zip_path.is_file()
    assert (package.directory / "README-人工验收说明.md").is_file()
    assert (package.directory / "人工验收清单.csv").is_file()
    combined_markdown = (package.directory / "全部切片脚本.md").read_text(encoding="utf-8")
    combined_json = json.loads(
        (package.directory / "全部切片脚本.json").read_text(encoding="utf-8")
    )
    assert "不受信任的内容" in combined_markdown
    assert "正确术语" in combined_markdown
    assert combined_json["untrusted_transcript"] is True
    assert combined_json["clips"][0]["transcript_text"].startswith("这里用了正确术语")
    index = package.index_path.read_text(encoding="utf-8")
    assert "不代表自动通过" in index
    assert "这一步做对了" in index
    assert "verified_audio_asr" in index
    assert "错误术语" in index and "正确术语" in index
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    clip = manifest["clips"][0]
    assert clip["score"] == 86
    assert clip["subtitle_revision_artifact_id"] == "subtitle_1"
    assert clip["title_options"][1]["title_score"] == 91
    assert (package.directory / clip["video_filename"]).is_file()
    assert (package.directory / clip["subtitle_filename"]).is_file()
    assert "audit/agent-run-result.json" in package.member_sha256
    with zipfile.ZipFile(package.zip_path) as archive:
        assert archive.testzip() is None
        assert "README-人工验收说明.md" in archive.namelist()
        assert "人工验收清单.csv" in archive.namelist()
        assert "全部切片脚本.md" in archive.namelist()
        assert "全部切片脚本.json" in archive.namelist()


def test_agent_review_package_rejects_render_member_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, transcript, result_path = _run_evidence(tmp_path)
    _install_fake_media(monkeypatch)
    render = render_agent_clipping_result(
        source_video=source,
        transcript_path=transcript,
        run_result_path=result_path,
        output_dir=tmp_path / "render",
    )
    render.clips[0].subtitle_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(AgentClippingDeliveryError, match="differs from manifest"):
        export_agent_clipping_review_package(
            transcript_path=transcript,
            run_result_path=result_path,
            render_manifest_path=tmp_path / "render" / "render-manifest.json",
            output_dir=tmp_path / "review-package",
        )


def test_agent_render_failure_never_publishes_partial_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, transcript, result_path = _run_evidence(tmp_path)
    _install_fake_media(monkeypatch)

    def fail_after_partial_write(**arguments: object) -> object:
        output_path = arguments["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"partial")
        raise RuntimeError("fixture render failure")

    monkeypatch.setattr(
        "liveclip.services.agent_clipping_delivery.render_edit_plan_revision",
        fail_after_partial_write,
    )
    output = (tmp_path / "render").resolve()

    with pytest.raises(RuntimeError, match="fixture render failure"):
        render_agent_clipping_result(
            source_video=source,
            transcript_path=transcript,
            run_result_path=result_path,
            output_dir=output,
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".render-attempt-*"))


def test_agent_delivery_commands_are_exposed_and_bind_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        allowed_media_roots=(tmp_path.resolve(),),
        resolved_data_dir=lambda base: (base / "data/projects").resolve(),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        cli_module,
        "resolve_allowed_source",
        lambda path, _roots, *, forbidden_roots: path,
    )

    def fake_render(**arguments: object) -> SimpleNamespace:
        captured.update(arguments)
        return SimpleNamespace(model_dump=lambda **_kwargs: {"clip_count": 1})

    monkeypatch.setattr(cli_module, "render_agent_clipping_result", fake_render)
    render_result = CliRunner().invoke(
        cli_module.app,
        [
            "agent-clipping-render",
            "--source",
            str((tmp_path / "source.mp4").resolve()),
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--run-result",
            str(tmp_path / "agent-run.json"),
            "--output",
            str(tmp_path / "render"),
            "--candidate-id",
            "clip_1",
        ],
    )

    assert render_result.exit_code == 0, render_result.output
    assert json.loads(render_result.output)["clip_count"] == 1
    assert captured["candidate_ids"] == ["clip_1"]

    captured.clear()

    def fake_package(**arguments: object) -> SimpleNamespace:
        captured.update(arguments)
        return SimpleNamespace(model_dump=lambda **_kwargs: {"clip_count": 1})

    monkeypatch.setattr(cli_module, "export_agent_clipping_review_package", fake_package)
    package_result = CliRunner().invoke(
        cli_module.app,
        [
            "agent-clipping-review-package",
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--run-result",
            str(tmp_path / "agent-run.json"),
            "--render-manifest",
            str(tmp_path / "render" / "render-manifest.json"),
            "--output",
            str(tmp_path / "review"),
            "--no-zip",
        ],
    )

    assert package_result.exit_code == 0, package_result.output
    assert json.loads(package_result.output)["clip_count"] == 1
    assert captured["include_zip"] is False


def _run_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = (tmp_path / "source.mp4").resolve()
    source.write_bytes(b"fixture source media")
    transcript = (tmp_path / "transcript.srt").resolve()
    transcript.write_text(
        """1
00:00:00,000 --> 00:00:20,000
这里用了错误术语

2
00:00:20,000 --> 00:00:50,000
接着解释完整方法并给出结论
""",
        encoding="utf-8",
    )
    transcript_sha256 = hashlib.sha256(transcript.read_bytes()).hexdigest()
    candidate = AgentArtifact(
        artifact_id="clip_1",
        artifact_type="clip_candidate",
        data={
            "profile": "short_highlight",
            "variant_group_id": "lesson_1",
            "source_candidate_ids": [],
            "start_cue_id": 1,
            "end_cue_id": 2,
            "start_ms": 0,
            "end_ms": 50_000,
            "duration_ms": 50_000,
            "score": 86,
            "score_reason": "问题、方法和结论完整, 值得人工选择。",
            "score_dimensions": [
                {"name": "完整性", "score": 90, "rationale": "方法闭环"},
                {"name": "可理解性", "score": 82, "rationale": "小白可理解"},
            ],
        },
        evidence=({"cue_ids": [1, 2]},),
    )
    titles = build_title_options_artifact(
        SaveTitleOptionsArguments.model_validate(
            {
                "artifact_id": "titles_1",
                "candidate_artifact_id": candidate.artifact_id,
                "primary_index": 1,
                "options": [
                    {
                        "title": "总讲不清? 先把这一步补上",
                        "style_label": "痛点",
                        "title_score": 84,
                        "grounding_cue_ids": [1, 2],
                        "rationale": "对应原文中的问题与方法",
                    },
                    {
                        "title": "这一步做对了, 新手也能讲清楚",
                        "style_label": "结果",
                        "title_score": 91,
                        "grounding_cue_ids": [1, 2],
                        "rationale": "对新手说明明确收益",
                    },
                    {
                        "title": "别急着下结论, 方法才是关键",
                        "style_label": "反差",
                        "title_score": 87,
                        "grounding_cue_ids": [2],
                        "rationale": "由方法和结论提炼",
                    },
                ],
            }
        ),
        allowed_cue_ids=(1, 2),
    )
    original = (
        SubtitleCueRecord(
            cue_id=1,
            segment_id="cue_000001",
            start_ms=0,
            end_ms=20_000,
            text="这里用了错误术语",
        ),
        SubtitleCueRecord(
            cue_id=2,
            segment_id="cue_000002",
            start_ms=20_000,
            end_ms=50_000,
            text="接着解释完整方法并给出结论",
        ),
    )
    calibration = SubtitleCalibrationEvidence(
        evidence_kind="verified_audio_asr",
        provider="fixture",
        model="fixture-asr",
        contract_version="fixture-asr-v1",
        requested_start_ms=0,
        requested_end_ms=50_000,
        language="zh",
        chunks=(
            CalibrationChunkEvidence(
                chunk_id="chunk_000000",
                source_start_ms=0,
                source_end_ms=50_000,
                size_bytes=10,
                sha256="b" * 64,
            ),
        ),
        segments=(),
    )
    audio_evidence = AgentArtifact(
        artifact_id="audio_1",
        artifact_type="subtitle_audio_evidence",
        data=SubtitleAudioEvidenceData(
            source_candidate_id=candidate.artifact_id,
            start_cue_id=1,
            end_cue_id=2,
            original_cues=original,
            calibration=calibration,
        ).model_dump(mode="json"),
        evidence=({"chunk_id": "chunk_000000", "sha256": "b" * 64},),
    )
    corrected = (
        original[0].model_copy(update={"text": "这里用了正确术语"}),
        original[1],
    )
    revision = AgentArtifact(
        artifact_id="subtitle_1",
        artifact_type="subtitle_revision",
        data=SubtitleRevisionData(
            source_candidate_id=candidate.artifact_id,
            audio_evidence_artifact_id=audio_evidence.artifact_id,
            evidence_kind="verified_audio_asr",
            provider="fixture",
            model="fixture-asr",
            corrected_cues=corrected,
            changes=(
                {
                    "cue_id": 1,
                    "original_text": original[0].text,
                    "corrected_text": corrected[0].text,
                },
            ),
        ).model_dump(mode="json"),
        evidence=(
            {
                "audio_evidence_artifact_id": audio_evidence.artifact_id,
                "source_candidate_id": candidate.artifact_id,
            },
        ),
    )
    skill = load_packaged_agent_skill("agent_clipping_v2")
    result = AgentRunResult(
        run_id="delivery_fixture",
        run_identity_sha256="a" * 64,
        skill_version=skill.version,
        skill_sha256=skill.sha256,
        provider="fixture",
        model="fixture-agent",
        model_settings={"fixture": True},
        initial_context={
            "task": "fixture",
            "source": {
                "transcript_sha256": transcript_sha256,
                "transcript_duration_ms": 50_000,
            },
        },
        events=(),
        artifacts=(candidate, titles, audio_evidence, revision),
        summary="Fixture Agent run completed.",
    )
    result_path = (tmp_path / "agent-run.json").resolve()
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return source, transcript, result_path


def _install_fake_media(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "liveclip.services.agent_clipping_delivery.run_ffprobe",
        lambda _path: {
            "streams": [
                {"codec_type": "video", "index": 0, "disposition": {}},
                {"codec_type": "audio", "index": 1},
            ]
        },
    )

    def render(**arguments: object) -> object:
        output_path = arguments["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"rendered fixture video")
        video_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        quality_dir = output_path.parent / f"{output_path.stem}-quality"
        quality_dir.mkdir()
        quality_path = quality_dir / "quality-report.json"
        quality_path.write_text(
            json.dumps(
                {
                    "media_sha256": video_sha256,
                    "automatic_status": "passed",
                    "full_decode": "passed",
                }
            ),
            encoding="utf-8",
        )
        contact_path = quality_dir / "contact-sheet.png"
        contact_path.write_bytes(b"fixture contact sheet")
        return SimpleNamespace(
            sha256=video_sha256,
            quality_report_path=quality_path.resolve(),
            contact_sheet_path=contact_path.resolve(),
            contact_sheet_sha256=hashlib.sha256(contact_path.read_bytes()).hexdigest(),
            encoder="fixture",
            attempts=1,
        )

    monkeypatch.setattr(
        "liveclip.services.agent_clipping_delivery.render_edit_plan_revision",
        render,
    )
