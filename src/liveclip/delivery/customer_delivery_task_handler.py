"""Worker handler that builds one immutable customer delivery (Stage 19c)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from liveclip.application.customer_deliveries import (
    CustomerDeliveryPersistence,
    CustomerDeliveryWork,
)
from liveclip.application.pipeline import LeaseIdentity
from liveclip.delivery.customer_package import (
    CustomerPackageCancelled,
    CustomerPackageClip,
    CustomerPackageError,
    build_customer_package,
)
from liveclip.domain.customer_delivery import CustomerText
from liveclip.media.artifacts import project_directory


class CustomerDeliveryTaskCancelled(RuntimeError):
    """A customer delivery task was cancelled before publication."""


class CustomerDeliveryTaskHandler:
    def __init__(
        self,
        *,
        data_dir: Path,
        publication_fence: Callable[[LeaseIdentity, CustomerDeliveryWork], None],
    ) -> None:
        self._data_dir = data_dir
        self._publication_fence = publication_fence

    def execute(
        self,
        work: CustomerDeliveryWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> CustomerDeliveryPersistence:
        project_dir = project_directory(self._data_dir, work.project_id)
        clips = tuple(
            CustomerPackageClip(
                ordinal=clip.ordinal,
                profile=clip.profile,
                text=CustomerText(title=clip.title, hook=clip.hook, summary=clip.summary),
                duration_ms=clip.duration_ms,
                video_path=_owned_path(project_dir, clip.video_relative_path),
                video_sha256=clip.video_sha256,
                video_size_bytes=clip.video_size_bytes,
                subtitle_path=_owned_path(project_dir, clip.subtitle_relative_path),
                subtitle_sha256=clip.subtitle_sha256,
                subtitle_size_bytes=clip.subtitle_size_bytes,
            )
            for clip in work.clips
        )
        try:
            result = build_customer_package(
                project_dir=project_dir,
                delivery_version=work.delivery_version,
                title=work.title,
                created_at=work.created_at.isoformat(),
                clips=clips,
                cancel_requested=cancel_requested,
                publication_fence=lambda: self._publication_fence(lease, work),
            )
        except CustomerPackageCancelled as exc:
            raise CustomerDeliveryTaskCancelled("customer delivery was cancelled") from exc
        directory = result.directory.relative_to(project_dir).as_posix()
        return CustomerDeliveryPersistence(
            directory_relative_path=directory,
            manifest_relative_path=f"{directory}/manifest.json",
            manifest_sha256=result.manifest_sha256,
            manifest_size_bytes=result.manifest_size_bytes,
            zip_relative_path=f"{directory}/{result.zip_name}",
            zip_sha256=result.zip_sha256,
            zip_size_bytes=result.zip_size_bytes,
        )


def _owned_path(project_dir: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        "\\" in relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CustomerPackageError("customer delivery input path is invalid")
    return project_dir / Path(*relative.parts)


__all__ = ["CustomerDeliveryTaskCancelled", "CustomerDeliveryTaskHandler"]
