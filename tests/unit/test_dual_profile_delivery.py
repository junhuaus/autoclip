from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.delivery.package import hash_zip_member
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
    profile_statistics,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.services.captions import captions_for_clip
from liveclip.services.dual_profile_delivery import (
    DualProfileDeliveryError,
    export_dual_profile_review_package,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate(
    *,
    candidate_id: str,
    profile: ClipProfile,
    start_ms: int,
    end_ms: int,
    cue_id: int,
    title: str,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        variant_group_id="shared_lesson",
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}_window",),
        start_cue_id=cue_id,
        end_cue_id=cue_id,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        title=title,
        hook=f"{title}高光语句",
        summary=f"{title}内容摘要",
        score=88,
        review_status=CandidateDisposition.MANUAL_REVIEW,
        evidence_cue_ids=(cue_id,),
        review_reason=f"{title}需要人工确认",
    )


def _profile(candidate: FinalProfileCandidate) -> FinalProfileResult:
    return FinalProfileResult(
        profile=candidate.profile,
        raw_candidate_ids=(candidate.candidate_id,),
        manual_review=(candidate,),
        statistics=profile_statistics((candidate.candidate_id,), (candidate,)),
    )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    transcript_path = tmp_path / "transcript.srt"
    transcript_path.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片完整教学主题\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片完整教学主题\n",
        encoding="utf-8",
    )
    source_hash = _sha(transcript_path.read_bytes())
    short = _candidate(
        candidate_id="short-one",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
        title="短片教学",
    )
    lesson = _candidate(
        candidate_id="lesson-one",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
        title="长片教学",
    ).model_copy(update={"evidence_cue_ids": (1, 2)})
    final = DualProfileFinalResult(
        source_hash=source_hash,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _profile(short),
            ClipProfile.MINI_LESSON: _profile(lesson),
        },
    )
    final_path = tmp_path / "final-validated.json"
    final_path.write_text(
        json.dumps(final.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    run_manifest = DualProfileRunManifest(
        source_hash=source_hash,
        requested_profiles=final.requested_profiles,
        executed_profiles=final.executed_profiles,
        profiles={
            profile: ProfileManifestStats(**value.statistics.model_dump())
            for profile, value in final.profiles.items()
        },
        provider="mock",
        model="mock-model",
        prompt_files={"discovery": ("prompt.md",)},
        prompt_hashes={"discovery": "d" * 64},
        calls={"discovery": 2, "global_review": 2},
        input_tokens=100,
        output_tokens=20,
        latency_ms=50,
        cache_hits=0,
        retry_count=0,
        repair_count=0,
    )
    run_path = tmp_path / "run-manifest.json"
    run_path.write_text(
        json.dumps(run_manifest.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    transcript = load_srt_transcript(transcript_path)
    render_root = tmp_path / "renders"
    render_root.mkdir()
    clips: list[dict[str, object]] = []
    for candidate in (short, lesson):
        profile_dir = render_root / candidate.profile.value
        quality_dir = profile_dir / f"{candidate.candidate_id}-quality"
        quality_dir.mkdir(parents=True)
        video_path = profile_dir / f"{candidate.candidate_id}.mp4"
        video_path.write_bytes(f"video-{candidate.candidate_id}".encode())
        video_sha = _sha(video_path.read_bytes())
        captions = captions_for_clip(
            transcript.segments,
            source_start_ms=candidate.start_ms,
            source_end_ms=candidate.end_ms,
        )
        subtitle_path = profile_dir / f"{candidate.candidate_id}.srt"
        subtitle_path.write_text(captions_to_srt(captions), encoding="utf-8")
        contact_path = quality_dir / "contact-sheet.png"
        contact_path.write_bytes(f"png-{candidate.candidate_id}".encode())
        quality_path = quality_dir / "quality-report.json"
        quality_path.write_text(
            json.dumps(
                {
                    "media_sha256": video_sha,
                    "automatic_status": "passed",
                    "full_decode": "passed",
                }
            ),
            encoding="utf-8",
        )
        clips.append(
            {
                "candidate_id": candidate.candidate_id,
                "profile": candidate.profile.value,
                "variant_group_id": candidate.variant_group_id,
                "review_status": candidate.review_status.value,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "duration_ms": candidate.duration_ms,
                "video_path": str(video_path.resolve()),
                "video_sha256": video_sha,
                "subtitle_path": str(subtitle_path.resolve()),
                "subtitle_sha256": _sha(subtitle_path.read_bytes()),
                "quality_report_path": str(quality_path.resolve()),
                "contact_sheet_path": str(contact_path.resolve()),
                "contact_sheet_sha256": _sha(contact_path.read_bytes()),
                "encoder": "fixture",
                "render_attempts": 1,
            }
        )
    render_manifest = {
        "schema_version": "1",
        "algorithm_version": "dual-profile-direct-v1",
        "source_video": "直播源.ts",
        "profiles": ["short_highlight", "mini_lesson"],
        "candidate_filter": ["lesson-one", "short-one"],
        "clip_count": 2,
        "clips": clips,
    }
    render_path = render_root / "render-manifest.json"
    render_path.write_text(
        json.dumps(render_manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "transcript": transcript_path,
        "final": final_path,
        "run": run_path,
        "render": render_path,
        "render_root": render_root,
    }


def test_dual_profile_review_package_is_browsable_and_verified(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output = tmp_path / "review-package"

    result = export_dual_profile_review_package(
        transcript_path=paths["transcript"],
        final_result_path=paths["final"],
        run_manifest_path=paths["run"],
        render_manifest_path=paths["render"],
        output_dir=output,
    )

    assert result.clip_count == 2
    assert result.profile_counts == {
        ClipProfile.SHORT_HIGHLIGHT: 1,
        ClipProfile.MINI_LESSON: 1,
    }
    html = result.index_path.read_text(encoding="utf-8")
    assert "短片 short_highlight" in html
    assert "长片 mini_lesson" in html
    assert "待人工审核快照" in html
    assert "manual_review" in html
    assert html.count("<video controls") == 2
    assert "http://" not in html and "https://" not in html and "fetch(" not in html
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "liveclip.dual-profile-offline-review-package.v1"
    assert manifest["package_type"] == "dual_profile_offline_review"
    assert manifest["profile_counts"] == {"mini_lesson": 1, "short_highlight": 1}
    assert all(value["review_status"] == "manual_review" for value in manifest["clips"])
    assert manifest["clips"][0]["editor_keywords"]
    assert manifest["clips"][0]["editor_keywords"][0]["timing_precision"] == "segment"
    assert manifest["clips"][0]["editor_keywords"][0]["source_start_ms"] == 0
    assert manifest["clips"][0]["video_filename"].startswith("clips/short_highlight/01-")
    assert manifest["clips"][1]["video_filename"].startswith("clips/mini_lesson/02-")
    assert result.zip_path is not None
    with zipfile.ZipFile(result.zip_path) as archive:
        names = archive.namelist()
        assert "index.html" in names
        assert "checksums.sha256" in names
        assert "manifest.json" in names
        assert len([name for name in names if name.endswith(".mp4")]) == 2
        assert len([name for name in names if name.endswith(".srt")]) == 2
        for name in names:
            assert hash_zip_member(archive, name) == result.member_sha256[name]
    assert _sha(result.zip_path.read_bytes()) == result.zip_sha256


def test_dual_profile_review_package_never_replaces_existing_output(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output = tmp_path / "review-package"
    output.mkdir()
    marker = output / "owner.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(DualProfileDeliveryError, match="could not be published"):
        export_dual_profile_review_package(
            transcript_path=paths["transcript"],
            final_result_path=paths["final"],
            run_manifest_path=paths["run"],
            render_manifest_path=paths["render"],
            output_dir=output,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_dual_profile_review_package_rejects_a_path_outside_render_root(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    payload = json.loads(paths["render"].read_text(encoding="utf-8"))
    payload["clips"][0]["video_path"] = str(outside.resolve())
    payload["clips"][0]["video_sha256"] = _sha(outside.read_bytes())
    paths["render"].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DualProfileDeliveryError, match="escapes the render directory"):
        export_dual_profile_review_package(
            transcript_path=paths["transcript"],
            final_result_path=paths["final"],
            run_manifest_path=paths["run"],
            render_manifest_path=paths["render"],
            output_dir=tmp_path / "review-package",
        )


def test_dual_profile_review_package_rejects_tampered_media(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    payload = json.loads(paths["render"].read_text(encoding="utf-8"))
    Path(payload["clips"][0]["video_path"]).write_bytes(b"tampered")

    with pytest.raises(DualProfileDeliveryError, match="manifest hash"):
        export_dual_profile_review_package(
            transcript_path=paths["transcript"],
            final_result_path=paths["final"],
            run_manifest_path=paths["run"],
            render_manifest_path=paths["render"],
            output_dir=tmp_path / "review-package",
        )


def test_dual_profile_review_package_cli_exports_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_export(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(model_dump=lambda **_kwargs: {"clip_count": 12})

    monkeypatch.setattr(cli_module, "export_dual_profile_review_package", fake_export)
    result = CliRunner().invoke(
        cli_module.app,
        [
            "dual-profile-review-package",
            "--transcript",
            str(tmp_path / "transcript.srt"),
            "--final-result",
            str(tmp_path / "final.json"),
            "--run-manifest",
            str(tmp_path / "run.json"),
            "--render-manifest",
            str(tmp_path / "render.json"),
            "--output",
            str(tmp_path / "review"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["clip_count"] == 12
    assert captured["include_zip"] is True
    assert captured["package_version"] == "v001"
