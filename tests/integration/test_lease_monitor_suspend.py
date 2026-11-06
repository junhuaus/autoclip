"""LeaseMonitor renews early after a simulated host suspend.

Wall time is shifted with ``ShiftedWallClock`` while monotonic time keeps its
real pace, exactly as a macOS sleep does. Leases are real SQLite task-queue
leases, so fencing is the production ``heartbeat``/``observe`` SQL.

A suspend during monitoring is applied from inside the monitor thread, right
after an ``observe`` call returns, so it always lands between two polls and the
outcome does not depend on thread scheduling.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from lease_suspend import ShiftedWallClock
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

import liveclip.application.lease_monitor as lease_monitor_module
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.tasks import HeartbeatResult, TaskLease, TaskQueueTransientError
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import PipelineRunRow, ProjectRow, TaskRow
from liveclip.db.task_queue import SQLiteTaskQueue, TaskSpec
from liveclip.domain.state_transitions import PipelineRunStatus, ResourceClass, TaskKind

# The production defaults (Settings.worker_lease_seconds / worker_heartbeat_seconds).
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
PROJECT_ID = "p" * 32
RUN_ID = "r" * 32
# The monitor renews on every poll once less than half an interval remains.
RENEW_WITHIN_SECONDS = HEARTBEAT_SECONDS / 2
FAILED = "failed"
# Upper bound for waiting on the monitor thread.  A passing run takes
# milliseconds; the bound only has to survive a starved thread on a loaded host.
WAIT_SECONDS = 30


@dataclass
class _Held:
    engine: Engine
    queue: SQLiteTaskQueue
    lease: TaskLease
    clock: ShiftedWallClock
    heartbeats: list[HeartbeatResult | str | None] = field(default_factory=list)
    observes: list[HeartbeatResult | None] = field(default_factory=list)
    heartbeat_done: threading.Event = field(default_factory=threading.Event)
    suspend_after_observe: dict[int, timedelta] = field(default_factory=dict)
    failing_heartbeats: int = 0
    # (observe calls, heartbeat calls) when the first renewal succeeded, read in
    # the monitor thread, so assertions on it do not depend on how quickly the
    # main thread stops the monitor afterwards.
    first_renewal: tuple[int, int] | None = None

    def shifted_now(self) -> datetime:
        return datetime.now(UTC) + self.clock.offset

    def stored_expiry(self) -> datetime:
        with self.engine.connect() as connection:
            value = connection.scalar(
                select(TaskRow.lease_expires_at).where(TaskRow.id == self.lease.task_id)
            )
        assert isinstance(value, datetime)
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def heartbeat(self, lease: TaskLease) -> HeartbeatResult | None:
        if self.failing_heartbeats:
            self.failing_heartbeats -= 1
            self.heartbeats.append(FAILED)
            raise TaskQueueTransientError("simulated locked database")
        result = self.queue.heartbeat(lease)
        self.heartbeats.append(result)
        if result is not None and self.first_renewal is None:
            self.first_renewal = (len(self.observes), len(self.heartbeats))
            self.heartbeat_done.set()
        return result

    def observe(self, lease: TaskLease) -> HeartbeatResult | None:
        result = self.queue.observe(lease)
        self.observes.append(result)
        # Runs in the monitor thread between two polls: deterministic.
        duration = self.suspend_after_observe.pop(len(self.observes), None)
        if duration is not None:
            self.clock.suspend(duration)
        return result

    def monitor(self) -> LeaseMonitor:
        return LeaseMonitor(
            heartbeat=self.heartbeat,
            observe=self.observe,
            lease=self.lease,
            heartbeat_seconds=HEARTBEAT_SECONDS,
            cancellation_poll_seconds=0.01,
        )


@pytest.fixture
def held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Held]:
    clock = ShiftedWallClock(monkeypatch)
    engine = create_sqlite_engine(tmp_path / "queue.sqlite3", busy_timeout_ms=1_000)
    Base.metadata.create_all(engine)
    created = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=PROJECT_ID,
                name="Lease project",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=created,
                updated_at=created,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=RUN_ID,
                project_id=PROJECT_ID,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"top_n": 15},
                config_fingerprint="c" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=created,
                updated_at=created,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
    queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="t" * 32,
            operation_key="render:suspend",
            input_fingerprint="f" * 64,
            pipeline_run_id=RUN_ID,
            resource_class=ResourceClass.HEAVY,
            priority=100,
            depends_on_task_id=None,
            not_before=None,
            max_retries=3,
            expected_generation=1,
            expected_revision=1,
            expected_revision_epoch=0,
        )
    )
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    try:
        yield _Held(engine=engine, queue=queue, lease=lease, clock=clock)
    finally:
        engine.dispose(close=True)


def _wait_for_polls(held: _Held, monitor: LeaseMonitor, count: int) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while len(held.observes) < count:
        assert time.monotonic() < deadline, (
            f"monitor did not poll: observes={len(held.observes)} "
            f"heartbeats={held.heartbeats!r} "
            f"thread_alive={monitor._thread.is_alive()} lost_lease={monitor.lost_lease}"
        )
        time.sleep(0.005)


def _wait_until_stopped(monitor: LeaseMonitor) -> None:
    monitor._thread.join(timeout=WAIT_SECONDS)
    assert not monitor._thread.is_alive()


@pytest.mark.integration
@pytest.mark.parametrize("asleep_seconds", [95, 110])
def test_suspend_shorter_than_lease_renews_immediately_and_keeps_the_lease(
    held: _Held, asleep_seconds: int
) -> None:
    # Longer than lease - heartbeat (90 s), shorter than the 120 s lease: before
    # Stage 6 the heartbeat paced on monotonic time came 30 s after wake, past
    # expiry, and the lease was lost.  At 95 s only the jump rule fires (25 s
    # remain); at 110 s the remaining-lease rule fires as well.
    suspend = timedelta(seconds=asleep_seconds)
    assert suspend > timedelta(seconds=LEASE_SECONDS - HEARTBEAT_SECONDS)
    held.suspend_after_observe[1] = suspend
    monitor = held.monitor()
    monitor.start()
    try:
        assert held.heartbeat_done.wait(timeout=WAIT_SECONDS)
    finally:
        monitor.stop()

    # Renewed by the first heartbeat, on the poll right after the suspend.
    assert held.first_renewal == (1, 1)
    renewed = held.heartbeats[0]
    assert isinstance(renewed, HeartbeatResult)
    assert monitor.lost_lease is False
    assert held.stored_expiry() == renewed.lease_expires_at
    # The renewal happened on the post-suspend wall clock.
    assert renewed.lease_expires_at >= held.lease.lease_expires_at + suspend
    # So the next heartbeat, one monotonic interval later, still finds the lease.
    later = held.shifted_now() + timedelta(seconds=HEARTBEAT_SECONDS)
    assert held.queue.heartbeat(held.lease, now=later) is not None


@pytest.mark.integration
def test_suspend_longer_than_lease_still_loses_the_lease(held: _Held) -> None:
    original_expiry = held.stored_expiry()
    held.suspend_after_observe[1] = timedelta(seconds=LEASE_SECONDS + 1)
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_until_stopped(monitor)
    finally:
        monitor.stop()

    # The immediate renewal is refused by the fenced heartbeat; nothing is resurrected.
    assert held.heartbeats == [None]
    assert monitor.lost_lease is True
    assert monitor.should_stop() is True
    assert held.stored_expiry() == original_expiry
    assert held.queue.heartbeat(held.lease) is None


@pytest.mark.integration
def test_failed_renewal_after_a_suspend_is_retried_before_expiry(held: _Held) -> None:
    # Many processes waking together can find SQLite locked.  The renewal that
    # failed is retried on the next poll while less than half an interval of
    # the lease remains, not one monotonic interval (30 s) later.
    suspend = timedelta(seconds=LEASE_SECONDS - 10)
    assert timedelta(seconds=LEASE_SECONDS) - suspend < timedelta(seconds=RENEW_WITHIN_SECONDS)
    held.failing_heartbeats = 1
    held.suspend_after_observe[1] = suspend
    monitor = held.monitor()
    monitor.start()
    try:
        assert held.heartbeat_done.wait(timeout=WAIT_SECONDS)
    finally:
        monitor.stop()

    # The failed renewal and its retry are consecutive polls after the suspend.
    assert held.first_renewal == (1, 2)
    assert held.heartbeats[0] == FAILED
    renewed = held.heartbeats[1]
    assert isinstance(renewed, HeartbeatResult)
    assert monitor.lost_lease is False
    assert held.stored_expiry() == renewed.lease_expires_at
    assert renewed.lease_expires_at >= held.lease.lease_expires_at + suspend


@pytest.mark.integration
def test_suspend_before_the_first_poll_is_renewed_while_unexpired(held: _Held) -> None:
    # The jump rule has no baseline yet; the remaining-lease rule still renews.
    suspend = timedelta(seconds=LEASE_SECONDS - 10)
    held.clock.suspend(suspend)
    monitor = held.monitor()
    monitor.start()
    try:
        assert held.heartbeat_done.wait(timeout=WAIT_SECONDS)
    finally:
        monitor.stop()

    # Renewed by the first heartbeat, on the first poll.
    assert held.first_renewal == (0, 1)
    renewed = held.heartbeats[0]
    assert isinstance(renewed, HeartbeatResult)
    assert monitor.lost_lease is False
    assert renewed.lease_expires_at >= held.lease.lease_expires_at + suspend


@pytest.mark.integration
def test_suspend_before_the_first_poll_past_expiry_still_loses_the_lease(
    held: _Held,
) -> None:
    original_expiry = held.stored_expiry()
    held.clock.suspend(timedelta(seconds=LEASE_SECONDS + 1))
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_until_stopped(monitor)
    finally:
        monitor.stop()

    assert held.heartbeats == [None]
    assert held.observes == []
    assert monitor.lost_lease is True
    assert held.stored_expiry() == original_expiry


@pytest.mark.integration
def test_without_a_wall_clock_jump_the_heartbeat_schedule_is_unchanged(
    held: _Held,
) -> None:
    original_expiry = held.stored_expiry()
    # A sub-threshold step (for example an NTP correction) is not a suspend.
    held.suspend_after_observe[3] = timedelta(milliseconds=500)
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, monitor, 25)
    finally:
        monitor.stop()

    assert not held.suspend_after_observe
    assert held.heartbeats == []
    assert all(result is not None for result in held.observes)
    assert monitor.lost_lease is False
    assert held.stored_expiry() == original_expiry


@pytest.mark.integration
def test_a_stall_between_clock_reads_is_not_a_jump(
    held: _Held, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On a loaded host the monitor thread can be descheduled between its wall
    # and monotonic reads; both clocks then advance together, which is not a
    # suspend.  Inject a 3 s stall right after the monitor's first wall read.
    stall = timedelta(seconds=3)
    clock = held.clock
    real_monotonic = time.monotonic
    monotonic_offset = [0.0]
    pending = [True]
    shifted = lease_monitor_module.datetime

    class StallAfterFirstWallRead(shifted):  # type: ignore[misc,valid-type]
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def,override]
            value = super().now(tz)
            if pending[0]:
                pending[0] = False
                clock.suspend(stall)
                monotonic_offset[0] += stall.total_seconds()
            return value

    monkeypatch.setattr(lease_monitor_module, "datetime", StallAfterFirstWallRead)
    monkeypatch.setattr(
        lease_monitor_module,
        "time",
        SimpleNamespace(monotonic=lambda: real_monotonic() + monotonic_offset[0]),
    )
    original_expiry = held.stored_expiry()
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, monitor, 25)
    finally:
        monitor.stop()

    assert pending == [False]
    assert held.heartbeats == []
    assert monitor.lost_lease is False
    assert held.stored_expiry() == original_expiry


@pytest.mark.integration
def test_more_than_half_an_interval_remaining_does_not_renew_early(held: _Held) -> None:
    # Documented threshold: with 25 s of the lease left (10 s above the 15 s
    # rule, slack for a loaded host) and no jump seen by the monitor, the paced
    # schedule is kept.
    held.clock.suspend(timedelta(seconds=LEASE_SECONDS - RENEW_WITHIN_SECONDS - 10))
    original_expiry = held.stored_expiry()
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, monitor, 20)
    finally:
        monitor.stop()

    assert held.heartbeats == []
    assert monitor.lost_lease is False
    assert held.stored_expiry() == original_expiry
