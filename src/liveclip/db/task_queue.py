from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import exists, func, insert, or_, select, true, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from liveclip.application.tasks import (
    HeartbeatResult,
    TaskLease,
    TaskQueueTransientError,
    validate_task_diagnostic_relative_path,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    DeliveryRow,
    EditPackageRow,
    PipelineRunRow,
    ReleasePackageRow,
    RenderJobRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.releases import ReleasePackageStatus, transition_release_package
from liveclip.domain.state_transitions import (
    AttemptOutcome,
    DeliveryStatus,
    EditPackageStatus,
    FailureClass,
    PipelineRunStatus,
    RenderStatus,
    ResourceClass,
    StageRunStatus,
    TaskKind,
    TaskStatus,
    transition_delivery,
    transition_edit_package,
    transition_render,
)


class TaskQueueError(RuntimeError):
    pass


class TaskQueueBusy(TaskQueueError, TaskQueueTransientError):
    pass


class TaskOperationConflict(TaskQueueError):
    pass


class CompletionResult(StrEnum):
    COMPLETED = "completed"
    ALREADY_SUCCEEDED = "already_succeeded"
    CANCELLATION_REQUESTED = "cancellation_requested"
    LOST_LEASE = "lost_lease"


@dataclass(frozen=True, slots=True)
class TaskSpec:
    kind: TaskKind
    target_id: str
    operation_key: str
    input_fingerprint: str
    pipeline_run_id: str | None = None
    stage_run_id: str | None = None
    depends_on_task_id: str | None = None
    resource_class: ResourceClass = ResourceClass.HEAVY
    priority: int = 100
    not_before: datetime | None = None
    max_retries: int = 3
    expected_generation: int | None = None
    expected_revision: int | None = None
    expected_revision_epoch: int | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.target_id, "target ID")
        if not 1 <= len(self.operation_key) <= 160:
            raise ValueError("operation key must contain 1-160 characters")
        if not re.fullmatch(r"[a-f0-9]{64}", self.input_fingerprint):
            raise ValueError("input fingerprint must be a lowercase SHA-256")
        if self.kind == TaskKind.STAGE and self.stage_run_id != self.target_id:
            raise ValueError("stage task target must be its StageRun ID")
        if self.priority < 0 or self.max_retries < 0:
            raise ValueError("priority and max retries must be nonnegative")
        if self.not_before is not None:
            _require_aware(self.not_before)


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    task_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    requeued: int = 0
    failed: int = 0
    cancelled: int = 0


