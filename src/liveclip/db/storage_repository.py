from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, insert, or_, select
from sqlalchemy.engine import Connection, Engine

from liveclip.application.identity import AdministrationDenied
from liveclip.application.storage import (
    ProjectPurgeCommand,
    ProjectPurgePlan,
    ProjectPurgeResult,
    ProjectStorageUsage,
    StorageCleanupResult,
    StorageConflict,
    StorageReport,
)
from liveclip.application.workspace import WorkspaceUser
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CandidateClipRow,
    ClipCommentRow,
    ClipCommentThreadRow,
    DeliveryRow,
    EditPackageRow,
    EditPlanRevisionRow,
    IdempotencyRecordRow,
    PipelineRunRow,
    ProjectRow,
    ReleaseItemRow,
    ReleaseMetricSnapshotRow,
    ReleasePackageRow,
    RenderJobRow,
    SourceMediaRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.state_transitions import (
    AssetStatus,
    PipelineRunStatus,
    RenderStatus,
    TaskStatus,
)
from liveclip.media.secure_files import (
    SecureFileError,
    cleanup_tree_identity_no_follow,
    directory_identity_no_follow,
    ensure_directory_no_follow,
    interrupted_tree_cleanup_path,
    publish_directory_no_replace_no_follow,
    remove_tree_no_follow,
)
from liveclip.services.database_backup import (
    DatabaseBackupError,
    backup_database,
    default_backup_path,
)
from liveclip.services.janitor import cleanup_terminal_attempt_worktrees


@dataclass(frozen=True, slots=True)
class _StorageTree:
    files: dict[str, int]
    unsafe_entries: dict[str | None, int]
    top_level_directories: frozenset[str]


@dataclass(frozen=True, slots=True)
class _PurgeProject:
    project_id: str
    name: str
    lifecycle: str
    management_version: int
    current_pipeline_run_id: str | None
    source_path: str | None
    source_filename: str | None


@dataclass(frozen=True, slots=True)
class _QuarantinedProjectDirectory:
    original: Path
    quarantined: Path
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _ProjectPurgeSnapshot:
    plan: ProjectPurgePlan
    current_pipeline_run_id: str | None
    directory_identity: tuple[int, int] | None
    directory_tree_fingerprint: str


