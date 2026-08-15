# ruff: noqa: RUF001
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.releases import ReleasePackageWork
from liveclip.delivery.edit_package import (
    EditPackageError,
    EditPackageTransientError,
    validate_editor_video,
)
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
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.domain.releases import (
    ReleaseApprovalStatus,
    ReleaseEditorialFacts,
    ReleaseMediaFacts,
    ReleasePreflight,
    evaluate_release_preflight,
)
from liveclip.domain.time import ms_to_ffmpeg
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    capture_pinned_file_evidence,
    create_directory_exclusive_no_follow,
    directory_identity_no_follow,
    ensure_directory_no_follow,
    publish_directory_no_replace_no_follow,
    publish_regular_file_immutable_no_follow,
    remove_tree_no_follow,
    write_bytes_immutable_no_follow,
)


class ReleasePackageError(RuntimeError):
    """A platform package failed deterministic local construction or validation."""


class ReleasePackageTransientError(ReleasePackageError):
    """A platform package failed for a bounded-retry local reason."""


class ReleasePackageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    release_package_id: str
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    directory: Path
    manifest_path: Path
    zip_path: Path | None
    manifest: dict[str, object]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    member_sha256: dict[str, str]
    directory_identity: tuple[int, int] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_evidence(self) -> ReleasePackageResult:
        if self.member_sha256.get("manifest.json") != self.manifest_sha256:
            raise ValueError("release package manifest evidence is inconsistent")
        if (self.zip_path is None) != (self.zip_sha256 is None):
            raise ValueError("release package ZIP evidence is incomplete")
        if self.zip_path is not None and self.member_sha256.get(self.zip_path.name) != (
            self.zip_sha256
        ):
            raise ValueError("release package ZIP evidence is inconsistent")
        validate_zip_members(self.member_sha256)
        return self


def create_release_package(
    *,
    project_dir: Path,
    work: ReleasePackageWork,
    video_path: Path,
    cancel_requested: Callable[[], bool] | None = None,
    publication_fence: Callable[[], None] | None = None,
) -> ReleasePackageResult:
    _validate_work(work)
    _check_cancel(cancel_requested)
    try:
        resolved_project = ensure_directory_no_follow(project_dir)
        packages_dir = ensure_directory_no_follow(resolved_project / "release-packages")
        item_dir = ensure_directory_no_follow(packages_dir / work.release_item_id)
    except SecureFileError as exc:
        raise ReleasePackageError("release package directory is not symlink-free") from exc
    lock_path = item_dir / ".release-package.lock"
    try:
        write_bytes_immutable_no_follow(
            lock_path,
            b"LiveClip release package lock\n",
            max_bytes=64,
        )
        lock_evidence = capture_pinned_file_evidence(lock_path)
    except SecureFileError as exc:
        raise ReleasePackageError("release package lock could not be opened safely") from exc
    package_version = f"v{work.version:03d}"
    destination = item_dir / package_version
    with lock_evidence.pinned:
        fcntl.flock(lock_evidence.pinned.descriptor, fcntl.LOCK_EX)
        temporary = item_dir / f".{package_version}-attempt-{uuid.uuid4().hex}"
        try:
            temporary_identity = create_directory_exclusive_no_follow(temporary)
        except SecureFileError as exc:
            raise ReleasePackageError(
                "release package attempt could not be created safely"
            ) from exc
        published = False
        try:
            result = _build_release_package(
                temporary=temporary,
                destination=destination,
                work=work,
                video_path=video_path,
                cancel_requested=cancel_requested,
            )
            _check_cancel(cancel_requested)
            if publication_fence is not None:
                publication_fence()
            try:
                with ExitStack() as stack:
                    pinned = _capture_members(
                        temporary,
                        result.member_sha256,
                        stack=stack,
                    )
                    publish_directory_no_replace_no_follow(
                        temporary,
                        destination,
                        pinned_files=pinned,
                    )
                    published = True
                    if publication_fence is not None:
                        publication_fence()
            except SecureFileError as exc:
                raise ReleasePackageError("release package could not be published safely") from exc
        except Exception:
            try:
                remove_tree_no_follow(
                    destination if published else temporary,
                    required_ancestor=item_dir,
                    expected_identity=temporary_identity,
                )
            except SecureFileError as cleanup_error:
                raise ReleasePackageError(
                    "release package attempt could not be cleaned up safely"
                ) from cleanup_error
            raise
        finally:
            fcntl.flock(lock_evidence.pinned.descriptor, fcntl.LOCK_UN)
    return result.model_copy(
        update={
            "directory": destination,
            "manifest_path": destination / "manifest.json",
            "zip_path": (destination / release_archive_name(work) if work.include_zip else None),
            "directory_identity": temporary_identity,
        }
    )