class SQLiteTaskQueue:
    def __init__(self, engine: Engine, *, lease_seconds: int) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("task queue requires a SQLAlchemy Engine")
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("lease duration must be a positive integer")
        self._engine = engine
        self._lease_seconds = lease_seconds

    def enqueue(self, spec: TaskSpec, *, now: datetime | None = None) -> EnqueueResult:
        instant = _now(now)
        try:
            with begin_immediate(self._engine) as connection:
                existing = (
                    connection.execute(
                        select(
                            TaskRow.id,
                            TaskRow.kind,
                            TaskRow.target_id,
                            TaskRow.input_fingerprint,
                            TaskRow.pipeline_run_id,
                            TaskRow.stage_run_id,
                            TaskRow.depends_on_task_id,
                            TaskRow.resource_class,
                            TaskRow.priority,
                            TaskRow.max_retries,
                            TaskRow.expected_generation,
                            TaskRow.expected_revision,
                            TaskRow.expected_revision_epoch,
                        ).where(TaskRow.operation_key == spec.operation_key)
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    expected = (
                        spec.kind.value,
                        spec.target_id,
                        spec.input_fingerprint,
                        spec.pipeline_run_id,
                        spec.stage_run_id,
                        spec.depends_on_task_id,
                        spec.resource_class.value,
                        spec.priority,
                        spec.max_retries,
                        spec.expected_generation,
                        spec.expected_revision,
                        spec.expected_revision_epoch,
                    )
                    actual = (
                        existing["kind"],
                        existing["target_id"],
                        existing["input_fingerprint"],
                        existing["pipeline_run_id"],
                        existing["stage_run_id"],
                        existing["depends_on_task_id"],
                        existing["resource_class"],
                        existing["priority"],
                        existing["max_retries"],
                        existing["expected_generation"],
                        existing["expected_revision"],
                        existing["expected_revision_epoch"],
                    )
                    if actual != expected:
                        raise TaskOperationConflict(
                            "operation key was already used with a different task input"
                        )
                    return EnqueueResult(task_id=str(existing["id"]), created=False)
                task_id = new_id()
                connection.execute(
                    insert(TaskRow).values(
                        id=task_id,
                        kind=spec.kind.value,
                        target_id=spec.target_id,
                        operation_key=spec.operation_key,
                        input_fingerprint=spec.input_fingerprint,
                        resource_class=spec.resource_class.value,
                        pipeline_run_id=spec.pipeline_run_id,
                        stage_run_id=spec.stage_run_id,
                        depends_on_task_id=spec.depends_on_task_id,
                        status=TaskStatus.QUEUED.value,
                        priority=spec.priority,
                        not_before=spec.not_before or instant,
                        expected_generation=spec.expected_generation,
                        expected_revision=spec.expected_revision,
                        expected_revision_epoch=spec.expected_revision_epoch,
                        attempt_count=0,
                        retry_count=0,
                        manual_retry_count=0,
                        max_retries=spec.max_retries,
                        created_at=instant,
                        updated_at=instant,
                    )
                )
                return EnqueueResult(task_id=task_id, created=True)
        except OperationalError as exc:
            raise _queue_operational_error(exc) from exc

    def claim(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        pipeline_run_id: str | None = None,
        task_kind: TaskKind | None = None,
    ) -> TaskLease | None:
        _validate_worker_id(worker_id)
        if pipeline_run_id is not None:
            _validate_identifier(pipeline_run_id, "pipeline run ID")
        instant = _now(now)
        expires_at = instant + timedelta(seconds=self._lease_seconds)
        lease_token = secrets.token_hex(32)
        dependency = aliased(TaskRow)
        running_heavy = aliased(TaskRow)
        try:
            with begin_immediate(self._engine) as connection:
                self._recover_expired(connection, instant)
                task_id = connection.scalar(
                    select(TaskRow.id)
                    .where(
                        TaskRow.status == TaskStatus.QUEUED.value,
                        TaskRow.kind == task_kind.value if task_kind is not None else true(),
                        TaskRow.pipeline_run_id == pipeline_run_id
                        if pipeline_run_id is not None
                        else true(),
                        TaskRow.not_before <= instant,
                        TaskRow.cancellation_requested_at.is_(None),
                        or_(
                            TaskRow.depends_on_task_id.is_(None),
                            exists(
                                select(dependency.id).where(
                                    dependency.id == TaskRow.depends_on_task_id,
                                    dependency.status == TaskStatus.SUCCEEDED.value,
                                )
                            ),
                        ),
                        or_(
                            TaskRow.resource_class != ResourceClass.HEAVY.value,
                            ~exists(
                                select(running_heavy.id).where(
                                    running_heavy.status == TaskStatus.RUNNING.value,
                                    running_heavy.resource_class == ResourceClass.HEAVY.value,
                                    running_heavy.lease_expires_at > instant,
                                )
                            ),
                        ),
                    )
                    .order_by(
                        TaskRow.priority.desc(),
                        TaskRow.not_before,
                        TaskRow.created_at,
                        TaskRow.id,
                    )
                    .limit(1)
                )
                if task_id is None:
                    return None
                claimed = (
                    connection.execute(
                        update(TaskRow)
                        .where(
                            TaskRow.id == task_id,
                            TaskRow.status == TaskStatus.QUEUED.value,
                            TaskRow.cancellation_requested_at.is_(None),
                        )
                        .values(
                            status=TaskStatus.RUNNING.value,
                            worker_id=worker_id,
                            lease_token=lease_token,
                            heartbeat_at=instant,
                            lease_expires_at=expires_at,
                            attempt_count=TaskRow.attempt_count + 1,
                            failure_class=None,
                            error_code=None,
                            safe_error_message=None,
                            updated_at=instant,
                        )
                        .returning(
                            TaskRow.id,
                            TaskRow.kind,
                            TaskRow.target_id,
                            TaskRow.pipeline_run_id,
                            TaskRow.stage_run_id,
                            TaskRow.attempt_count,
                            TaskRow.cancellation_requested_at,
                        )
                    )
                    .mappings()
                    .one()
                )
                attempt_number = int(claimed["attempt_count"])
                connection.execute(
                    insert(TaskAttemptRow).values(
                        id=new_id(),
                        task_id=task_id,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        lease_token=lease_token,
                        outcome=AttemptOutcome.RUNNING.value,
                        started_at=instant,
                        heartbeat_at=instant,
                        lease_expires_at=expires_at,
                    )
                )
                self._activate_stage_owner(connection, claimed, instant)
                return TaskLease(
                    task_id=str(claimed["id"]),
                    kind=TaskKind(str(claimed["kind"])),
                    target_id=str(claimed["target_id"]),
                    worker_id=worker_id,
                    lease_token=lease_token,
                    heartbeat_at=instant,
                    lease_expires_at=expires_at,
                    attempt_number=attempt_number,
                    cancellation_requested=claimed["cancellation_requested_at"] is not None,
                )
        except OperationalError as exc:
            raise _queue_operational_error(exc) from exc

    def heartbeat(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> HeartbeatResult | None:
        instant = _now(now)
        expires_at = instant + timedelta(seconds=self._lease_seconds)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                update(TaskRow)
                .where(*_owned_unexpired_lease(lease, instant))
                .values(
                    heartbeat_at=instant,
                    lease_expires_at=expires_at,
                    updated_at=instant,
                )
                .returning(TaskRow.cancellation_requested_at)
            ).one_or_none()
            if row is None:
                return None
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(heartbeat_at=instant, lease_expires_at=expires_at)
            )
            return HeartbeatResult(
                lease_expires_at=expires_at,
                cancellation_requested=row[0] is not None,
            )

    def observe(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> HeartbeatResult | None:
        """Read cancellation/fencing state without extending the lease."""

        instant = _now(now)
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    select(TaskRow.lease_expires_at, TaskRow.cancellation_requested_at).where(
                        *_owned_unexpired_lease(lease, instant)
                    )
                ).one_or_none()
        except OperationalError as exc:
            raise _queue_operational_error(exc) from exc
        if row is None:
            return None
        return HeartbeatResult(
            lease_expires_at=row[0],
            cancellation_requested=row[1] is not None,
        )

    def complete(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> CompletionResult:
        instant = _now(now)
        with begin_immediate(self._engine) as connection:
            completed = connection.execute(
                update(TaskRow)
                .where(
                    *_owned_unexpired_lease(lease, instant),
                    TaskRow.cancellation_requested_at.is_(None),
                )
                .values(
                    status=TaskStatus.SUCCEEDED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=instant,
                    updated_at=instant,
                )
                .returning(TaskRow.id)
            ).scalar_one_or_none()
            if completed is not None:
                self._finish_attempt(
                    connection,
                    lease,
                    outcome=AttemptOutcome.SUCCEEDED,
                    finished_at=instant,
                )
                return CompletionResult.COMPLETED
            current = connection.execute(
                select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                    TaskRow.id == lease.task_id
                )
            ).one_or_none()
            if current is not None and current[0] == TaskStatus.SUCCEEDED.value:
                return CompletionResult.ALREADY_SUCCEEDED
            if current is not None and current[1] is not None:
                return CompletionResult.CANCELLATION_REQUESTED
            return CompletionResult.LOST_LEASE

    def fail(
        self,
        lease: TaskLease,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        retry_delay_ms: int = 0,
        diagnostic_relative_path: str | None = None,
        now: datetime | None = None,
    ) -> TaskStatus | None:
        if retry_delay_ms < 0:
            raise ValueError("retry delay must be nonnegative")
        _validate_safe_error(error_code, safe_message)
        diagnostic_relative_path = validate_task_diagnostic_relative_path(diagnostic_relative_path)
        if diagnostic_relative_path is not None:
            parts = diagnostic_relative_path.split("/")
            if parts[1:3] != [lease.task_id, lease.lease_token]:
                raise ValueError("task diagnostic path belongs to another attempt")
        instant = _now(now)
        with begin_immediate(self._engine) as connection:
            owned = connection.execute(
                select(
                    TaskRow.retry_count,
                    TaskRow.max_retries,
                    TaskRow.cancellation_requested_at,
                ).where(*_owned_unexpired_lease(lease, instant))
            ).one_or_none()
            if owned is None:
                return None
            retry_count, max_retries = int(owned[0]), int(owned[1])
            if owned[2] is not None:
                _fail_task_dependents(
                    connection,
                    task_id=lease.task_id,
                    target=TaskStatus.CANCELLED,
                    error_code="RENDER_CANCELLED",
                    safe_message="The render stopped because its task was cancelled",
                    instant=instant,
                )
                connection.execute(
                    update(TaskRow)
                    .where(*_owned_unexpired_lease(lease, instant))
                    .values(
                        status=TaskStatus.CANCELLED.value,
                        worker_id=None,
                        lease_token=None,
                        heartbeat_at=None,
                        lease_expires_at=None,
                        completed_at=instant,
                        updated_at=instant,
                    )
                )
                self._finish_attempt(
                    connection,
                    lease,
                    outcome=AttemptOutcome.CANCELLED,
                    finished_at=instant,
                )
                return TaskStatus.CANCELLED
            retryable = failure_class == FailureClass.TRANSIENT and retry_count < max_retries
            target = TaskStatus.QUEUED if retryable else TaskStatus.FAILED
            _fail_task_dependents(
                connection,
                task_id=lease.task_id,
                target=target,
                error_code=error_code,
                safe_message=safe_message,
                instant=instant,
            )
            values: dict[str, object] = {
                "status": target.value,
                "worker_id": None,
                "lease_token": None,
                "heartbeat_at": None,
                "lease_expires_at": None,
                "failure_class": failure_class.value,
                "error_code": error_code,
                "safe_error_message": safe_message,
                "updated_at": instant,
            }
            if retryable:
                values["retry_count"] = retry_count + 1
                values["not_before"] = instant + timedelta(milliseconds=retry_delay_ms)
            else:
                values["completed_at"] = instant
            connection.execute(
                update(TaskRow).where(*_owned_unexpired_lease(lease, instant)).values(**values)
            )
            self._finish_attempt(
                connection,
                lease,
                outcome=AttemptOutcome.FAILED,
                finished_at=instant,
                failure_class=failure_class,
                error_code=error_code,
                safe_message=safe_message,
                diagnostic_relative_path=diagnostic_relative_path,
            )
            return target

    def request_cancel(self, task_id: str, *, now: datetime | None = None) -> TaskStatus:
        _validate_identifier(task_id, "task ID")
        instant = _now(now)
        with begin_immediate(self._engine) as connection:
            status = connection.scalar(select(TaskRow.status).where(TaskRow.id == task_id))
            if status is None:
                raise TaskQueueError("task does not exist")
            current = TaskStatus(str(status))
            if current == TaskStatus.QUEUED:
                _fail_task_dependents(
                    connection,
                    task_id=task_id,
                    target=TaskStatus.CANCELLED,
                    error_code="RENDER_CANCELLED",
                    safe_message="The render stopped because its task was cancelled",
                    instant=instant,
                )
                connection.execute(
                    update(TaskRow)
                    .where(TaskRow.id == task_id, TaskRow.status == TaskStatus.QUEUED.value)
                    .values(
                        status=TaskStatus.CANCELLED.value,
                        cancellation_requested_at=instant,
                        completed_at=instant,
                        updated_at=instant,
                    )
                )
                return TaskStatus.CANCELLED
            if current == TaskStatus.RUNNING:
                connection.execute(
                    update(TaskRow)
                    .where(TaskRow.id == task_id, TaskRow.status == TaskStatus.RUNNING.value)
                    .values(cancellation_requested_at=instant, updated_at=instant)
                )
            return current

    def acknowledge_cancel(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> bool:
        instant = _now(now)
        with begin_immediate(self._engine) as connection:
            cancelled = connection.execute(
                update(TaskRow)
                .where(
                    *_owned_unexpired_lease(lease, instant),
                    TaskRow.cancellation_requested_at.is_not(None),
                )
                .values(
                    status=TaskStatus.CANCELLED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    completed_at=instant,
                    updated_at=instant,
                )
                .returning(TaskRow.id)
            ).scalar_one_or_none()
            if cancelled is None:
                return False
            _fail_task_dependents(
                connection,
                task_id=lease.task_id,
                target=TaskStatus.CANCELLED,
                error_code="RENDER_CANCELLED",
                safe_message="The render stopped because its task was cancelled",
                instant=instant,
            )
            self._finish_attempt(
                connection,
                lease,
                outcome=AttemptOutcome.CANCELLED,
                finished_at=instant,
            )
            return True

    def recover_expired(self, *, now: datetime | None = None) -> RecoveryResult:
        instant = _now(now)
        with begin_immediate(self._engine) as connection:
            return self._recover_expired(connection, instant)

    def _recover_expired(self, connection: Connection, instant: datetime) -> RecoveryResult:
        expired = connection.execute(
            select(
                TaskRow.id,
                TaskRow.lease_token,
                TaskRow.kind,
                TaskRow.stage_run_id,
                TaskRow.pipeline_run_id,
                TaskRow.retry_count,
                TaskRow.max_retries,
                TaskRow.cancellation_requested_at,
            ).where(
                TaskRow.status == TaskStatus.RUNNING.value,
                TaskRow.lease_expires_at <= instant,
            )
        ).all()
        requeued = failed = cancelled = 0
        for (
            task_id,
            lease_token,
            kind,
            stage_run_id,
            pipeline_run_id,
            retry_count,
            max_retries,
            cancel_requested,
        ) in expired:
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == task_id,
                    TaskAttemptRow.lease_token == lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(
                    outcome=AttemptOutcome.LOST_LEASE.value,
                    finished_at=instant,
                    failure_class=FailureClass.TRANSIENT.value,
                    error_code="LEASE_EXPIRED",
                    safe_error_message="Worker lease expired before task completion",
                )
            )
            if cancel_requested is not None:
                target = TaskStatus.CANCELLED
                cancelled += 1
            elif int(retry_count) < int(max_retries):
                target = TaskStatus.QUEUED
                requeued += 1
            else:
                target = TaskStatus.FAILED
                failed += 1
            _fail_task_dependents(
                connection,
                task_id=str(task_id),
                target=target,
                error_code=(
                    "RENDER_CANCELLED" if target == TaskStatus.CANCELLED else "LEASE_EXPIRED"
                ),
                safe_message=(
                    "The render stopped because its task was cancelled"
                    if target == TaskStatus.CANCELLED
                    else "Worker lease expired before render completion"
                ),
                instant=instant,
            )
            values: dict[str, object] = {
                "status": target.value,
                "worker_id": None,
                "lease_token": None,
                "heartbeat_at": None,
                "lease_expires_at": None,
                "failure_class": FailureClass.TRANSIENT.value,
                "error_code": "LEASE_EXPIRED",
                "safe_error_message": "Worker lease expired before task completion",
                "updated_at": instant,
            }
            if target == TaskStatus.QUEUED:
                values["retry_count"] = int(retry_count) + 1
                values["not_before"] = instant
            else:
                values["completed_at"] = instant
            connection.execute(update(TaskRow).where(TaskRow.id == task_id).values(**values))
            if kind == TaskKind.STAGE.value:
                if stage_run_id is None or pipeline_run_id is None:
                    raise TaskQueueError("stage task is missing its persistence owner")
                self._recover_stage_owner(
                    connection,
                    stage_run_id=str(stage_run_id),
                    pipeline_run_id=str(pipeline_run_id),
                    target=target,
                    retry_count=int(retry_count) + (1 if target == TaskStatus.QUEUED else 0),
                    instant=instant,
                )
        return RecoveryResult(requeued=requeued, failed=failed, cancelled=cancelled)

    @staticmethod
    def _activate_stage_owner(
        connection: Connection,
        claimed: RowMapping,
        instant: datetime,
    ) -> None:
        if claimed["kind"] != TaskKind.STAGE.value:
            return
        stage_run_id = claimed["stage_run_id"]
        pipeline_run_id = claimed["pipeline_run_id"]
        if stage_run_id is None or pipeline_run_id is None:
            raise TaskQueueError("stage task is missing its persistence owner")
        activated_stage = connection.execute(
            update(StageRunRow)
            .where(
                StageRunRow.id == stage_run_id,
                StageRunRow.status.in_([StageRunStatus.QUEUED.value, StageRunStatus.RUNNING.value]),
            )
            .values(
                status=StageRunStatus.RUNNING.value,
                started_at=func.coalesce(StageRunRow.started_at, instant),
                updated_at=instant,
            )
            .returning(StageRunRow.id)
        ).scalar_one_or_none()
        activated_run = connection.execute(
            update(PipelineRunRow)
            .where(
                PipelineRunRow.id == pipeline_run_id,
                PipelineRunRow.status.in_(
                    [PipelineRunStatus.QUEUED.value, PipelineRunStatus.RUNNING.value]
                ),
                PipelineRunRow.cancellation_requested_at.is_(None),
            )
            .values(
                status=PipelineRunStatus.RUNNING.value,
                started_at=func.coalesce(PipelineRunRow.started_at, instant),
                updated_at=instant,
            )
            .returning(PipelineRunRow.id)
        ).scalar_one_or_none()
        if activated_stage is None or activated_run is None:
            raise TaskQueueError("stage task owner is not runnable")

    @staticmethod
    def _recover_stage_owner(
        connection: Connection,
        *,
        stage_run_id: str,
        pipeline_run_id: str,
        target: TaskStatus,
        retry_count: int,
        instant: datetime,
    ) -> None:
        common_stage_values: dict[str, object] = {
            "retry_count": retry_count,
            "failure_class": FailureClass.TRANSIENT.value,
            "error_code": "LEASE_EXPIRED",
            "safe_error_message": "Worker lease expired before task completion",
            "updated_at": instant,
        }
        if target == TaskStatus.QUEUED:
            connection.execute(
                update(StageRunRow)
                .where(StageRunRow.id == stage_run_id)
                .values(**common_stage_values)
            )
            return
        if target == TaskStatus.FAILED:
            common_stage_values.update(
                {"status": StageRunStatus.FAILED.value, "finished_at": instant}
            )
            connection.execute(
                update(StageRunRow)
                .where(StageRunRow.id == stage_run_id)
                .values(**common_stage_values)
            )
            connection.execute(
                update(PipelineRunRow)
                .where(
                    PipelineRunRow.id == pipeline_run_id,
                    PipelineRunRow.status.in_(
                        [PipelineRunStatus.QUEUED.value, PipelineRunStatus.RUNNING.value]
                    ),
                )
                .values(
                    status=PipelineRunStatus.FAILED.value,
                    failure_class=FailureClass.TRANSIENT.value,
                    error_code="LEASE_EXPIRED",
                    safe_error_message="Worker lease expired before task completion",
                    finished_at=instant,
                    updated_at=instant,
                )
            )
            return
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == stage_run_id)
            .values(
                status=StageRunStatus.CANCELLED.value,
                finished_at=instant,
                updated_at=instant,
            )
        )
        connection.execute(
            update(PipelineRunRow)
            .where(
                PipelineRunRow.id == pipeline_run_id,
                PipelineRunRow.status.in_(
                    [PipelineRunStatus.QUEUED.value, PipelineRunStatus.RUNNING.value]
                ),
            )
            .values(
                status=PipelineRunStatus.CANCELLED.value,
                cancellation_requested_at=func.coalesce(
                    PipelineRunRow.cancellation_requested_at, instant
                ),
                finished_at=instant,
                updated_at=instant,
            )
        )
        connection.execute(
            update(TaskRow)
            .where(
                TaskRow.pipeline_run_id == pipeline_run_id,
                TaskRow.status == TaskStatus.QUEUED.value,
            )
            .values(
                status=TaskStatus.CANCELLED.value,
                cancellation_requested_at=instant,
                completed_at=instant,
                updated_at=instant,
            )
        )
        connection.execute(
            update(StageRunRow)
            .where(
                StageRunRow.pipeline_run_id == pipeline_run_id,
                StageRunRow.status == StageRunStatus.QUEUED.value,
            )
            .values(
                status=StageRunStatus.CANCELLED.value,
                finished_at=instant,
                updated_at=instant,
            )
        )

    @staticmethod
    def _finish_attempt(
        connection: Connection,
        lease: TaskLease,
        *,
        outcome: AttemptOutcome,
        finished_at: datetime,
        failure_class: FailureClass | None = None,
        error_code: str | None = None,
        safe_message: str | None = None,
        diagnostic_relative_path: str | None = None,
    ) -> None:
        connection.execute(
            update(TaskAttemptRow)
            .where(
                TaskAttemptRow.task_id == lease.task_id,
                TaskAttemptRow.lease_token == lease.lease_token,
                TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
            )
            .values(
                outcome=outcome.value,
                finished_at=finished_at,
                failure_class=failure_class.value if failure_class else None,
                error_code=error_code,
                safe_error_message=safe_message,
                diagnostic_relative_path=diagnostic_relative_path,
            )
        )


