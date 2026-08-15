from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import liveclip.application.delivery_runner as delivery_runner_module
from liveclip.application.delivery_runner import DeliveryRunOutcome, DeliveryTaskRunner
from liveclip.application.tasks import TaskLease
from liveclip.delivery.release_package import ReleasePackageTransientError
from liveclip.domain.state_transitions import FailureClass, TaskKind, TaskStatus


class _NoopLeaseMonitor:
    cancel_requested = False
    lost_lease = False

    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def should_stop(self) -> bool:
        return False


def test_release_package_transient_validation_uses_bounded_queue_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    lease = TaskLease(
        task_id="task_1",
        kind=TaskKind.DELIVERY,
        target_id="release_package_1",
        worker_id="worker_1",
        lease_token="lease_token_1",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=30),
        attempt_number=1,
        cancellation_requested=False,
    )
    queue = Mock()
    queue.claim.return_value = lease
    queue.fail.return_value = TaskStatus.QUEUED
    release_repository = Mock()
    release_repository.is_release_package_task.return_value = True
    release_repository.start_release_package.return_value = SimpleNamespace()
    release_handler = Mock()
    release_handler.execute.side_effect = ReleasePackageTransientError("temporary decoder failure")
    monkeypatch.setattr(delivery_runner_module, "LeaseMonitor", _NoopLeaseMonitor)
    runner = DeliveryTaskRunner(
        queue=queue,
        repository=Mock(),
        handler=Mock(),
        heartbeat_seconds=5,
        release_repository=release_repository,
        release_package_handler=release_handler,
    )

    assert runner.run_one(worker_id="worker_1") == DeliveryRunOutcome.RETRY_SCHEDULED
    queue.fail.assert_called_once()
    failure = queue.fail.call_args.kwargs
    assert failure["failure_class"] == FailureClass.TRANSIENT
    assert failure["error_code"] == "RELEASE_PACKAGE_MEDIA_VALIDATION_TEMPORARY"
    assert failure["retry_delay_ms"] == 1_000
