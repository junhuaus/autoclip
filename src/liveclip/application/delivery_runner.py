from __future__ import annotations

import threading
from enum import StrEnum

from liveclip.application.deliveries import DeliveryConflict, DeliveryRepository, DeliverySnapshot
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.render_runner import RenderTaskQueue
from liveclip.application.tasks import TaskLease, TaskQueueTransientError
from liveclip.delivery.package import DeliveryError
from liveclip.delivery.task_handler import DeliveryTaskCancelled, DeliveryTaskHandler
from liveclip.domain.state_transitions import DeliveryStatus, FailureClass, TaskKind, TaskStatus


class DeliveryRunOutcome(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST_LEASE = "lost_lease"


class DeliveryTaskRunner:
    def __init__(
        self,
        *,
        queue: RenderTaskQueue,
        repository: DeliveryRepository,
        handler: DeliveryTaskHandler,
        heartbeat_seconds: int,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._queue = queue
        self._repository = repository
        self._handler = handler
        self._heartbeat_seconds = heartbeat_seconds

    def run_one(self, *, worker_id: str) -> DeliveryRunOutcome:
        try:
            lease = self._queue.claim(worker_id=worker_id, task_kind=TaskKind.DELIVERY)
        except TaskQueueTransientError:
            return DeliveryRunOutcome.BUSY
        if lease is None:
            return DeliveryRunOutcome.IDLE
        identity = LeaseIdentity(
            task_id=lease.task_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
        )
        try:
            work = self._repository.start_delivery(identity)
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="DELIVERY_STATE_INVALID",
                safe_message="The delivery task is no longer valid for the current project",
            )
        monitor = LeaseMonitor(
            heartbeat=self._queue.heartbeat,
            observe=getattr(self._queue, "observe", None),
            lease=lease,
            heartbeat_seconds=self._heartbeat_seconds,
            thread_name=f"liveclip-delivery-lease-{lease.task_id[:8]}",
        )
        monitor.start()
        try:
            persistence = self._handler.execute(
                work,
                identity,
                cancel_requested=monitor.should_stop,
            )
            monitor.refresh()
            if monitor.cancel_requested:
                return (
                    DeliveryRunOutcome.CANCELLED
                    if self._queue.acknowledge_cancel(lease)
                    else DeliveryRunOutcome.LOST_LEASE
                )
            if monitor.lost_lease:
                return DeliveryRunOutcome.LOST_LEASE
            if self._repository.complete_delivery(identity, work, persistence):
                return DeliveryRunOutcome.SUCCEEDED
            return DeliveryRunOutcome.LOST_LEASE
        except DeliveryTaskCancelled:
            return (
                DeliveryRunOutcome.CANCELLED
                if self._queue.acknowledge_cancel(lease)
                else DeliveryRunOutcome.LOST_LEASE
            )
        except OSError:
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="DELIVERY_IO_TEMPORARY",
                safe_message="The delivery package could not be written and may be retried",
            )
        except (DeliveryConflict, DeliveryError, ValueError):
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="DELIVERY_VALIDATION_FAILED",
                safe_message="The delivery package did not pass deterministic validation",
            )
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="UNEXPECTED_DELIVERY_ERROR",
                safe_message="The delivery failed with an unexpected local error",
            )
        finally:
            monitor.stop()

    def run_until_terminal(
        self,
        delivery_id: str,
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
    ) -> DeliverySnapshot:
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("foreground poll interval must be between zero and five seconds")
        while True:
            snapshot = self._repository.get_delivery(delivery_id)
            if snapshot.status in {DeliveryStatus.SUCCEEDED, DeliveryStatus.FAILED}:
                return snapshot
            outcome = self.run_one(worker_id=worker_id)
            if outcome in {DeliveryRunOutcome.IDLE, DeliveryRunOutcome.BUSY}:
                threading.Event().wait(poll_seconds)

    def _fail(
        self,
        lease: TaskLease,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
    ) -> DeliveryRunOutcome:
        delay_ms = (
            min(30_000, 1_000 * (2 ** min(lease.attempt_number - 1, 5)))
            if failure_class == FailureClass.TRANSIENT
            else 0
        )
        target = self._queue.fail(
            lease,
            failure_class=failure_class,
            error_code=error_code,
            safe_message=safe_message,
            retry_delay_ms=delay_ms,
        )
        if target == TaskStatus.QUEUED:
            return DeliveryRunOutcome.RETRY_SCHEDULED
        if target == TaskStatus.FAILED:
            return DeliveryRunOutcome.FAILED
        if target == TaskStatus.CANCELLED:
            return DeliveryRunOutcome.CANCELLED
        return DeliveryRunOutcome.LOST_LEASE