class SqlAlchemyStorageAdministrationRepository:
    """Read local storage metadata without following filesystem links."""

    def __init__(self, engine: Engine, *, data_dir: Path) -> None:
        self._engine = engine
        self._data_dir = data_dir.resolve(strict=True)

    def report(self, *, actor: WorkspaceUser) -> StorageReport:
        # Filesystem traversal deliberately runs outside a SQLite write lock.
        # Fresh checks on both sides ensure a concurrent demotion either orders
        # after this report or prevents the private workspace-wide result from
        # being returned.
        _require_current_administrator(self._engine, actor.user_id)
        report = _storage_report(self._engine, self._data_dir)
        _require_current_administrator(self._engine, actor.user_id)
        return report

    def cleanup_terminal_attempts(
        self,
        *,
        actor: WorkspaceUser,
        correlation_id: str | None,
    ) -> StorageCleanupResult:
        _require_current_administrator(self._engine, actor.user_id)
        operation_id = new_id()
        _record_cleanup_audit(
            self._engine,
            actor=actor,
            operation_id=operation_id,
            action="storage.safe_cleanup_started",
            details={"scope": "terminal_attempt_worktrees_and_completed_purge_quarantine"},
            correlation_id=correlation_id,
        )
        try:
            cleanup = cleanup_terminal_attempt_worktrees(
                self._engine,
                data_dir=self._data_dir,
                authorize=lambda connection: _require_current_administrator_connection(
                    connection,
                    actor.user_id,
                ),
            )
            purge_cleanup = _cleanup_completed_purge_quarantine(
                self._engine,
                data_dir=self._data_dir,
                authorize=lambda connection: _require_current_administrator_connection(
                    connection,
                    actor.user_id,
                ),
            )
            _require_current_administrator(self._engine, actor.user_id)
            report = self.report(actor=actor)
        except Exception as exc:
            _record_cleanup_audit(
                self._engine,
                actor=actor,
                operation_id=operation_id,
                action="storage.safe_cleanup_interrupted",
                details={
                    "scope": "terminal_attempt_worktrees_and_completed_purge_quarantine",
                    "error_type": type(exc).__name__,
                },
                correlation_id=correlation_id,
            )
            raise
        _record_cleanup_audit(
            self._engine,
            actor=actor,
            operation_id=operation_id,
            action="storage.safe_cleanup_completed",
            details={
                "scope": "terminal_attempt_worktrees_and_completed_purge_quarantine",
                "inspected_attempts": cleanup.inspected,
                "cleaned_attempts": cleanup.cleaned,
                "failed_attempts": cleanup.failed,
                "inspected_purge_quarantines": purge_cleanup[0],
                "cleaned_purge_quarantines": purge_cleanup[1],
                "failed_purge_quarantines": purge_cleanup[2],
            },
            correlation_id=correlation_id,
        )
        return StorageCleanupResult(
            inspected_attempts=cleanup.inspected,
            cleaned_attempts=cleanup.cleaned,
            failed_attempts=cleanup.failed,
            inspected_purge_quarantines=purge_cleanup[0],
            cleaned_purge_quarantines=purge_cleanup[1],
            failed_purge_quarantines=purge_cleanup[2],
            report=report,
        )

    def project_purge_plan(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
    ) -> ProjectPurgePlan:
        _require_current_administrator(self._engine, actor.user_id)
        plan = _project_purge_snapshot(self._engine, self._data_dir, project_id).plan
        _require_current_administrator(self._engine, actor.user_id)
        return plan

    def purge_project(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
        command: ProjectPurgeCommand,
        correlation_id: str | None,
    ) -> ProjectPurgeResult:
        _require_current_administrator(self._engine, actor.user_id)
        snapshot = _project_purge_snapshot(self._engine, self._data_dir, project_id)
        _require_current_administrator(self._engine, actor.user_id)
        plan = snapshot.plan
        _validate_purge_command(actor, plan, command)
        try:
            backup = backup_database(
                self._engine,
                default_backup_path(self._data_dir, label=f"purge-{project_id[:8]}"),
            )
        except (DatabaseBackupError, OSError, SecureFileError) as exc:
            raise StorageConflict("verified database backup is required before purge") from exc

        operation_id = new_id()
        now = datetime.now(UTC)
        _require_current_administrator(self._engine, actor.user_id)
        _record_cleanup_audit(
            self._engine,
            actor=actor,
            operation_id=operation_id,
            action="storage.project_purge_started",
            details={
                "project_id": project_id,
                "project_name": plan.project_name,
                "snapshot_fingerprint": plan.snapshot_fingerprint,
                "generated_bytes": plan.generated_bytes,
                "generated_file_count": plan.generated_file_count,
                "source_media_preserved": True,
                "database_backup_filename": backup.path.name,
                "database_backup_sha256": backup.sha256,
                "quarantine_device": (
                    snapshot.directory_identity[0]
                    if snapshot.directory_identity is not None
                    else None
                ),
                "quarantine_inode": (
                    snapshot.directory_identity[1]
                    if snapshot.directory_identity is not None
                    else None
                ),
            },
            correlation_id=correlation_id,
        )
        try:
            ensure_directory_no_follow(self._data_dir / ".purge-quarantine")
        except SecureFileError as exc:
            raise StorageConflict("project purge quarantine is unsafe") from exc

        quarantined: _QuarantinedProjectDirectory | None = None
        try:
            _require_current_administrator(self._engine, actor.user_id)
            current_snapshot = _project_purge_snapshot(
                self._engine,
                self._data_dir,
                project_id,
            )
            current = current_snapshot.plan
            _validate_purge_command(actor, current, command)
            with begin_immediate(self._engine) as connection:
                _require_current_administrator_connection(connection, actor.user_id)
                _recheck_purge_database_snapshot(
                    connection,
                    current_snapshot,
                    data_dir=self._data_dir,
                )
                if _source_references_inside_project_directory(
                    connection,
                    self._data_dir / ".purge-quarantine" / operation_id,
                ):
                    raise StorageConflict("project purge quarantine is referenced as source media")
                try:
                    quarantined = _quarantine_project_directory(
                        self._data_dir,
                        project_id=project_id,
                        operation_id=operation_id,
                        expected_identity=current_snapshot.directory_identity,
                    )
                except SecureFileError as exc:
                    raise StorageConflict(
                        "project artifact scope changed after purge preview"
                    ) from exc
            if quarantined is not None:
                _verify_quarantined_project_tree(
                    self._data_dir,
                    quarantined,
                    expected_tree_fingerprint=current_snapshot.directory_tree_fingerprint,
                )
            with begin_immediate(self._engine) as connection:
                connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
                _require_current_administrator_connection(connection, actor.user_id)
                _recheck_purge_database_snapshot(
                    connection,
                    current_snapshot,
                    data_dir=self._data_dir,
                )
                if _source_references_inside_project_directory(
                    connection,
                    self._data_dir / ".purge-quarantine" / operation_id,
                ):
                    raise StorageConflict("project purge quarantine is referenced as source media")
                if quarantined is not None:
                    observed_identity = directory_identity_no_follow(quarantined.quarantined)
                    if observed_identity != quarantined.identity:
                        raise StorageConflict("project purge quarantine identity changed")
                task_ids = _project_task_ids(connection, project_id)
                if task_ids:
                    connection.execute(delete(TaskRow).where(TaskRow.id.in_(task_ids)))
                resource_ids = _project_resource_ids(connection, project_id)
                if resource_ids:
                    connection.execute(
                        delete(IdempotencyRecordRow).where(
                            IdempotencyRecordRow.resource_id.in_(resource_ids)
                        )
                    )
                deleted = connection.execute(
                    delete(ProjectRow).where(ProjectRow.id == project_id)
                ).rowcount
                if deleted != 1:
                    raise StorageConflict("project changed before purge could commit")
                connection.execute(
                    insert(AuditEventRow).values(
                        id=new_id(),
                        actor_user_id=actor.user_id,
                        actor_username=actor.username,
                        action="storage.project_purge_completed",
                        target_type="project",
                        target_id=project_id,
                        project_id=project_id,
                        before_json={
                            "name": current.project_name,
                            "lifecycle": current.lifecycle,
                            "management_version": current.management_version,
                        },
                        after_json={
                            "purged": True,
                            "operation_id": operation_id,
                            "quarantine_device": (
                                quarantined.identity[0] if quarantined is not None else None
                            ),
                            "quarantine_inode": (
                                quarantined.identity[1] if quarantined is not None else None
                            ),
                            "source_media_preserved": True,
                            "database_backup_filename": backup.path.name,
                            "database_backup_sha256": backup.sha256,
                        },
                        correlation_id=correlation_id,
                        created_at=now,
                    )
                )
        except Exception as exc:
            if quarantined is not None:
                with suppress(SecureFileError):
                    _restore_quarantined_project_directory(quarantined)
            _record_cleanup_audit(
                self._engine,
                actor=actor,
                operation_id=operation_id,
                action="storage.project_purge_interrupted",
                details={
                    "project_id": project_id,
                    "error_type": type(exc).__name__,
                    "source_media_preserved": True,
                },
                correlation_id=correlation_id,
            )
            raise

        cleanup_pending = False
        if quarantined is not None:
            try:
                remove_tree_no_follow(
                    quarantined.quarantined,
                    required_ancestor=self._data_dir / ".purge-quarantine",
                    expected_identity=quarantined.identity,
                )
            except SecureFileError:
                cleanup_pending = True
                _record_cleanup_audit(
                    self._engine,
                    actor=actor,
                    operation_id=operation_id,
                    action="storage.project_purge_cleanup_pending",
                    details={"project_id": project_id},
                    correlation_id=correlation_id,
                )
        return ProjectPurgeResult(
            project_id=project_id,
            project_name=plan.project_name,
            purged_at=now,
            removed_generated_bytes=plan.generated_bytes,
            removed_generated_file_count=plan.generated_file_count,
            database_backup_filename=backup.path.name,
            database_backup_sha256=backup.sha256,
            filesystem_cleanup_pending=cleanup_pending,
        )


