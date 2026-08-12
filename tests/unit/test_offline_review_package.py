# ruff: noqa: RUF001
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from liveclip.delivery.package import hash_zip_member, validate_zip_members
from liveclip.delivery.review_package import (
    OfflineReviewClipInput,
    OfflineReviewPackageError,
    create_offline_review_package,
)
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.keywords import KeywordOccurrence, KeywordTimingPrecision
from liveclip.domain.state_transitions import ReviewStatus
from liveclip.media.fingerprint import stream_sha256


def _clip(tmp_path: Path, *, ordinal: int = 1) -> OfflineReviewClipInput:
    video = tmp_path / f"review-{ordinal}.mp4"
    video.write_bytes((f"clean-review-video-{ordinal}".encode()) * 1_000)
    return OfflineReviewClipInput(
        clip_id=f"clip_{ordinal}",
        candidate_key=f"candidate_{ordinal}",
        edit_plan_revision=ordinal,
        source_start_ms=60_000 * ordinal,
        source_end_ms=60_000 * ordinal + 30_000,
        score=max(0.0, 91.5 - ordinal),
        title=f"离线高光 {ordinal}",
        high_impact_sentence=f"这是第 {ordinal} 个高光语句",
        recommendation_reason="内容完整，并且给出了可执行的方法。",
        risk_flags=("效果表述",),
        captions=(
            CaptionCue(start_ms=0, end_ms=2_000, text="第一句字幕"),
            CaptionCue(start_ms=2_500, end_ms=5_000, text="第二句字幕"),
        ),
        keywords=(
            KeywordOccurrence(
                text="高光语句",
                clip_start_ms=0,
                clip_end_ms=2_000,
                source_start_ms=60_000 * ordinal,
                source_end_ms=60_000 * ordinal + 2_000,
                timing_precision=KeywordTimingPrecision.SEGMENT,
            ),
        ),
        review_status=ReviewStatus.PENDING_REVIEW,
        proxy_path=video,
        proxy_sha256=stream_sha256(video),
        proxy_size_bytes=video.stat().st_size,
        proxy_render_id=f"render_{ordinal}",
        proxy_asset_id=f"asset_{ordinal}",
        proxy_spec_fingerprint="c" * 64,
        proxy_render_revision_epoch=1,
        proxy_producer_task_id=f"task_{ordinal}",
        proxy_producer_task_kind="render",
        proxy_producer_stage=None,
        proxy_asset_input_fingerprint="c" * 64,
        proxy_asset_generation=3,
        proxy_asset_revision_epoch=1,
    )


def _create(tmp_path: Path, clips: tuple[OfflineReviewClipInput, ...]):
    return create_offline_review_package(
        project_dir=tmp_path / "project",
        project_id="project_1",
        project_name="直播 7.28",
        source_filename="/local/input/7.28.mp4",
        source_fingerprint="a" * 64,
        pipeline_run_id="run_1",
        generation=3,
        project_revision_epoch=4,
        project_status="pending_review",
        snapshot_fingerprint="b" * 64,
        clips=clips,
        include_zip=True,
    )


def test_offline_review_package_is_self_contained_versioned_and_hash_verified(
    tmp_path: Path,
) -> None:
    clips = (_clip(tmp_path, ordinal=1), _clip(tmp_path, ordinal=2))

    first = _create(tmp_path, clips)
    second = _create(tmp_path, clips)

    assert first.package_version == "v001"
    assert second.package_version == "v002"
    assert first.clip_count == 2
    assert first.zip_path is not None
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "liveclip.offline-review-package.v2"
    assert manifest["package_type"] == "offline_review"
    assert manifest["project_status_at_export"] == "pending_review"
    assert manifest["source_filename"] == "7.28.mp4"
    assert manifest["clip_count"] == 2
    assert manifest["project_revision_epoch"] == 4
    assert all(value["review_status"] == "pending_review" for value in manifest["clips"])
    first_clip = manifest["clips"][0]
    assert first_clip["high_impact_sentence"] == "这是第 1 个高光语句"
    assert first_clip["recommendation_reason"]
    assert first_clip["editor_keywords"][0]["timing_precision"] == "segment"
    assert first_clip["captions"][0]["text"] == "第一句字幕"
    assert first_clip["proxy_lineage"] == {
        "render_job_id": "render_1",
        "asset_id": "asset_1",
        "render_spec_fingerprint": "c" * 64,
        "render_revision_epoch": 1,
        "producer_task_id": "task_1",
        "producer_task_kind": "render",
        "producer_stage": None,
        "asset_input_fingerprint": "c" * 64,
        "asset_generation": 3,
        "asset_edit_plan_revision": 1,
        "asset_revision_epoch": 1,
    }

    offline_html = first.index_path.read_text(encoding="utf-8")
    assert "高光时刻" in offline_html
    assert "高光语句" in offline_html
    assert "编辑关键词（仅供编辑定位）" in offline_html
    assert "Content-Security-Policy" in offline_html
    assert "源视频" in offline_html and "segment" in offline_html
    assert offline_html.count("<video controls") == 2
    assert "fetch(" not in offline_html
    assert "http://" not in offline_html and "https://" not in offline_html

    for clip in manifest["clips"]:
        assert (first.directory / clip["video_filename"]).is_file()
        assert "-->" in (first.directory / clip["subtitle_filename"]).read_text(encoding="utf-8")
        description = (first.directory / clip["description_filename"]).read_text(encoding="utf-8")
        assert "高光语句" in description and "推荐理由" in description

    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
        validate_zip_members(names)
        assert set(names) == set(first.member_sha256) - {"offline-review.zip"}
        for name in names:
            assert hash_zip_member(archive, name) == first.member_sha256[name]
    assert stream_sha256(first.zip_path) == first.zip_sha256


