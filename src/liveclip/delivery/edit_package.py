# ruff: noqa: RUF001

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import struct
import uuid
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.edit_packages import EditPackageClipMetadata, subtitle_for_metadata
from liveclip.delivery.package import (
    DeliveryError,
    copy_immutable_member,
    create_verified_zip,
    normalize_srt,
    safe_filename_component,
    source_basename,
    validate_zip_members,
    verify_pinned_zip_members,
)
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    capture_pinned_file_evidence,
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    open_pinned_regular_file,
    publish_directory_no_replace_no_follow,
    remove_tree_no_follow,
    write_bytes_immutable_no_follow,
)
from liveclip.renderer.quality import MediaValidationError, full_decode, probe_media


class EditPackageError(RuntimeError):
    """An editor package could not be built or verified from immutable inputs."""


class EditPackageClipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ordinal: int = Field(ge=1, le=100)
    metadata: EditPackageClipMetadata
    video_path: Path
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    video_size_bytes: int = Field(gt=0)
    contact_sheet_path: Path
    contact_sheet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    contact_sheet_size_bytes: int = Field(gt=0)


class EditPackageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    edit_package_id: str
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    directory: Path
    manifest_path: Path
    zip_path: Path | None
    manifest: dict[str, object]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    member_sha256: dict[str, str]
    clip_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_evidence(self) -> EditPackageResult:
        if self.member_sha256.get("manifest.json") != self.manifest_sha256:
            raise ValueError("edit package manifest evidence is inconsistent")
        archive_name = f"liveclip-edit-package-{self.package_version}.zip"
        if (self.zip_path is None) != (self.zip_sha256 is None):
            raise ValueError("edit package ZIP evidence is incomplete")
        if self.zip_sha256 is not None and self.member_sha256.get(archive_name) != self.zip_sha256:
            raise ValueError("edit package ZIP evidence is inconsistent")
        validate_zip_members(self.member_sha256)
        return self


def create_edit_package(
    *,
    project_dir: Path,
    edit_package_id: str,
    project_id: str,
    project_name: str,
    owner_username: str,
    requested_by_username: str,
    source_filename: str,
    source_fingerprint: str,
    generation: int,
    project_revision_epoch: int,
    version: int,
    preset: str,
    content: str,
    snapshot_fingerprint: str,
    clips: Sequence[EditPackageClipInput],
    include_zip: bool,
    created_at: datetime,
    cancel_requested: Callable[[], bool] | None = None,
    publication_fence: Callable[[], None] | None = None,
) -> EditPackageResult:
    _validate_request(
        edit_package_id=edit_package_id,
        project_id=project_id,
        source_fingerprint=source_fingerprint,
        generation=generation,
        project_revision_epoch=project_revision_epoch,
        version=version,
        preset=preset,
        content=content,
        snapshot_fingerprint=snapshot_fingerprint,
        clips=clips,
    )
    try:
        resolved_project = ensure_directory_no_follow(project_dir)
        packages_dir = ensure_directory_no_follow(resolved_project / "edit-packages")
    except SecureFileError as exc:
        raise EditPackageError("edit package directory is not symlink-free") from exc
    lock_path = packages_dir / ".edit-package.lock"
    try:
        write_bytes_immutable_no_follow(
            lock_path,
            b"LiveClip edit package lock\n",
            max_bytes=64,
        )
        lock_file = open_pinned_regular_file(lock_path)
    except SecureFileError as exc:
        raise EditPackageError("edit package lock could not be opened safely") from exc

    package_version = f"v{version:03d}"
    destination = packages_dir / package_version
    with lock_file:
        fcntl.flock(lock_file.descriptor, fcntl.LOCK_EX)
        temporary = packages_dir / f".{package_version}-attempt-{uuid.uuid4().hex}"
        try:
            temporary_identity = create_directory_exclusive_no_follow(temporary)
        except SecureFileError as exc:
            raise EditPackageError("edit package attempt could not be created safely") from exc
        try:
            result = _build_edit_package(
                temporary=temporary,
                destination=destination,
                edit_package_id=edit_package_id,
                project_id=project_id,
                project_name=project_name,
                owner_username=owner_username,
                requested_by_username=requested_by_username,
                source_filename=source_filename,
                source_fingerprint=source_fingerprint,
                generation=generation,
                project_revision_epoch=project_revision_epoch,
                package_version=package_version,
                preset=preset,
                content=content,
                snapshot_fingerprint=snapshot_fingerprint,
                clips=clips,
                include_zip=include_zip,
                created_at=created_at,
                cancel_requested=cancel_requested,
            )
            _check_cancel(cancel_requested)
            if publication_fence is not None:
                publication_fence()
            try:
                with ExitStack() as stack:
                    pinned = _capture_members(temporary, result.member_sha256, stack=stack)
                    publish_directory_no_replace_no_follow(
                        temporary,
                        destination,
                        pinned_files=pinned,
                    )
            except SecureFileError as exc:
                raise EditPackageError("edit package could not be published safely") from exc
        except Exception:
            try:
                remove_tree_no_follow(
                    temporary,
                    required_ancestor=packages_dir,
                    expected_identity=temporary_identity,
                )
            except SecureFileError as cleanup_error:
                raise EditPackageError(
                    "edit package attempt could not be cleaned up safely"
                ) from cleanup_error
            raise
        finally:
            fcntl.flock(lock_file.descriptor, fcntl.LOCK_UN)
    return result.model_copy(
        update={
            "directory": destination,
            "manifest_path": destination / "manifest.json",
            "zip_path": (
                destination / f"liveclip-edit-package-{package_version}.zip"
                if include_zip
                else None
            ),
        }
    )


