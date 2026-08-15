from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.edit_packages import (
    EditPackageManifestClip,
    EditPackagePersistence,
    EditPackageWork,
)
from liveclip.application.pipeline import LeaseIdentity
from liveclip.delivery.edit_package import (
    EditPackageClipInput,
    EditPackageError,
    EditPackageTransientError,
    create_edit_package,
    validate_existing_edit_package,
)
from liveclip.delivery.package import DeliveryError
from liveclip.media.artifacts import project_directory
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    directory_identity_no_follow,
    require_directory_no_follow,
)


class EditPackageTaskCancelled(RuntimeError):
    """A durable edit-package task was cancelled before publication."""


class EditPackageTaskHandler:
    def __init__(
        self,
        *,
        data_dir: Path,
        assets: AssetStore,
        publication_fence: Callable[[LeaseIdentity, EditPackageWork], None],
    ) -> None:
        self._data_dir = data_dir
        self._assets = assets
        self._publication_fence = publication_fence

    def execute(
        self,
        work: EditPackageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> EditPackagePersistence:
        _check_cancel(cancel_requested)
        project_dir = project_directory(self._data_dir, work.project_id)
        package_version = f"v{work.version:03d}"
        package_root = f"edit-packages/{package_version}"
        manifest_reservation = self._reserve(
            work,
            lease,
            kind="edit_package_manifest",
            relative_path=f"{package_root}/manifest.json",
            mime_type="application/json",
        )
        zip_name = f"liveclip-edit-package-{package_version}.zip"
        zip_reservation = (
            self._reserve(
                work,
                lease,
                kind="edit_package_zip",
                relative_path=f"{package_root}/{zip_name}",
                mime_type="application/zip",
            )
            if work.include_zip
            else None
        )
        inputs = tuple(
            EditPackageClipInput(
                ordinal=clip.ordinal,
                metadata=clip.metadata,
                video_path=_resolve_owned_asset_path(
                    project_dir,
                    clip.video_relative_path,
                ),
                video_sha256=clip.video_sha256,
                video_size_bytes=clip.video_size_bytes,
                contact_sheet_path=_resolve_owned_asset_path(
                    project_dir,
                    clip.contact_sheet_relative_path,
                ),
                contact_sheet_sha256=clip.contact_sheet_sha256,
                contact_sheet_size_bytes=clip.contact_sheet_size_bytes,
            )
            for clip in work.clips
        )
        destination = project_dir / "edit-packages" / package_version
        try:
            require_directory_no_follow(destination)
        except SecureFileMissing:
            try:
                result = create_edit_package(
                    project_dir=project_dir,
                    edit_package_id=work.edit_package_id,
                    project_id=work.project_id,
                    project_name=work.project_name,
                    owner_username=work.owner_username,
                    requested_by_username=work.requested_by_username,
                    source_filename=work.source_filename,
                    source_fingerprint=work.source_fingerprint,
                    generation=work.generation,
                    project_revision_epoch=work.revision_epoch,
                    version=work.version,
                    preset=work.preset,
                    content=work.content,
                    snapshot_fingerprint=work.snapshot_fingerprint,
                    clips=inputs,
                    include_zip=work.include_zip,
                    created_at=work.created_at,
                    cancel_requested=cancel_requested,
                    publication_fence=lambda: self._publication_fence(lease, work),
                )
            except InterruptedError as exc:
                raise EditPackageTaskCancelled(
                    "edit package task cancellation was requested"
                ) from exc
        except SecureFileError as exc:
            raise EditPackageError("existing edit package directory is unsafe") from exc
        else:
            self._publication_fence(lease, work)
            try:
                existing_identity = directory_identity_no_follow(destination)
                result = validate_existing_edit_package(
                    destination,
                    edit_package_id=work.edit_package_id,
                    project_id=work.project_id,
                    package_version=package_version,
                    snapshot_fingerprint=work.snapshot_fingerprint,
                    include_zip=work.include_zip,
                )
            except EditPackageTransientError:
                # A bounded local outage does not prove the immutable bytes are
                # corrupt.  Keep them for the next exact retry.
                raise
            except InterruptedError as exc:
                self._withdraw_and_invalidate(
                    lease,
                    destination,
                    project_dir=project_dir,
                    expected_identity=existing_identity,
                    asset_ids=tuple(
                        reservation.asset_id
                        for reservation in (manifest_reservation, zip_reservation)
                        if reservation is not None
                    ),
                )
                raise EditPackageTaskCancelled(
                    "edit package task cancellation was requested"
                ) from exc
            except EditPackageError:
                self._withdraw_and_invalidate(
                    lease,
                    destination,
                    project_dir=project_dir,
                    expected_identity=existing_identity,
                    asset_ids=tuple(
                        reservation.asset_id
                        for reservation in (manifest_reservation, zip_reservation)
                        if reservation is not None
                    ),
                )
                raise
        try:
            _check_cancel(cancel_requested)
            self._publication_fence(lease, work)
            manifest_clips = _manifest_clips(result.manifest)
            committed_manifest = self._assets.commit(
                lease,
                manifest_reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "liveclip.edit-package.v1",
                    "edit_package_id": work.edit_package_id,
                    "package_version": package_version,
                    "snapshot_fingerprint": work.snapshot_fingerprint,
                    "clip_count": len(work.clips),
                },
                expected_sha256=result.manifest_sha256,
            )
            committed_zip = None
            if zip_reservation is not None:
                committed_zip = self._assets.commit(
                    lease,
                    zip_reservation,
                    project_dir=project_dir,
                    validation={
                        "schema_version": "liveclip.edit-package.v1",
                        "edit_package_id": work.edit_package_id,
                        "package_version": package_version,
                        "snapshot_fingerprint": work.snapshot_fingerprint,
                        "clip_count": len(work.clips),
                    },
                    expected_sha256=result.zip_sha256,
                )
            _check_cancel(cancel_requested)
            self._publication_fence(lease, work)
        except Exception:
            self._withdraw_and_invalidate(
                lease,
                result.directory,
                project_dir=project_dir,
                expected_identity=result.directory_identity,
                asset_ids=tuple(
                    reservation.asset_id
                    for reservation in (manifest_reservation, zip_reservation)
                    if reservation is not None
                ),
            )
            raise
        return EditPackagePersistence(
            manifest_asset_id=committed_manifest.asset_id,
            zip_asset_id=committed_zip.asset_id if committed_zip is not None else None,
            manifest_clips=manifest_clips,
            directory_identity=result.directory_identity,
        )

    def withdraw(
        self,
        work: EditPackageWork,
        lease: LeaseIdentity,
        persistence: EditPackagePersistence,
    ) -> None:
        project_dir = project_directory(self._data_dir, work.project_id)
        self._withdraw_and_invalidate(
            lease,
            project_dir / "edit-packages" / f"v{work.version:03d}",
            project_dir=project_dir,
            expected_identity=persistence.directory_identity,
            asset_ids=tuple(
                asset_id
                for asset_id in (persistence.manifest_asset_id, persistence.zip_asset_id)
                if asset_id is not None
            ),
        )

    def _withdraw_and_invalidate(
        self,
        lease: LeaseIdentity,
        directory: Path,
        *,
        project_dir: Path,
        expected_identity: tuple[int, int] | None,
        asset_ids: tuple[str, ...],
    ) -> None:
        if expected_identity is None:
            raise EditPackageError("edit package publication identity is missing")
        try:
            relative_directory = directory.relative_to(project_dir)
        except ValueError as exc:
            raise EditPackageError("edit package publication escaped its project") from exc
        self._assets.withdraw_attempt_publication(
            lease,
            asset_ids,
            project_dir=project_dir,
            relative_directory=relative_directory.as_posix(),
            expected_identity=expected_identity,
            reason="edit package publication was withdrawn",
        )

    def _reserve(
        self,
        work: EditPackageWork,
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


def _manifest_clips(manifest: dict[str, object]) -> tuple[EditPackageManifestClip, ...]:
    raw = manifest.get("clips")
    if not isinstance(raw, list) or not raw:
        raise EditPackageError("edit package manifest has no clips")
    values: list[EditPackageManifestClip] = []
    for item in raw:
        if not isinstance(item, dict):
            raise EditPackageError("edit package manifest clip is invalid")
        try:
            values.append(
                EditPackageManifestClip(
                    clip_id=_required_text(item, "clip_id"),
                    ordinal=_positive_int(item, "ordinal"),
                    edit_plan_revision=_positive_int(item, "edit_plan_revision"),
                    title=_required_text(item, "title"),
                    video_filename=_optional_text(item, "video_filename"),
                    subtitle_filename=_optional_text(item, "subtitle_filename"),
                    thumbnail_filename=_required_text(item, "thumbnail_filename"),
                    video_sha256=_optional_text(item, "video_sha256"),
                    subtitle_sha256=_optional_text(item, "subtitle_sha256"),
                    thumbnail_sha256=_required_text(item, "thumbnail_sha256"),
                )
            )
        except KeyError as exc:
            raise EditPackageError("edit package manifest clip fields are missing") from exc
    if len({value.clip_id for value in values}) != len(values):
        raise EditPackageError("edit package manifest clip IDs are duplicated")
    return tuple(values)


def _resolve_owned_asset_path(project_dir: Path, relative_path: str) -> Path:
    if "\\" in relative_path:
        raise EditPackageError("edit package input asset path is invalid")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise EditPackageError("edit package input asset path is invalid")
    candidate = project_dir / Path(*relative.parts)
    if project_dir not in candidate.parents:
        raise EditPackageError("edit package input asset escaped its project")
    return candidate


def _required_text(value: dict[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise EditPackageError("edit package manifest text field is invalid")
    return item


def _optional_text(value: dict[str, object], key: str) -> str | None:
    item = value[key]
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise EditPackageError("edit package manifest optional field is invalid")
    return item


def _positive_int(value: dict[str, object], key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
        raise EditPackageError("edit package manifest integer field is invalid")
    return item


def _check_cancel(callback: Callable[[], bool]) -> None:
    if callback():
        raise EditPackageTaskCancelled("edit package task cancellation was requested")


__all__ = [
    "DeliveryError",
    "EditPackageTaskCancelled",
    "EditPackageTaskHandler",
]
