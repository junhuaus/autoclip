from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.releases import (
    ReleasePackagePersistence,
    ReleasePackageWork,
)
from liveclip.delivery.release_package import (
    ReleasePackageError,
    ReleasePackageTransientError,
    create_release_package,
    release_archive_name,
    validate_existing_release_package,
)
from liveclip.media.artifacts import project_directory
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    directory_identity_no_follow,
    require_directory_no_follow,
)


class ReleasePackageTaskCancelled(RuntimeError):
    """A durable release-package task was cancelled before publication."""


class ReleasePackageTaskHandler:
    def __init__(
        self,
        *,
        data_dir: Path,
        assets: AssetStore,
        publication_fence: Callable[[LeaseIdentity, ReleasePackageWork], None],
    ) -> None:
        self._data_dir = data_dir
        self._assets = assets
        self._publication_fence = publication_fence

    def execute(
        self,
        work: ReleasePackageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> ReleasePackagePersistence:
        _check_cancel(cancel_requested)
        project_dir = project_directory(self._data_dir, work.project_id)
        package_root = f"release-packages/{work.release_item_id}/v{work.version:03d}"
        manifest_reservation = self._reserve(
            work,
            lease,
            kind="release_package_manifest",
            relative_path=f"{package_root}/manifest.json",
            mime_type="application/json",
        )
        archive_name = release_archive_name(work)
        zip_reservation = (
            self._reserve(
                work,
                lease,
                kind="release_package_zip",
                relative_path=f"{package_root}/{archive_name}",
                mime_type="application/zip",
            )
            if work.include_zip
            else None
        )
        video_path = _resolve_owned_asset_path(
            project_dir,
            work.source_video_relative_path,
        )
        destination = (
            project_dir / "release-packages" / work.release_item_id / f"v{work.version:03d}"
        )
        try:
            require_directory_no_follow(destination)
        except SecureFileMissing:
            try:
                result = create_release_package(
                    project_dir=project_dir,
                    work=work,
                    video_path=video_path,
                    cancel_requested=cancel_requested,
                    publication_fence=lambda: self._publication_fence(lease, work),
                )
            except InterruptedError as exc:
                raise ReleasePackageTaskCancelled(
                    "release package task cancellation was requested"
                ) from exc
        except SecureFileError as exc:
            raise ReleasePackageError("existing release package directory is unsafe") from exc
        else:
            self._publication_fence(lease, work)
            try:
                existing_identity = directory_identity_no_follow(destination)
                result = validate_existing_release_package(
                    destination,
                    work=work,
                    cancel_requested=cancel_requested,
                )
            except ReleasePackageTransientError:
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
                raise ReleasePackageTaskCancelled(
                    "release package task cancellation was requested"
                ) from exc
            except ReleasePackageError:
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
            validation: dict[str, object] = {
                "schema_version": "liveclip.release-package.v1",
                "release_package_id": work.release_package_id,
                "package_version": f"v{work.version:03d}",
                "snapshot_fingerprint": work.snapshot_fingerprint,
                "platform": work.preset.platform.value,
            }
            committed_manifest = self._assets.commit(
                lease,
                manifest_reservation,
                project_dir=project_dir,
                validation=validation,
                expected_sha256=result.manifest_sha256,
            )
            committed_zip = None
            if zip_reservation is not None:
                committed_zip = self._assets.commit(
                    lease,
                    zip_reservation,
                    project_dir=project_dir,
                    validation=validation,
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
        return ReleasePackagePersistence(
            manifest_asset_id=committed_manifest.asset_id,
            zip_asset_id=committed_zip.asset_id if committed_zip is not None else None,
            manifest_sha256=result.manifest_sha256,
            zip_sha256=result.zip_sha256,
            directory_identity=result.directory_identity,
        )

    def withdraw(
        self,
        work: ReleasePackageWork,
        lease: LeaseIdentity,
        persistence: ReleasePackagePersistence,
    ) -> None:
        project_dir = project_directory(self._data_dir, work.project_id)
        self._withdraw_and_invalidate(
            lease,
            project_dir / "release-packages" / work.release_item_id / f"v{work.version:03d}",
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
            raise ReleasePackageError("release package publication identity is missing")
        try:
            relative_directory = directory.relative_to(project_dir)
        except ValueError as exc:
            raise ReleasePackageError("release package publication escaped its project") from exc
        self._assets.withdraw_attempt_publication(
            lease,
            asset_ids,
            project_dir=project_dir,
            relative_directory=relative_directory.as_posix(),
            expected_identity=expected_identity,
            reason="release package publication was withdrawn",
        )

    def _reserve(
        self,
        work: ReleasePackageWork,
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
        raise ReleasePackageError("release package input asset path is invalid")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ReleasePackageError("release package input asset path is invalid")
    candidate = project_dir / Path(*relative.parts)
    if project_dir not in candidate.parents:
        raise ReleasePackageError("release package input asset escaped its project")
    return candidate


def _check_cancel(callback: Callable[[], bool]) -> None:
    if callback():
        raise ReleasePackageTaskCancelled("release package task cancellation was requested")


__all__ = [
    "ReleasePackageTaskCancelled",
    "ReleasePackageTaskHandler",
]
