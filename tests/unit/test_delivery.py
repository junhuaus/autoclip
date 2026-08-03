import json
import zipfile
from pathlib import Path

import pytest

from liveclip.delivery.package import (
    DeliveryClipInput,
    DeliveryError,
    create_delivery,
    safe_filename_component,
    validate_zip_members,
)
from liveclip.media.fingerprint import stream_sha256


def make_clip(tmp_path: Path, **changes: object) -> DeliveryClipInput:
    video = tmp_path / "final-r1.mp4"
    video.write_bytes(b"verified-final-video" * 100)
    payload: dict[str, object] = {
        "clip_id": "clip_1",
        "edit_plan_revision": 1,
        "render_revision": 1,
        "title": "中文标题 / 安全测试",
        "source_start_ms": 1_000,
        "source_end_ms": 31_000,
        "score": 91.5,
        "review_status": "approved",
        "render_status": "succeeded",
        "final_video_path": video,
        "subtitle_srt": "1\n00:00:00,000 --> 00:00:02,000\n第一句\n",
    }
    payload.update(changes)
    return DeliveryClipInput.model_validate(payload)


def test_delivery_requires_approved_current_succeeded_render(tmp_path: Path) -> None:
    rejected = make_clip(tmp_path, review_status="rejected")
    with pytest.raises(DeliveryError, match="approved"):
        create_delivery(
            project_dir=tmp_path / "project",
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="a" * 64,
            clips=(rejected,),
            include_zip=True,
        )

    stale = make_clip(tmp_path, edit_plan_revision=2, render_revision=1)
    with pytest.raises(DeliveryError, match="stale"):
        create_delivery(
            project_dir=tmp_path / "project",
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="a" * 64,
            clips=(stale,),
            include_zip=True,
        )


def test_delivery_creates_immutable_versions_manifest_hash_and_safe_zip(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    clip = make_clip(tmp_path)

    first = create_delivery(
        project_dir=project_dir,
        project_id="project_1",
        source_filename="/private/media/source.mp4",
        source_fingerprint="b" * 64,
        clips=(clip,),
        include_zip=True,
    )
    second = create_delivery(
        project_dir=project_dir,
        project_id="project_1",
        source_filename="/private/media/source.mp4",
        source_fingerprint="b" * 64,
        clips=(clip,),
        include_zip=True,
    )

    assert first.delivery_version == "v001"
    assert second.delivery_version == "v002"
    assert first.directory.is_dir() and second.directory.is_dir()
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    entry = manifest["clips"][0]
    delivered_video = first.directory / entry["video_filename"]
    assert manifest["source_filename"] == "source.mp4"
    assert entry["sha256"] == stream_sha256(delivered_video)
    assert "中文标题-安全测试" in entry["video_filename"]
    assert first.zip_path is not None
    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
    assert names == [
        "clips/01-中文标题-安全测试.mp4",
        "subtitles/01-中文标题-安全测试.srt",
        "manifest.json",
    ]
    validate_zip_members(names)


@pytest.mark.parametrize(
    "names",
    (
        ("../escape.mp4",),
        ("/absolute.mp4",),
        ("clips\\escape.mp4",),
        ("clips/a.mp4", "clips/a.mp4"),
    ),
)
def test_zip_member_validation_rejects_traversal_and_duplicates(names: tuple[str, ...]) -> None:
    with pytest.raises(DeliveryError):
        validate_zip_members(names)


def test_safe_filename_component_is_bounded_readable_and_never_a_path() -> None:
    value = safe_filename_component("../ 重要 / 标题 \\ .. " + "长" * 100)
    assert value.startswith("重要-标题")
    assert "/" not in value and "\\" not in value and ".." not in value
    assert len(value.encode("utf-8")) <= 72
