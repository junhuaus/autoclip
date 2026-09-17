from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import OperationalError

from liveclip.application.deliveries import (
    DeliveryConflict,
    DeliveryPersistence,
    DeliveryRequest,
    DeliveryResourceNotFound,
    DeliverySnapshot,
    DeliveryWork,
    DeliveryWorkClip,
)
from liveclip.application.delivery_progress import (
    WORK_PHASES,
    DeliveryProgressEvent,
    DeliveryProgressLostLease,
    DeliveryProgressWriteFailed,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import new_id
from liveclip.db.delivery_snapshot import (
    DeliverySetError,
    EligibleDeliverySet,
    load_eligible_delivery_set,
)
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    DeliveryClipRow,
    DeliveryProgressRow,
    DeliveryRow,
    PipelineRunRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.delivery.package import (
    DeliveryError,
    delivery_checksums_text,
    delivery_index_html,
    normalize_srt,
    safe_filename_component,
    validate_zip_infos,
)
from liveclip.delivery.task_handler import (
    _manifest_clips,
    _resolve_owned_asset_path,
    _source_basename,
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
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    PinnedRegularFile,
    SecureFileError,
    open_pinned_regular_file,
    require_directory_no_follow,
    validate_pinned_directory_files_no_follow,
)


class DeliveryInspectionStopped(RuntimeError):
    """Cancellation or lease loss stops inspection without classifying artifacts as invalid."""


class DeliveryInspectionRequired(RuntimeError):
    """Release the writer lock for hashing, retaining pinned files until final fencing."""

    def __init__(
        self,
        signature: tuple[object, ...],
        verify: Callable[[], bool],
        pins: list[PinnedRegularFile],
        stack: ExitStack,
    ) -> None:
        super().__init__("bound delivery requires artifact inspection")
        self.signature = signature
        self._verify = verify
        self._pins = pins
        self._stack = stack
        self._verified = False
        self.cancel_requested: Callable[[], bool] = lambda: False

    def check_cancel(self) -> None:
        if self.cancel_requested():
            raise DeliveryInspectionStopped

    def inspect(self) -> None:
        self._verified = self._verify()

    def still_valid(self) -> bool:
        if not self._verified or not self._pins:
            return False
        try:
            for pinned in self._pins:
                pinned.validate_at(pinned.path)
        except (SecureFileError, OSError):
            return False
        return True

    def close(self) -> None:
        self._stack.close()


def current_delivery_progress_authority(
    connection: Connection, delivery_id: str, *, now: datetime
) -> tuple[RowMapping, RowMapping, RowMapping] | None:
    """Resolve live ownership using database state, never a cached attempt ID."""
    delivery = (
        connection.execute(select(DeliveryRow).where(DeliveryRow.id == delivery_id))
        .mappings()
        .one_or_none()
    )
    if delivery is None or delivery["status"] != DeliveryStatus.CREATING.value:
        return None
    task = (
        connection.execute(select(TaskRow).where(TaskRow.id == delivery["task_id"]))
        .mappings()
        .one_or_none()
    )
    project = (
        connection.execute(select(ProjectRow).where(ProjectRow.id == delivery["project_id"]))
        .mappings()
        .one_or_none()
    )
    if (
        task is None
        or project is None
        or (
            task["target_id"] != delivery_id
            or task["kind"] != TaskKind.DELIVERY.value
            or task["status"] != TaskStatus.RUNNING.value
            or task["lease_expires_at"] is None
            or task["lease_expires_at"] <= now
            or task["cancellation_requested_at"] is not None
            or task["pipeline_run_id"] != project["current_pipeline_run_id"]
            or task["expected_generation"] != project["current_generation"]
            or delivery["expected_generation"] != project["current_generation"]
            or task["expected_revision_epoch"] != project["revision_epoch"]
            or delivery["expected_revision_epoch"] != project["revision_epoch"]
            or task["input_fingerprint"]
            != _delivery_package_fingerprint(
                snapshot_fingerprint=delivery["snapshot_fingerprint"],
                delivery_id=delivery_id,
                version=delivery["version"],
                include_zip=delivery["include_zip"],
                created_at=delivery["created_at"],
            )
        )
    ):
        return None
    attempt = (
        connection.execute(
            select(TaskAttemptRow).where(
                TaskAttemptRow.task_id == task["id"],
                TaskAttemptRow.attempt_number == task["attempt_count"],
                TaskAttemptRow.worker_id == task["worker_id"],
                TaskAttemptRow.lease_token == task["lease_token"],
                TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
            )
        )
        .mappings()
        .one_or_none()
    )
    return (delivery, task, attempt) if attempt is not None else None


class _DeliveryProgressSink:
    def __init__(
        self, engine: Engine, lease: LeaseIdentity, work: DeliveryWork, attempt_number: int
    ) -> None:
        self._engine = engine
        self._lease = lease
        self._work = work
        self._attempt_number = attempt_number

    def advance(self, event: DeliveryProgressEvent) -> None:
        # Validation defects are deterministic; only SQLite operational failures retry.
        event = DeliveryProgressEvent.model_validate(event)
        try:
            with begin_immediate(self._engine) as connection:
                now = datetime.now(UTC)
                authority = current_delivery_progress_authority(
                    connection, self._work.delivery_id, now=now
                )
                if authority is None:
                    raise DeliveryProgressLostLease("delivery progress authority expired")
                delivery, task, attempt = authority
                if (
                    task["id"] != self._lease.task_id
                    or task["worker_id"] != self._lease.worker_id
                    or task["lease_token"] != self._lease.lease_token
                    or task["attempt_count"] != self._attempt_number
                    or delivery["project_id"] != self._work.project_id
                    or task["expected_generation"] != self._work.generation
                    or task["expected_revision_epoch"] != self._work.revision_epoch
                    or task["input_fingerprint"] != self._work.package_fingerprint
                    or task["pipeline_run_id"] != self._work.run_id
                ):
                    raise DeliveryProgressLostLease("delivery progress identity changed")
                identity = (
                    DeliveryProgressRow.delivery_id == self._work.delivery_id,
                    DeliveryProgressRow.task_attempt_id == attempt["id"],
                )
                previous = (
                    connection.execute(select(DeliveryProgressRow).where(*identity))
                    .mappings()
                    .one_or_none()
                )
                values = dict(
                    phase=event.phase.value,
                    unit=event.unit.value,
                    completed=event.completed,
                    total=event.total,
                    business_advanced_at=now,
                )
                if previous is not None:
                    if (
                        previous["attempt_number"] != self._attempt_number
                        or previous["expected_generation"] != self._work.generation
                        or previous["expected_revision_epoch"] != self._work.revision_epoch
                        or previous["package_fingerprint"] != self._work.package_fingerprint
                    ):
                        raise DeliveryProgressLostLease("persisted progress identity changed")
                    old_phase = WORK_PHASES.index(previous["phase"])
                    new_phase = WORK_PHASES.index(event.phase)
                    if new_phase < old_phase or (
                        new_phase == old_phase
                        and (
                            event.completed < previous["completed"]
                            or (previous["total"] is not None and event.total != previous["total"])
                        )
                    ):
                        raise ValueError("delivery progress must advance monotonically")
                    if all(
                        previous[key] == values[key]
                        for key in ("phase", "unit", "completed", "total")
                    ):
                        return
                    connection.execute(
                        update(DeliveryProgressRow).where(*identity).values(**values)
                    )
                else:
                    connection.execute(
                        insert(DeliveryProgressRow).values(
                            delivery_id=self._work.delivery_id,
                            task_attempt_id=attempt["id"],
                            attempt_number=self._attempt_number,
                            expected_generation=self._work.generation,
                            expected_revision_epoch=self._work.revision_epoch,
                            package_fingerprint=self._work.package_fingerprint,
                            started_at=now,
                            **values,
                        )
                    )
        except OperationalError as exc:
            # A writer wait can outlive this lease. Recheck without a writer lock
            # before asking the queue to retry; never classify a successor as ours.
            try:
                with self._engine.connect() as connection:
                    authority = current_delivery_progress_authority(
                        connection, self._work.delivery_id, now=datetime.now(UTC)
                    )
                    if authority is None or (
                        authority[1]["id"] != self._lease.task_id
                        or authority[1]["worker_id"] != self._lease.worker_id
                        or authority[1]["lease_token"] != self._lease.lease_token
                        or authority[1]["attempt_count"] != self._attempt_number
                        or authority[1]["input_fingerprint"] != self._work.package_fingerprint
                        or authority[1]["expected_generation"] != self._work.generation
                        or authority[1]["expected_revision_epoch"] != self._work.revision_epoch
                    ):
                        raise DeliveryProgressLostLease(
                            "delivery lease changed during writer wait"
                        ) from exc
            except OperationalError:
                # Authority is unknown while SQLite is unavailable. The queue's
                # own lease fence remains mandatory for any eventual retry.
                pass
            raise DeliveryProgressWriteFailed("delivery progress could not be persisted") from exc


class SqlAlchemyDeliveryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def progress_sink(
        self, lease: LeaseIdentity, work: DeliveryWork, *, attempt_number: int
    ) -> _DeliveryProgressSink:
        return _DeliveryProgressSink(self._engine, lease, work, attempt_number)

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
            return self.enqueue_delivery_on_connection(
                connection,
                project_id,
                request,
                max_retries=max_retries,
                idempotency=idempotency,
                now=now,
            )

    def enqueue_delivery_on_connection(
        self,
        connection: Connection,
        project_id: str,
        request: DeliveryRequest,
        *,
        max_retries: int,
        idempotency: IdempotencyContext | None,
        now: datetime,
    ) -> DeliverySnapshot:
        """Allocate on the caller's writer transaction; never commit independently."""
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

    def observe_bound_delivery(
        self,
        connection: Connection,
        delivery_id: str,
        *,
        eligible: EligibleDeliverySet,
        include_zip: bool,
        data_dir: Path | None,
        inspection: DeliveryInspectionRequired | None = None,
    ) -> tuple[str | None, bool]:
        """Inspect only the immutable bound row; task success alone proves nothing."""
        row = (
            connection.execute(
                select(
                    DeliveryRow,
                    TaskRow.input_fingerprint,
                    TaskRow.status.label("task_status"),
                    TaskRow.pipeline_run_id,
                    TaskRow.kind.label("task_kind"),
                    TaskRow.target_id,
                    TaskRow.operation_key,
                    TaskRow.expected_generation.label("task_generation"),
                    TaskRow.expected_revision_epoch.label("task_epoch"),
                )
                .join(TaskRow, TaskRow.id == DeliveryRow.task_id)
                .where(DeliveryRow.id == delivery_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return "DELIVERY_BINDING_INVALID", False
        fingerprint = _delivery_package_fingerprint(
            snapshot_fingerprint=row["snapshot_fingerprint"],
            delivery_id=delivery_id,
            version=row["version"],
            include_zip=row["include_zip"],
            created_at=row["created_at"],
        )
        if (
            row["project_id"] != eligible.project_id
            or row["task_kind"] != TaskKind.DELIVERY.value
            or row["target_id"] != delivery_id
            or row["operation_key"] != f"delivery:{delivery_id}"
            or row["pipeline_run_id"] != eligible.run_id
            or row["expected_generation"] != eligible.generation
            or row["task_generation"] != row["expected_generation"]
            or row["task_epoch"] != row["expected_revision_epoch"]
            or row["include_zip"] != include_zip
            or row["input_fingerprint"] != fingerprint
            or row["snapshot_fingerprint"] != eligible.fingerprint
            or row["directory_relative_path"] != f"deliveries/v{row['version']:03d}"
        ):
            return "DELIVERY_BINDING_INVALID", False
        if row["status"] == "failed" or row["task_status"] in {"failed", "cancelled"}:
            return "DELIVERY_FAILED", False
        if row["status"] in {"queued", "creating"} and row["task_status"] in {"queued", "running"}:
            return None, False
        if row["status"] != "succeeded" or row["task_status"] != "succeeded":
            return "DELIVERY_BINDING_INVALID", False
        if data_dir is None:
            return "DELIVERY_ARTIFACTS_INVALID", False
        clips = (
            connection.execute(
                select(DeliveryClipRow)
                .where(DeliveryClipRow.delivery_id == delivery_id)
                .order_by(DeliveryClipRow.ordinal)
            )
            .mappings()
            .all()
        )
        if (
            not clips
            or len(clips) != len(eligible.clips)
            or any(
                saved["candidate_clip_id"] != clip.clip_id
                or saved["edit_plan_revision_id"] != clip.edit_plan_revision_id
                or saved["edit_plan_revision"] != clip.edit_plan_revision
                or saved["render_job_id"] != clip.render_job_id
                or saved["sha256"] != clip.video_sha256
                or saved["title"] != clip.title
                or saved["source_start_ms"] != clip.source_start_ms
                or saved["source_end_ms"] != clip.source_end_ms
                or saved["score"] != clip.score
                or saved["ordinal"] != ordinal
                or saved["video_filename"]
                != (f"clips/{ordinal:02d}-{safe_filename_component(clip.title)}.mp4")
                or saved["subtitle_filename"]
                != (f"subtitles/{ordinal:02d}-{safe_filename_component(clip.title)}.srt")
                for ordinal, (saved, clip) in enumerate(zip(clips, eligible.clips, strict=True), 1)
            )
        ):
            return "DELIVERY_ARTIFACTS_INVALID", False
        ids = [row["manifest_asset_id"]]
        if include_zip:
            ids.append(row["zip_asset_id"])
        if None in ids or len(set(ids)) != len(ids) or (not include_zip and row["zip_asset_id"]):
            return "DELIVERY_ARTIFACTS_INVALID", False
        assets = (
            connection.execute(
                select(
                    AssetRow,
                    TaskAttemptRow.task_id.label("producer_task_id"),
                    TaskAttemptRow.outcome.label("producer_outcome"),
                )
                .join(TaskAttemptRow, TaskAttemptRow.id == AssetRow.producer_attempt_id)
                .where(AssetRow.id.in_(ids))
            )
            .mappings()
            .all()
        )
        by_id = {asset["id"]: asset for asset in assets}
        if set(by_id) != set(ids) or any(
            asset["project_id"] != eligible.project_id
            or asset["status"] != "committed"
            or asset["producer_task_id"] != row["task_id"]
            or asset["producer_outcome"] != AttemptOutcome.SUCCEEDED.value
            or asset["input_fingerprint"] != fingerprint
            or asset["generation"] != eligible.generation
            or asset["revision_epoch"] != row["expected_revision_epoch"]
            or not asset["sha256"]
            or not asset["size_bytes"]
            for asset in assets
        ):
            return "DELIVERY_ARTIFACTS_INVALID", False
        for asset_id, kind, filename in (
            (row["manifest_asset_id"], "delivery_manifest", "manifest.json"),
            (row["zip_asset_id"], "delivery_zip", "delivery.zip"),
        ):
            if asset_id is not None and (
                by_id[asset_id]["kind"] != kind
                or by_id[asset_id]["relative_path"]
                != f"{row['directory_relative_path']}/{filename}"
            ):
                return "DELIVERY_ARTIFACTS_INVALID", False
        work = DeliveryWork(
            delivery_id=delivery_id,
            task_id=row["task_id"],
            project_id=eligible.project_id,
            run_id=eligible.run_id,
            generation=eligible.generation,
            revision_epoch=row["expected_revision_epoch"],
            version=row["version"],
            include_zip=include_zip,
            snapshot_fingerprint=eligible.fingerprint,
            package_fingerprint=fingerprint,
            created_at=row["created_at"],
            source_filename=eligible.source_filename,
            source_fingerprint=eligible.source_fingerprint,
            clips=tuple(
                DeliveryWorkClip(
                    clip_id=c.clip_id,
                    edit_plan_revision_id=c.edit_plan_revision_id,
                    render_job_id=c.render_job_id,
                    edit_plan_revision=c.edit_plan_revision,
                    title=c.title,
                    source_start_ms=c.source_start_ms,
                    source_end_ms=c.source_end_ms,
                    score=c.score,
                    video_relative_path=c.video_relative_path,
                    video_sha256=c.video_sha256,
                    subtitle_relative_path=c.subtitle_relative_path,
                    subtitle_sha256=c.subtitle_sha256,
                    hook=c.hook,
                    reason=c.reason,
                    risk_flags=c.risk_flags,
                    keywords=c.keywords,
                )
                for c in eligible.clips
            ),
        )
        media_ids = tuple(
            asset_id
            for clip in eligible.clips
            for asset_id in (clip.video_asset_id, clip.subtitle_asset_id)
        )
        media_rows = connection.execute(
            select(AssetRow.id, AssetRow.relative_path, AssetRow.sha256, AssetRow.size_bytes)
            .where(AssetRow.id.in_(media_ids))
            .order_by(AssetRow.id)
        ).all()
        signature: tuple[object, ...] = (
            work,
            eligible,
            tuple(dict(asset) for asset in sorted(assets, key=lambda a: a["id"])),
            tuple(media_rows),
            data_dir,
        )
        if inspection is not None:
            if inspection.signature == signature and inspection.still_valid():
                return None, True
            return "DELIVERY_ARTIFACTS_INVALID", False
        pins: list[PinnedRegularFile] = []
        stack = ExitStack()

        def verify() -> bool:
            try:
                root = require_directory_no_follow(data_dir / eligible.project_id)
                paths = [root / asset["relative_path"] for asset in assets]
                paths.extend(
                    _resolve_owned_asset_path(root, asset.relative_path) for asset in media_rows
                )
                destination = root / row["directory_relative_path"]
                paths.extend((destination / "index.html", destination / "checksums.sha256"))
                for ordinal, clip in enumerate(eligible.clips, 1):
                    stem = f"{ordinal:02d}-{safe_filename_component(clip.title)}"
                    paths.extend(
                        (
                            destination / "clips" / f"{stem}.mp4",
                            destination / "subtitles" / f"{stem}.srt",
                        )
                    )
                evidence: dict[Path, PinnedFileEvidence] = {}
                for path in paths:
                    request.check_cancel()
                    pinned = stack.enter_context(open_pinned_regular_file(path))
                    pins.append(pinned)
                    evidence[path] = PinnedFileEvidence(
                        pinned=pinned,
                        sha256=pinned.sha256(cancel_requested=request.cancel_requested),
                        size_bytes=pinned.metadata.st_size,
                    )
                for asset in assets:
                    observed = evidence[root / asset["relative_path"]]
                    if (observed.sha256, observed.size_bytes) != (
                        asset["sha256"],
                        asset["size_bytes"],
                    ):
                        return False
                for media_asset in media_rows:
                    observed = evidence[_resolve_owned_asset_path(root, media_asset.relative_path)]
                    if (observed.sha256, observed.size_bytes) != (
                        media_asset.sha256,
                        media_asset.size_bytes,
                    ):
                        return False
                _verify_inspected_package(root, work, evidence, check_cancel=request.check_cancel)
            except (DeliveryError, SecureFileError, OSError, ValueError, zipfile.BadZipFile):
                request.check_cancel()
                return False
            request.check_cancel()
            return True

        request = DeliveryInspectionRequired(signature, verify, pins, stack)
        raise request

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
                        hook=clip.hook,
                        reason=clip.reason,
                        risk_flags=clip.risk_flags,
                        keywords=clip.keywords,
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
        if not work.clips:
            raise DeliveryConflict("delivery completion requires at least one clip")
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
                    or archive_validation.get("members") != len(work.clips) * 2 + 3
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


def _verify_inspected_package(
    root: Path,
    work: DeliveryWork,
    evidence: dict[Path, PinnedFileEvidence],
    *,
    check_cancel: Callable[[], None],
) -> None:
    """Validate the held package with bounded, interruptible ZIP reads.

    Reuse the packager's manifest parser, normalized subtitles, deterministic
    metadata and directory/ZIP safety contracts; never rehash without cancellation.
    """
    destination = root / "deliveries" / f"v{work.version:03d}"
    check_cancel()
    manifest = json.loads(
        evidence[destination / "manifest.json"].pinned.read_bytes(max_bytes=2_000_000)
    )
    if not isinstance(manifest, dict) or (
        manifest.get("schema_version") != "1"
        or manifest.get("project_id") != work.project_id
        or manifest.get("delivery_id") != work.delivery_id
        or manifest.get("delivery_version") != f"v{work.version:03d}"
        or manifest.get("source_filename") != _source_basename(work.source_filename)
        or manifest.get("source_fingerprint") != work.source_fingerprint
        or manifest.get("snapshot_fingerprint") != work.snapshot_fingerprint
    ):
        raise DeliveryError("inspected manifest identity changed")
    entries = _manifest_clips(manifest)
    if len(entries) != len(work.clips):
        raise DeliveryError("inspected clip set changed")
    members = {"manifest.json": evidence[destination / "manifest.json"]}
    for ordinal, (entry, clip) in enumerate(zip(entries, work.clips, strict=True), 1):
        check_cancel()
        stem = f"{ordinal:02d}-{safe_filename_component(clip.title)}"
        if (
            entry.clip_id != clip.clip_id
            or entry.edit_plan_revision != clip.edit_plan_revision
            or entry.title != clip.title
            or entry.source_start_ms != clip.source_start_ms
            or entry.source_end_ms != clip.source_end_ms
            or entry.duration_ms != clip.source_end_ms - clip.source_start_ms
            or entry.score != clip.score
            or entry.review_status != "approved"
            or entry.sha256 != clip.video_sha256
            or entry.video_filename != f"clips/{stem}.mp4"
            or entry.subtitle_filename != f"subtitles/{stem}.srt"
        ):
            raise DeliveryError("inspected clip metadata changed")
        video = evidence[destination / entry.video_filename]
        subtitle = evidence[destination / entry.subtitle_filename]
        original = evidence[_resolve_owned_asset_path(root, clip.subtitle_relative_path)]
        subtitle_sha = hashlib.sha256(
            normalize_srt(original.pinned.read_bytes(max_bytes=2_000_000).decode("utf-8")).encode(
                "utf-8"
            )
        ).hexdigest()
        if video.sha256 != clip.video_sha256 or subtitle.sha256 != subtitle_sha:
            raise DeliveryError("inspected clip bytes changed")
        members[entry.video_filename] = video
        members[entry.subtitle_filename] = subtitle
    index = evidence[destination / "index.html"]
    if index.sha256 != hashlib.sha256(delivery_index_html(manifest).encode("utf-8")).hexdigest():
        raise DeliveryError("inspected index changed")
    members["index.html"] = index
    checksums = evidence[destination / "checksums.sha256"]
    if (
        checksums.sha256
        != hashlib.sha256(
            delivery_checksums_text({name: item.sha256 for name, item in members.items()}).encode(
                "utf-8"
            )
        ).hexdigest()
    ):
        raise DeliveryError("inspected checksums changed")
    members["checksums.sha256"] = checksums
    if work.include_zip:
        archive_evidence = evidence[destination / "delivery.zip"]
        with (
            os.fdopen(os.dup(archive_evidence.pinned.descriptor), "rb") as stream,
            zipfile.ZipFile(stream) as archive,
        ):
            if set(validate_zip_infos(archive.infolist())) != set(members):
                raise DeliveryError("inspected ZIP members changed")
            for name, member in members.items():
                check_cancel()
                if archive.getinfo(name).file_size != member.size_bytes:
                    raise DeliveryError("inspected ZIP member size changed")
                digest = hashlib.sha256()
                with archive.open(name) as content:
                    while True:
                        check_cancel()
                        block = content.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                if digest.hexdigest() != member.sha256:
                    raise DeliveryError("inspected ZIP member hash changed")
        members["delivery.zip"] = archive_evidence
    check_cancel()
    validate_pinned_directory_files_no_follow(destination, members, rehash=False)


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