def validate_existing_edit_package(
    destination: Path,
    *,
    edit_package_id: str,
    project_id: str,
    package_version: str,
    snapshot_fingerprint: str,
    include_zip: bool,
) -> EditPackageResult:
    try:
        manifest_evidence = capture_pinned_file_evidence(destination / "manifest.json")
        try:
            manifest_bytes = manifest_evidence.pinned.read_bytes(max_bytes=4_000_000)
        finally:
            manifest_evidence.pinned.close()
        raw = json.loads(manifest_bytes)
    except (SecureFileError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditPackageError("existing edit package manifest is invalid") from exc
    if not isinstance(raw, dict):
        raise EditPackageError("existing edit package manifest is invalid")
    manifest = {str(key): value for key, value in raw.items()}
    if (
        manifest.get("schema_version") != "liveclip.edit-package.v1"
        or manifest.get("edit_package_id") != edit_package_id
        or manifest.get("project_id") != project_id
        or manifest.get("package_version") != package_version
        or manifest.get("snapshot_fingerprint") != snapshot_fingerprint
    ):
        raise EditPackageError("existing edit package differs from its reservation")
    raw_members = manifest.get("members")
    if not isinstance(raw_members, dict) or not raw_members:
        raise EditPackageError("existing edit package member evidence is missing")
    content_hashes = _validated_hash_map(raw_members)
    for name, expected in content_hashes.items():
        _assert_member_hash(destination, name, expected)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    checksums_name = "checksums.sha256"
    checksums_evidence = _member_evidence(destination, checksums_name)
    try:
        checksum_bytes = checksums_evidence.pinned.read_bytes(max_bytes=2_000_000)
    finally:
        checksums_evidence.pinned.close()
    expected_checksums = _checksums_payload({**content_hashes, "manifest.json": manifest_sha256})
    if checksum_bytes != expected_checksums:
        raise EditPackageError("existing edit package checksums are invalid")
    checksums_sha256 = hashlib.sha256(checksum_bytes).hexdigest()
    member_hashes = {
        **content_hashes,
        "manifest.json": manifest_sha256,
        checksums_name: checksums_sha256,
    }
    zip_path = destination / f"liveclip-edit-package-{package_version}.zip"
    zip_sha256 = None
    if include_zip:
        zip_evidence = _member_evidence(destination, zip_path.name)
        try:
            zip_sha256 = zip_evidence.sha256
            verify_pinned_zip_members(
                zip_evidence,
                expected_sha256=member_hashes,
                expected_manifest=manifest,
            )
        except DeliveryError as exc:
            raise EditPackageError("existing edit package ZIP is invalid") from exc
        finally:
            zip_evidence.pinned.close()
        member_hashes[zip_path.name] = zip_sha256
    elif zip_path.exists():
        raise EditPackageError("non-ZIP edit package unexpectedly contains an archive")
    clips = manifest.get("clips")
    if not isinstance(clips, list) or not clips:
        raise EditPackageError("existing edit package clip list is invalid")
    return EditPackageResult(
        edit_package_id=edit_package_id,
        package_version=package_version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=zip_path if include_zip else None,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_hashes,
        clip_count=len(clips),
    )


def _build_edit_package(
    *,
    temporary: Path,
    destination: Path,
    edit_package_id: str,
    project_id: str,
    project_name: str,
    owner_username: str,
    requested_by_username: str,
    source_filename: str,
    source_fingerprint: str,
    generation: int,
    project_revision_epoch: int,
    package_version: str,
    preset: str,
    content: str,
    snapshot_fingerprint: str,
    clips: Sequence[EditPackageClipInput],
    include_zip: bool,
    created_at: datetime,
    cancel_requested: Callable[[], bool] | None,
) -> EditPackageResult:
    directories = ["metadata", "thumbnails"]
    if content == "full":
        directories = ["media", "subtitles", *directories]
    for directory in directories:
        try:
            ensure_directory_no_follow(temporary / directory)
        except SecureFileError as exc:
            raise EditPackageError("edit package member directory is unsafe") from exc
    content_hashes: dict[str, str] = {}
    manifest_clips: list[dict[str, object]] = []
    csv_rows: list[dict[str, str | int | float]] = []
    for clip in clips:
        _check_cancel(cancel_requested)
        title_component = safe_filename_component(clip.metadata.title)
        stem = f"{clip.ordinal:02d}-{title_component}"
        ascii_alias = f"{clip.ordinal:02d}-clip-{clip.metadata.clip_id[:8]}"
        video_name: str | None = None
        subtitle_name: str | None = None
        video_hash: str | None = None
        subtitle_hash: str | None = None
        video_validation: dict[str, object] | None = None
        if content == "full":
            video_name = f"media/{stem}.mp4"
            subtitle_name = f"subtitles/{stem}.srt"
            video_target = temporary / Path(*PurePosixPath(video_name).parts)
            video_hash = copy_immutable_member(
                clip.video_path,
                video_target,
                expected_sha256=clip.video_sha256,
            )
            video_validation = _validate_editor_video(
                video_target,
                cancel_requested=cancel_requested,
            )
            subtitle = normalize_srt(subtitle_for_metadata(clip.metadata))
            subtitle_payload = subtitle.encode("utf-8")
            if subtitle_payload.startswith(b"\xef\xbb\xbf"):
                raise EditPackageError("edit package subtitle must not contain a UTF-8 BOM")
            subtitle_hash = hashlib.sha256(subtitle_payload).hexdigest()
            _write_member(temporary, subtitle_name, subtitle_payload, maximum_bytes=1_000_000)
            content_hashes[video_name] = video_hash
            content_hashes[subtitle_name] = subtitle_hash

        thumbnail_name = f"thumbnails/{stem}.png"
        thumbnail_target = temporary / Path(*PurePosixPath(thumbnail_name).parts)
        thumbnail_hash = copy_immutable_member(
            clip.contact_sheet_path,
            thumbnail_target,
            expected_sha256=clip.contact_sheet_sha256,
        )
        content_hashes[thumbnail_name] = thumbnail_hash
        keyword_text = "; ".join(
            f"{item.text}@{item.clip_start_ms / 1000:.3f}s" for item in clip.metadata.keywords
        )
        risk_text = "; ".join(clip.metadata.risk_flags)
        manifest_entry: dict[str, object] = {
            "ordinal": clip.ordinal,
            "clip_id": clip.metadata.clip_id,
            "edit_plan_revision": clip.metadata.edit_plan_revision,
            "title": clip.metadata.title,
            "high_impact_sentence": clip.metadata.high_impact_sentence,
            "recommendation_reason": clip.metadata.recommendation_reason,
            "risk_flags": list(clip.metadata.risk_flags),
            "keywords": [item.model_dump(mode="json") for item in clip.metadata.keywords],
            "source_start_ms": clip.metadata.source_start_ms,
            "source_end_ms": clip.metadata.source_end_ms,
            "duration_ms": clip.metadata.source_end_ms - clip.metadata.source_start_ms,
            "score": clip.metadata.score,
            "review_status": clip.metadata.review_status.value,
            "video_filename": video_name,
            "subtitle_filename": subtitle_name,
            "thumbnail_filename": thumbnail_name,
            "ascii_video_alias": f"{ascii_alias}.mp4" if video_name else None,
            "ascii_subtitle_alias": f"{ascii_alias}.srt" if subtitle_name else None,
            "video_sha256": video_hash,
            "subtitle_sha256": subtitle_hash,
            "thumbnail_sha256": thumbnail_hash,
            "video_validation": video_validation,
        }
        manifest_clips.append(manifest_entry)
        csv_rows.append(
            {
                "ordinal": clip.ordinal,
                "clip_id": clip.metadata.clip_id,
                "revision": clip.metadata.edit_plan_revision,
                "title": clip.metadata.title,
                "high_impact_sentence": clip.metadata.high_impact_sentence,
                "recommendation_reason": clip.metadata.recommendation_reason,
                "risk_flags": risk_text,
                "keywords_and_clip_times": keyword_text,
                "source_start_seconds": round(clip.metadata.source_start_ms / 1_000, 3),
                "source_end_seconds": round(clip.metadata.source_end_ms / 1_000, 3),
                "score": clip.metadata.score,
                "review_status": clip.metadata.review_status.value,
                "video_filename": video_name or "",
                "subtitle_filename": subtitle_name or "",
                "thumbnail_filename": thumbnail_name,
                "ascii_video_alias": f"{ascii_alias}.mp4" if video_name else "",
                "ascii_subtitle_alias": f"{ascii_alias}.srt" if subtitle_name else "",
            }
        )

    clips_json = {
        "schema_version": "liveclip.edit-package.clips.v1",
        "clips": manifest_clips,
    }
    _write_json_member(temporary, "metadata/clips.json", clips_json, content_hashes)
    csv_payload = _csv_payload(csv_rows)
    _write_hashed_member(temporary, "metadata/clips.csv", csv_payload, content_hashes)
    guide_payload = _guide_text(package_version, content=content).encode("utf-8")
    _write_hashed_member(
        temporary,
        "metadata/README-导入剪映.txt",
        guide_payload,
        content_hashes,
    )
    aliases_payload = _alias_csv_payload(manifest_clips)
    _write_hashed_member(
        temporary,
        "metadata/ascii-aliases.csv",
        aliases_payload,
        content_hashes,
    )

    manifest: dict[str, object] = {
        "schema_version": "liveclip.edit-package.v1",
        "edit_package_id": edit_package_id,
        "package_version": package_version,
        "project_id": project_id,
        "project_name": project_name,
        "project_owner": owner_username,
        "requested_by": requested_by_username,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "source_filename": source_basename(source_filename),
        "source_fingerprint": source_fingerprint,
        "generation": generation,
        "project_revision_epoch": project_revision_epoch,
        "preset": preset,
        "content": content,
        "snapshot_fingerprint": snapshot_fingerprint,
        "subtitle_encoding": "UTF-8 without BOM",
        "subtitle_timeline": "clip_relative_ms",
        "clean_video": content == "full",
        "clips": manifest_clips,
        "members": dict(sorted(content_hashes.items())),
    }
    manifest_payload = _json_payload(manifest)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    _write_member(temporary, "manifest.json", manifest_payload, maximum_bytes=4_000_000)
    checksum_members = {**content_hashes, "manifest.json": manifest_sha256}
    checksums_payload = _checksums_payload(checksum_members)
    checksums_sha256 = hashlib.sha256(checksums_payload).hexdigest()
    _write_member(
        temporary,
        "checksums.sha256",
        checksums_payload,
        maximum_bytes=2_000_000,
    )
    member_hashes = {
        **content_hashes,
        "manifest.json": manifest_sha256,
        "checksums.sha256": checksums_sha256,
    }
    zip_path: Path | None = None
    zip_sha256: str | None = None
    if include_zip:
        archive_name = f"liveclip-edit-package-{package_version}.zip"
        zip_path = temporary / archive_name
        archive_members = tuple(PurePosixPath(name) for name in validate_zip_members(member_hashes))
        try:
            zip_sha256 = create_verified_zip(
                root=temporary,
                output_path=zip_path,
                members=archive_members,
                manifest=manifest,
                expected_sha256=member_hashes,
            )
        except DeliveryError as exc:
            raise EditPackageError("edit package ZIP validation failed") from exc
        member_hashes[archive_name] = zip_sha256
    return EditPackageResult(
        edit_package_id=edit_package_id,
        package_version=package_version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=(destination / zip_path.name) if zip_path is not None else None,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_hashes,
        clip_count=len(clips),
    )


def _validate_request(
    *,
    edit_package_id: str,
    project_id: str,
    source_fingerprint: str,
    generation: int,
    project_revision_epoch: int,
    version: int,
    preset: str,
    content: str,
    snapshot_fingerprint: str,
    clips: Sequence[EditPackageClipInput],
) -> None:
    for identifier in (edit_package_id, project_id):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) is None:
            raise EditPackageError("edit package identifier is invalid")
    if re.fullmatch(r"[a-f0-9]{64}", source_fingerprint) is None:
        raise EditPackageError("edit package source fingerprint is invalid")
    if re.fullmatch(r"[a-f0-9]{64}", snapshot_fingerprint) is None:
        raise EditPackageError("edit package snapshot fingerprint is invalid")
    if generation < 1 or project_revision_epoch < 0 or not 1 <= version <= 999:
        raise EditPackageError("edit package version fence is invalid")
    if preset != "clean_editing" or content not in {"full", "metadata_only"}:
        raise EditPackageError("edit package preset is invalid")
    if not clips or len(clips) > 100:
        raise EditPackageError("edit package clip count is invalid")
    ordinals = tuple(clip.ordinal for clip in clips)
    identifiers = tuple(clip.metadata.clip_id for clip in clips)
    if ordinals != tuple(range(1, len(clips) + 1)) or len(set(identifiers)) != len(identifiers):
        raise EditPackageError("edit package selection order is invalid")


