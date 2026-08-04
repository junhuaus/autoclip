from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.tasks import HeartbeatResult, TaskLease
from liveclip.domain.state_transitions import TaskKind


def _lease(*, expires_in_seconds: float = 30) -> TaskLease:
    now = datetime.now(UTC)
    return TaskLease(
        task_id="a" * 32,
        kind=TaskKind.RENDER,
        target_id="b" * 32,
        worker_id="worker",
        lease_token="c" * 64,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=expires_in_seconds),
        attempt_number=1,
        cancellation_requested=False,
    )


def test_cancellation_poll_does_not_wait_for_heartbeat_interval() -> None:
    lease = _lease()
    observed = threading.Event()
    heartbeat_calls = 0

    def heartbeat(_: TaskLease) -> HeartbeatResult:
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return HeartbeatResult(
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            cancellation_requested=False,
        )

    def observe(_: TaskLease) -> HeartbeatResult:
        observed.set()
        return HeartbeatResult(
            lease_expires_at=lease.lease_expires_at,
            cancellation_requested=True,
        )

    monitor = LeaseMonitor(
        heartbeat=heartbeat,
        observe=observe,
        lease=lease,
        heartbeat_seconds=30,
        cancellation_poll_seconds=0.01,
    )
    monitor.start()
    try:
        assert observed.wait(timeout=0.5)
        assert monitor.should_stop() is True
        assert monitor.cancel_requested is True
        assert heartbeat_calls == 0
    finally:
        monitor.stop()


def test_observed_missing_lease_is_fenced_without_heartbeat() -> None:
    lease = _lease()
    observed = threading.Event()

    def observe(_: TaskLease) -> None:
        observed.set()
        return None

    monitor = LeaseMonitor(
        heartbeat=lambda _: None,
        observe=observe,
        lease=lease,
        heartbeat_seconds=30,
        cancellation_poll_seconds=0.01,
    )
    monitor.start()
    try:
        assert observed.wait(timeout=0.5)
        assert monitor.lost_lease is True
    finally:
        monitor.stop()