def _owned_unexpired_lease(lease: TaskLease, instant: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        TaskRow.id == lease.task_id,
        TaskRow.status == TaskStatus.RUNNING.value,
        TaskRow.worker_id == lease.worker_id,
        TaskRow.lease_token == lease.lease_token,
        TaskRow.lease_expires_at > instant,
    )


def _fail_task_dependents(
    connection: Connection,
    *,
    task_id: str,
    target: TaskStatus,
    error_code: str,
    safe_message: str,
    instant: datetime,
) -> None:
    _fail_task_renders(
        connection,
        task_id=task_id,
        target=target,
        error_code=error_code,
        safe_message=safe_message,
        instant=instant,
    )
    _fail_task_deliveries(
        connection,
        task_id=task_id,
        target=target,
        error_code=error_code,
        safe_message=safe_message,
        instant=instant,
    )
    _fail_task_edit_packages(
        connection,
        task_id=task_id,
        target=target,
        error_code=error_code,
        safe_message=safe_message,
        instant=instant,
    )
    _fail_task_release_packages(
        connection,
        task_id=task_id,
        target=target,
        error_code=error_code,
        safe_message=safe_message,
        instant=instant,
    )


def _fail_task_renders(
    connection: Connection,
    *,
    task_id: str,
    target: TaskStatus,
    error_code: str,
    safe_message: str,
    instant: datetime,
) -> None:
    target_status = RenderStatus.QUEUED if target == TaskStatus.QUEUED else RenderStatus.FAILED
    for current in (RenderStatus.QUEUED, RenderStatus.RUNNING):
        transition_render(current, RenderStatus.FAILED)
        if target_status == RenderStatus.QUEUED:
            transition_render(RenderStatus.FAILED, RenderStatus.QUEUED)
    connection.execute(
        update(RenderJobRow)
        .where(
            RenderJobRow.task_id == task_id,
            RenderJobRow.status.in_([RenderStatus.QUEUED.value, RenderStatus.RUNNING.value]),
        )
        .values(
            status=target_status.value,
            error_code=error_code,
            safe_error_message=safe_message,
            updated_at=instant,
        )
    )