def _project_purge_snapshot(
    engine: Engine,
    data_dir: Path,
    project_id: str,
) -> _ProjectPurgeSnapshot:
    with engine.connect() as connection:
        project = _load_purge_project(connection, project_id)
        active_run_count = len(_active_project_run_ids(connection, project_id))
        active_task_count = len(_active_project_task_ids(connection, project_id))
        source_references_inside = _source_references_inside_project_directory(
            connection,
            data_dir / project_id,
        )
    project_dir = data_dir / project_id
    generated_files: tuple[tuple[str, int], ...] = ()
    unsafe_entry_count = 0
    directory_identity: tuple[int, int] | None = None
    if project_dir.exists() or project_dir.is_symlink():
        try:
            directory_identity = directory_identity_no_follow(project_dir)
            tree = _scan_tree_no_follow(
                project_dir,
                expected_filesystem=_directory_filesystem_identity_no_follow(data_dir),
            )
        except SecureFileError as exc:
            raise StorageConflict("project artifact directory is unsafe") from exc
        generated_files = tuple(sorted(tree.files.items()))
        unsafe_entry_count = sum(tree.unsafe_entries.values())

    blockers: list[str] = []
    if project.lifecycle != ProjectLifecycle.ARCHIVED.value:
        blockers.append("project_must_be_archived")
    if active_run_count or active_task_count:
        blockers.append("active_work_must_finish")
    if source_references_inside:
        blockers.append("source_reference_inside_generated_project_directory")
    if unsafe_entry_count:
        blockers.append("unsafe_generated_entries_must_be_removed")
    payload = {
        "schema_version": "liveclip.project-purge-plan.v1",
        "project_id": project.project_id,
        "project_name": project.name,
        "lifecycle": project.lifecycle,
        "management_version": project.management_version,
        "current_pipeline_run_id": project.current_pipeline_run_id,
        "source_path": project.source_path,
        "directory_identity": directory_identity,
        "generated_files": generated_files,
        "unsafe_entry_count": unsafe_entry_count,
        "active_run_count": active_run_count,
        "active_task_count": active_task_count,
        "source_references_inside": source_references_inside,
        "blockers": blockers,
    }
    tree_fingerprint = _tree_fingerprint(generated_files, unsafe_entry_count)
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return _ProjectPurgeSnapshot(
        plan=ProjectPurgePlan(
            project_id=project.project_id,
            project_name=project.name,
            lifecycle=project.lifecycle,
            management_version=project.management_version,
            generated_bytes=sum(size for _, size in generated_files),
            generated_file_count=len(generated_files),
            unsafe_entry_count=unsafe_entry_count,
            source_filename=project.source_filename,
            active_run_count=active_run_count,
            active_task_count=active_task_count,
            blockers=tuple(blockers),
            ready=not blockers,
            snapshot_fingerprint=fingerprint,
            confirmation_phrase=f"PURGE {project.project_id}",
        ),
        current_pipeline_run_id=project.current_pipeline_run_id,
        directory_identity=directory_identity,
        directory_tree_fingerprint=tree_fingerprint,
    )


def _validate_purge_command(
    actor: WorkspaceUser,
    plan: ProjectPurgePlan,
    command: ProjectPurgeCommand,
) -> None:
    if not plan.ready:
        raise StorageConflict("project purge is blocked by current project state")
    if command.snapshot_fingerprint != plan.snapshot_fingerprint:
        raise StorageConflict("project purge preview is stale; scan it again")
    if command.project_name != plan.project_name:
        raise StorageConflict("project name confirmation does not match")
    if command.administrator_username != actor.username:
        raise StorageConflict("administrator confirmation does not match the current session")
    if command.confirmation_phrase != plan.confirmation_phrase:
        raise StorageConflict("project purge confirmation phrase does not match")


