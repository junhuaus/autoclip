"""LeaseMonitor renews immediately after a simulated host suspend.

Wall time is shifted with ``ShiftedWallClock`` while monotonic time keeps its
real pace, exactly as a macOS sleep does. Leases are real SQLite task-queue
leases, so fencing is the production ``heartbeat``/``observe`` SQL.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lease_suspend import ShiftedWallClock
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.tasks import HeartbeatResult, TaskLease
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


@dataclass
class _Held:
    engine: Engine
    queue: SQLiteTaskQueue
    lease: TaskLease
    clock: ShiftedWallClock
    heartbeats: list[HeartbeatResult | None]
    observes: list[HeartbeatResult | None]
    heartbeat_done: threading.Event
    observe_done: threading.Event

    def shifted_now(self) -> datetime:
        return datetime.now(UTC) + self.clock.offset

    def stored_expiry(self) -> datetime:
        with self.engine.connect() as connection:
            value = connection.scalar(
                select(TaskRow.lease_expires_at).where(TaskRow.id == self.lease.task_id)
            )
        assert isinstance(value, datetime)
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def monitor(self) -> LeaseMonitor:
        return LeaseMonitor(
            heartbeat=_recording(self.queue.heartbeat, self.heartbeats, self.heartbeat_done),
            observe=_recording(self.queue.observe, self.observes, self.observe_done),
            lease=self.lease,
            heartbeat_seconds=HEARTBEAT_SECONDS,
            cancellation_poll_seconds=0.01,
        )


def _recording(
    operation: Callable[[TaskLease], HeartbeatResult | None],
    results: list[HeartbeatResult | None],
    done: threading.Event,
) -> Callable[[TaskLease], HeartbeatResult | None]:
    def call(lease: TaskLease) -> HeartbeatResult | None:
        result = operation(lease)
        results.append(result)
        done.set()
        return result

    return call


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
        yield _Held(
            engine=engine,
            queue=queue,
            lease=lease,
            clock=clock,
            heartbeats=[],
            observes=[],
            heartbeat_done=threading.Event(),
            observe_done=threading.Event(),
        )
    finally:
        engine.dispose(close=True)


def _wait_for_polls(held: _Held, count: int) -> None:
    deadline = time.monotonic() + 5
    while len(held.observes) < count:
        assert time.monotonic() < deadline, "monitor did not poll"
        time.sleep(0.005)


@pytest.mark.integration
def test_suspend_shorter_than_lease_renews_immediately_and_keeps_the_lease(
    held: _Held,
) -> None:
    # Longer than lease - heartbeat (90 s), shorter than the 120 s lease: before
    # the monitor detected the jump, the heartbeat paced on monotonic time came
    # 30 s after wake, past expiry, and the lease was lost.
    suspend = timedelta(seconds=LEASE_SECONDS - 10)
    assert suspend > timedelta(seconds=LEASE_SECONDS - HEARTBEAT_SECONDS)
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, 1)
        assert held.heartbeats == []
        held.clock.suspend(suspend)
        assert held.heartbeat_done.wait(timeout=5)
    finally:
        monitor.stop()

    assert len(held.heartbeats) == 1
    renewed = held.heartbeats[0]
    assert renewed is not None
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
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, 1)
        held.clock.suspend(timedelta(seconds=LEASE_SECONDS + 1))
        assert held.heartbeat_done.wait(timeout=5)
        monitor._thread.join(timeout=5)
        assert not monitor._thread.is_alive()
    finally:
        monitor.stop()

    # The immediate renewal is refused by the fenced heartbeat; nothing is resurrected.
    assert held.heartbeats == [None]
    assert monitor.lost_lease is True
    assert monitor.should_stop() is True
    assert held.stored_expiry() == original_expiry
    assert held.queue.heartbeat(held.lease) is None


@pytest.mark.integration
def test_without_a_wall_clock_jump_the_heartbeat_schedule_is_unchanged(
    held: _Held,
) -> None:
    original_expiry = held.stored_expiry()
    monitor = held.monitor()
    monitor.start()
    try:
        _wait_for_polls(held, 3)
        # A sub-threshold step (for example an NTP correction) is not a suspend.
        held.clock.suspend(timedelta(milliseconds=500))
        polls = len(held.observes)
        _wait_for_polls(held, polls + 20)
    finally:
        monitor.stop()

    assert held.heartbeats == []
    assert all(result is not None for result in held.observes)
    assert monitor.lost_lease is False
    assert held.stored_expiry() == original_expiry