def _validate_editor_video(
    path: Path,
    *,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, object]:
    try:
        probe = probe_media(path, cancel_requested=cancel_requested)
        streams = probe.get("streams")
        if not isinstance(streams, list):
            raise EditPackageError("editor video probe has no stream list")
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        if not isinstance(video, dict) or not isinstance(audio, dict):
            raise EditPackageError("editor video must contain video and audio")
        if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
            raise EditPackageError("editor video must use H.264 and AAC")
        if video.get("pix_fmt") != "yuv420p":
            raise EditPackageError("editor video must use yuv420p")
        if video.get("field_order") not in {None, "unknown", "progressive"}:
            raise EditPackageError("editor video must be progressive")
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
        if width <= 0 or height <= width:
            raise EditPackageError("editor video must be portrait")
        format_payload = probe.get("format")
        if not isinstance(format_payload, dict) or "mp4" not in str(
            format_payload.get("format_name", "")
        ).split(","):
            raise EditPackageError("editor video must be MP4")
        full_decode(path, cancel_requested=cancel_requested)
        if not _has_fast_start(path):
            raise EditPackageError("editor video must place moov before mdat")
    except MediaValidationError as exc:
        raise EditPackageError("editor video validation failed") from exc
    return {
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
        "scan": "progressive",
        "fast_start": True,
        "full_decode": "passed",
        "width": width,
        "height": height,
    }