def validate_existing_release_package(
    destination: Path,
    *,
    work: ReleasePackageWork,
    cancel_requested: Callable[[], bool] | None = None,
) -> ReleasePackageResult:
    _validate_work(work)
    _check_cancel(cancel_requested)
    try:
        manifest_evidence = capture_pinned_file_evidence(destination / "manifest.json")
        try:
            manifest_bytes = manifest_evidence.pinned.read_bytes(max_bytes=4_000_000)
        finally:
            manifest_evidence.pinned.close()
        raw = json.loads(manifest_bytes)
    except (SecureFileError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleasePackageError("existing release package manifest is invalid") from exc
    if not isinstance(raw, dict):
        raise ReleasePackageError("existing release package manifest is invalid")
    manifest = {str(key): value for key, value in raw.items()}
    package_version = f"v{work.version:03d}"
    raw_members = manifest.get("members")
    if not isinstance(raw_members, dict) or not raw_members:
        raise ReleasePackageError("existing release package member evidence is missing")
    content_hashes = _validated_hash_map(raw_members)
    for name, digest in content_hashes.items():
        _assert_member_hash(destination, name, digest)

    stem = safe_filename_component(work.title)
    video_name = f"media/{stem}.mp4"
    subtitle_name = f"subtitles/{stem}.srt" if work.caption_mode.value == "clean_separate" else None
    cover_name = f"cover/{stem}-cover.png"
    if content_hashes.get(video_name) != work.source_video_sha256:
        raise ReleasePackageError("existing release package video differs from its source")
    video_evidence = _member_evidence(
        destination,
        video_name,
        expected_sha256=work.source_video_sha256,
    )
    try:
        if video_evidence.size_bytes != work.source_video_size_bytes:
            raise ReleasePackageError("existing release package video size changed")
    finally:
        video_evidence.pinned.close()
    video_path = destination / Path(*PurePosixPath(video_name).parts)
    media_validation, actual_preflight = _validate_release_video(
        work,
        video_path,
        cancel_requested=cancel_requested,
    )
    _validate_recovered_cover(
        destination,
        video_path=video_path,
        cover_name=cover_name,
        timestamp_ms=work.cover_time_ms,
        cancel_requested=cancel_requested,
    )
    expected_content_hashes = _expected_release_content_hashes(
        work,
        video_name=video_name,
        subtitle_name=subtitle_name,
        cover_name=cover_name,
        cover_sha256=content_hashes.get(cover_name),
        media_validation=media_validation,
        actual_preflight=actual_preflight,
    )
    if content_hashes != expected_content_hashes:
        raise ReleasePackageError("existing release package content differs from its reservation")
    expected_manifest = _release_manifest(
        work,
        package_version=package_version,
        video_name=video_name,
        subtitle_name=subtitle_name,
        cover_name=cover_name,
        video_sha256=work.source_video_sha256,
        media_validation=media_validation,
        actual_preflight=actual_preflight,
        hashes=expected_content_hashes,
    )
    expected_manifest_payload = _json_payload(expected_manifest)
    if manifest != expected_manifest or manifest_bytes != expected_manifest_payload:
        raise ReleasePackageError("existing release package differs from its reservation")

    manifest_sha256 = hashlib.sha256(expected_manifest_payload).hexdigest()
    checksums_payload = _checksums_payload({**content_hashes, "manifest.json": manifest_sha256})
    checksums = _member_evidence(destination, "checksums.sha256")
    try:
        stored_checksums = checksums.pinned.read_bytes(max_bytes=2_000_000)
    finally:
        checksums.pinned.close()
    if stored_checksums != checksums_payload:
        raise ReleasePackageError("existing release package checksums are invalid")
    checksums_sha256 = hashlib.sha256(stored_checksums).hexdigest()
    member_hashes = {
        **content_hashes,
        "manifest.json": manifest_sha256,
        "checksums.sha256": checksums_sha256,
    }
    archive = destination / release_archive_name(work)
    zip_sha256 = None
    if work.include_zip:
        zip_evidence = _member_evidence(destination, archive.name)
        try:
            zip_sha256 = zip_evidence.sha256
            verify_pinned_zip_members(
                zip_evidence,
                expected_sha256=member_hashes,
                expected_manifest=manifest,
            )
        except DeliveryError as exc:
            raise ReleasePackageError("existing release package ZIP is invalid") from exc
        finally:
            zip_evidence.pinned.close()
        member_hashes[archive.name] = zip_sha256
    elif archive.exists():
        raise ReleasePackageError("non-ZIP release package unexpectedly contains an archive")
    expected_files = set(member_hashes)
    actual_files = _actual_member_names(destination)
    if actual_files != expected_files:
        raise ReleasePackageError("existing release package member set changed")
    _check_cancel(cancel_requested)
    return ReleasePackageResult(
        release_package_id=work.release_package_id,
        package_version=package_version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=archive if work.include_zip else None,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_hashes,
        directory_identity=directory_identity_no_follow(destination),
    )


def _build_release_package(
    *,
    temporary: Path,
    destination: Path,
    work: ReleasePackageWork,
    video_path: Path,
    cancel_requested: Callable[[], bool] | None,
) -> ReleasePackageResult:
    for directory in ("media", "cover", "metadata"):
        try:
            ensure_directory_no_follow(temporary / directory)
        except SecureFileError as exc:
            raise ReleasePackageError("release package member directory is unsafe") from exc
    if work.caption_mode.value == "clean_separate":
        try:
            ensure_directory_no_follow(temporary / "subtitles")
        except SecureFileError as exc:
            raise ReleasePackageError("release subtitle directory is unsafe") from exc
    _check_cancel(cancel_requested)
    stem = safe_filename_component(work.title)
    video_name = f"media/{stem}.mp4"
    video_target = temporary / Path(*PurePosixPath(video_name).parts)
    video_sha256 = copy_immutable_member(
        video_path,
        video_target,
        expected_sha256=work.source_video_sha256,
    )
    if video_target.stat().st_size != work.source_video_size_bytes:
        raise ReleasePackageError("release source video size changed")
    media_validation, actual_preflight = _validate_release_video(
        work,
        video_target,
        cancel_requested=cancel_requested,
    )
    hashes: dict[str, str] = {video_name: video_sha256}
    subtitle_name = None
    if work.caption_mode.value == "clean_separate":
        subtitle_name = f"subtitles/{stem}.srt"
        try:
            subtitle = normalize_srt(captions_to_srt(work.captions))
        except DeliveryError as exc:
            raise ReleasePackageError("release subtitle is invalid") from exc
        subtitle_payload = subtitle.encode("utf-8")
        if subtitle_payload.startswith(b"\xef\xbb\xbf"):
            raise ReleasePackageError("release subtitle must not contain a UTF-8 BOM")
        _write_hashed_member(
            temporary,
            subtitle_name,
            subtitle_payload,
            hashes,
            maximum_bytes=1_000_000,
        )
    cover_name = f"cover/{stem}-cover.png"
    cover_target = temporary / Path(*PurePosixPath(cover_name).parts)
    _extract_cover(
        video_target,
        cover_target,
        timestamp_ms=work.cover_time_ms,
        cancel_requested=cancel_requested,
    )
    hashes[cover_name] = _hash_member(cover_target)
    _write_hashed_member(
        temporary,
        "metadata/release-copy.txt",
        _release_copy(work).encode("utf-8"),
        hashes,
        maximum_bytes=100_000,
    )
    _write_json_member(
        temporary,
        "metadata/release-copy.json",
        _release_copy_json(work),
        hashes,
    )
    _write_json_member(
        temporary,
        "metadata/checklist.json",
        work.checklist.model_dump(mode="json"),
        hashes,
    )
    _write_json_member(
        temporary,
        "metadata/preflight.json",
        _release_preflight_payload(work, media_validation, actual_preflight),
        hashes,
    )
    _write_hashed_member(
        temporary,
        "README-发布说明.txt",
        _guide_text(work, subtitle_name=subtitle_name).encode("utf-8"),
        hashes,
        maximum_bytes=100_000,
    )
    package_version = f"v{work.version:03d}"
    manifest = _release_manifest(
        work,
        package_version=package_version,
        video_name=video_name,
        subtitle_name=subtitle_name,
        cover_name=cover_name,
        video_sha256=video_sha256,
        media_validation=media_validation,
        actual_preflight=actual_preflight,
        hashes=hashes,
    )
    manifest_payload = _json_payload(manifest)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    _write_member(
        temporary,
        "manifest.json",
        manifest_payload,
        maximum_bytes=4_000_000,
    )
    checksum_members = {**hashes, "manifest.json": manifest_sha256}
    checksums_payload = _checksums_payload(checksum_members)
    checksums_sha256 = hashlib.sha256(checksums_payload).hexdigest()
    _write_member(
        temporary,
        "checksums.sha256",
        checksums_payload,
        maximum_bytes=2_000_000,
    )
    member_hashes = {
        **hashes,
        "manifest.json": manifest_sha256,
        "checksums.sha256": checksums_sha256,
    }
    zip_path = None
    zip_sha256 = None
    if work.include_zip:
        archive_name = release_archive_name(work)
        zip_path = temporary / archive_name
        try:
            zip_sha256 = create_verified_zip(
                root=temporary,
                output_path=zip_path,
                members=tuple(PurePosixPath(name) for name in validate_zip_members(member_hashes)),
                manifest=manifest,
                expected_sha256=member_hashes,
            )
        except DeliveryError as exc:
            raise ReleasePackageError("release package ZIP validation failed") from exc
        member_hashes[archive_name] = zip_sha256
    return ReleasePackageResult(
        release_package_id=work.release_package_id,
        package_version=package_version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=(destination / zip_path.name) if zip_path is not None else None,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_hashes,
    )


def _release_copy_json(work: ReleasePackageWork) -> dict[str, object]:
    return {
        "title": work.title,
        "title_variants": list(work.title_variants),
        "description": work.description,
        "hashtags": list(work.hashtags),
        "cta": work.cta,
        "high_impact_sentence": work.high_impact_sentence,
        "risk_flags": list(work.risk_flags),
    }


def _release_preflight_payload(
    work: ReleasePackageWork,
    media_validation: dict[str, object],
    actual_preflight: ReleasePreflight,
) -> dict[str, object]:
    return {
        "source_preflight": work.preflight.model_dump(mode="json"),
        "package_media_validation": media_validation,
        "package_preflight": actual_preflight.model_dump(mode="json"),
        "actual_bytes_validated": True,
    }


def _release_manifest(
    work: ReleasePackageWork,
    *,
    package_version: str,
    video_name: str,
    subtitle_name: str | None,
    cover_name: str,
    video_sha256: str,
    media_validation: dict[str, object],
    actual_preflight: ReleasePreflight,
    hashes: dict[str, str],
) -> dict[str, object]:
    return {
        "schema_version": "liveclip.release-package.v1",
        "release_package_id": work.release_package_id,
        "release_item_id": work.release_item_id,
        "package_version": package_version,
        "project_id": work.project_id,
        "project_name": work.project_name,
        "requested_by": work.requested_by_username,
        "created_at": work.created_at.astimezone(UTC).isoformat(),
        "source_filename": source_basename(work.source_filename),
        "source_fingerprint": work.source_fingerprint,
        "generation": work.generation,
        "project_revision_epoch": work.revision_epoch,
        "snapshot_fingerprint": work.snapshot_fingerprint,
        "platform": work.preset.platform.value,
        "preset_id": work.preset.preset_id,
        "account_label": work.account_label,
        "caption_mode": work.caption_mode.value,
        "planned_publish_at": (
            work.planned_publish_at.astimezone(UTC).isoformat()
            if work.planned_publish_at is not None
            else None
        ),
        "clip_id": work.clip_id,
        "edit_plan_revision": work.edit_plan_revision,
        "source_start_ms": work.source_start_ms,
        "source_end_ms": work.source_end_ms,
        "duration_ms": work.source_end_ms - work.source_start_ms,
        "score": work.score,
        "title": work.title,
        "high_impact_sentence": work.high_impact_sentence,
        "description": work.description,
        "hashtags": list(work.hashtags),
        "cta": work.cta,
        "risk_flags": list(work.risk_flags),
        "video_filename": video_name,
        "subtitle_filename": subtitle_name,
        "cover_filename": cover_name,
        "video_sha256": video_sha256,
        "media_validation": media_validation,
        "package_preflight": actual_preflight.model_dump(mode="json"),
        "safe_zone": work.preset.safe_zone.model_dump(mode="json"),
        "members": dict(sorted(hashes.items())),
    }


def _expected_release_content_hashes(
    work: ReleasePackageWork,
    *,
    video_name: str,
    subtitle_name: str | None,
    cover_name: str,
    cover_sha256: str | None,
    media_validation: dict[str, object],
    actual_preflight: ReleasePreflight,
) -> dict[str, str]:
    if cover_sha256 is None or re.fullmatch(r"[a-f0-9]{64}", cover_sha256) is None:
        raise ReleasePackageError("existing release package cover evidence is missing")
    values: dict[str, bytes] = {
        "metadata/release-copy.txt": _release_copy(work).encode("utf-8"),
        "metadata/release-copy.json": _json_payload(_release_copy_json(work)),
        "metadata/checklist.json": _json_payload(work.checklist.model_dump(mode="json")),
        "metadata/preflight.json": _json_payload(
            _release_preflight_payload(work, media_validation, actual_preflight)
        ),
        "README-发布说明.txt": _guide_text(
            work,
            subtitle_name=subtitle_name,
        ).encode("utf-8"),
    }
    if subtitle_name is not None:
        try:
            subtitle = normalize_srt(captions_to_srt(work.captions))
        except DeliveryError as exc:
            raise ReleasePackageError("release subtitle is invalid") from exc
        values[subtitle_name] = subtitle.encode("utf-8")
    return {
        video_name: work.source_video_sha256,
        cover_name: cover_sha256,
        **{name: hashlib.sha256(payload).hexdigest() for name, payload in values.items()},
    }


def _validate_recovered_cover(
    destination: Path,
    *,
    video_path: Path,
    cover_name: str,
    timestamp_ms: int,
    cancel_requested: Callable[[], bool] | None,
) -> None:
    actual = _member_evidence(destination, cover_name)
    try:
        actual_payload = actual.pinned.read_bytes(max_bytes=30_000_000)
    finally:
        actual.pinned.close()
    validation_dir = destination.parent / (
        f".{destination.name}-cover-validation-{uuid.uuid4().hex}"
    )
    try:
        validation_identity = create_directory_exclusive_no_follow(validation_dir)
    except SecureFileError as exc:
        raise ReleasePackageError("release cover validation directory is unsafe") from exc
    expected_path = validation_dir / "expected-cover.png"
    try:
        _extract_cover(
            video_path,
            expected_path,
            timestamp_ms=timestamp_ms,
            cancel_requested=cancel_requested,
        )
        expected = capture_pinned_file_evidence(expected_path)
        try:
            expected_payload = expected.pinned.read_bytes(max_bytes=30_000_000)
        finally:
            expected.pinned.close()
        try:
            with Image.open(BytesIO(actual_payload)) as actual_image:
                actual_pixels = actual_image.convert("RGB")
            with Image.open(BytesIO(expected_payload)) as expected_image:
                expected_pixels = expected_image.convert("RGB")
            if (
                actual_pixels.size != expected_pixels.size
                or actual_pixels.tobytes() != expected_pixels.tobytes()
            ):
                raise ReleasePackageError(
                    "existing release package cover differs from the selected frame"
                )
        except (OSError, ValueError) as exc:
            raise ReleasePackageError("existing release package cover is invalid") from exc
    finally:
        try:
            remove_tree_no_follow(
                validation_dir,
                required_ancestor=destination.parent,
                expected_identity=validation_identity,
            )
        except SecureFileError as exc:
            raise ReleasePackageError(
                "release cover validation directory could not be removed safely"
            ) from exc


def _extract_cover(
    video_path: Path,
    output_path: Path,
    *,
    timestamp_ms: int,
    cancel_requested: Callable[[], bool] | None,
) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise ReleasePackageError("ffmpeg is not available for cover extraction")
    temporary = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.png")
    argv = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        ms_to_ffmpeg(timestamp_ms),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(temporary),
    ]
    try:
        result = run_cancellable_process(
            argv,
            timeout_seconds=60,
            cancel_requested=cancel_requested,
        )
    except ProcessCancelled as exc:
        temporary.unlink(missing_ok=True)
        raise InterruptedError("release cover extraction was cancelled") from exc
    except subprocess.TimeoutExpired as exc:
        temporary.unlink(missing_ok=True)
        raise ReleasePackageTransientError("release cover extraction timed out") from exc
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ReleasePackageTransientError(
            "release cover extraction could not start temporarily"
        ) from exc
    if result.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        raise ReleasePackageError("release cover extraction failed")
    try:
        publish_regular_file_immutable_no_follow(temporary, output_path)
        evidence = capture_pinned_file_evidence(output_path)
        try:
            payload = evidence.pinned.read_bytes(max_bytes=30_000_000)
        finally:
            evidence.pinned.close()
        with Image.open(BytesIO(payload)) as image:
            image.verify()
            if image.width <= 0 or image.height <= image.width:
                raise ReleasePackageError("release cover is not a valid portrait image")
    except SecureFileError as exc:
        temporary.unlink(missing_ok=True)
        raise ReleasePackageError("release cover could not be published safely") from exc


