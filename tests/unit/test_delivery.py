import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from liveclip.delivery import package as delivery_package
from liveclip.delivery.package import (
    DeliveryClipInput,
    DeliveryError,
    create_delivery,
    hash_zip_member,
    safe_filename_component,
    validate_zip_infos,
    validate_zip_members,
)
from liveclip.media import secure_files
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
        "final_video_sha256": stream_sha256(video),
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
        for name in names:
            assert hash_zip_member(archive, name) == first.member_sha256[name]
    assert names == [
        "clips/01-中文标题-安全测试.mp4",
        "subtitles/01-中文标题-安全测试.srt",
        "manifest.json",
    ]
    validate_zip_members(names)
    assert first.manifest_sha256 == stream_sha256(first.manifest_path)
    assert first.zip_sha256 == stream_sha256(first.zip_path)
    assert set(first.member_sha256) == {*names, "delivery.zip"}
    for name, expected_sha256 in first.member_sha256.items():
        assert stream_sha256(first.directory / name) == expected_sha256


@pytest.mark.parametrize(
    "names",
    (
        ("../escape.mp4",),
        ("/absolute.mp4",),
        ("clips\\escape.mp4",),
        ("C:/escape.mp4",),
        ("clips/control\x01.mp4",),
        ("clips/a.mp4", "clips/a.mp4"),
        ("clips/Ａ.mp4", "clips/A.mp4"),  # noqa: RUF001
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


def test_delivery_rejects_symlinked_delivery_root_without_external_write(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_dir / "deliveries").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DeliveryError, match="symlink-free"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="d" * 64,
            clips=(make_clip(tmp_path),),
            include_zip=True,
        )
    assert not list(outside.iterdir())


def test_delivery_copy_compares_bytes_to_committed_hash(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    clip = make_clip(tmp_path)
    clip.final_video_path.write_bytes(b"x" * clip.final_video_path.stat().st_size)

    with pytest.raises(DeliveryError, match="committed hash"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="e" * 64,
            clips=(clip,),
            include_zip=True,
        )
    assert not (project_dir / "deliveries" / "v001").exists()


def test_zip_stream_rejects_subtitle_symlink_swap_without_external_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("EXTERNAL-SECRET", encoding="utf-8")
    real_write = delivery_package._write_pinned_zip_member
    swapped = False

    def racing_write(
        archive: zipfile.ZipFile,
        name: str,
        evidence: secure_files.PinnedFileEvidence,
    ) -> None:
        nonlocal swapped
        if not swapped and name.startswith("subtitles/"):
            swapped = True
            evidence.pinned.path.unlink()
            evidence.pinned.path.symlink_to(outside)
        real_write(archive, name, evidence)

    monkeypatch.setattr(delivery_package, "_write_pinned_zip_member", racing_write)

    with pytest.raises(DeliveryError, match="stable local members"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="4" * 64,
            clips=(make_clip(tmp_path),),
            include_zip=True,
        )

    assert swapped
    assert outside.read_text(encoding="utf-8") == "EXTERNAL-SECRET"
    assert not (project_dir / "deliveries" / "v001").exists()
    assert not tuple((project_dir / "deliveries").glob(".v001-attempt-*"))


def test_delivery_rejects_zip_replacement_after_validation_before_directory_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    real_rename = secure_files._rename_directory_no_replace
    replaced = False

    def racing_rename(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal replaced
        if not replaced and destination_name == "v001":
            replaced = True
            attempt = project_dir / "deliveries" / source_name
            archive = attempt / "delivery.zip"
            archive.unlink()
            archive.write_bytes(b"attacker-zip")
        real_rename(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )

    monkeypatch.setattr(secure_files, "_rename_directory_no_replace", racing_rename)

    with pytest.raises(DeliveryError, match="published safely"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="5" * 64,
            clips=(make_clip(tmp_path),),
            include_zip=True,
        )

    assert replaced
    assert not (project_dir / "deliveries" / "v001").exists()
    assert not tuple((project_dir / "deliveries").glob(".v001-attempt-*"))


def test_delivery_publication_rejects_post_validation_directory_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    deliveries_dir = project_dir / "deliveries"
    attacker = deliveries_dir / ".attacker-ready"
    attacker.mkdir(parents=True)
    (attacker / "attacker.txt").write_text("attacker", encoding="utf-8")
    real_rename = secure_files._rename_directory_no_replace
    swapped = False

    def racing_rename(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped and destination_name == "v001":
            swapped = True
            os.rename(
                source_name,
                ".detached-verified",
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
            os.rename(
                attacker.name,
                source_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
        real_rename(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )

    monkeypatch.setattr(secure_files, "_rename_directory_no_replace", racing_rename)

    with pytest.raises(DeliveryError, match="published safely"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="f" * 64,
            clips=(make_clip(tmp_path),),
            include_zip=True,
        )

    assert swapped
    assert not (deliveries_dir / "v001").exists()
    assert not tuple(deliveries_dir.glob(".v001-attempt-*"))
    quarantined = tuple(deliveries_dir.glob(".v001.rejected-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "attacker.txt").read_text(encoding="utf-8") == "attacker"
    assert (deliveries_dir / ".detached-verified" / "manifest.json").is_file()


def test_delivery_expected_version_never_clobbers_and_cleans_attempt(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    clip = make_clip(tmp_path)
    first = create_delivery(
        project_dir=project_dir,
        project_id="project_1",
        source_filename="source.mp4",
        source_fingerprint="1" * 64,
        clips=(clip,),
        include_zip=True,
        expected_version=1,
    )
    original_manifest = first.manifest_path.read_bytes()

    with pytest.raises(DeliveryError, match="published safely"):
        create_delivery(
            project_dir=project_dir,
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="2" * 64,
            clips=(clip,),
            include_zip=True,
            expected_version=1,
        )

    assert first.manifest_path.read_bytes() == original_manifest
    assert not tuple((project_dir / "deliveries").glob(".v001-attempt-*"))


def test_delivery_cleanup_never_follows_swapped_attempt_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_marker = outside / "keep.txt"
    outside_marker.write_text("keep", encoding="utf-8")
    captured_temporary: Path | None = None

    def failing_build(**arguments: object) -> None:
        nonlocal captured_temporary
        temporary = arguments["temporary"]
        assert isinstance(temporary, Path)
        captured_temporary = temporary
        temporary.rename(temporary.with_name(".detached-attempt"))
        temporary.symlink_to(outside, target_is_directory=True)
        raise DeliveryError("injected build failure")

    monkeypatch.setattr(delivery_package, "_build_delivery", failing_build)

    with pytest.raises(DeliveryError, match="cleaned up safely"):
        create_delivery(
            project_dir=tmp_path / "project",
            project_id="project_1",
            source_filename="source.mp4",
            source_fingerprint="3" * 64,
            clips=(make_clip(tmp_path),),
            include_zip=True,
        )

    assert captured_temporary is not None and captured_temporary.is_symlink()
    assert outside_marker.read_text(encoding="utf-8") == "keep"


def test_zip_info_validation_rejects_non_regular_encrypted_and_oversized_members() -> None:
    symbolic = zipfile.ZipInfo("clips/link.mp4")
    symbolic.create_system = 3
    symbolic.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(DeliveryError, match="non-regular"):
        validate_zip_infos((symbolic,))

    encrypted = zipfile.ZipInfo("clips/encrypted.mp4")
    encrypted.flag_bits |= 0x1
    with pytest.raises(DeliveryError, match="encrypted"):
        validate_zip_infos((encrypted,))

    oversized = zipfile.ZipInfo("clips/large.mp4")
    oversized.file_size = 513 * 1024 * 1024
    with pytest.raises(DeliveryError, match="size budget"):
        validate_zip_infos((oversized,))