def _fail_task_deliveries(
    connection: Connection,
    *,
    task_id: str,
    target: TaskStatus,
    error_code: str,
    safe_message: str,
    instant: datetime,
) -> None:
    target_status = DeliveryStatus.QUEUED if target == TaskStatus.QUEUED else DeliveryStatus.FAILED
    for current in (DeliveryStatus.QUEUED, DeliveryStatus.CREATING):
        transition_delivery(current, DeliveryStatus.FAILED)
        if target_status == DeliveryStatus.QUEUED:
            transition_delivery(DeliveryStatus.FAILED, DeliveryStatus.QUEUED)
    connection.execute(
        update(DeliveryRow)
        .where(
            DeliveryRow.task_id == task_id,
            DeliveryRow.status.in_([DeliveryStatus.QUEUED.value, DeliveryStatus.CREATING.value]),
        )
        .values(
            status=target_status.value,
            error_code=error_code,
            safe_error_message=safe_message,
            completed_at=None if target_status == DeliveryStatus.QUEUED else instant,
        )
    )


def _fail_task_edit_packages(
    connection: Connection,
    *,
    task_id: str,
    target: TaskStatus,
    error_code: str,
    safe_message: str,
    instant: datetime,
) -> None:
    target_status = (
        EditPackageStatus.QUEUED if target == TaskStatus.QUEUED else EditPackageStatus.FAILED
    )
    for current in (EditPackageStatus.QUEUED, EditPackageStatus.CREATING):
        transition_edit_package(current, EditPackageStatus.FAILED)
        if target_status == EditPackageStatus.QUEUED:
            transition_edit_package(EditPackageStatus.FAILED, EditPackageStatus.QUEUED)
    connection.execute(
        update(EditPackageRow)
        .where(
            EditPackageRow.task_id == task_id,
            EditPackageRow.status.in_(
                [EditPackageStatus.QUEUED.value, EditPackageStatus.CREATING.value]
            ),
        )
        .values(
            status=target_status.value,
            error_code=error_code,
            safe_error_message=safe_message,
            completed_at=None if target_status == EditPackageStatus.QUEUED else instant,
        )
    )