def _validate_work(work: ReleasePackageWork) -> None:
    for identifier in (
        work.release_package_id,
        work.release_item_id,
        work.project_id,
        work.clip_id,
    ):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) is None:
            raise ReleasePackageError("release package identifier is invalid")
    for digest in (
        work.source_fingerprint,
        work.source_video_sha256,
        work.snapshot_fingerprint,
        work.package_fingerprint,
    ):
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ReleasePackageError("release package fingerprint is invalid")
    if not 1 <= work.version <= 999 or work.generation < 1 or work.revision_epoch < 0:
        raise ReleasePackageError("release package version fence is invalid")
    duration_ms = work.source_end_ms - work.source_start_ms
    if duration_ms <= 0 or work.cover_time_ms >= duration_ms:
        raise ReleasePackageError("release cover time is outside the clip")
    if not work.preflight.passed or not work.checklist.complete:
        raise ReleasePackageError("release package preflight is incomplete")
    if not work.captions:
        raise ReleasePackageError("release package requires current captions")


def _validate_release_video(
    work: ReleasePackageWork,
    video_path: Path,
    *,
    cancel_requested: Callable[[], bool] | None,
) -> tuple[dict[str, object], ReleasePreflight]:
    try:
        media_validation = validate_editor_video(
            video_path,
            cancel_requested=cancel_requested,
        )
    except EditPackageTransientError as exc:
        raise ReleasePackageTransientError(
            "release source media validation temporarily failed"
        ) from exc
    except EditPackageError as exc:
        raise ReleasePackageError("release source media validation failed") from exc
    return media_validation, _validate_actual_platform_media(
        work,
        media_validation,
        size_bytes=_required_validation_integer(media_validation, "size_bytes"),
    )