def test_offline_review_package_escapes_editorial_html_in_html_and_markdown(
    tmp_path: Path,
) -> None:
    clip = _clip(tmp_path).model_copy(
        update={
            "title": "标题 <img src=x onerror=alert(1)>",
            "high_impact_sentence": "高光 <script>alert(1)</script>",
            "recommendation_reason": "理由 <iframe src=evil></iframe>",
        }
    )

    result = _create(tmp_path, (clip,))
    offline_html = result.index_path.read_text(encoding="utf-8")
    description = next((result.directory / "descriptions").glob("*.md")).read_text(encoding="utf-8")

    assert "<script>" not in offline_html and "<iframe" not in offline_html
    assert "&lt;script&gt;" in offline_html and "&lt;iframe" in offline_html
    assert "<script>" not in description and "<iframe" not in description
    assert "&lt;script&gt;" in description and "&lt;iframe" in description


def test_offline_review_package_rejects_changed_proxy_without_publishing(
    tmp_path: Path,
) -> None:
    clip = _clip(tmp_path)
    clip.proxy_path.write_bytes(b"x" * clip.proxy_size_bytes)

    with pytest.raises(OfflineReviewPackageError, match="committed hash"):
        _create(tmp_path, (clip,))

    packages = tmp_path / "project" / "offline-review-packages"
    assert not (packages / "v001").exists()
    assert not tuple(packages.glob(".v001-attempt-*"))


def test_offline_review_package_supports_pipeline_maximum_of_100_clips(
    tmp_path: Path,
) -> None:
    result = _create(
        tmp_path,
        tuple(_clip(tmp_path, ordinal=value) for value in range(1, 101)),
    )

    assert result.clip_count == 100
    assert result.zip_path is not None
    with zipfile.ZipFile(result.zip_path) as archive:
        assert len(archive.infolist()) == 305


def test_offline_review_package_withdraws_publication_when_post_fence_fails(
    tmp_path: Path,
) -> None:
    calls = 0

    def fence() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("snapshot changed")

    clip = _clip(tmp_path)
    with pytest.raises(RuntimeError, match="snapshot changed"):
        create_offline_review_package(
            project_dir=tmp_path / "project",
            project_id="project_1",
            project_name="直播 7.28",
            source_filename="/local/input/7.28.mp4",
            source_fingerprint="a" * 64,
            pipeline_run_id="run_1",
            generation=3,
            project_revision_epoch=4,
            project_status="pending_review",
            snapshot_fingerprint="b" * 64,
            clips=(clip,),
            include_zip=True,
            publication_fence=fence,
        )

    packages = tmp_path / "project" / "offline-review-packages"
    assert calls == 2
    assert not (packages / "v001").exists()
    assert not tuple(packages.glob(".v001-attempt-*"))


def test_offline_review_package_recovers_owned_orphan_attempt(tmp_path: Path) -> None:
    packages = tmp_path / "project/offline-review-packages"
    orphan = packages / ".v001-attempt-0123456789abcdef01234567"
    orphan.mkdir(parents=True)
    (orphan / "partial.mp4").write_bytes(b"partial" * 1_000)

    result = _create(tmp_path, (_clip(tmp_path),))

    assert result.package_version == "v001"
    assert not orphan.exists()


def test_offline_review_package_refuses_orphan_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    packages = tmp_path / "project/offline-review-packages"
    packages.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    orphan = packages / ".v001-attempt-0123456789abcdef01234567"
    orphan.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OfflineReviewPackageError, match="entry is unsafe"):
        _create(tmp_path, (_clip(tmp_path),))

    assert marker.read_text(encoding="utf-8") == "keep"
    assert orphan.is_symlink()
    assert not (packages / "v001").exists()
