from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from liveclip.db.models import ReleaseItemRow, ReleasePackageRow, TaskRow
from liveclip.domain.releases import ReleasePackageStatus, transition_release_package
from liveclip.domain.state_transitions import (
    FailureClass,
    TaskStatus,
    transition_task,
)

RELEASE_PACKAGE_STALE_CODE = "RELEASE_PACKAGE_STALE"
RELEASE_PACKAGE_STALE_MESSAGE = (
    "Release package became stale after release content or eligibility changed"
)


@dataclass(frozen=True, slots=True)
class InvalidatedReleasePackage:
    release_package_id: str
    release_item_id: str
    project_id: str
    task_id: str | None
    previous_status: ReleasePackageStatus


def invalidate_active_release_packages(
    connection: Connection,
    *,
    instant: datetime,
    release_item_ids: tuple[str, ...] | None = None,
    candidate_clip_ids: tuple[str, ...] | None = None,
    project_id: str | None = None,
) -> tuple[InvalidatedReleasePackage, ...]:
    """Fail active platform packages and fence their durable tasks atomically."""

    if release_item_ids == () or candidate_clip_ids == ():
        return ()
    if release_item_ids is None and candidate_clip_ids is None and project_id is None:
        raise ValueError("release package invalidation requires an explicit scope")
    query = (
        select(
            ReleasePackageRow.id,
            ReleasePackageRow.release_item_id,
            ReleasePackageRow.project_id,
            ReleasePackageRow.task_id,
            ReleasePackageRow.status,
        )
        .select_from(ReleasePackageRow)
        .join(ReleaseItemRow, ReleaseItemRow.id == ReleasePackageRow.release_item_id)
        .where(
            ReleasePackageRow.status.in_(
                [
                    ReleasePackageStatus.QUEUED.value,
                    ReleasePackageStatus.CREATING.value,
                ]
            )
        )
    )
    if release_item_ids is not None:
        query = query.where(ReleasePackageRow.release_item_id.in_(release_item_ids))
    if candidate_clip_ids is not None:
        query = query.where(ReleaseItemRow.candidate_clip_id.in_(candidate_clip_ids))
    if project_id is not None:
        query = query.where(ReleasePackageRow.project_id == project_id)
    rows = connection.execute(query).all()
    if not rows:
        return ()
    invalidated = tuple(
        InvalidatedReleasePackage(
            release_package_id=str(row.id),
            release_item_id=str(row.release_item_id),
            project_id=str(row.project_id),
            task_id=str(row.task_id) if row.task_id is not None else None,
            previous_status=ReleasePackageStatus(str(row.status)),
        )
        for row in rows
    )
    for item in invalidated:
        transition_release_package(item.previous_status, ReleasePackageStatus.FAILED)
    package_ids = tuple(item.release_package_id for item in invalidated)
    connection.execute(
        update(ReleasePackageRow)
        .where(
            ReleasePackageRow.id.in_(package_ids),
            ReleasePackageRow.status.in_(
                [
                    ReleasePackageStatus.QUEUED.value,
                    ReleasePackageStatus.CREATING.value,
                ]
            ),
        )
        .values(
            status=ReleasePackageStatus.FAILED.value,
            error_code=RELEASE_PACKAGE_STALE_CODE,
            safe_error_message=RELEASE_PACKAGE_STALE_MESSAGE,
            completed_at=instant,
        )
    )
    task_ids = tuple(item.task_id for item in invalidated if item.task_id is not None)
    if not task_ids:
        return invalidated
    queued_task_ids = tuple(
        str(value)
        for value in connection.scalars(
            select(TaskRow.id).where(
                TaskRow.id.in_(task_ids),
                TaskRow.status == TaskStatus.QUEUED.value,
            )
        )
    )
    for _task_id in queued_task_ids:
        transition_task(TaskStatus.QUEUED, TaskStatus.CANCELLED)
    if queued_task_ids:
        connection.execute(
            update(TaskRow)
            .where(
                TaskRow.id.in_(queued_task_ids),
                TaskRow.status == TaskStatus.QUEUED.value,
            )
            .values(
                status=TaskStatus.CANCELLED.value,
                cancellation_requested_at=instant,
                failure_class=FailureClass.DETERMINISTIC.value,
                error_code=RELEASE_PACKAGE_STALE_CODE,
                safe_error_message=RELEASE_PACKAGE_STALE_MESSAGE,
                completed_at=instant,
                updated_at=instant,
            )
        )
    connection.execute(
        update(TaskRow)
        .where(
            TaskRow.id.in_(task_ids),
            TaskRow.status == TaskStatus.RUNNING.value,
        )
        .values(
            cancellation_requested_at=instant,
            failure_class=FailureClass.DETERMINISTIC.value,
            error_code=RELEASE_PACKAGE_STALE_CODE,
            safe_error_message=RELEASE_PACKAGE_STALE_MESSAGE,
            updated_at=instant,
        )
    )
    return invalidated


__all__ = [
    "RELEASE_PACKAGE_STALE_CODE",
    "RELEASE_PACKAGE_STALE_MESSAGE",
    "InvalidatedReleasePackage",
    "invalidate_active_release_packages",
]
