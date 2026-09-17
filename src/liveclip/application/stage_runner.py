from __future__ import annotations

import logging
import threading
import traceback
from enum import StrEnum

from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineConfigInvalid,
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
from liveclip.application.tasks import TaskLease, TaskQueuePort, TaskQueueTransientError
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    TaskKind,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class RunOneOutcome(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
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
        try:
            lease = self._queue.claim(
                worker_id=worker_id,
                pipeline_run_id=pipeline_run_id,
                task_kind=TaskKind.STAGE,
            )
        except TaskQueueTransientError:
            return RunOneOutcome.BUSY
        if lease is None:
            return RunOneOutcome.IDLE
        identity = _identity(lease)
        try:
            work = self._repository.start_or_resume_stage(identity)
        except StageLeaseLost:
            return RunOneOutcome.LOST_LEASE
        except PipelineConfigInvalid:
            return self._record_failure(
                lease,
                identity,
                StageExecutionError(
                    failure_class=FailureClass.DETERMINISTIC,
                    error_code="STAGE_CONFIG_INVALID",
                    safe_message="The persisted pipeline configuration failed integrity checks",
                ),
            )
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            site = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
            logger.error(
                "unexpected stage failure error_class=%s error_site=%s",
                type(exc).__name__,
                site,
            )
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
                    diagnostic_relative_path=None,
                )
                else RunOneOutcome.LOST_LEASE
            )
        monitor = LeaseMonitor(
            heartbeat=self._queue.heartbeat,
            observe=getattr(self._queue, "observe", None),
            lease=lease,
            heartbeat_seconds=self._heartbeat_seconds,
            thread_name=f"liveclip-stage-lease-{lease.task_id[:8]}",
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
                diagnostic_relative_path=result.diagnostic_relative_path,
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
            if outcome in {RunOneOutcome.IDLE, RunOneOutcome.BUSY}:
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
            diagnostic_relative_path=error.diagnostic_relative_path,
        )
        if target == TaskStatus.QUEUED:
            return RunOneOutcome.RETRY_SCHEDULED
        if target == TaskStatus.FAILED:
            return RunOneOutcome.FAILED
        if target == TaskStatus.CANCELLED:
            return RunOneOutcome.CANCELLED
        return RunOneOutcome.LOST_LEASE


def _identity(lease: TaskLease) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
    )
