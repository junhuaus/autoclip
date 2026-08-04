from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.deliveries import (
    DeliveryConflict,
    DeliveryPersistence,
    DeliveryRequest,
    DeliveryResourceNotFound,
    DeliverySnapshot,
    DeliveryWork,
    DeliveryWorkClip,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import new_id
from liveclip.db.delivery_snapshot import DeliverySetError, load_eligible_delivery_set
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    DeliveryClipRow,
    DeliveryRow,
    PipelineRunRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
    TaskStatus,
    transition_delivery,
    transition_task,
)


class SqlAlchemyDeliveryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue_delivery(
        self,
        project_id: str,
        request: DeliveryRequest,
        *,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> DeliverySnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            replay_delivery_id = load_idempotent_resource(
                connection, idempotency, resource_type="delivery"
            )
            if replay_delivery_id is not None:
                return _get_delivery(connection, replay_delivery_id)
            try:
                eligible = load_eligible_delivery_set(connection, project_id)
            except DeliverySetError as exc:
                raise DeliveryConflict(str(exc)) from exc
            run_status = connection.scalar(
                select(PipelineRunRow.status).where(PipelineRunRow.id == eligible.run_id)
            )
            if run_status != PipelineRunStatus.COMPLETED.value:
                raise DeliveryConflict("project pipeline is not complete")
            current_version = connection.scalar(
                select(func.max(DeliveryRow.version)).where(DeliveryRow.project_id == project_id)
            )
            version = int(current_version or 0) + 1
            if version > 999:
                raise DeliveryConflict("delivery version space is exhausted")
            delivery_id = new_id()
            task_id = new_id()
            package_fingerprint = _delivery_package_fingerprint(
                snapshot_fingerprint=eligible.fingerprint,
                delivery_id=delivery_id,
                version=version,
                include_zip=request.include_zip,
                created_at=now,
            )
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.DELIVERY.value,
                    target_id=delivery_id,
                    operation_key=f"delivery:{delivery_id}",
                    input_fingerprint=package_fingerprint,
                    resource_class=ResourceClass.HEAVY.value,
                    pipeline_run_id=eligible.run_id,
                    status=TaskStatus.QUEUED.value,
                    priority=700,
                    not_before=now,
                    expected_generation=eligible.generation,
                    expected_revision_epoch=eligible.revision_epoch,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=max_retries,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(DeliveryRow).values(
                    id=delivery_id,
                    project_id=project_id,
                    task_id=task_id,
                    version=version,
                    status=DeliveryStatus.QUEUED.value,
                    expected_revision_epoch=eligible.revision_epoch,
                    expected_generation=eligible.generation,
                    snapshot_fingerprint=eligible.fingerprint,
                    directory_relative_path=f"deliveries/v{version:03d}",
                    include_zip=request.include_zip,
                    created_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="delivery",
                resource_id=delivery_id,
            )
            return _get_delivery(connection, delivery_id)

    def get_delivery(self, delivery_id: str) -> DeliverySnapshot:
        with self._engine.connect() as connection:
            return _get_delivery(connection, delivery_id)

    def list_deliveries(self, project_id: str) -> tuple[DeliverySnapshot, ...]:
        with self._engine.connect() as connection:
            project_exists = connection.scalar(
                select(ProjectRow.id).where(ProjectRow.id == project_id)
            )
            if project_exists is None:
                raise DeliveryResourceNotFound("project does not exist")
            rows = connection.execute(
                select(
                    DeliveryRow.id,
                    DeliveryRow.project_id,
                    DeliveryRow.task_id,
                    DeliveryRow.version,
                    DeliveryRow.status,
                    DeliveryRow.manifest_asset_id,
                    DeliveryRow.zip_asset_id,
                    DeliveryRow.include_zip,
                    DeliveryRow.error_code,
                    DeliveryRow.safe_error_message,
                    func.count(DeliveryClipRow.id).label("clip_count"),
                )
                .outerjoin(DeliveryClipRow, DeliveryClipRow.delivery_id == DeliveryRow.id)
                .where(DeliveryRow.project_id == project_id)
                .group_by(DeliveryRow.id)
                .order_by(DeliveryRow.version.desc())
            )
            return tuple(_snapshot(row) for row in rows if row.task_id is not None)

    def start_delivery(self, lease: LeaseIdentity) -> DeliveryWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.id.label("task_id"),
                    TaskRow.target_id,
                    TaskRow.input_fingerprint,
                    TaskRow.expected_generation,
                    TaskRow.expected_revision_epoch,
                    DeliveryRow.id.label("delivery_id"),
                    DeliveryRow.status.label("delivery_status"),
                    DeliveryRow.version,
                    DeliveryRow.include_zip,
                    DeliveryRow.snapshot_fingerprint,
                    DeliveryRow.created_at.label("delivery_created_at"),
                    DeliveryRow.expected_generation.label("delivery_generation"),
                    DeliveryRow.expected_revision_epoch.label("delivery_epoch"),
                    ProjectRow.id.label("project_id"),
                    ProjectRow.current_pipeline_run_id.label("run_id"),
                    ProjectRow.current_generation,
                    ProjectRow.revision_epoch,
                )
                .join(DeliveryRow, DeliveryRow.task_id == TaskRow.id)
                .join(ProjectRow, ProjectRow.id == DeliveryRow.project_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.kind == TaskKind.DELIVERY.value,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                raise DeliveryConflict("delivery task lost its active lease")
            if (
                str(row.target_id) != str(row.delivery_id)
                or int(row.expected_generation) != int(row.current_generation)
                or int(row.delivery_generation) != int(row.current_generation)
                or int(row.expected_revision_epoch) != int(row.revision_epoch)
                or int(row.delivery_epoch) != int(row.revision_epoch)
                or str(row.input_fingerprint)
                != _delivery_package_fingerprint(
                    snapshot_fingerprint=str(row.snapshot_fingerprint),
                    delivery_id=str(row.delivery_id),
                    version=int(row.version),
                    include_zip=bool(row.include_zip),
                    created_at=row.delivery_created_at,
                )
            ):
                raise DeliveryConflict("delivery task is stale for the current project")
            try:
                eligible = load_eligible_delivery_set(connection, str(row.project_id))
            except DeliverySetError as exc:
                raise DeliveryConflict(str(exc)) from exc
            if eligible.fingerprint != str(row.snapshot_fingerprint):
                raise DeliveryConflict("approved render set changed before delivery started")
            current = DeliveryStatus(str(row.delivery_status))
            transition_delivery(current, DeliveryStatus.CREATING)
            connection.execute(
                update(DeliveryRow)
                .where(
                    DeliveryRow.id == row.delivery_id,
                    DeliveryRow.status == DeliveryStatus.QUEUED.value,
                )
                .values(
                    status=DeliveryStatus.CREATING.value,
                    error_code=None,
                    safe_error_message=None,
                )
            )
            return DeliveryWork(
                delivery_id=str(row.delivery_id),
                task_id=str(row.task_id),
                project_id=str(row.project_id),
                run_id=eligible.run_id,
                generation=eligible.generation,
                revision_epoch=eligible.revision_epoch,
                version=int(row.version),
                include_zip=bool(row.include_zip),
                snapshot_fingerprint=eligible.fingerprint,
                package_fingerprint=str(row.input_fingerprint),
                created_at=row.delivery_created_at,
                source_filename=eligible.source_filename,
                source_fingerprint=eligible.source_fingerprint,
                clips=tuple(
                    DeliveryWorkClip(
                        clip_id=clip.clip_id,
                        edit_plan_revision_id=clip.edit_plan_revision_id,
                        render_job_id=clip.render_job_id,
                        edit_plan_revision=clip.edit_plan_revision,
                        title=clip.title,
                        source_start_ms=clip.source_start_ms,
                        source_end_ms=clip.source_end_ms,
                        score=clip.score,
                        video_relative_path=clip.video_relative_path,
                        video_sha256=clip.video_sha256,
                        subtitle_relative_path=clip.subtitle_relative_path,
                        subtitle_sha256=clip.subtitle_sha256,
                    )
                    for clip in eligible.clips
                ),
            )

    def complete_delivery(
        self,
        lease: LeaseIdentity,
        work: DeliveryWork,
        persistence: DeliveryPersistence,
    ) -> bool:
        now = datetime.now(UTC)
        asset_ids = [persistence.manifest_asset_id]
        if persistence.zip_asset_id is not None:
            asset_ids.append(persistence.zip_asset_id)
        if len(set(asset_ids)) != len(asset_ids):
            raise DeliveryConflict("delivery package assets must be distinct")
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.input_fingerprint,
                    DeliveryRow.status,
                    DeliveryRow.snapshot_fingerprint,
                    DeliveryRow.include_zip,
                    ProjectRow.current_pipeline_run_id,
                    ProjectRow.current_generation,
                    ProjectRow.revision_epoch,
                )
                .join(DeliveryRow, DeliveryRow.task_id == TaskRow.id)
                .join(ProjectRow, ProjectRow.id == DeliveryRow.project_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                    DeliveryRow.id == work.delivery_id,
                )
            ).one_or_none()
            if row is None:
                return False
            if (
                str(row.current_pipeline_run_id) != work.run_id
                or int(row.current_generation) != work.generation
                or int(row.revision_epoch) != work.revision_epoch
                or str(row.input_fingerprint) != work.package_fingerprint
                or str(row.snapshot_fingerprint) != work.snapshot_fingerprint
                or bool(row.include_zip) != work.include_zip
            ):
                return False
            try:
                current = load_eligible_delivery_set(connection, work.project_id)
            except DeliverySetError:
                return False
            if current.fingerprint != work.snapshot_fingerprint:
                return False
            assets = connection.execute(
                select(
                    AssetRow.id,
                    AssetRow.kind,
                    AssetRow.relative_path,
                    AssetRow.input_fingerprint,
                    AssetRow.sha256,
                    AssetRow.size_bytes,
                    AssetRow.generation,
                    AssetRow.revision_epoch,
                    AssetRow.producer_attempt_id,
                    AssetRow.validation_json,
                ).where(
                    AssetRow.id.in_(asset_ids),
                    AssetRow.project_id == work.project_id,
                    AssetRow.status == AssetStatus.COMMITTED.value,
                )
            ).all()
            by_id = {str(asset.id): asset for asset in assets}
            if set(by_id) != set(asset_ids):
                raise DeliveryConflict("delivery completion requires committed package assets")
            producer_attempt_ids = {
                str(asset.producer_attempt_id)
                for asset in assets
                if asset.producer_attempt_id is not None
            }
            producer_task_ids = set(
                str(value)
                for value in connection.scalars(
                    select(TaskAttemptRow.task_id).where(
                        TaskAttemptRow.id.in_(producer_attempt_ids)
                    )
                )
            )
            if any(asset.producer_attempt_id is None for asset in assets) or producer_task_ids != {
                lease.task_id
            }:
                raise DeliveryConflict("delivery package assets belong to another task")
            manifest = by_id[persistence.manifest_asset_id]
            manifest_validation = manifest.validation_json
            if (
                manifest.kind != "delivery_manifest"
                or manifest.relative_path != f"deliveries/v{work.version:03d}/manifest.json"
                or manifest.input_fingerprint != work.package_fingerprint
                or not manifest.sha256
                or int(manifest.size_bytes or 0) <= 0
                or manifest.generation is None
                or int(manifest.generation) != work.generation
                or manifest.revision_epoch is None
                or int(manifest.revision_epoch) != work.revision_epoch
                or not isinstance(manifest_validation, dict)
                or manifest_validation.get("schema_version") != "1"
                or manifest_validation.get("delivery_id") != work.delivery_id
                or manifest_validation.get("delivery_version") != f"v{work.version:03d}"
                or manifest_validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
                or manifest_validation.get("clip_count") != len(work.clips)
            ):
                raise DeliveryConflict("delivery manifest asset is invalid")
            if work.include_zip:
                if persistence.zip_asset_id is None:
                    raise DeliveryConflict("ZIP delivery is missing its archive asset")
                archive = by_id[persistence.zip_asset_id]
                archive_validation = archive.validation_json
                if (
                    archive.kind != "delivery_zip"
                    or archive.relative_path != f"deliveries/v{work.version:03d}/delivery.zip"
                    or archive.input_fingerprint != work.package_fingerprint
                    or not archive.sha256
                    or int(archive.size_bytes or 0) <= 0
                    or archive.generation is None
                    or int(archive.generation) != work.generation
                    or archive.revision_epoch is None
                    or int(archive.revision_epoch) != work.revision_epoch
                    or not isinstance(archive_validation, dict)
                    or archive_validation.get("schema_version") != "1"
                    or archive_validation.get("delivery_id") != work.delivery_id
                    or archive_validation.get("delivery_version") != f"v{work.version:03d}"
                    or archive_validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
                    or archive_validation.get("members") != len(work.clips) * 2 + 1
                ):
                    raise DeliveryConflict("delivery ZIP asset is invalid")
            elif persistence.zip_asset_id is not None:
                raise DeliveryConflict("non-ZIP delivery unexpectedly contains an archive")
            if tuple(clip.clip_id for clip in persistence.manifest_clips) != tuple(
                clip.clip_id for clip in work.clips
            ):
                raise DeliveryConflict("delivery manifest clip set changed")
            if connection.scalar(
                select(func.count())
                .select_from(DeliveryClipRow)
                .where(DeliveryClipRow.delivery_id == work.delivery_id)
            ):
                raise DeliveryConflict("delivery clip snapshot was already persisted")
            for ordinal, clip in enumerate(work.clips, start=1):
                manifest_clip = persistence.manifest_clips[ordinal - 1]
                if (
                    manifest_clip.edit_plan_revision != clip.edit_plan_revision
                    or manifest_clip.title != clip.title
                    or manifest_clip.source_start_ms != clip.source_start_ms
                    or manifest_clip.source_end_ms != clip.source_end_ms
                    or manifest_clip.duration_ms != clip.source_end_ms - clip.source_start_ms
                    or manifest_clip.score != clip.score
                    or manifest_clip.review_status != "approved"
                    or manifest_clip.sha256 != clip.video_sha256
                ):
                    raise DeliveryConflict("delivery manifest clip snapshot changed")
                connection.execute(
                    insert(DeliveryClipRow).values(
                        id=new_id(),
                        delivery_id=work.delivery_id,
                        ordinal=ordinal,
                        candidate_clip_id=clip.clip_id,
                        edit_plan_revision_id=clip.edit_plan_revision_id,
                        render_job_id=clip.render_job_id,
                        edit_plan_revision=clip.edit_plan_revision,
                        title=clip.title,
                        video_filename=manifest_clip.video_filename,
                        subtitle_filename=manifest_clip.subtitle_filename,
                        source_start_ms=clip.source_start_ms,
                        source_end_ms=clip.source_end_ms,
                        score=clip.score,
                        sha256=manifest_clip.sha256,
                    )
                )
            transition_delivery(DeliveryStatus(str(row.status)), DeliveryStatus.SUCCEEDED)
            connection.execute(
                update(DeliveryRow)
                .where(
                    DeliveryRow.id == work.delivery_id,
                    DeliveryRow.status == DeliveryStatus.CREATING.value,
                )
                .values(
                    status=DeliveryStatus.SUCCEEDED.value,
                    manifest_asset_id=persistence.manifest_asset_id,
                    zip_asset_id=persistence.zip_asset_id,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=now,
                )
            )
            transition_task(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
            connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                )
                .values(
                    status=TaskStatus.SUCCEEDED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(outcome=AttemptOutcome.SUCCEEDED.value, finished_at=now)
            )
            return True