def _fail_task_release_packages(
    connection: Connection,
    *,
    task_id: str,
    target: TaskStatus,
    error_code: str,
    safe_message: str,
    instant: datetime,
) -> None:
    target_status = (
        ReleasePackageStatus.QUEUED if target == TaskStatus.QUEUED else ReleasePackageStatus.FAILED
    )
    for current in (ReleasePackageStatus.QUEUED, ReleasePackageStatus.CREATING):
        transition_release_package(current, ReleasePackageStatus.FAILED)
        if target_status == ReleasePackageStatus.QUEUED:
            transition_release_package(
                ReleasePackageStatus.FAILED,
                ReleasePackageStatus.QUEUED,
            )
    connection.execute(
        update(ReleasePackageRow)
        .where(
            ReleasePackageRow.task_id == task_id,
            ReleasePackageRow.status.in_(
                [ReleasePackageStatus.QUEUED.value, ReleasePackageStatus.CREATING.value]
            ),
        )
        .values(
            status=target_status.value,
            error_code=error_code,
            safe_error_message=safe_message,
            completed_at=None if target_status == ReleasePackageStatus.QUEUED else instant,
        )
    )


def _now(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    _require_aware(instant)
    return instant.astimezone(UTC)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("task queue timestamps must be timezone-aware")


def _validate_identifier(value: str, label: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError(f"{label} is invalid")


def _validate_worker_id(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
        raise ValueError("worker ID is invalid")


def _validate_safe_error(code: str, message: str) -> None:
    if not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
        raise ValueError("error code is invalid")
    if not message or len(message) > 500 or any(character in message for character in "\r\n"):
        raise ValueError("safe error message is invalid")


def _queue_operational_error(exc: OperationalError) -> TaskQueueError:
    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
        return TaskQueueBusy("SQLite task queue is temporarily busy")
    return TaskQueueError("SQLite task queue operation failed")