def _validate_actual_platform_media(
    work: ReleasePackageWork,
    media_validation: dict[str, object],
    *,
    size_bytes: int,
) -> ReleasePreflight:
    actual_duration_ms = _required_validation_integer(media_validation, "duration_ms")
    width = _required_validation_integer(media_validation, "width")
    height = _required_validation_integer(media_validation, "height")
    expected_duration_ms = work.source_end_ms - work.source_start_ms
    if abs(actual_duration_ms - expected_duration_ms) > 600:
        raise ReleasePackageError("release media duration differs from the selected clip")
    actual_preflight = evaluate_release_preflight(
        preset=work.preset,
        media=ReleaseMediaFacts(
            available=True,
            trusted_render_contract=True,
            container=str(media_validation.get("container", "")),
            video_codec=str(media_validation.get("video_codec", "")),
            audio_codec=str(media_validation.get("audio_codec", "")),
            pixel_format=str(media_validation.get("pixel_format", "")),
            progressive=media_validation.get("scan") == "progressive",
            fast_start=media_validation.get("fast_start") is True,
            full_decode=media_validation.get("full_decode") == "passed",
            width=width,
            height=height,
            duration_ms=actual_duration_ms,
            size_bytes=size_bytes,
            separate_subtitle_available=(
                work.caption_mode.value == "clean_separate" and bool(work.captions)
            ),
            format_evidence="actual_bytes",
        ),
        editorial=ReleaseEditorialFacts(
            selected_revision=work.edit_plan_revision,
            current_revision=work.edit_plan_revision,
            clip_review_approved=True,
            release_approval=ReleaseApprovalStatus.APPROVED,
            title=work.title,
            description=work.description,
            hashtags=work.hashtags,
            cover_time_ms=work.cover_time_ms,
            caption_mode=work.caption_mode,
            captions=work.captions,
            risk_flags=work.risk_flags,
            checklist=work.checklist,
            current_project_run=True,
        ),
    )
    source_duplicate = next(
        (check for check in work.preflight.checks if check.code == "duplicate_content"),
        None,
    )
    if source_duplicate is not None:
        checks = tuple(
            source_duplicate if check.code == "duplicate_content" else check
            for check in actual_preflight.checks
        )
        blockers = sum(check.outcome == "blocked" for check in checks)
        warnings = sum(check.outcome == "warning" for check in checks)
        actual_preflight = actual_preflight.model_copy(
            update={
                "checks": checks,
                "passed": blockers == 0,
                "blocker_count": blockers,
                "warning_count": warnings,
            }
        )
    if not actual_preflight.passed:
        raise ReleasePackageError("release media does not satisfy the selected platform preset")
    return actual_preflight