def _load_purge_project(connection: Connection, project_id: str) -> _PurgeProject:
    row = connection.execute(
        select(
            ProjectRow.id,
            ProjectRow.name,
            ProjectRow.lifecycle,
            ProjectRow.management_version,
            ProjectRow.current_pipeline_run_id,
            SourceMediaRow.resolved_path,
            SourceMediaRow.filename,
        )
        .outerjoin(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .where(ProjectRow.id == project_id)
    ).one_or_none()
    if row is None:
        raise LookupError("project does not exist")
    return _PurgeProject(
        project_id=str(row.id),
        name=str(row.name),
        lifecycle=str(row.lifecycle),
        management_version=int(row.management_version),
        current_pipeline_run_id=(
            str(row.current_pipeline_run_id) if row.current_pipeline_run_id is not None else None
        ),
        source_path=str(row.resolved_path) if row.resolved_path is not None else None,
        source_filename=str(row.filename) if row.filename is not None else None,
    )


def _recheck_purge_database_snapshot(
    connection: Connection,
    snapshot: _ProjectPurgeSnapshot,
    *,
    data_dir: Path,
) -> None:
    plan = snapshot.plan
    project = _load_purge_project(connection, plan.project_id)
    if (
        project.name != plan.project_name
        or project.lifecycle != ProjectLifecycle.ARCHIVED.value
        or project.management_version != plan.management_version
        or project.current_pipeline_run_id != snapshot.current_pipeline_run_id
        or _active_project_run_ids(connection, plan.project_id)
        or _active_project_task_ids(connection, plan.project_id)
        or _source_references_inside_project_directory(
            connection,
            data_dir / plan.project_id,
        )
    ):
        raise StorageConflict("project changed before purge could commit")


def _active_project_run_ids(connection: Connection, project_id: str) -> set[str]:
    return {
        str(run_id)
        for run_id in connection.scalars(
            select(PipelineRunRow.id).where(
                PipelineRunRow.project_id == project_id,
                PipelineRunRow.status.in_(
                    (PipelineRunStatus.QUEUED.value, PipelineRunStatus.RUNNING.value)
                ),
            )
        )
    }


def _active_project_task_ids(connection: Connection, project_id: str) -> set[str]:
    task_ids = _project_task_ids(connection, project_id)
    if not task_ids:
        return set()
    return {
        str(task_id)
        for task_id in connection.scalars(
            select(TaskRow.id).where(
                TaskRow.id.in_(task_ids),
                TaskRow.status.in_((TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)),
            )
        )
    }


def _project_task_ids(connection: Connection, project_id: str) -> set[str]:
    run_ids = select(PipelineRunRow.id).where(PipelineRunRow.project_id == project_id)
    render_task_ids = (
        select(RenderJobRow.task_id)
        .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
        .where(CandidateClipRow.project_id == project_id, RenderJobRow.task_id.is_not(None))
    )
    delivery_task_ids = select(DeliveryRow.task_id).where(
        DeliveryRow.project_id == project_id,
        DeliveryRow.task_id.is_not(None),
    )
    edit_package_task_ids = select(EditPackageRow.task_id).where(
        EditPackageRow.project_id == project_id,
        EditPackageRow.task_id.is_not(None),
    )
    release_package_task_ids = select(ReleasePackageRow.task_id).where(
        ReleasePackageRow.project_id == project_id,
        ReleasePackageRow.task_id.is_not(None),
    )
    return {
        str(task_id)
        for task_id in connection.scalars(
            select(TaskRow.id).where(
                or_(
                    TaskRow.pipeline_run_id.in_(run_ids),
                    TaskRow.id.in_(render_task_ids),
                    TaskRow.id.in_(delivery_task_ids),
                    TaskRow.id.in_(edit_package_task_ids),
                    TaskRow.id.in_(release_package_task_ids),
                )
            )
        )
    }


def _project_resource_ids(connection: Connection, project_id: str) -> set[str]:
    resource_ids = {project_id}
    queries = (
        select(PipelineRunRow.id).where(PipelineRunRow.project_id == project_id),
        select(CandidateClipRow.id).where(CandidateClipRow.project_id == project_id),
        select(ClipCommentThreadRow.id)
        .join(
            EditPlanRevisionRow,
            EditPlanRevisionRow.id == ClipCommentThreadRow.edit_plan_revision_id,
        )
        .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
        .where(CandidateClipRow.project_id == project_id),
        select(ClipCommentRow.id)
        .join(ClipCommentThreadRow, ClipCommentThreadRow.id == ClipCommentRow.thread_id)
        .join(
            EditPlanRevisionRow,
            EditPlanRevisionRow.id == ClipCommentThreadRow.edit_plan_revision_id,
        )
        .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
        .where(CandidateClipRow.project_id == project_id),
        select(RenderJobRow.id)
        .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
        .where(CandidateClipRow.project_id == project_id),
        select(DeliveryRow.id).where(DeliveryRow.project_id == project_id),
        select(EditPackageRow.id).where(EditPackageRow.project_id == project_id),
        select(ReleasePackageRow.id).where(ReleasePackageRow.project_id == project_id),
        select(ReleaseItemRow.id).where(ReleaseItemRow.project_id == project_id),
        select(ReleaseMetricSnapshotRow.id)
        .join(ReleaseItemRow, ReleaseItemRow.id == ReleaseMetricSnapshotRow.release_item_id)
        .where(ReleaseItemRow.project_id == project_id),
    )
    for query in queries:
        values = connection.scalars(query)
        resource_ids.update(str(value) for value in values)
    return resource_ids


def _quarantine_project_directory(
    data_dir: Path,
    *,
    project_id: str,
    operation_id: str,
    expected_identity: tuple[int, int] | None,
) -> _QuarantinedProjectDirectory | None:
    project_dir = data_dir / project_id
    try:
        identity = directory_identity_no_follow(project_dir)
    except SecureFileError as exc:
        if not project_dir.exists() and not project_dir.is_symlink():
            if expected_identity is not None:
                raise SecureFileError("project directory disappeared after purge preview") from exc
            return None
        raise
    if expected_identity is None or identity != expected_identity:
        raise SecureFileError("project directory changed after purge preview")
    quarantine_root = data_dir / ".purge-quarantine"
    destination = quarantine_root / operation_id
    try:
        publish_directory_no_replace_no_follow(
            project_dir,
            destination,
            expected_identity=identity,
        )
        if directory_identity_no_follow(destination) != identity:
            raise SecureFileError("quarantined project directory identity changed")
    except (OSError, SecureFileError) as exc:
        raise SecureFileError("project directory could not be quarantined safely") from exc
    return _QuarantinedProjectDirectory(
        original=project_dir,
        quarantined=destination,
        identity=identity,
    )


def _verify_quarantined_project_tree(
    data_dir: Path,
    quarantined: _QuarantinedProjectDirectory,
    *,
    expected_tree_fingerprint: str,
) -> None:
    try:
        if directory_identity_no_follow(quarantined.quarantined) != quarantined.identity:
            raise SecureFileError("quarantined project directory identity changed")
        tree = _scan_tree_no_follow(
            quarantined.quarantined,
            expected_filesystem=_directory_filesystem_identity_no_follow(data_dir),
        )
    except SecureFileError as exc:
        raise StorageConflict("project quarantine could not be verified safely") from exc
    observed = _tree_fingerprint(
        tuple(sorted(tree.files.items())),
        sum(tree.unsafe_entries.values()),
    )
    if observed != expected_tree_fingerprint:
        raise StorageConflict("project artifact scope changed after purge preview")


def _restore_quarantined_project_directory(
    quarantined: _QuarantinedProjectDirectory,
) -> None:
    try:
        publish_directory_no_replace_no_follow(
            quarantined.quarantined,
            quarantined.original,
            expected_identity=quarantined.identity,
        )
    except (OSError, SecureFileError) as exc:
        raise SecureFileError("project directory quarantine could not be rolled back") from exc


def _source_is_inside_project_directory(source: Path, project_dir: Path) -> bool:
    try:
        source_real = source.expanduser().resolve(strict=False)
        project_real = project_dir.resolve(strict=False)
        source_real.relative_to(project_real)
    except ValueError:
        return False
    except (OSError, RuntimeError):
        return True
    return True


def _source_references_inside_project_directory(
    connection: Connection,
    project_dir: Path,
) -> tuple[str, ...]:
    """Return every project/source field whose local path falls in generated scope."""

    references: set[str] = set()
    rows = connection.execute(
        select(
            ProjectRow.id,
            ProjectRow.source_request_path,
            SourceMediaRow.resolved_path,
        ).outerjoin(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
    )
    for row in rows:
        project_id = str(row.id)
        if row.source_request_path is not None and _source_is_inside_project_directory(
            Path(str(row.source_request_path)),
            project_dir,
        ):
            references.add(f"{project_id}:source_request_path")
        if row.resolved_path is not None and _source_is_inside_project_directory(
            Path(str(row.resolved_path)),
            project_dir,
        ):
            references.add(f"{project_id}:source_media")
    return tuple(sorted(references))


def _tree_fingerprint(files: tuple[tuple[str, int], ...], unsafe_entry_count: int) -> str:
    payload = {
        "files": files,
        "unsafe_entry_count": unsafe_entry_count,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _open_directory_fd(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise SecureFileError("storage directory is unsafe") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise SecureFileError("storage endpoint is not a directory")
    return descriptor


def _cleanup_completed_purge_quarantine(
    engine: Engine,
    *,
    data_dir: Path,
    authorize: Callable[[Connection], None],
) -> tuple[int, int, int]:
    with engine.connect() as connection:
        authorize(connection)
        values = connection.scalars(
            select(AuditEventRow.after_json).where(
                AuditEventRow.action == "storage.project_purge_completed"
            )
        ).all()
    completed_identities: dict[str, tuple[int, int]] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        operation_id = value.get("operation_id")
        device = value.get("quarantine_device")
        inode = value.get("quarantine_inode")
        if (
            isinstance(operation_id, str)
            and len(operation_id) == 32
            and all(character in "0123456789abcdef" for character in operation_id)
            and isinstance(device, int)
            and not isinstance(device, bool)
            and device >= 0
            and isinstance(inode, int)
            and not isinstance(inode, bool)
            and inode > 0
        ):
            completed_identities[operation_id] = (device, inode)
    quarantine_root = data_dir / ".purge-quarantine"
    if not quarantine_root.exists() and not quarantine_root.is_symlink():
        return (0, 0, 0)
    root_fd = _open_directory_fd(quarantine_root)
    inspected = 0
    cleaned = 0
    failed = 0
    os.close(root_fd)
    for operation_id, expected_identity in completed_identities.items():
        target = quarantine_root / operation_id
        try:
            observed_identity = cleanup_tree_identity_no_follow(target)
        except SecureFileError:
            inspected += 1
            failed += 1
            continue
        if observed_identity is None:
            continue
        inspected += 1
        try:
            with begin_immediate(engine) as connection:
                authorize(connection)
                identity = cleanup_tree_identity_no_follow(target)
                if identity is None:
                    continue
                if identity != expected_identity:
                    raise SecureFileError("purge quarantine identity differs from audit evidence")
                if any(
                    _source_is_inside_project_directory(source, cleanup_target)
                    for source in _all_source_paths(connection)
                    for cleanup_target in (
                        target,
                        interrupted_tree_cleanup_path(target),
                    )
                ):
                    raise SecureFileError("purge quarantine is referenced as source media")
            changed = remove_tree_no_follow(
                target,
                required_ancestor=quarantine_root,
                expected_identity=identity,
            )
        except SecureFileError:
            failed += 1
        else:
            cleaned += int(changed)
    return inspected, cleaned, failed


def _all_source_paths(connection: Connection) -> tuple[Path, ...]:
    rows = connection.execute(
        select(
            ProjectRow.source_request_path,
            SourceMediaRow.resolved_path,
        ).outerjoin(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
    ).all()
    return tuple(
        Path(str(value))
        for row in rows
        for value in (row.source_request_path, row.resolved_path)
        if value is not None
    )


def recover_interrupted_project_purges(
    engine: Engine,
    *,
    data_dir: Path,
) -> tuple[int, int, int]:
    """Restore exact pre-commit purge quarantines left by process termination."""

    with engine.connect() as connection:
        started = connection.execute(
            select(
                AuditEventRow.target_id,
                AuditEventRow.actor_user_id,
                AuditEventRow.actor_username,
                AuditEventRow.after_json,
            ).where(AuditEventRow.action == "storage.project_purge_started")
        ).all()
        completed_values = connection.scalars(
            select(AuditEventRow.after_json).where(
                AuditEventRow.action == "storage.project_purge_completed"
            )
        ).all()
    completed_operation_ids = {
        str(value["operation_id"])
        for value in completed_values
        if isinstance(value, dict) and isinstance(value.get("operation_id"), str)
    }
    inspected = 0
    recovered = 0
    failed = 0
    for row in started:
        operation_id = str(row.target_id) if row.target_id is not None else ""
        details = row.after_json
        if operation_id in completed_operation_ids or not isinstance(details, dict):
            continue
        project_id = details.get("project_id")
        device = details.get("quarantine_device")
        inode = details.get("quarantine_inode")
        if (
            not _valid_storage_identifier(operation_id)
            or not isinstance(project_id, str)
            or not _valid_storage_identifier(project_id)
            or not isinstance(device, int)
            or isinstance(device, bool)
            or device < 0
            or not isinstance(inode, int)
            or isinstance(inode, bool)
            or inode <= 0
        ):
            continue
        target = data_dir / ".purge-quarantine" / operation_id
        if not target.exists() and not target.is_symlink():
            continue
        inspected += 1
        try:
            with begin_immediate(engine) as connection:
                project_exists = connection.scalar(
                    select(ProjectRow.id).where(ProjectRow.id == project_id)
                )
                if project_exists is None:
                    raise SecureFileError(
                        "interrupted purge has no project row and cannot be restored automatically"
                    )
                quarantined = _QuarantinedProjectDirectory(
                    original=data_dir / project_id,
                    quarantined=target,
                    identity=(device, inode),
                )
                _restore_quarantined_project_directory(quarantined)
                connection.execute(
                    insert(AuditEventRow).values(
                        id=new_id(),
                        actor_user_id=row.actor_user_id,
                        actor_username=row.actor_username,
                        action="storage.project_purge_recovered",
                        target_type="project",
                        target_id=project_id,
                        project_id=project_id,
                        before_json={"operation_id": operation_id},
                        after_json={"restored": True},
                        correlation_id=None,
                        created_at=datetime.now(UTC),
                    )
                )
        except (OSError, SecureFileError):
            failed += 1
        else:
            recovered += 1
    return inspected, recovered, failed


def _valid_storage_identifier(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdef" for character in value)


def _storage_report(engine: Engine, data_dir: Path) -> StorageReport:
    scanned_at = datetime.now(UTC)
    tree = _scan_tree_no_follow(data_dir)
    with engine.connect() as connection:
        projects = connection.execute(
            select(ProjectRow.id, ProjectRow.name, ProjectRow.lifecycle).order_by(
                ProjectRow.created_at,
                ProjectRow.id,
            )
        ).all()
        sources = connection.execute(
            select(SourceMediaRow.project_id, SourceMediaRow.size_bytes)
        ).all()
        assets = connection.execute(
            select(
                AssetRow.id,
                AssetRow.project_id,
                AssetRow.status,
                AssetRow.relative_path,
            )
        ).all()
        stale_renders = connection.execute(
            select(
                CandidateClipRow.project_id,
                RenderJobRow.asset_id,
                RenderJobRow.subtitle_asset_id,
                RenderJobRow.quality_report_asset_id,
                RenderJobRow.contact_sheet_asset_id,
            )
            .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
            .where(RenderJobRow.status == RenderStatus.STALE.value)
        ).all()

    source_bytes: dict[str, int] = defaultdict(int)
    for source in sources:
        source_bytes[str(source.project_id)] += int(source.size_bytes)

    stale_asset_ids: set[str] = set()
    for render in stale_renders:
        stale_asset_ids.update(
            str(asset_id)
            for asset_id in (
                render.asset_id,
                render.subtitle_asset_id,
                render.quality_report_asset_id,
                render.contact_sheet_asset_id,
            )
            if asset_id is not None
        )

    assets_by_project: dict[str, list[Any]] = defaultdict(list)
    for asset in assets:
        assets_by_project[str(asset.project_id)].append(asset)

    usage: list[ProjectStorageUsage] = []
    for project in projects:
        project_id = str(project.id)
        actual = {
            path: size for path, size in tree.files.items() if _belongs_to_project(path, project_id)
        }
        registered_paths: set[str] = set()
        tracked_bytes = 0
        stale_bytes = 0
        orphan_bytes = 0
        pending_bytes = 0
        missing_committed = 0
        for asset in assets_by_project.get(project_id, []):
            key = _asset_storage_key(project_id, str(asset.relative_path))
            if key is None:
                if asset.status == AssetStatus.COMMITTED.value:
                    missing_committed += 1
                continue
            registered_paths.add(key)
            observed_size = actual.get(key)
            if observed_size is None:
                if asset.status == AssetStatus.COMMITTED.value:
                    missing_committed += 1
                continue
            tracked_bytes += observed_size
            if str(asset.id) in stale_asset_ids:
                stale_bytes += observed_size
            if asset.status == AssetStatus.ORPHANED.value:
                orphan_bytes += observed_size
            elif asset.status == AssetStatus.PENDING.value:
                pending_bytes += observed_size
        untracked = {path: size for path, size in actual.items() if path not in registered_paths}
        usage.append(
            ProjectStorageUsage(
                project_id=project_id,
                project_name=str(project.name),
                lifecycle=str(project.lifecycle),
                actual_bytes=sum(actual.values()),
                actual_file_count=len(actual),
                tracked_asset_bytes=tracked_bytes,
                stale_render_asset_bytes=stale_bytes,
                orphan_asset_bytes=orphan_bytes,
                pending_asset_bytes=pending_bytes,
                untracked_bytes=sum(untracked.values()),
                untracked_file_count=len(untracked),
                missing_committed_asset_count=missing_committed,
                unsafe_entry_count=tree.unsafe_entries.get(project_id, 0),
                source_reference_bytes=source_bytes.get(project_id, 0),
            )
        )

    database_bytes = sum(
        size
        for path, size in tree.files.items()
        if path in {"liveclip.sqlite3", "liveclip.sqlite3-wal", "liveclip.sqlite3-shm"}
    )
    migration_backup_bytes = sum(
        size
        for path, size in tree.files.items()
        if PurePosixPath(path).parts[:1] == ("migration-backups",)
    )
    database_backup_bytes = sum(
        size
        for path, size in tree.files.items()
        if PurePosixPath(path).parts[:1] == ("database-backups",)
    )
    purge_quarantine_files = {
        path: size
        for path, size in tree.files.items()
        if PurePosixPath(path).parts[:1] == (".purge-quarantine",)
    }
    purge_quarantine_bytes = sum(purge_quarantine_files.values())
    project_directory_bytes = sum(item.actual_bytes for item in usage)
    project_ids = {str(project.id) for project in projects}
    reserved_directories = {
        "migration-backups",
        "database-backups",
        ".purge-quarantine",
        ".attempt-cleanup-quarantine",
    }
    unknown_directories = tree.top_level_directories - project_ids - reserved_directories
    unknown_project_files = {
        path: size
        for path, size in tree.files.items()
        if PurePosixPath(path).parts[:1] and PurePosixPath(path).parts[0] in unknown_directories
    }
    unknown_project_directory_bytes = sum(unknown_project_files.values())
    data_directory_bytes = sum(tree.files.values())
    other_bytes = max(
        0,
        data_directory_bytes
        - database_bytes
        - migration_backup_bytes
        - database_backup_bytes
        - purge_quarantine_bytes
        - project_directory_bytes
        - unknown_project_directory_bytes,
    )
    disk = shutil.disk_usage(data_dir)
    return StorageReport(
        scanned_at=scanned_at,
        filesystem_capacity_bytes=disk.total,
        filesystem_free_bytes=disk.free,
        data_directory_bytes=data_directory_bytes,
        database_bytes=database_bytes,
        migration_backup_bytes=migration_backup_bytes,
        database_backup_bytes=database_backup_bytes,
        purge_quarantine_bytes=purge_quarantine_bytes,
        purge_quarantine_file_count=len(purge_quarantine_files),
        project_directory_bytes=project_directory_bytes,
        unknown_project_directory_bytes=unknown_project_directory_bytes,
        unknown_project_file_count=len(unknown_project_files),
        other_bytes=other_bytes,
        unsafe_entry_count=sum(tree.unsafe_entries.values()),
        projects=tuple(usage),
    )


def _scan_tree_no_follow(
    root: Path,
    *,
    expected_filesystem: tuple[int, int | None] | None = None,
) -> _StorageTree:
    files: dict[str, int] = {}
    unsafe_entries: dict[str | None, int] = defaultdict(int)
    top_level_directories: set[str] = set()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(root, flags)
    try:
        root_metadata = os.fstat(root_fd)
        root_filesystem = _directory_filesystem_identity(root_fd, root_metadata)
    except OSError as exc:
        os.close(root_fd)
        raise SecureFileError("storage filesystem identity could not be inspected") from exc
    if expected_filesystem is not None and root_filesystem != expected_filesystem:
        os.close(root_fd)
        return _StorageTree(
            files={},
            unsafe_entries={None: 1},
            top_level_directories=frozenset(),
        )
    visited: set[tuple[int, int]] = {(root_metadata.st_dev, root_metadata.st_ino)}

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        try:
            with os.scandir(directory_fd) as entries:
                values = tuple(entries)
        except OSError:
            unsafe_entries[prefix[0] if prefix else None] += 1
            return
        for entry in values:
            top_level = prefix[0] if prefix else entry.name
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                unsafe_entries[top_level] += 1
                continue
            parts = (*prefix, entry.name)
            if stat.S_ISREG(metadata.st_mode):
                files[PurePosixPath(*parts).as_posix()] = int(metadata.st_size)
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                unsafe_entries[top_level] += 1
                continue
            if metadata.st_dev != root_filesystem[0]:
                unsafe_entries[top_level] += 1
                continue
            if not prefix:
                top_level_directories.add(entry.name)
            try:
                child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                current = os.fstat(child_fd)
            except OSError:
                unsafe_entries[top_level] += 1
                continue
            try:
                if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                    unsafe_entries[top_level] += 1
                    continue
                if _directory_filesystem_identity(child_fd, current) != root_filesystem:
                    unsafe_entries[top_level] += 1
                    continue
                identity = (current.st_dev, current.st_ino)
                if identity in visited:
                    unsafe_entries[top_level] += 1
                    continue
                visited.add(identity)
                walk(child_fd, parts)
            finally:
                os.close(child_fd)

    try:
        walk(root_fd, ())
    finally:
        os.close(root_fd)
    return _StorageTree(
        files=files,
        unsafe_entries=dict(unsafe_entries),
        top_level_directories=frozenset(top_level_directories),
    )


def _directory_filesystem_identity(
    descriptor: int,
    metadata: os.stat_result,
) -> tuple[int, int | None]:
    filesystem = os.fstatvfs(descriptor)
    fsid = getattr(filesystem, "f_fsid", None)
    return metadata.st_dev, int(fsid) if fsid is not None else None


def _directory_filesystem_identity_no_follow(path: Path) -> tuple[int, int | None]:
    descriptor = _open_directory_fd(path)
    try:
        return _directory_filesystem_identity(descriptor, os.fstat(descriptor))
    except OSError as exc:
        raise SecureFileError("storage filesystem identity could not be inspected") from exc
    finally:
        os.close(descriptor)


def _belongs_to_project(path: str, project_id: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) >= 2 and parts[0] == project_id


def _asset_storage_key(project_id: str, relative_path: str) -> str | None:
    if "\\" in relative_path:
        return None
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None
    return PurePosixPath(project_id, *relative.parts).as_posix()


def _require_current_administrator(engine: Engine, user_id: str) -> None:
    with engine.connect() as connection:
        current = connection.execute(
            select(WorkspaceUserRow.is_active, WorkspaceUserRow.system_role).where(
                WorkspaceUserRow.id == user_id
            )
        ).one_or_none()
    if current is None or not current.is_active or current.system_role != "administrator":
        raise AdministrationDenied("system administrator permission is required")


def _require_current_administrator_connection(connection: Connection, user_id: str) -> None:
    current = connection.execute(
        select(WorkspaceUserRow.is_active, WorkspaceUserRow.system_role).where(
            WorkspaceUserRow.id == user_id
        )
    ).one_or_none()
    if current is None or not current.is_active or current.system_role != "administrator":
        raise AdministrationDenied("system administrator permission is required")


def _record_cleanup_audit(
    engine: Engine,
    *,
    actor: WorkspaceUser,
    operation_id: str,
    action: str,
    details: dict[str, object],
    correlation_id: str | None,
) -> None:
    with begin_immediate(engine) as connection:
        connection.execute(
            insert(AuditEventRow).values(
                id=new_id(),
                actor_user_id=actor.user_id,
                actor_username=actor.username,
                action=action,
                target_type="storage_cleanup",
                target_id=operation_id,
                project_id=None,
                before_json=None,
                after_json=details,
                correlation_id=correlation_id,
                created_at=datetime.now(UTC),
            )
        )


__all__ = [
    "SqlAlchemyStorageAdministrationRepository",
    "recover_interrupted_project_purges",
]
