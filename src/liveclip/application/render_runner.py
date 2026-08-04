from __future__ import annotations

import threading
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.rendering import QueuedRender, RenderConflict, RenderRepository
from liveclip.application.tasks import HeartbeatResult, TaskLease, TaskQueueTransientError
from liveclip.domain.state_transitions import FailureClass, RenderStatus, TaskKind, TaskStatus
from liveclip.media.artifacts import ArtifactPublicationError
from liveclip.renderer.ffmpeg import FFmpegRenderCancelled, FFmpegRenderError
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    MediaValidationTransientError,
)
from liveclip.renderer.task_handler import RenderTaskCancelled, RenderTaskHandler


class RenderRunOutcome(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST_LEASE = "lost_lease"


class RenderTaskQueue(Protocol):
    def claim(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        pipeline_run_id: str | None = None,
        task_kind: TaskKind | None = None,
    ) -> TaskLease | None: ...

    def heartbeat(
        self, lease: TaskLease, *, now: datetime | None = None
    ) -> HeartbeatResult | None: ...

    def observe(
        self, lease: TaskLease, *, now: datetime | None = None
    ) -> HeartbeatResult | None: ...

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
    ) -> TaskStatus | None: ...

    def acknowledge_cancel(self, lease: TaskLease, *, now: datetime | None = None) -> bool: ...


class RenderTaskRunner:
    def __init__(
        self,
        *,
        queue: RenderTaskQueue,
        repository: RenderRepository,
        handler: RenderTaskHandler,
        heartbeat_seconds: int,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._queue = queue
        self._repository = repository
        self._handler = handler
        self._heartbeat_seconds = heartbeat_seconds

    def run_one(self, *, worker_id: str) -> RenderRunOutcome:
        try:
            lease = self._queue.claim(worker_id=worker_id, task_kind=TaskKind.RENDER)
        except TaskQueueTransientError:
            return RenderRunOutcome.BUSY
        if lease is None:
            return RenderRunOutcome.IDLE
        identity = LeaseIdentity(
            task_id=lease.task_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
        )
        try:
            work = self._repository.start_render(identity)
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RENDER_STATE_INVALID",
                safe_message="The render task is no longer valid for its clip revision",
            )
        monitor = LeaseMonitor(
            heartbeat=self._queue.heartbeat,
            observe=getattr(self._queue, "observe", None),
            lease=lease,
            heartbeat_seconds=self._heartbeat_seconds,
            thread_name=f"liveclip-render-lease-{lease.task_id[:8]}",
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
                    RenderRunOutcome.CANCELLED
                    if self._queue.acknowledge_cancel(lease)
                    else RenderRunOutcome.LOST_LEASE
                )
            if monitor.lost_lease:
                return RenderRunOutcome.LOST_LEASE
            if self._repository.complete_render(identity, work, persistence):
                return RenderRunOutcome.SUCCEEDED
            return RenderRunOutcome.LOST_LEASE
        except (RenderTaskCancelled, FFmpegRenderCancelled, MediaValidationCancelled):
            return (
                RenderRunOutcome.CANCELLED
                if self._queue.acknowledge_cancel(lease)
                else RenderRunOutcome.LOST_LEASE
            )
        except FFmpegRenderError as exc:
            return self._fail(
                lease,
                failure_class=(
                    FailureClass.TRANSIENT if exc.retryable else FailureClass.DETERMINISTIC
                ),
                error_code=("RENDER_TEMPORARY" if exc.retryable else "RENDER_VALIDATION_FAILED"),
                safe_message=(
                    "The local renderer failed temporarily and may be retried"
                    if exc.retryable
                    else "The renderer rejected deterministic media or layout input"
                ),
                diagnostic_relative_path=exc.diagnostic_relative_path,
            )
        except (MediaValidationTransientError, OSError):
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="RENDER_TEMPORARY",
                safe_message="The local renderer failed temporarily and may be retried",
            )
        except (RenderConflict, MediaValidationError, ArtifactPublicationError, ValueError):
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RENDER_VALIDATION_FAILED",
                safe_message="The rendered clip did not pass deterministic validation",
            )
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="UNEXPECTED_RENDER_ERROR",
                safe_message="The render failed with an unexpected local error",
            )
        finally:
            monitor.stop()

    def run_until_terminal(
        self,
        render_id: str,
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
    ) -> QueuedRender:
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("foreground poll interval must be between zero and five seconds")
        while True:
            snapshot = self._repository.get_render(render_id)
            if snapshot.status in {
                RenderStatus.SUCCEEDED,
                RenderStatus.FAILED,
                RenderStatus.STALE,
            }:
                return snapshot
            outcome = self.run_one(worker_id=worker_id)
            if outcome in {RenderRunOutcome.IDLE, RenderRunOutcome.BUSY}:
                threading.Event().wait(poll_seconds)

    def _fail(
        self,
        lease: TaskLease,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        diagnostic_relative_path: str | None = None,
    ) -> RenderRunOutcome:
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
            diagnostic_relative_path=diagnostic_relative_path,
        )
        if target == TaskStatus.QUEUED:
            return RenderRunOutcome.RETRY_SCHEDULED
        if target == TaskStatus.FAILED:
            return RenderRunOutcome.FAILED
        if target == TaskStatus.CANCELLED:
            return RenderRunOutcome.CANCELLED
        return RenderRunOutcome.LOST_LEASE