def _required_validation_integer(
    media_validation: dict[str, object],
    key: str,
) -> int:
    value = media_validation.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ReleasePackageError("release media validation evidence is incomplete")
    try:
        return int(value)
    except ValueError as exc:
        raise ReleasePackageError("release media validation evidence is incomplete") from exc


def _release_copy(work: ReleasePackageWork) -> str:
    variants = "\n".join(f"- {value}" for value in work.title_variants) or "- 无"
    hashtags = " ".join(f"#{value}" for value in work.hashtags) or "无"
    return (
        f"发布标题\n{work.title}\n\n"
        f"备选标题\n{variants}\n\n"
        f"正文\n{work.description or '无'}\n\n"
        f"话题\n{hashtags}\n\n"
        f"行动提示\n{work.cta or '无'}\n\n"
        f"高光语句\n{work.high_impact_sentence}\n"
    )


def _guide_text(work: ReleasePackageWork, *, subtitle_name: str | None) -> str:
    subtitle_step = (
        f"3. 将 {subtitle_name} 作为 UTF-8 无 BOM 的 SRT 导入并保持可编辑。\n"
        if subtitle_name is not None
        else "3. 当前视频使用已烧录字幕模式，不另附 SRT。\n"
    )
    return (
        f"LiveClip 平台发布包 v{work.version:03d}\n\n"
        f"目标平台：{work.preset.label}\n"
        f"账号：{work.account_label}\n\n"
        "1. 导入 media/ 中的 MP4；该文件已通过 MP4/H.264/AAC、竖屏、"
        "逐行、yuv420p、Fast Start 和完整解码检查。\n"
        "2. cover/ 中的 PNG 是人工选择时间点生成的封面候选。\n"
        + subtitle_step
        + "4. metadata/release-copy.txt 可直接复制标题、正文、话题和 CTA；发布前仍需人工确认。\n"
        "5. metadata/checklist.json 和 preflight.json 保存权利、隐私和平台检查证据。\n"
        "6. checksums.sha256 用于传输后校验；LiveClip 未自动上传或排期到外部平台。\n"
    )


