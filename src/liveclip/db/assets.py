from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import Row, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql import Select

from liveclip.application.assets import AssetReservation, AssetReservationError
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    PipelineRunStatus,
    TaskKind,
    TaskStatus,
)
from liveclip.media.secure_files import (
    SecureFileError,
    directory_identity_no_follow,
    ensure_directory_no_follow,
    open_pinned_regular_file,
    publish_directory_no_replace_no_follow,
    remove_tree_no_follow,
    require_directory_no_follow,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _LeaseScope:
    attempt_id: str
    task_id: str
    task_kind: TaskKind
    target_id: str
    pipeline_run_id: str
    project_id: str
    generation: int
    revision_epoch: int
    expected_revision: int | None
    expected_revision_epoch: int | None


@dataclass(frozen=True, slots=True)
class _WithdrawalScope:
    attempt_id: str
    project_id: str
    attempt_directory_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _PersistedAsset:
    asset_id: str
    project_id: str
    candidate_id: str | None
    producer_attempt_id: str | None
    status: AssetStatus
    kind: str
    relative_path: str
    mime_type: str
    input_fingerprint: str
    sha256: str | None
    size_bytes: int | None
    generation: int | None
    edit_plan_revision: int | None
    revision_epoch: int | None


_AssetValues = tuple[
    str,
    str,
    str | None,
    str | None,
    str,
    str,
    str,
    str,
    str,
    str | None,
    int | None,
    int | None,
    int | None,
    int | None,
]


class SqlAlchemyAssetStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def reserve(
        self,
        lease: LeaseIdentity,
        *,
        project_id: str,
        kind: str,
        relative_path: str,
        mime_type: str,
        input_fingerprint: str,
        generation: int | None = None,
        candidate_id: str | None = None,
        edit_plan_revision: int | None = None,
        revision_epoch: int | None = None,
    ) -> AssetReservation:
        canonical_path = _validate_relative_path(relative_path)
        if not re.fullmatch(r"[a-f0-9]{64}", input_fingerprint):
            raise ValueError("asset input fingerprint must be a lowercase SHA-256")
        if not re.fullmatch(r"[a-z0-9_.-]{1,50}", kind):
            raise ValueError("asset kind is invalid")
        if not mime_type or len(mime_type) > 120:
            raise ValueError("asset MIME type is invalid")
        if candidate_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate_id):
            raise ValueError("asset candidate ID is invalid")
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            scope = _load_lease_scope(connection, lease, now=now)
            _validate_requested_scope(
                connection,
                scope,
                project_id=project_id,
                generation=generation,
                candidate_id=candidate_id,
                edit_plan_revision=edit_plan_revision,
                revision_epoch=revision_epoch,
            )
            existing = _load_asset_by_path(
                connection,
                project_id=scope.project_id,
                relative_path=canonical_path,
            )
            if existing is not None:
                if (
                    existing.kind != kind
                    or existing.mime_type != mime_type
                    or existing.input_fingerprint != input_fingerprint
                    or existing.generation != generation
                    or existing.candidate_id != candidate_id
                    or existing.edit_plan_revision != edit_plan_revision
                    or existing.revision_epoch != revision_epoch
                ):
                    raise AssetReservationError(
                        "immutable asset path is reserved for a different input"
                    )
                if existing.producer_attempt_id is None:
                    raise AssetReservationError("asset has no producer attempt")
                old_attempt = connection.execute(
                    select(TaskAttemptRow.task_id, TaskAttemptRow.outcome).where(
                        TaskAttemptRow.id == existing.producer_attempt_id
                    )
                ).one_or_none()
                if old_attempt is None or str(old_attempt.task_id) != scope.task_id:
                    raise AssetReservationError("asset belongs to a different logical task")
                if (
                    existing.status == AssetStatus.PENDING
                    and existing.producer_attempt_id != scope.attempt_id
                ):
                    if old_attempt.outcome == AttemptOutcome.RUNNING.value:
                        raise AssetReservationError("asset is owned by another active attempt")
                    connection.execute(
                        update(AssetRow)
                        .where(
                            AssetRow.id == existing.asset_id,
                            AssetRow.status == AssetStatus.PENDING.value,
                            AssetRow.producer_attempt_id == existing.producer_attempt_id,
                        )
                        .values(producer_attempt_id=scope.attempt_id)
                    )
                if (
                    existing.status == AssetStatus.COMMITTED
                    and existing.producer_attempt_id != scope.attempt_id
                ):
                    if old_attempt.outcome == AttemptOutcome.RUNNING.value:
                        raise AssetReservationError("asset is owned by another active attempt")
                    adopted = connection.execute(
                        update(AssetRow)
                        .where(
                            AssetRow.id == existing.asset_id,
                            AssetRow.status == AssetStatus.COMMITTED.value,
                            AssetRow.producer_attempt_id == existing.producer_attempt_id,
                        )
                        .values(producer_attempt_id=scope.attempt_id)
                        .returning(AssetRow.id)
                    ).scalar_one_or_none()
                    if adopted is None:
                        raise AssetReservationError(
                            "committed asset reservation lost its retry fence"
                        )
                if existing.status == AssetStatus.INVALID:
                    if (
                        existing.producer_attempt_id != scope.attempt_id
                        and old_attempt.outcome == AttemptOutcome.RUNNING.value
                    ):
                        raise AssetReservationError(
                            "invalid asset is still owned by an active attempt"
                        )
                    changed = connection.execute(
                        update(AssetRow)
                        .where(
                            AssetRow.id == existing.asset_id,
                            AssetRow.status == AssetStatus.INVALID.value,
                            AssetRow.producer_attempt_id == existing.producer_attempt_id,
                        )
                        .values(
                            status=AssetStatus.PENDING.value,
                            producer_attempt_id=scope.attempt_id,
                            sha256=None,
                            size_bytes=None,
                            validation_json=None,
                            committed_at=None,
                        )
                        .returning(AssetRow.id)
                    ).scalar_one_or_none()
                    if changed is None:
                        raise AssetReservationError(
                            "invalid asset reservation lost its retry fence"
                        )
                    return AssetReservation(
                        asset_id=existing.asset_id,
                        status=AssetStatus.PENDING,
                        relative_path=existing.relative_path,
                        sha256=None,
                        size_bytes=None,
                    )
                return _reservation(existing)
            asset_id = new_id()
            connection.execute(
                insert(AssetRow).values(
                    id=asset_id,
                    project_id=scope.project_id,
                    candidate_clip_id=candidate_id,
                    producer_attempt_id=scope.attempt_id,
                    status=AssetStatus.PENDING.value,
                    kind=kind,
                    relative_path=canonical_path,
                    mime_type=mime_type,
                    input_fingerprint=input_fingerprint,
                    generation=generation,
                    edit_plan_revision=edit_plan_revision,
                    revision_epoch=revision_epoch,
                    created_at=now,
                )
            )
            return AssetReservation(
                asset_id=asset_id,
                status=AssetStatus.PENDING,
                relative_path=canonical_path,
                sha256=None,
                size_bytes=None,
            )

    def commit(
        self,
        lease: LeaseIdentity,
        reservation: AssetReservation,
        *,
        project_dir: Path,
        validation: dict[str, object],
        expected_sha256: str | None = None,
    ) -> AssetReservation:
        if expected_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise ValueError("expected asset SHA-256 must be lowercase hexadecimal")
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            scope = _load_lease_scope(connection, lease, now=now)
            current = _load_asset(connection, reservation.asset_id)
            _assert_owned_asset(connection, scope, current, reservation)

        try:
            project_root = require_directory_no_follow(project_dir)
        except SecureFileError as exc:
            raise AssetReservationError("asset project directory is not symlink-free") from exc
        if project_root.name != current.project_id:
            raise AssetReservationError("asset project directory does not match its owner")
        asset_path = project_root / Path(*PurePosixPath(current.relative_path).parts)
        try:
            with open_pinned_regular_file(asset_path) as pinned:
                size_bytes = pinned.metadata.st_size
                if size_bytes <= 0:
                    raise AssetReservationError("reserved asset is empty")
                sha256 = pinned.sha256()
                if expected_sha256 is not None and sha256 != expected_sha256:
                    raise AssetReservationError(
                        "reserved asset bytes differ from the validated artifact"
                    )

                now = datetime.now(UTC)
                with begin_immediate(self._engine) as connection:
                    scope = _load_lease_scope(connection, lease, now=now)
                    current = _load_asset(connection, reservation.asset_id)
                    _assert_owned_asset(connection, scope, current, reservation)
                    if current.status == AssetStatus.COMMITTED:
                        if current.sha256 != sha256 or current.size_bytes != size_bytes:
                            raise AssetReservationError("committed asset bytes changed")
                        result = AssetReservation(
                            asset_id=current.asset_id,
                            status=current.status,
                            relative_path=current.relative_path,
                            sha256=sha256,
                            size_bytes=size_bytes,
                        )
                    else:
                        if current.status != AssetStatus.PENDING:
                            raise AssetReservationError("asset reservation is not publishable")
                        if current.producer_attempt_id != scope.attempt_id:
                            raise AssetReservationError(
                                "asset commit is not owned by the current attempt"
                            )
                        committed = connection.execute(
                            update(AssetRow)
                            .where(
                                AssetRow.id == current.asset_id,
                                AssetRow.status == AssetStatus.PENDING.value,
                                AssetRow.producer_attempt_id == scope.attempt_id,
                            )
                            .values(
                                status=AssetStatus.COMMITTED.value,
                                sha256=sha256,
                                size_bytes=size_bytes,
                                validation_json=validation,
                                committed_at=now,
                            )
                            .returning(AssetRow.id)
                        ).scalar_one_or_none()
                        if committed is None:
                            raise AssetReservationError("asset commit lost its ownership fence")
                        result = AssetReservation(
                            asset_id=current.asset_id,
                            status=AssetStatus.COMMITTED,
                            relative_path=current.relative_path,
                            sha256=sha256,
                            size_bytes=size_bytes,
                        )
                    pinned.validate_binding()
                pinned.validate_binding()
                return result
        except SecureFileError as exc:
            raise AssetReservationError(
                "reserved asset output is missing, symbolic, or unstable"
            ) from exc

    def invalidate_attempt_assets(
        self,
        lease: LeaseIdentity,
        asset_ids: tuple[str, ...],
        *,
        reason: str,
    ) -> None:
        """Demote assets owned by one exact attempt after withdrawing publication."""

        if not asset_ids:
            return
        if not reason or len(reason) > 200:
            raise ValueError("asset invalidation reason is invalid")
        unique_asset_ids = set(asset_ids)
        with begin_immediate(self._engine) as connection:
            attempt_id = connection.scalar(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.worker_id == lease.worker_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                )
            )
            if attempt_id is None:
                raise AssetReservationError("asset invalidation attempt does not exist")
            connection.execute(
                update(AssetRow)
                .where(
                    AssetRow.id.in_(unique_asset_ids),
                    AssetRow.producer_attempt_id == attempt_id,
                    AssetRow.status.in_((AssetStatus.PENDING.value, AssetStatus.COMMITTED.value)),
                )
                .values(
                    status=AssetStatus.INVALID.value,
                    validation_json={"publication_withdrawn": True, "reason": reason},
                )
            )

    def withdraw_attempt_publication(
        self,
        lease: LeaseIdentity,
        asset_ids: tuple[str, ...],
        *,
        project_dir: Path,
        relative_directory: str,
        expected_identity: tuple[int, int],
        reason: str,
    ) -> bool:
        """Move an official package out of view under the exact active lease.

        The O(1) inode-bound rename and Asset invalidation share one SQLite
        writer transaction.  A successor attempt therefore either adopts the
        committed Assets first, or observes the old publication already
        quarantined; an expired producer can never delete its successor's
        official package.
        """

        if not asset_ids or len(set(asset_ids)) != len(asset_ids):
            raise ValueError("publication withdrawal requires distinct assets")
        if not re.fullmatch(r"[a-f0-9]{32}", lease.task_id) or not re.fullmatch(
            r"[a-f0-9]{64}", lease.lease_token
        ):
            raise ValueError("publication withdrawal lease identity is invalid")
        if any(not re.fullmatch(r"[a-f0-9]{32}", asset_id) for asset_id in asset_ids):
            raise ValueError("publication withdrawal asset ID is invalid")
        if not reason or len(reason) > 200:
            raise ValueError("asset invalidation reason is invalid")
        relative = _validate_relative_path(relative_directory)
        if len(expected_identity) != 2 or expected_identity[0] < 0 or expected_identity[1] <= 0:
            raise ValueError("publication directory identity is invalid")
        try:
            root = require_directory_no_follow(project_dir)
        except SecureFileError as exc:
            raise AssetReservationError("asset project directory is not symlink-free") from exc

        source = root / Path(*PurePosixPath(relative).parts)
        moved = False
        quarantine: Path | None = None
        attempt_root: Path | None = None
        try:
            now = datetime.now(UTC)
            with begin_immediate(self._engine) as connection:
                scope = _load_withdrawal_scope(connection, lease, now=now)
                if scope is None:
                    return False
                if root.name != scope.project_id:
                    raise AssetReservationError("asset project directory does not match its owner")
                current_assets = tuple(
                    _persisted_asset(row)
                    for row in connection.execute(
                        _asset_select().where(AssetRow.id.in_(set(asset_ids)))
                    ).all()
                )
                if len(current_assets) != len(asset_ids):
                    raise AssetReservationError("publication assets are incomplete")
                prefix = f"{relative}/"
                if any(
                    asset.project_id != scope.project_id
                    or asset.producer_attempt_id != scope.attempt_id
                    or asset.status not in {AssetStatus.PENDING, AssetStatus.COMMITTED}
                    or not asset.relative_path.startswith(prefix)
                    for asset in current_assets
                ):
                    # A retry may already have adopted the exact publication.
                    # In that case this stale caller owns neither the Assets nor
                    # the right to move the official directory.
                    return False

                attempt_root = require_directory_no_follow(
                    root / ".attempts" / lease.task_id / lease.lease_token
                )
                if directory_identity_no_follow(attempt_root) != scope.attempt_directory_identity:
                    raise AssetReservationError("publication withdrawal attempt directory changed")
                withdrawal_root = ensure_directory_no_follow(attempt_root / "withdrawals")
                quarantine = withdrawal_root / (
                    "package-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()
                )
                publish_directory_no_replace_no_follow(
                    source,
                    quarantine,
                    expected_identity=expected_identity,
                )
                moved = True
                changed = set(
                    connection.execute(
                        update(AssetRow)
                        .where(
                            AssetRow.id.in_(set(asset_ids)),
                            AssetRow.producer_attempt_id == scope.attempt_id,
                            AssetRow.status.in_(
                                (AssetStatus.PENDING.value, AssetStatus.COMMITTED.value)
                            ),
                        )
                        .values(
                            status=AssetStatus.INVALID.value,
                            validation_json={
                                "publication_withdrawn": True,
                                "reason": reason,
                            },
                        )
                        .returning(AssetRow.id)
                    ).scalars()
                )
                if changed != set(asset_ids):
                    raise AssetReservationError("publication withdrawal lost its Asset fence")
        except Exception:
            if moved and quarantine is not None:
                try:
                    publish_directory_no_replace_no_follow(
                        quarantine,
                        source,
                        expected_identity=expected_identity,
                    )
                except SecureFileError as restore_error:
                    raise AssetReservationError(
                        "publication withdrawal could not be rolled back safely"
                    ) from restore_error
            raise

        if quarantine is not None and attempt_root is not None:
            try:
                remove_tree_no_follow(
                    quarantine,
                    required_ancestor=attempt_root,
                    expected_identity=expected_identity,
                )
            except SecureFileError as exc:
                # The official endpoint is already absent and the Assets are
                # INVALID.  Keep the exact inode in the attempt quarantine for
                # the existing janitor instead of restoring a false success.
                logger.warning(
                    "package_withdrawal_cleanup_deferred error_type=%s",
                    type(exc).__name__,
                )
        return True


