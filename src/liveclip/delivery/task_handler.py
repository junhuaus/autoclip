from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.deliveries import (
    DeliveryManifestClip,
    DeliveryPersistence,
    DeliveryWork,
)
from liveclip.application.pipeline import LeaseIdentity
from liveclip.delivery.package import (
    DeliveryClipInput,
    DeliveryError,
    create_delivery,
    normalize_srt,
    safe_filename_component,
    validate_zip_members,
)
from liveclip.media.artifacts import project_directory
from liveclip.media.fingerprint import stream_sha256


class DeliveryTaskCancelled(RuntimeError):
    """The durable delivery task was cancelled before package publication."""


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
        clips = tuple(
            DeliveryClipInput(
                clip_id=clip.clip_id,
                edit_plan_revision=clip.edit_plan_revision,
                render_revision=clip.edit_plan_revision,
                title=clip.title,
                source_start_ms=clip.source_start_ms,
                source_end_ms=clip.source_end_ms,
                score=clip.score,
                review_status="approved",
                render_status="succeeded",
                final_video_path=_resolve_verified_asset(
                    project_dir,
                    clip.video_relative_path,
                    clip.video_sha256,
                ),
                subtitle_srt=_resolve_verified_asset(
                    project_dir,
                    clip.subtitle_relative_path,
                    clip.subtitle_sha256,
                ).read_text(encoding="utf-8"),
            )
            for clip in work.clips
        )
        _check_cancel(cancel_requested)
        destination = project_dir / "deliveries" / version
        if destination.is_dir():
            manifest = _validate_existing_delivery(destination, work, inputs=clips)
        else:
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
            )
            manifest = _read_manifest(result.manifest_path)
        _check_cancel(cancel_requested)
        manifest_clips = _manifest_clips(manifest)
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
        )
        committed_zip = None
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
                    "members": len(work.clips) * 2 + 1,
                },
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


def _resolve_verified_asset(project_dir: Path, relative_path: str, sha256: str) -> Path:
    if "\\" in relative_path:
        raise DeliveryError("delivery input asset path is invalid")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise DeliveryError("delivery input asset path is invalid")
    candidate = project_dir / Path(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise DeliveryError("delivery input asset is missing or symbolic")
    resolved = candidate.resolve(strict=True)
    if project_dir not in resolved.parents or stream_sha256(resolved) != sha256:
        raise DeliveryError("delivery input asset failed its ownership or hash check")
    return resolved


def _validate_existing_delivery(
    destination: Path,
    work: DeliveryWork,
    *,
    inputs: tuple[DeliveryClipInput, ...],
) -> dict[str, object]:
    if destination.is_symlink():
        raise DeliveryError("existing delivery directory is symbolic")
    manifest_path = destination / "manifest.json"
    manifest = _read_manifest(manifest_path)
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
    input_by_id = {value.clip_id: value for value in inputs}
    for ordinal, (entry, clip) in enumerate(zip(entries, work.clips, strict=True), start=1):
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
        video = _resolve_member(destination, entry.video_filename)
        subtitle = _resolve_member(destination, entry.subtitle_filename)
        expected_input = input_by_id[entry.clip_id]
        if stream_sha256(video) != entry.sha256 or subtitle.read_bytes() != normalize_srt(
            expected_input.subtitle_srt
        ).encode("utf-8"):
            raise DeliveryError("existing delivery video hash differs from its manifest")
    zip_path = destination / "delivery.zip"
    if work.include_zip:
        if zip_path.is_symlink() or not zip_path.is_file():
            raise DeliveryError("existing ZIP delivery is missing")
        with zipfile.ZipFile(zip_path, mode="r") as archive:
            names = validate_zip_members(info.filename for info in archive.infolist())
            expected_names = (
                *(
                    name
                    for entry in entries
                    for name in (entry.video_filename, entry.subtitle_filename)
                ),
                "manifest.json",
            )
            if names != expected_names:
                raise DeliveryError("existing ZIP member list differs from its manifest")
            if archive.testzip() is not None:
                raise DeliveryError("existing ZIP delivery is corrupt")
            if json.loads(archive.read("manifest.json")) != manifest:
                raise DeliveryError("existing ZIP manifest differs from disk manifest")
            for name in names:
                if name == "manifest.json":
                    continue
                member = _resolve_member(destination, name)
                if archive.read(name) != member.read_bytes():
                    raise DeliveryError("existing ZIP member differs from the delivery directory")
    elif zip_path.exists():
        raise DeliveryError("non-ZIP delivery contains an unexpected archive")
    return manifest


def _read_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise DeliveryError("delivery manifest is missing or invalid")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise DeliveryError("delivery manifest schema is invalid")
    return {str(key): value for key, value in payload.items()}


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
        if len(value.sha256) != 64 or value.source_end_ms <= value.source_start_ms:
            raise DeliveryError("delivery manifest clip hash is invalid")
        values.append(value)
    if len({value.clip_id for value in values}) != len(values):
        raise DeliveryError("delivery manifest clip IDs are duplicated")
    return tuple(values)


def _resolve_member(root: Path, name: str) -> Path:
    relative = _safe_member_name(name)
    candidate = root / Path(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise DeliveryError("delivery member is missing or symbolic")
    resolved = candidate.resolve(strict=True)
    if root.resolve(strict=True) not in resolved.parents:
        raise DeliveryError("delivery member escaped its version directory")
    return resolved


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
