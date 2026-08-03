from __future__ import annotations

import threading
from datetime import UTC, datetime
from enum import StrEnum

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineService,
    RunSnapshot,
    StageExecutionRepository,
    StageLeaseLost,
)
from liveclip.application.stage_execution import (
    StageCancelled,
    StageExecutionError,
    StageHandler,
)
from liveclip.application.tasks import TaskLease, TaskQueuePort
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    TaskKind,
    TaskStatus,
)


class RunOneOutcome(StrEnum):
    IDLE = "idle"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST_LEASE = "lost_lease"


class StageTaskRunner:
    def __init__(
        self,
        *,
        queue: TaskQueuePort,
        repository: StageExecutionRepository,
        pipeline_service: PipelineService,
        handler: StageHandler,
        heartbeat_seconds: int,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._queue = queue
        self._repository = repository
        self._pipeline_service = pipeline_service
        self._handler = handler
        self._heartbeat_seconds = heartbeat_seconds

    def run_one(
        self,
        *,
        worker_id: str,
        pipeline_run_id: str | None = None,
    ) -> RunOneOutcome:
        lease = self._queue.claim(
            worker_id=worker_id,
            pipeline_run_id=pipeline_run_id,
            task_kind=TaskKind.STAGE,
        )
        if lease is None:
            return RunOneOutcome.IDLE
        identity = _identity(lease)
        try:
            work = self._repository.start_or_resume_stage(identity)
        except StageLeaseLost:
            return RunOneOutcome.LOST_LEASE
        except Exception:
            return self._record_failure(
                lease,
                identity,
                StageExecutionError(
                    failure_class=FailureClass.TRANSIENT,
                    error_code="STAGE_START_TEMPORARY",
                    safe_message="The stage could not initialize its local state",
                ),
            )
        if work.already_succeeded:
            if work.output_fingerprint is None or work.checkpoint is None:
                return self._record_failure(
                    lease,
                    identity,
                    StageExecutionError(
                        failure_class=FailureClass.DETERMINISTIC,
                        error_code="STAGE_CHECKPOINT_INVALID",
                        safe_message="The completed stage checkpoint is incomplete",
                    ),
                )
            return (
                RunOneOutcome.SUCCEEDED
                if self._repository.complete_stage(
                    identity,
                    output_fingerprint=work.output_fingerprint,
                    checkpoint=work.checkpoint,
                )
                else RunOneOutcome.LOST_LEASE
            )
        monitor = _HeartbeatMonitor(
            queue=self._queue,
            lease=lease,
            interval_seconds=self._heartbeat_seconds,
        )
        if work.cancellation_requested:
            monitor.request_cancel()
        monitor.start()
        try:
            result = self._handler.execute(
                work,
                identity,
                cancel_requested=monitor.should_stop,
            )
            monitor.refresh()
            if monitor.cancel_requested:
                return (
                    RunOneOutcome.CANCELLED
                    if self._repository.cancel_stage(identity)
                    else RunOneOutcome.LOST_LEASE
                )
            if monitor.lost_lease:
                return RunOneOutcome.LOST_LEASE
            completed = self._repository.complete_stage(
                identity,
                output_fingerprint=result.output_fingerprint,
                checkpoint=result.checkpoint,
            )
            if completed:
                return RunOneOutcome.SUCCEEDED
            if monitor.cancel_requested and self._repository.cancel_stage(identity):
                return RunOneOutcome.CANCELLED
            return RunOneOutcome.LOST_LEASE
        except StageCancelled:
            return (
                RunOneOutcome.CANCELLED
                if self._repository.cancel_stage(identity)
                else RunOneOutcome.LOST_LEASE
            )
        except StageExecutionError as exc:
            return self._record_failure(lease, identity, exc)
        except Exception:
            return self._record_failure(
                lease,
                identity,
                StageExecutionError(
                    failure_class=FailureClass.DETERMINISTIC,
                    error_code="UNEXPECTED_STAGE_ERROR",
                    safe_message="The stage failed with an unexpected local error",
                ),
            )
        finally:
            monitor.stop()

    def run_until_terminal(
        self,
        run_id: str,
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
    ) -> RunSnapshot:
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("foreground poll interval must be between zero and five seconds")
        while True:
            snapshot = self._pipeline_service.get_run(run_id)
            if snapshot.status in {
                PipelineRunStatus.COMPLETED,
                PipelineRunStatus.FAILED,
                PipelineRunStatus.CANCELLED,
            }:
                return snapshot
            outcome = self.run_one(worker_id=worker_id, pipeline_run_id=run_id)
            if outcome == RunOneOutcome.IDLE:
                threading.Event().wait(poll_seconds)

    def _record_failure(
        self,
        lease: TaskLease,
        identity: LeaseIdentity,
        error: StageExecutionError,
    ) -> RunOneOutcome:
        if error.failure_class == FailureClass.TRANSIENT:
            delay_ms = min(30_000, 1_000 * (2 ** min(lease.attempt_number - 1, 5)))
        else:
            delay_ms = 0
        target = self._repository.fail_stage(
            identity,
            failure_class=error.failure_class,
            error_code=error.error_code,
            safe_message=error.safe_message,
            retry_delay_ms=delay_ms,
        )
        if target == TaskStatus.QUEUED:
            return RunOneOutcome.RETRY_SCHEDULED
        if target == TaskStatus.FAILED:
            return RunOneOutcome.FAILED
        if target == TaskStatus.CANCELLED:
            return RunOneOutcome.CANCELLED
        return RunOneOutcome.LOST_LEASE


class _HeartbeatMonitor:
    def __init__(
        self,
        *,
        queue: TaskQueuePort,
        lease: TaskLease,
        interval_seconds: int,
    ) -> None:
        self._queue = queue
        self._lease = lease
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._lost = threading.Event()
        self._last_expiry = lease.lease_expires_at
        self._refresh_lock = threading.Lock()
        if lease.cancellation_requested:
            self._cancel.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"liveclip-heartbeat-{lease.task_id[:8]}",
            daemon=True,
        )

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def lost_lease(self) -> bool:
        return self._lost.is_set()

    def should_stop(self) -> bool:
        return self.cancel_requested or self.lost_lease

    def request_cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        self._thread.start()

    def refresh(self) -> None:
        with self._refresh_lock:
            try:
                heartbeat = self._queue.heartbeat(self._lease)
            except Exception:
                if datetime.now(UTC) >= self._last_expiry:
                    self._lost.set()
                return
            if heartbeat is None:
                self._lost.set()
                return
            self._last_expiry = heartbeat.lease_expires_at
            if heartbeat.cancellation_requested:
                self._cancel.set()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self.refresh()
            if self.lost_lease:
                return


def _identity(lease: TaskLease) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
    )