def _load_withdrawal_scope(
    connection: Connection,
    lease: LeaseIdentity,
    *,
    now: datetime,
) -> _WithdrawalScope | None:
    """Load an unexpired producer without rejecting a requested cancellation."""

    row = connection.execute(
        select(
            TaskAttemptRow.id,
            PipelineRunRow.project_id,
            TaskAttemptRow.temp_identity,
        )
        .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
        .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
        .where(
            TaskRow.id == lease.task_id,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.worker_id == lease.worker_id,
            TaskRow.lease_token == lease.lease_token,
            TaskRow.lease_expires_at > now,
            TaskAttemptRow.lease_token == lease.lease_token,
            TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
        )
    ).one_or_none()
    if row is None:
        return None
    identity = _parse_directory_identity(str(row[2]) if row[2] is not None else None)
    if identity is None:
        raise AssetReservationError("publication withdrawal has no recorded attempt directory")
    return _WithdrawalScope(
        attempt_id=str(row[0]),
        project_id=str(row[1]),
        attempt_directory_identity=identity,
    )


def _parse_directory_identity(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    device, inode = (int(part) for part in parts)
    if device < 0 or inode <= 0:
        return None
    return device, inode


def _load_lease_scope(
    connection: Connection,
    lease: LeaseIdentity,
    *,
    now: datetime,
) -> _LeaseScope:
    row = (
        connection.execute(
            select(
                TaskAttemptRow.id.label("attempt_id"),
                TaskRow.id.label("task_id"),
                TaskRow.kind,
                TaskRow.target_id,
                TaskRow.pipeline_run_id,
                TaskRow.expected_generation,
                TaskRow.expected_revision,
                TaskRow.expected_revision_epoch,
                PipelineRunRow.project_id,
                PipelineRunRow.generation.label("run_generation"),
                PipelineRunRow.status.label("run_status"),
                ProjectRow.current_pipeline_run_id,
                ProjectRow.current_generation,
                ProjectRow.revision_epoch,
            )
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
            .join(ProjectRow, ProjectRow.id == PipelineRunRow.project_id)
            .where(
                TaskRow.id == lease.task_id,
                TaskRow.status == TaskStatus.RUNNING.value,
                TaskRow.worker_id == lease.worker_id,
                TaskRow.lease_token == lease.lease_token,
                TaskRow.lease_expires_at > now,
                TaskRow.cancellation_requested_at.is_(None),
                TaskAttemptRow.lease_token == lease.lease_token,
                TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                PipelineRunRow.cancellation_requested_at.is_(None),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise AssetReservationError("asset operation lost its task lease")
    if row["pipeline_run_id"] is None or row["expected_generation"] is None:
        raise AssetReservationError("asset task is missing its project generation owner")
    run_id = str(row["pipeline_run_id"])
    generation = int(row["expected_generation"])
    task_kind = TaskKind(str(row["kind"]))
    run_status = PipelineRunStatus(str(row["run_status"]))
    allowed_run_statuses = (
        {PipelineRunStatus.RUNNING}
        if task_kind == TaskKind.STAGE
        else {PipelineRunStatus.RUNNING, PipelineRunStatus.COMPLETED}
    )
    if (
        run_status not in allowed_run_statuses
        or str(row["current_pipeline_run_id"]) != run_id
        or int(row["run_generation"]) != generation
        or int(row["current_generation"]) != generation
    ):
        raise AssetReservationError("asset task belongs to an outdated project generation")
    return _LeaseScope(
        attempt_id=str(row["attempt_id"]),
        task_id=str(row["task_id"]),
        task_kind=task_kind,
        target_id=str(row["target_id"]),
        pipeline_run_id=run_id,
        project_id=str(row["project_id"]),
        generation=generation,
        revision_epoch=int(row["revision_epoch"]),
        expected_revision=(
            int(row["expected_revision"]) if row["expected_revision"] is not None else None
        ),
        expected_revision_epoch=(
            int(row["expected_revision_epoch"])
            if row["expected_revision_epoch"] is not None
            else None
        ),
    )


def _validate_requested_scope(
    connection: Connection,
    scope: _LeaseScope,
    *,
    project_id: str,
    generation: int | None,
    candidate_id: str | None,
    edit_plan_revision: int | None,
    revision_epoch: int | None,
) -> None:
    if project_id != scope.project_id:
        raise AssetReservationError("asset project does not match its leased task")
    if generation != scope.generation:
        raise AssetReservationError("asset generation does not match its leased task")
    if scope.expected_revision is not None and edit_plan_revision != scope.expected_revision:
        raise AssetReservationError("asset revision does not match its leased task")
    if scope.expected_revision_epoch is not None:
        if scope.revision_epoch != scope.expected_revision_epoch:
            raise AssetReservationError("asset task revision epoch is no longer current")
        if revision_epoch != scope.expected_revision_epoch:
            raise AssetReservationError("asset revision epoch does not match its leased task")
    elif revision_epoch is not None and revision_epoch != scope.revision_epoch:
        raise AssetReservationError("asset revision epoch is no longer current")
    if candidate_id is None:
        if edit_plan_revision is not None and scope.expected_revision is None:
            raise AssetReservationError("asset revision has no candidate ownership")
        return
    if edit_plan_revision is None or revision_epoch is None:
        raise AssetReservationError("candidate assets require revision and epoch fences")
    if scope.task_kind == TaskKind.RENDER and scope.target_id != candidate_id:
        raise AssetReservationError("render task target does not match the asset candidate")
    revision_id = connection.scalar(
        select(EditPlanRevisionRow.id)
        .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
        .where(
            CandidateClipRow.id == candidate_id,
            CandidateClipRow.project_id == scope.project_id,
            CandidateClipRow.pipeline_run_id == scope.pipeline_run_id,
            CandidateClipRow.current_revision == edit_plan_revision,
            CandidateClipRow.selected_for_review.is_(True),
            EditPlanRevisionRow.revision == edit_plan_revision,
        )
    )
    if revision_id is None:
        raise AssetReservationError("asset candidate revision is not current for its task")


def _assert_owned_asset(
    connection: Connection,
    scope: _LeaseScope,
    asset: _PersistedAsset,
    reservation: AssetReservation,
) -> None:
    if reservation.relative_path != asset.relative_path:
        raise AssetReservationError("asset reservation path differs from its database row")
    _validate_requested_scope(
        connection,
        scope,
        project_id=asset.project_id,
        generation=asset.generation,
        candidate_id=asset.candidate_id,
        edit_plan_revision=asset.edit_plan_revision,
        revision_epoch=asset.revision_epoch,
    )
    if asset.producer_attempt_id is None:
        raise AssetReservationError("asset has no producer attempt")
    if asset.producer_attempt_id != scope.attempt_id:
        raise AssetReservationError("asset is not owned by the current attempt")
    producer_task_id = connection.scalar(
        select(TaskAttemptRow.task_id).where(TaskAttemptRow.id == asset.producer_attempt_id)
    )
    if producer_task_id is None or str(producer_task_id) != scope.task_id:
        raise AssetReservationError("asset belongs to a different logical task")


def _load_asset_by_path(
    connection: Connection,
    *,
    project_id: str,
    relative_path: str,
) -> _PersistedAsset | None:
    row = connection.execute(
        _asset_select().where(
            AssetRow.project_id == project_id,
            AssetRow.relative_path == relative_path,
        )
    ).one_or_none()
    return _persisted_asset(row) if row is not None else None


def _load_asset(connection: Connection, asset_id: str) -> _PersistedAsset:
    row = connection.execute(_asset_select().where(AssetRow.id == asset_id)).one_or_none()
    if row is None:
        raise AssetReservationError("asset reservation does not exist")
    return _persisted_asset(row)


def _asset_select() -> Select[_AssetValues]:
    return select(
        AssetRow.id,
        AssetRow.project_id,
        AssetRow.candidate_clip_id,
        AssetRow.producer_attempt_id,
        AssetRow.status,
        AssetRow.kind,
        AssetRow.relative_path,
        AssetRow.mime_type,
        AssetRow.input_fingerprint,
        AssetRow.sha256,
        AssetRow.size_bytes,
        AssetRow.generation,
        AssetRow.edit_plan_revision,
        AssetRow.revision_epoch,
    )


def _persisted_asset(row: Row[_AssetValues]) -> _PersistedAsset:
    (
        asset_id,
        project_id,
        candidate_id,
        producer_attempt_id,
        status,
        kind,
        relative_path,
        mime_type,
        input_fingerprint,
        sha256,
        size_bytes,
        generation,
        edit_plan_revision,
        revision_epoch,
    ) = row
    return _PersistedAsset(
        asset_id=str(asset_id),
        project_id=str(project_id),
        candidate_id=str(candidate_id) if candidate_id is not None else None,
        producer_attempt_id=(str(producer_attempt_id) if producer_attempt_id is not None else None),
        status=AssetStatus(str(status)),
        kind=str(kind),
        relative_path=str(relative_path),
        mime_type=str(mime_type),
        input_fingerprint=str(input_fingerprint),
        sha256=str(sha256) if sha256 is not None else None,
        size_bytes=int(size_bytes) if size_bytes is not None else None,
        generation=int(generation) if generation is not None else None,
        edit_plan_revision=(int(edit_plan_revision) if edit_plan_revision is not None else None),
        revision_epoch=int(revision_epoch) if revision_epoch is not None else None,
    )


def _reservation(asset: _PersistedAsset) -> AssetReservation:
    return AssetReservation(
        asset_id=asset.asset_id,
        status=asset.status,
        relative_path=asset.relative_path,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
    )


def _validate_relative_path(value: str) -> str:
    if "\\" in value:
        raise ValueError("asset path cannot contain backslashes")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("asset path must be canonical and project-relative")
    canonical = path.as_posix()
    if canonical != value or len(canonical) > 500:
        raise ValueError("asset path must be canonical and bounded")
    return canonical
