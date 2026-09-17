from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.deliveries import (
    DeliveryManifestClip,
    DeliveryPersistence,
    DeliveryWork,
)
from liveclip.application.delivery_progress import DeliveryProgressPhase, DeliveryProgressSink
from liveclip.application.pipeline import LeaseIdentity
from liveclip.delivery.package import (
    DeliveryClipInput,
    DeliveryError,
    create_delivery,
    delivery_checksums_text,
    delivery_index_html,
    normalize_srt,
    report_delivery_progress,
    safe_filename_component,
    verify_pinned_zip_members,
)
from liveclip.media.artifacts import project_directory
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    SecureFileMissing,
    capture_pinned_file_evidence,
    require_directory_no_follow,
    validate_pinned_directory_files_no_follow,
)


class DeliveryTaskCancelled(RuntimeError):
    """The durable delivery task was cancelled before package publication."""


@dataclass(frozen=True, slots=True)
class _ValidatedDelivery:
    manifest: dict[str, object]
    manifest_sha256: str
    zip_sha256: str | None


class DeliveryTaskHandler:
    def __init__(self, *, data_dir: Path, assets: AssetStore) -> None:
        self._data_dir = data_dir
        self._assets = assets

    def execute(
        self,
        work: DeliveryWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
        progress: DeliveryProgressSink | None = None,
    ) -> DeliveryPersistence:
        _check_cancel(cancel_requested)
        project_dir = project_directory(self._data_dir, work.project_id)
        version = f"v{work.version:03d}"
        manifest_relative = f"deliveries/{version}/manifest.json"
        zip_relative = f"deliveries/{version}/delivery.zip"
        manifest_reservation = self._reserve(
            work,
            lease,
            kind="delivery_manifest",
            relative_path=manifest_relative,
            mime_type="application/json",
        )
        zip_reservation = (
            self._reserve(
                work,
                lease,
                kind="delivery_zip",
                relative_path=zip_relative,
                mime_type="application/zip",
            )
            if work.include_zip
            else None
        )
        clip_inputs: list[DeliveryClipInput] = []
        for clip in work.clips:
            video_path = _resolve_owned_asset_path(project_dir, clip.video_relative_path)
            subtitle_srt = _read_verified_text_asset(
                project_dir,
                clip.subtitle_relative_path,
                clip.subtitle_sha256,
            )
            clip_inputs.append(
                DeliveryClipInput(
                    clip_id=clip.clip_id,
                    edit_plan_revision=clip.edit_plan_revision,
                    render_revision=clip.edit_plan_revision,
                    title=clip.title,
                    hook=clip.hook,
                    reason=clip.reason,
                    risk_flags=clip.risk_flags,
                    keywords=clip.keywords,
                    source_start_ms=clip.source_start_ms,
                    source_end_ms=clip.source_end_ms,
                    score=clip.score,
                    review_status="approved",
                    render_status="succeeded",
                    final_video_path=video_path,
                    final_video_sha256=clip.video_sha256,
                    subtitle_srt=subtitle_srt,
                )
            )
        clips = tuple(clip_inputs)
        _check_cancel(cancel_requested)
        destination = project_dir / "deliveries" / version
        expected_manifest_sha256: str | None
        expected_zip_sha256: str | None
        try:
            require_directory_no_follow(destination)
        except SecureFileMissing:
            result = create_delivery(
                project_dir=project_dir,
                project_id=work.project_id,
                source_filename=work.source_filename,
                source_fingerprint=work.source_fingerprint,
                clips=clips,
                include_zip=work.include_zip,
                expected_version=work.version,
                delivery_id=work.delivery_id,
                snapshot_fingerprint=work.snapshot_fingerprint,
                created_at=work.created_at,
                progress=progress,
                check_cancel=lambda: _check_cancel(cancel_requested),
            )
            expected_manifest_sha256 = result.manifest_sha256
            expected_zip_sha256 = result.zip_sha256
        except SecureFileError as exc:
            raise DeliveryError("existing delivery directory is unsafe") from exc
        else:
            expected_manifest_sha256 = manifest_reservation.sha256
            expected_zip_sha256 = zip_reservation.sha256 if zip_reservation is not None else None
        validated = _validate_existing_delivery(
            destination,
            work,
            inputs=clips,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_zip_sha256=expected_zip_sha256,
            progress=progress,
            check_cancel=lambda: _check_cancel(cancel_requested),
        )
        _check_cancel(cancel_requested)
        manifest_clips = _manifest_clips(validated.manifest)
        asset_total = 2 if work.include_zip else 1
        report_delivery_progress(progress, DeliveryProgressPhase.COMMITTING_ASSETS, 0, asset_total)
        committed_manifest = self._assets.commit(
            lease,
            manifest_reservation,
            project_dir=project_dir,
            validation={
                "schema_version": "1",
                "delivery_id": work.delivery_id,
                "delivery_version": version,
                "snapshot_fingerprint": work.snapshot_fingerprint,
                "clip_count": len(work.clips),
            },
            expected_sha256=validated.manifest_sha256,
        )
        committed_zip = None
        report_delivery_progress(progress, DeliveryProgressPhase.COMMITTING_ASSETS, 1, asset_total)
        if zip_reservation is not None:
            committed_zip = self._assets.commit(
                lease,
                zip_reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "delivery_id": work.delivery_id,
                    "delivery_version": version,
                    "snapshot_fingerprint": work.snapshot_fingerprint,
                    "members": len(work.clips) * 2 + 3,
                },
                expected_sha256=validated.zip_sha256,
            )
            report_delivery_progress(
                progress, DeliveryProgressPhase.COMMITTING_ASSETS, 2, asset_total
            )
        return DeliveryPersistence(
            manifest_asset_id=committed_manifest.asset_id,
            zip_asset_id=committed_zip.asset_id if committed_zip else None,
            manifest_clips=manifest_clips,
        )

    def _reserve(
        self,
        work: DeliveryWork,
        lease: LeaseIdentity,
        *,
        kind: str,
        relative_path: str,
        mime_type: str,
    ) -> AssetReservation:
        return self._assets.reserve(
            lease,
            project_id=work.project_id,
            kind=kind,
            relative_path=relative_path,
            mime_type=mime_type,
            input_fingerprint=work.package_fingerprint,
            generation=work.generation,
            revision_epoch=work.revision_epoch,
        )


