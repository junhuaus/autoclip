from __future__ import annotations

import logging
import threading
from enum import StrEnum

from liveclip.application.deliveries import DeliveryConflict, DeliveryRepository, DeliverySnapshot
from liveclip.application.delivery_progress import (
    DeliveryProgressLostLease,
    DeliveryProgressWriteFailed,
)
from liveclip.application.edit_packages import (
    EditPackageConflict,
    EditPackagePersistence,
    EditPackageRepository,
    EditPackageSnapshot,
    EditPackageWork,
)
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.releases import (
    ReleaseConflict,
    ReleasePackagePersistence,
    ReleasePackageSnapshot,
    ReleasePackageWork,
    ReleaseRepository,
)
from liveclip.application.render_runner import RenderTaskQueue
from liveclip.application.tasks import TaskLease, TaskQueueTransientError
from liveclip.delivery.edit_package import EditPackageError, EditPackageTransientError
from liveclip.delivery.edit_package_task_handler import (
    EditPackageTaskCancelled,
    EditPackageTaskHandler,
)
from liveclip.delivery.package import DeliveryError
from liveclip.delivery.release_package import (
    ReleasePackageError,
    ReleasePackageTransientError,
)
from liveclip.delivery.release_package_task_handler import (
    ReleasePackageTaskCancelled,
    ReleasePackageTaskHandler,
)
from liveclip.delivery.task_handler import DeliveryTaskCancelled, DeliveryTaskHandler
from liveclip.domain.state_transitions import DeliveryStatus, FailureClass, TaskKind, TaskStatus