def release_archive_name(work: ReleasePackageWork) -> str:
    title = safe_filename_component(work.title, maximum_utf8_bytes=48)
    return (
        f"liveclip-release-{work.preset.platform.value}-{title}-"
        f"{work.release_item_id[:8]}-v{work.version:03d}.zip"
    )


def _json_payload(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json_member(
    root: Path,
    name: str,
    value: object,
    hashes: dict[str, str],
) -> None:
    _write_hashed_member(
        root,
        name,
        _json_payload(value),
        hashes,
        maximum_bytes=4_000_000,
    )


def _write_hashed_member(
    root: Path,
    name: str,
    payload: bytes,
    hashes: dict[str, str],
    *,
    maximum_bytes: int,
) -> None:
    _write_member(root, name, payload, maximum_bytes=maximum_bytes)
    hashes[name] = hashlib.sha256(payload).hexdigest()


def _write_member(root: Path, name: str, payload: bytes, *, maximum_bytes: int) -> None:
    validate_zip_members((name,))
    path = root / Path(*PurePosixPath(name).parts)
    try:
        write_bytes_immutable_no_follow(path, payload, max_bytes=maximum_bytes)
    except SecureFileError as exc:
        raise ReleasePackageError("release package metadata could not be written safely") from exc


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
        raise ReleasePackageError("release package member is missing or unsafe") from exc


def _assert_member_hash(root: Path, name: str, expected_sha256: str) -> None:
    evidence = _member_evidence(root, name, expected_sha256=expected_sha256)
    evidence.pinned.close()


def _hash_member(path: Path) -> str:
    try:
        evidence = capture_pinned_file_evidence(path)
        try:
            return evidence.sha256
        finally:
            evidence.pinned.close()
    except SecureFileError as exc:
        raise ReleasePackageError("release package member is unsafe") from exc


def _validated_hash_map(value: dict[object, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, digest in value.items():
        name = str(key)
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ReleasePackageError("release package member hash is invalid")
        result[name] = digest
    validate_zip_members(result)
    return result


def _actual_member_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ReleasePackageError("release package contains a symbolic link")
        if path.is_file():
            names.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ReleasePackageError("release package contains a non-regular entry")
    validate_zip_members(names)
    return names


def _check_cancel(callback: Callable[[], bool] | None) -> None:
    if callback is not None and callback():
        raise InterruptedError("release package creation was cancelled")


__all__ = [
    "ReleasePackageError",
    "ReleasePackageResult",
    "ReleasePackageTransientError",
    "create_release_package",
    "release_archive_name",
    "validate_existing_release_package",
]