def _resolve_owned_asset_path(project_dir: Path, relative_path: str) -> Path:
    if "\\" in relative_path:
        raise DeliveryError("delivery input asset path is invalid")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise DeliveryError("delivery input asset path is invalid")
    candidate = project_dir / Path(*relative.parts)
    if project_dir not in candidate.parents:
        raise DeliveryError("delivery input asset escaped its project")
    return candidate


def _read_verified_text_asset(
    project_dir: Path,
    relative_path: str,
    sha256: str,
) -> str:
    candidate = _resolve_owned_asset_path(project_dir, relative_path)
    try:
        evidence = capture_pinned_file_evidence(candidate, expected_sha256=sha256)
        try:
            payload = evidence.pinned.read_bytes(max_bytes=1_000_000)
        finally:
            evidence.pinned.close()
    except (SecureFileError, ValueError) as exc:
        raise DeliveryError("delivery subtitle asset is missing or unsafe") from exc
    try:
        return payload.decode("utf-8")
    except UnicodeError as exc:
        raise DeliveryError("delivery subtitle asset is not valid UTF-8") from exc


def _validate_existing_delivery(
    destination: Path,
    work: DeliveryWork,
    *,
    inputs: tuple[DeliveryClipInput, ...],
    expected_manifest_sha256: str | None,
    expected_zip_sha256: str | None,
    progress: DeliveryProgressSink | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> _ValidatedDelivery:
    # Count the handler's exact final directory reread, plus its ZIP-member reread.
    # Builder validation and earlier metadata parsing are intentionally uncounted.
    member_count = len(work.clips) * 2 + 3
    total = member_count * 2 + 1 if work.include_zip else member_count
    verified = 0

    def verified_members(count: int) -> None:
        nonlocal verified
        verified += count
        if check_cancel is not None:
            check_cancel()
        report_delivery_progress(progress, DeliveryProgressPhase.VERIFYING_PACKAGE, verified, total)

    verified_members(0)
    try:
        require_directory_no_follow(destination)
    except SecureFileError as exc:
        raise DeliveryError("existing delivery directory is unsafe") from exc
    with ExitStack() as stack:
        manifest_evidence = _capture_delivery_member(
            destination,
            "manifest.json",
            expected_sha256=expected_manifest_sha256,
            stack=stack,
        )
        try:
            manifest_bytes = manifest_evidence.pinned.read_bytes(max_bytes=2_000_000)
            raw_manifest = json.loads(manifest_bytes)
        except (SecureFileError, UnicodeError, json.JSONDecodeError) as exc:
            raise DeliveryError("delivery manifest is missing or invalid") from exc
        if not isinstance(raw_manifest, dict) or raw_manifest.get("schema_version") != "1":
            raise DeliveryError("delivery manifest schema is invalid")
        manifest = {str(key): value for key, value in raw_manifest.items()}
        if (
            manifest.get("project_id") != work.project_id
            or manifest.get("delivery_id") != work.delivery_id
            or manifest.get("delivery_version") != f"v{work.version:03d}"
            or manifest.get("source_filename") != _source_basename(work.source_filename)
            or manifest.get("source_fingerprint") != work.source_fingerprint
            or manifest.get("snapshot_fingerprint") != work.snapshot_fingerprint
        ):
            raise DeliveryError("existing delivery does not match its database reservation")
        entries = _manifest_clips(manifest)
        if tuple(entry.clip_id for entry in entries) != tuple(clip.clip_id for clip in work.clips):
            raise DeliveryError("existing delivery clip set differs from its reservation")

        disk_evidence: dict[str, PinnedFileEvidence] = {}
        archive_hashes: dict[str, str] = {}
        input_by_id = {value.clip_id: value for value in inputs}
        for ordinal, (entry, clip) in enumerate(
            zip(entries, work.clips, strict=True),
            start=1,
        ):
            expected_stem = f"{ordinal:02d}-{safe_filename_component(clip.title)}"
            if (
                entry.edit_plan_revision != clip.edit_plan_revision
                or entry.title != clip.title
                or entry.video_filename != f"clips/{expected_stem}.mp4"
                or entry.subtitle_filename != f"subtitles/{expected_stem}.srt"
                or entry.source_start_ms != clip.source_start_ms
                or entry.source_end_ms != clip.source_end_ms
                or entry.duration_ms != clip.source_end_ms - clip.source_start_ms
                or entry.score != clip.score
                or entry.review_status != "approved"
                or entry.sha256 != clip.video_sha256
            ):
                raise DeliveryError("existing delivery clip metadata differs from its reservation")
            expected_input = input_by_id[entry.clip_id]
            subtitle_hash = hashlib.sha256(
                normalize_srt(expected_input.subtitle_srt).encode("utf-8")
            ).hexdigest()
            video_evidence = _capture_delivery_member(
                destination,
                entry.video_filename,
                expected_sha256=entry.sha256,
                stack=stack,
            )
            subtitle_evidence = _capture_delivery_member(
                destination,
                entry.subtitle_filename,
                expected_sha256=subtitle_hash,
                stack=stack,
            )
            disk_evidence[entry.video_filename] = video_evidence
            disk_evidence[entry.subtitle_filename] = subtitle_evidence
            archive_hashes[entry.video_filename] = entry.sha256
            archive_hashes[entry.subtitle_filename] = subtitle_hash

        disk_evidence["manifest.json"] = manifest_evidence
        archive_hashes["manifest.json"] = manifest_evidence.sha256
        index_sha256 = hashlib.sha256(delivery_index_html(manifest).encode("utf-8")).hexdigest()
        index_evidence = _capture_delivery_member(
            destination,
            "index.html",
            expected_sha256=index_sha256,
            stack=stack,
        )
        disk_evidence["index.html"] = index_evidence
        archive_hashes["index.html"] = index_sha256
        checksums_sha256 = hashlib.sha256(
            delivery_checksums_text(archive_hashes).encode("utf-8")
        ).hexdigest()
        checksums_evidence = _capture_delivery_member(
            destination,
            "checksums.sha256",
            expected_sha256=checksums_sha256,
            stack=stack,
        )
        disk_evidence["checksums.sha256"] = checksums_evidence
        archive_hashes["checksums.sha256"] = checksums_sha256
        zip_sha256: str | None = None
        if work.include_zip:
            zip_evidence = _capture_delivery_member(
                destination,
                "delivery.zip",
                expected_sha256=expected_zip_sha256,
                stack=stack,
            )
            disk_evidence["delivery.zip"] = zip_evidence
            zip_sha256 = zip_evidence.sha256
            verify_pinned_zip_members(
                zip_evidence,
                expected_sha256=archive_hashes,
                expected_manifest=manifest,
                expected_sizes={
                    name: evidence.size_bytes
                    for name, evidence in disk_evidence.items()
                    if name != "delivery.zip"
                },
                progress=verified_members,
            )
        elif expected_zip_sha256 is not None:
            raise DeliveryError("non-ZIP delivery has an unexpected committed ZIP hash")
        try:
            validate_pinned_directory_files_no_follow(
                destination,
                disk_evidence,
                rehash=True,
            )
            verified_members(len(disk_evidence))
        except SecureFileError as exc:
            raise DeliveryError("existing delivery members are not stable and exact") from exc
        return _ValidatedDelivery(
            manifest=manifest,
            manifest_sha256=manifest_evidence.sha256,
            zip_sha256=zip_sha256,
        )


def _manifest_clips(manifest: dict[str, object]) -> tuple[DeliveryManifestClip, ...]:
    raw = manifest.get("clips")
    if not isinstance(raw, list) or not raw:
        raise DeliveryError("delivery manifest has no clips")
    values: list[DeliveryManifestClip] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DeliveryError("delivery manifest clip is invalid")
        try:
            value = DeliveryManifestClip(
                clip_id=str(item["clip_id"]),
                edit_plan_revision=_positive_int(item, "edit_plan_revision"),
                title=_required_text(item, "title"),
                video_filename=str(item["video_filename"]),
                subtitle_filename=str(item["subtitle_filename"]),
                source_start_ms=_seconds_to_exact_ms(item, "source_start"),
                source_end_ms=_seconds_to_exact_ms(item, "source_end"),
                duration_ms=_seconds_to_exact_ms(item, "duration"),
                score=_score(item),
                review_status=_required_text(item, "review_status"),
                sha256=str(item["sha256"]),
            )
        except KeyError as exc:
            raise DeliveryError("delivery manifest clip fields are missing") from exc
        _safe_member_name(value.video_filename)
        _safe_member_name(value.subtitle_filename)
        if (
            len(value.sha256) != 64
            or any(character not in "0123456789abcdef" for character in value.sha256)
            or value.source_end_ms <= value.source_start_ms
        ):
            raise DeliveryError("delivery manifest clip hash is invalid")
        values.append(value)
    if len({value.clip_id for value in values}) != len(values):
        raise DeliveryError("delivery manifest clip IDs are duplicated")
    return tuple(values)


def _capture_delivery_member(
    root: Path,
    name: str,
    *,
    expected_sha256: str | None,
    stack: ExitStack,
) -> PinnedFileEvidence:
    relative = _safe_member_name(name)
    try:
        evidence = capture_pinned_file_evidence(
            root / Path(*relative.parts),
            expected_sha256=expected_sha256,
        )
    except (SecureFileError, ValueError) as exc:
        raise DeliveryError("delivery member is missing, symbolic, or changed") from exc
    stack.callback(evidence.pinned.close)
    return evidence


def _safe_member_name(name: str) -> PurePosixPath:
    if "\\" in name:
        raise DeliveryError("delivery member path is invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DeliveryError("delivery member path is invalid")
    if path.as_posix() != name:
        raise DeliveryError("delivery member path is not canonical")
    return path


def _required_text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise DeliveryError("delivery manifest clip text field is invalid")
    return item


def _positive_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise DeliveryError("delivery manifest clip integer field is invalid")
    return item


def _seconds_to_exact_ms(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise DeliveryError("delivery manifest clip time field is invalid")
    try:
        milliseconds = Decimal(str(item)) * 1_000
    except (InvalidOperation, ValueError) as exc:
        raise DeliveryError("delivery manifest clip time field is invalid") from exc
    if not milliseconds.is_finite() or milliseconds != milliseconds.to_integral_value():
        raise DeliveryError("delivery manifest clip time field is not exact milliseconds")
    return int(milliseconds)


def _score(value: dict[str, object]) -> float:
    item = value.get("score")
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise DeliveryError("delivery manifest clip score is invalid")
    score = float(item)
    if not 0 <= score <= 100:
        raise DeliveryError("delivery manifest clip score is invalid")
    return score


def _source_basename(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).name or "source-media"


def _check_cancel(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise DeliveryTaskCancelled("delivery task cancellation was requested")