logger = logging.getLogger(__name__)


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
        edit_package_repository: EditPackageRepository | None = None,
        edit_package_handler: EditPackageTaskHandler | None = None,
        release_repository: ReleaseRepository | None = None,
        release_package_handler: ReleasePackageTaskHandler | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._queue = queue
        self._repository = repository
        self._handler = handler
        self._heartbeat_seconds = heartbeat_seconds
        if (edit_package_repository is None) != (edit_package_handler is None):
            raise ValueError("edit-package repository and handler must be configured together")
        self._edit_package_repository = edit_package_repository
        self._edit_package_handler = edit_package_handler
        if (release_repository is None) != (release_package_handler is None):
            raise ValueError("release-package repository and handler must be configured together")
        self._release_repository = release_repository
        self._release_package_handler = release_package_handler

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
        if (
            self._edit_package_repository is not None
            and self._edit_package_handler is not None
            and self._edit_package_repository.is_edit_package_task(
                lease.task_id,
                lease.target_id,
            )
        ):
            return self._run_edit_package(lease, identity)
        if (
            self._release_repository is not None
            and self._release_package_handler is not None
            and self._release_repository.is_release_package_task(
                lease.task_id,
                lease.target_id,
            )
        ):
            return self._run_release_package(lease, identity)
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
            factory = getattr(self._repository, "progress_sink", None)
            progress_options = (
                {"progress": factory(identity, work, attempt_number=lease.attempt_number)}
                if factory is not None
                else {}
            )
            persistence = self._handler.execute(
                work,
                identity,
                cancel_requested=monitor.should_stop,
                **progress_options,
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
        except DeliveryProgressLostLease:
            return (
                DeliveryRunOutcome.CANCELLED
                if self._queue.acknowledge_cancel(lease)
                else DeliveryRunOutcome.LOST_LEASE
            )
        except DeliveryProgressWriteFailed:
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="DELIVERY_PROGRESS_WRITE_TEMPORARY",
                safe_message="Delivery progress could not be saved and may be retried",
            )
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

    def run_edit_package_until_terminal(
        self,
        edit_package_id: str,
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
    ) -> EditPackageSnapshot:
        if self._edit_package_repository is None:
            raise RuntimeError("edit-package runner is not configured")
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("foreground poll interval must be between zero and five seconds")
        while True:
            snapshot = self._edit_package_repository.get_edit_package(edit_package_id)
            if snapshot.status.value in {"succeeded", "failed"}:
                return snapshot
            outcome = self.run_one(worker_id=worker_id)
            if outcome in {DeliveryRunOutcome.IDLE, DeliveryRunOutcome.BUSY}:
                threading.Event().wait(poll_seconds)

    def run_release_package_until_terminal(
        self,
        release_package_id: str,
        *,
        worker_id: str,
        poll_seconds: float = 0.2,
    ) -> ReleasePackageSnapshot:
        if self._release_repository is None:
            raise RuntimeError("release-package runner is not configured")
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("foreground poll interval must be between zero and five seconds")
        while True:
            snapshot = self._release_repository.get_package(release_package_id)
            if snapshot.status.value in {"succeeded", "failed"}:
                return snapshot
            outcome = self.run_one(worker_id=worker_id)
            if outcome in {DeliveryRunOutcome.IDLE, DeliveryRunOutcome.BUSY}:
                threading.Event().wait(poll_seconds)

    def _run_edit_package(
        self,
        lease: TaskLease,
        identity: LeaseIdentity,
    ) -> DeliveryRunOutcome:
        repository = self._edit_package_repository
        handler = self._edit_package_handler
        if repository is None or handler is None:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="EDIT_PACKAGE_NOT_CONFIGURED",
                safe_message="The edit-package task is not configured on this worker",
            )
        try:
            work = repository.start_edit_package(identity)
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="EDIT_PACKAGE_STATE_INVALID",
                safe_message="The edit-package task is no longer valid for this project",
            )
        monitor = LeaseMonitor(
            heartbeat=self._queue.heartbeat,
            observe=getattr(self._queue, "observe", None),
            lease=lease,
            heartbeat_seconds=self._heartbeat_seconds,
            thread_name=f"liveclip-edit-package-lease-{lease.task_id[:8]}",
        )
        monitor.start()
        persistence = None
        try:
            persistence = handler.execute(
                work,
                identity,
                cancel_requested=monitor.should_stop,
            )
            monitor.refresh()
            if monitor.cancel_requested:
                self._withdraw_edit_package(handler, work, identity, persistence)
                return (
                    DeliveryRunOutcome.CANCELLED
                    if self._queue.acknowledge_cancel(lease)
                    else DeliveryRunOutcome.LOST_LEASE
                )
            if monitor.lost_lease:
                return DeliveryRunOutcome.LOST_LEASE
            if repository.complete_edit_package(identity, work, persistence):
                return DeliveryRunOutcome.SUCCEEDED
            self._withdraw_edit_package(handler, work, identity, persistence)
            return DeliveryRunOutcome.LOST_LEASE
        except EditPackageTaskCancelled:
            return (
                DeliveryRunOutcome.CANCELLED
                if self._queue.acknowledge_cancel(lease)
                else DeliveryRunOutcome.LOST_LEASE
            )
        except OSError:
            self._withdraw_edit_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="EDIT_PACKAGE_IO_TEMPORARY",
                safe_message="The edit package could not be written and may be retried",
            )
        except EditPackageTransientError:
            self._withdraw_edit_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="EDIT_PACKAGE_MEDIA_VALIDATION_TEMPORARY",
                safe_message="The edit package media could not be validated and may be retried",
            )
        except (EditPackageConflict, EditPackageError, DeliveryError) as exc:
            logger.warning(
                "edit_package_validation_failed error_type=%s detail=%s",
                type(exc).__name__,
                str(exc),
            )
            self._withdraw_edit_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="EDIT_PACKAGE_VALIDATION_FAILED",
                safe_message="The edit package did not pass deterministic validation",
            )
        except ValueError as exc:
            logger.warning(
                "edit_package_validation_failed error_type=%s",
                type(exc).__name__,
            )
            self._withdraw_edit_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="EDIT_PACKAGE_VALIDATION_FAILED",
                safe_message="The edit package did not pass deterministic validation",
            )
        except Exception:
            self._withdraw_edit_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="UNEXPECTED_EDIT_PACKAGE_ERROR",
                safe_message="The edit package failed with an unexpected local error",
            )
        finally:
            monitor.stop()

    def _run_release_package(
        self,
        lease: TaskLease,
        identity: LeaseIdentity,
    ) -> DeliveryRunOutcome:
        repository = self._release_repository
        handler = self._release_package_handler
        if repository is None or handler is None:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RELEASE_PACKAGE_NOT_CONFIGURED",
                safe_message="The release-package task is not configured on this worker",
            )
        try:
            work = repository.start_release_package(identity)
        except Exception:
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RELEASE_PACKAGE_STATE_INVALID",
                safe_message="The release-package task is no longer valid for this release item",
            )
        monitor = LeaseMonitor(
            heartbeat=self._queue.heartbeat,
            observe=getattr(self._queue, "observe", None),
            lease=lease,
            heartbeat_seconds=self._heartbeat_seconds,
            thread_name=f"liveclip-release-package-lease-{lease.task_id[:8]}",
        )
        monitor.start()
        persistence = None
        try:
            persistence = handler.execute(
                work,
                identity,
                cancel_requested=monitor.should_stop,
            )
            monitor.refresh()
            if monitor.cancel_requested:
                self._withdraw_release_package(handler, work, identity, persistence)
                return (
                    DeliveryRunOutcome.CANCELLED
                    if self._queue.acknowledge_cancel(lease)
                    else DeliveryRunOutcome.LOST_LEASE
                )
            if monitor.lost_lease:
                return DeliveryRunOutcome.LOST_LEASE
            if repository.complete_release_package(identity, work, persistence):
                return DeliveryRunOutcome.SUCCEEDED
            self._withdraw_release_package(handler, work, identity, persistence)
            return DeliveryRunOutcome.LOST_LEASE
        except ReleasePackageTaskCancelled:
            return (
                DeliveryRunOutcome.CANCELLED
                if self._queue.acknowledge_cancel(lease)
                else DeliveryRunOutcome.LOST_LEASE
            )
        except OSError:
            self._withdraw_release_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="RELEASE_PACKAGE_IO_TEMPORARY",
                safe_message="The release package could not be written and may be retried",
            )
        except ReleasePackageTransientError:
            self._withdraw_release_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.TRANSIENT,
                error_code="RELEASE_PACKAGE_MEDIA_VALIDATION_TEMPORARY",
                safe_message="The release package media could not be validated and may be retried",
            )
        except (ReleaseConflict, ReleasePackageError, DeliveryError, ValueError) as exc:
            logger.warning(
                "release_package_validation_failed error_type=%s detail=%s",
                type(exc).__name__,
                str(exc),
            )
            self._withdraw_release_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RELEASE_PACKAGE_VALIDATION_FAILED",
                safe_message="The release package did not pass deterministic validation",
            )
        except Exception:
            self._withdraw_release_package(handler, work, identity, persistence)
            return self._fail(
                lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="UNEXPECTED_RELEASE_PACKAGE_ERROR",
                safe_message="The release package failed with an unexpected local error",
            )
        finally:
            monitor.stop()

    @staticmethod
    def _withdraw_edit_package(
        handler: EditPackageTaskHandler,
        work: EditPackageWork,
        identity: LeaseIdentity,
        persistence: EditPackagePersistence | None,
    ) -> None:
        if persistence is None:
            return
        try:
            handler.withdraw(work, identity, persistence)
        except Exception as exc:
            logger.error(
                "edit_package_withdrawal_failed error_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _withdraw_release_package(
        handler: ReleasePackageTaskHandler,
        work: ReleasePackageWork,
        identity: LeaseIdentity,
        persistence: ReleasePackagePersistence | None,
    ) -> None:
        if persistence is None:
            return
        try:
            handler.withdraw(work, identity, persistence)
        except Exception as exc:
            logger.error(
                "release_package_withdrawal_failed error_type=%s",
                type(exc).__name__,
            )

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
