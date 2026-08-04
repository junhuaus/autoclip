from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.rendering import QueuedRender, RenderConflict, RenderRepository
from liveclip.application.tasks import HeartbeatResult, TaskLease
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

    def fail(
        self,
        lease: TaskLease,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        retry_delay_ms: int = 0,
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
        lease = self._queue.claim(worker_id=worker_id, task_kind=TaskKind.RENDER)
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
        monitor = _HeartbeatMonitor(
            heartbeat=self._queue.heartbeat,
            lease=lease,
            interval_seconds=self._heartbeat_seconds,
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
        except (FFmpegRenderError, MediaValidationTransientError, OSError):
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
            if outcome == RenderRunOutcome.IDLE:
                threading.Event().wait(poll_seconds)

    def _fail(
        self,
        lease: TaskLease,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
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
        )
        if target == TaskStatus.QUEUED:
            return RenderRunOutcome.RETRY_SCHEDULED
        if target == TaskStatus.FAILED:
            return RenderRunOutcome.FAILED
        if target == TaskStatus.CANCELLED:
            return RenderRunOutcome.CANCELLED
        return RenderRunOutcome.LOST_LEASE


class _HeartbeatMonitor:
    def __init__(
        self,
        *,
        heartbeat: Callable[..., HeartbeatResult | None],
        lease: TaskLease,
        interval_seconds: int,
    ) -> None:
        self._heartbeat = heartbeat
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
            name=f"liveclip-render-heartbeat-{lease.task_id[:8]}",
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

    def start(self) -> None:
        self._thread.start()

    def refresh(self) -> None:
        with self._refresh_lock:
            try:
                result = self._heartbeat(self._lease)
            except Exception:
                if datetime.now(UTC) >= self._last_expiry:
                    self._lost.set()
                return
            if result is None:
                self._lost.set()
                return
            self._last_expiry = result.lease_expires_at
            if result.cancellation_requested:
                self._cancel.set()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self.refresh()
            if self.lost_lease:
                return