def _snapshot(row: object) -> DeliverySnapshot:
    return DeliverySnapshot(
        delivery_id=str(row.id),  # type: ignore[attr-defined]
        project_id=str(row.project_id),  # type: ignore[attr-defined]
        task_id=str(row.task_id),  # type: ignore[attr-defined]
        version=int(row.version),  # type: ignore[attr-defined]
        delivery_version=f"v{int(row.version):03d}",  # type: ignore[attr-defined]
        status=DeliveryStatus(str(row.status)),  # type: ignore[attr-defined]
        clip_count=int(row.clip_count),  # type: ignore[attr-defined]
        manifest_asset_id=(
            str(row.manifest_asset_id) if row.manifest_asset_id else None  # type: ignore[attr-defined]
        ),
        zip_asset_id=(
            str(row.zip_asset_id) if row.zip_asset_id else None  # type: ignore[attr-defined]
        ),
        include_zip=bool(row.include_zip),  # type: ignore[attr-defined]
        error_code=str(row.error_code) if row.error_code else None,  # type: ignore[attr-defined]
        safe_error_message=(
            str(row.safe_error_message) if row.safe_error_message else None  # type: ignore[attr-defined]
        ),
    )


def _get_delivery(connection: Connection, delivery_id: str) -> DeliverySnapshot:
    row = connection.execute(
        select(
            DeliveryRow.id,
            DeliveryRow.project_id,
            DeliveryRow.task_id,
            DeliveryRow.version,
            DeliveryRow.status,
            DeliveryRow.manifest_asset_id,
            DeliveryRow.zip_asset_id,
            DeliveryRow.include_zip,
            DeliveryRow.error_code,
            DeliveryRow.safe_error_message,
            func.count(DeliveryClipRow.id).label("clip_count"),
        )
        .outerjoin(DeliveryClipRow, DeliveryClipRow.delivery_id == DeliveryRow.id)
        .where(DeliveryRow.id == delivery_id)
        .group_by(DeliveryRow.id)
    ).one_or_none()
    if row is None or row.task_id is None:
        raise DeliveryResourceNotFound("delivery does not exist")
    return _snapshot(row)


def _delivery_package_fingerprint(
    *,
    snapshot_fingerprint: str,
    delivery_id: str,
    version: int,
    include_zip: bool,
    created_at: datetime,
) -> str:
    payload = {
        "schema_version": "delivery-package-v1",
        "snapshot_fingerprint": snapshot_fingerprint,
        "delivery_id": delivery_id,
        "version": version,
        "include_zip": include_zip,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "packager": "liveclip-delivery-v1",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
