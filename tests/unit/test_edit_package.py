# ruff: noqa: RUF001
from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import liveclip.delivery.edit_package as edit_package_module
from liveclip.application.edit_packages import (
    EditPackageClipMetadata,
    EditPackageItem,
    EditPackageRequest,
)
from liveclip.delivery.edit_package import (
    EditPackageClipInput,
    EditPackageError,
    EditPackageTransientError,
    create_edit_package,
    validate_editor_video,
    validate_existing_edit_package,
)
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.keywords import KeywordOccurrence, KeywordTimingPrecision
from liveclip.domain.state_transitions import ReviewStatus
from liveclip.media.fingerprint import stream_sha256
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationTransientError,
)


def _metadata() -> EditPackageClipMetadata:
    return EditPackageClipMetadata(
        clip_id="clip_1",
        candidate_key="candidate_1",
        edit_plan_revision=3,
        source_start_ms=60_000,
        source_end_ms=90_000,
        score=91.5,
        title="真实高光",
        high_impact_sentence="这是可以显示在屏幕上的高光语句。",
        recommendation_reason="观点完整，并且给出了具体方法。",
        risk_flags=("效果表述",),
        captions=(
            CaptionCue(start_ms=0, end_ms=2_000, text="第一句字幕"),
            CaptionCue(start_ms=2_500, end_ms=5_000, text="第二句字幕"),
        ),
        keywords=(
            KeywordOccurrence(
                text="具体方法",
                clip_start_ms=2_500,
                clip_end_ms=5_000,
                source_start_ms=62_500,
                source_end_ms=65_000,
                timing_precision=KeywordTimingPrecision.SEGMENT,
            ),
        ),
        review_status=ReviewStatus.PENDING_REVIEW,
    )


def _metadata_only_package(tmp_path: Path):
    video = tmp_path / "unused-proxy.mp4"
    video.write_bytes(b"unused clean proxy")
    contact_sheet = tmp_path / "contact-sheet.png"
    contact_sheet.write_bytes(b"safe contact sheet" * 100)
    clip = EditPackageClipInput(
        ordinal=1,
        metadata=_metadata(),
        video_path=video,
        video_sha256=stream_sha256(video),
        video_size_bytes=video.stat().st_size,
        contact_sheet_path=contact_sheet,
        contact_sheet_sha256=stream_sha256(contact_sheet),
        contact_sheet_size_bytes=contact_sheet.stat().st_size,
    )
    return create_edit_package(
        project_dir=tmp_path / "project",
        edit_package_id="package_1",
        project_id="project_1",
        project_name="直播项目",
        owner_username="owner",
        requested_by_username="editor",
        source_filename="/allowed/input/live.ts",
        source_fingerprint="a" * 64,
        generation=2,
        project_revision_epoch=7,
        version=1,
        preset="clean_editing",
        content="metadata_only",
        snapshot_fingerprint="b" * 64,
        clips=(clip,),
        include_zip=True,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def test_request_rejects_duplicate_clips_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        EditPackageRequest(
            items=(
                EditPackageItem(clip_id="clip_1", expected_revision=1),
                EditPackageItem(clip_id="clip_1", expected_revision=2),
            )
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EditPackageRequest.model_validate(
            {
                "items": [{"clip_id": "clip_1", "expected_revision": 1}],
                "command": "ffmpeg -i private.mp4",
            }
        )


def test_metadata_only_package_is_immutable_hash_verified_and_zip_safe(
    tmp_path: Path,
) -> None:
    result = _metadata_only_package(tmp_path)

    assert result.package_version == "v001"
    assert result.zip_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "liveclip.edit-package.v1"
    assert manifest["source_filename"] == "live.ts"
    assert manifest["content"] == "metadata_only"
    assert manifest["clips"][0]["video_filename"] is None
    assert manifest["clips"][0]["subtitle_filename"] is None
    assert manifest["clips"][0]["high_impact_sentence"]
    assert manifest["clips"][0]["keywords"][0]["text"] == "具体方法"
    assert not (result.directory / "media").exists()
    assert not (result.directory / "subtitles").exists()
    with zipfile.ZipFile(result.zip_path) as archive:
        assert archive.testzip() is None
        assert all(
            not name.startswith("/") and ".." not in Path(name).parts for name in archive.namelist()
        )
        assert "metadata/clips.csv" in archive.namelist()
        assert "metadata/README-导入剪映.txt" in archive.namelist()

    recovered = validate_existing_edit_package(
        result.directory,
        edit_package_id="package_1",
        project_id="project_1",
        package_version="v001",
        snapshot_fingerprint="b" * 64,
        include_zip=True,
    )
    assert recovered.manifest_sha256 == result.manifest_sha256
    assert recovered.zip_sha256 == result.zip_sha256


def test_existing_package_rejects_changed_member(tmp_path: Path) -> None:
    result = _metadata_only_package(tmp_path)
    (result.directory / "metadata/clips.csv").write_text("changed", encoding="utf-8")

    with pytest.raises(EditPackageError, match="missing or unsafe"):
        validate_existing_edit_package(
            result.directory,
            edit_package_id="package_1",
            project_id="project_1",
            package_version="v001",
            snapshot_fingerprint="b" * 64,
            include_zip=True,
        )


def test_editor_video_validation_preserves_transient_failure_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video = tmp_path / "proxy.mp4"
    video.write_bytes(b"not inspected")

    def fail_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise MediaValidationTransientError("temporary ffprobe failure")

    monkeypatch.setattr(edit_package_module, "probe_media", fail_probe)

    with pytest.raises(EditPackageTransientError, match="temporarily failed"):
        validate_editor_video(video, cancel_requested=lambda: False)


def test_editor_video_validation_preserves_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video = tmp_path / "proxy.mp4"
    video.write_bytes(b"not inspected")

    def cancel_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise MediaValidationCancelled("cancelled")

    monkeypatch.setattr(edit_package_module, "probe_media", cancel_probe)

    with pytest.raises(InterruptedError, match="cancelled"):
        validate_editor_video(video, cancel_requested=lambda: True)