def _has_fast_start(path: Path) -> bool:
    try:
        with open_pinned_regular_file(path) as pinned:
            size = pinned.metadata.st_size
            offset = 0
            moov_offset: int | None = None
            mdat_offset: int | None = None
            while offset + 8 <= size and offset < size:
                header = os.pread(pinned.descriptor, 16, offset)
                if len(header) < 8:
                    break
                box_size = struct.unpack(">I", header[:4])[0]
                box_type = header[4:8]
                header_size = 8
                if box_size == 1:
                    if len(header) < 16:
                        return False
                    box_size = struct.unpack(">Q", header[8:16])[0]
                    header_size = 16
                elif box_size == 0:
                    box_size = size - offset
                if box_size < header_size or offset + box_size > size:
                    return False
                if box_type == b"moov" and moov_offset is None:
                    moov_offset = offset
                if box_type == b"mdat" and mdat_offset is None:
                    mdat_offset = offset
                if moov_offset is not None and mdat_offset is not None:
                    return moov_offset < mdat_offset
                offset += box_size
            pinned.validate_binding()
    except SecureFileError as exc:
        raise EditPackageError("editor video changed during fast-start validation") from exc
    return False


def _csv_payload(rows: list[dict[str, str | int | float]]) -> bytes:
    if not rows:
        raise EditPackageError("edit package metadata is empty")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _alias_csv_payload(clips: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames = (
        "clip_id",
        "title",
        "video_filename",
        "ascii_video_alias",
        "subtitle_filename",
        "ascii_subtitle_alias",
    )
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for clip in clips:
        writer.writerow({name: clip.get(name) or "" for name in fieldnames})
    return stream.getvalue().encode("utf-8")


def _guide_text(package_version: str, *, content: str) -> str:
    media_step = (
        "1. 解压 ZIP，把 media/ 中的 MP4 全部导入剪映专业版或 CapCut Desktop/Web。\n"
        "2. 导入 subtitles/ 中与 MP4 同名的 SRT；"
        "字幕是 UTF-8（无 BOM）且时间从每个切片 00:00 开始。\n"
        if content == "full"
        else "1. 此包为仅元数据模式，不含 MP4/SRT；请结合 LiveClip 的单条下载使用。\n"
    )
    return (
        f"LiveClip 编辑交接包 {package_version}\n\n"
        + media_step
        + "3. metadata/clips.csv 适合表格查看；clips.json 保留高光语句、理由、风险和关键词时间。\n"
        + "4. thumbnails/ 是每条高光的审核联系表，可辅助选素材和封面。\n"
        + "5. checksums.sha256 用于确认传输后文件未变化；"
        + "ascii-aliases.csv 提供编码兼容的改名建议。\n\n"
        + "注意：视频是无 LiveClip 烧字的干净审核代理，可继续剪辑；字幕保持独立可编辑。"
        + "剪映/CapCut 移动端不声明支持直接导入外部 SRT，请使用桌面版或网页版。"
        + "本包不是未公开格式的剪映草稿工程。\n"
    )


def _json_payload(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json_member(
    root: Path,
    name: str,
    value: object,
    hashes: dict[str, str],
) -> None:
    _write_hashed_member(root, name, _json_payload(value), hashes)


def _write_hashed_member(
    root: Path,
    name: str,
    payload: bytes,
    hashes: dict[str, str],
) -> None:
    _write_member(root, name, payload, maximum_bytes=4_000_000)
    hashes[name] = hashlib.sha256(payload).hexdigest()


def _write_member(root: Path, name: str, payload: bytes, *, maximum_bytes: int) -> None:
    validate_zip_members((name,))
    path = root / Path(*PurePosixPath(name).parts)
    try:
        write_bytes_immutable_no_follow(path, payload, max_bytes=maximum_bytes)
    except SecureFileError as exc:
        raise EditPackageError("edit package metadata could not be written safely") from exc


def _checksums_payload(values: dict[str, str]) -> bytes:
    validate_zip_members(values)
    return "".join(f"{values[name]}  {name}\n" for name in sorted(values)).encode("utf-8")


def _capture_members(
    root: Path,
    hashes: dict[str, str],
    *,
    stack: ExitStack,
) -> dict[str, PinnedFileEvidence]:
    pinned: dict[str, PinnedFileEvidence] = {}
    for name in validate_zip_members(hashes):
        evidence = _member_evidence(root, name, expected_sha256=hashes[name])
        stack.callback(evidence.pinned.close)
        pinned[name] = evidence
    return pinned


def _member_evidence(
    root: Path,
    name: str,
    *,
    expected_sha256: str | None = None,
) -> PinnedFileEvidence:
    validate_zip_members((name,))
    try:
        return capture_pinned_file_evidence(
            root / Path(*PurePosixPath(name).parts),
            expected_sha256=expected_sha256,
        )
    except SecureFileError as exc:
        raise EditPackageError("edit package member is missing or unsafe") from exc


def _assert_member_hash(root: Path, name: str, expected_sha256: str) -> None:
    evidence = _member_evidence(root, name, expected_sha256=expected_sha256)
    evidence.pinned.close()


def _validated_hash_map(value: dict[object, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, digest in value.items():
        name = str(key)
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise EditPackageError("edit package member hash is invalid")
        result[name] = digest
    validate_zip_members(result)
    return result


def _check_cancel(callback: Callable[[], bool] | None) -> None:
    if callback is not None and callback():
        raise InterruptedError("edit package creation was cancelled")
