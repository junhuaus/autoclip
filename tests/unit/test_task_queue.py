from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine

import liveclip.db.task_queue as task_queue_module
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import DeliveryRow, PipelineRunRow, ProjectRow, TaskAttemptRow, TaskRow
from liveclip.db.task_queue import (
    CompletionResult,
    SQLiteTaskQueue,
    TaskLease,
    TaskOperationConflict,
    TaskSpec,
)
from liveclip.domain.state_transitions import (
    AttemptOutcome,
    DeliveryStatus,
    FailureClass,
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
    TaskStatus,
)

NOW = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
PROJECT_ID = "p" * 32
RUN_ID = "r" * 32


@pytest.fixture
def queue_context(tmp_path: Path) -> Iterator[tuple[Engine, SQLiteTaskQueue]]:
    engine = create_sqlite_engine(tmp_path / "queue.sqlite3", busy_timeout_ms=1_000)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=PROJECT_ID,
                name="Queue project",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=NOW,
                updated_at=NOW,
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
                created_at=NOW,
                updated_at=NOW,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=10)
    try:
        yield engine, queue
    finally:
        engine.dispose(close=True)


def _spec(
    suffix: str,
    *,
    priority: int = 100,
    resource_class: ResourceClass = ResourceClass.HEAVY,
    depends_on_task_id: str | None = None,
    not_before: datetime | None = None,
    max_retries: int = 3,
    fingerprint: str | None = None,
) -> TaskSpec:
    return TaskSpec(
        kind=TaskKind.RENDER,
        target_id=(suffix * 32)[:32],
        operation_key=f"render:{suffix}",
        input_fingerprint=fingerprint or (suffix[0].lower() * 64),
        pipeline_run_id=RUN_ID,
        resource_class=resource_class,
        priority=priority,
        depends_on_task_id=depends_on_task_id,
        not_before=not_before,
        max_retries=max_retries,
        expected_generation=1,
        expected_revision=1,
        expected_revision_epoch=0,
    )


def _task_status(engine: Engine, task_id: str) -> str:
    with engine.connect() as connection:
        value = connection.scalar(select(TaskRow.status).where(TaskRow.id == task_id))
    assert isinstance(value, str)
    return value


def test_enqueue_is_idempotent_and_rejects_operation_key_reuse(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    first = queue.enqueue(_spec("a"), now=NOW)
    repeated = queue.enqueue(_spec("a"), now=NOW)

    assert repeated == first.__class__(task_id=first.task_id, created=False)
    with pytest.raises(TaskOperationConflict, match="different task input"):
        queue.enqueue(_spec("a", fingerprint="b" * 64), now=NOW)
    for changed in (
        replace(_spec("a"), priority=101),
        replace(_spec("a"), resource_class=ResourceClass.CHEAP),
        replace(_spec("a"), max_retries=4),
        replace(_spec("a"), expected_revision=2),
    ):
        with pytest.raises(TaskOperationConflict, match="different task input"):
            queue.enqueue(changed, now=NOW)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(TaskRow)) == 1


def test_two_simultaneous_claimers_obtain_exactly_one_lease(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a"), now=NOW).task_id
    barrier = Barrier(3)

    def claim(worker: str) -> TaskLease | None:
        barrier.wait()
        return queue.claim(worker_id=worker, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim, worker) for worker in ("worker-a", "worker-b")]
        barrier.wait()
        results = [future.result(timeout=5) for future in futures]

    leases = [result for result in results if result is not None]
    assert len(leases) == 1
    assert leases[0].task_id == task_id
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(TaskAttemptRow)) == 1


def test_complete_is_fenced_and_idempotent(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a"), now=NOW).task_id
    lease = queue.claim(worker_id="worker-a", now=NOW)
    assert lease is not None

    assert queue.complete(lease, now=NOW + timedelta(seconds=1)) == CompletionResult.COMPLETED
    assert (
        queue.complete(lease, now=NOW + timedelta(seconds=1)) == CompletionResult.ALREADY_SUCCEEDED
    )
    assert _task_status(engine, task_id) == TaskStatus.SUCCEEDED.value
    with engine.connect() as connection:
        outcome = connection.scalar(
            select(TaskAttemptRow.outcome).where(TaskAttemptRow.task_id == task_id)
        )
    assert outcome == AttemptOutcome.SUCCEEDED.value


def test_completion_deferral_preserves_retries_and_parks_human_wait(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    spec = TaskSpec(
        kind=TaskKind.COMPLETION,
        target_id="i" * 32,
        operation_key="completion:goal-i",
        input_fingerprint="d" * 64,
        pipeline_run_id=RUN_ID,
        resource_class=ResourceClass.CHEAP,
        expected_generation=1,
    )
    task_id = queue.enqueue(spec, now=NOW).task_id
    first = queue.claim(worker_id="completion-worker", now=NOW, task_kind=TaskKind.COMPLETION)
    assert first is not None
    assert queue.defer_completion(first, wait_ms=5_000, now=NOW + timedelta(seconds=1)) == (
        TaskStatus.QUEUED
    )
    assert queue.claim(worker_id="completion-worker", now=NOW + timedelta(seconds=5)) is None
    second = queue.claim(
        worker_id="completion-worker",
        now=NOW + timedelta(seconds=6),
        task_kind=TaskKind.COMPLETION,
    )
    assert second is not None
    assert queue.defer_completion(second, wait_ms=None, now=NOW + timedelta(seconds=7)) == (
        TaskStatus.WAITING
    )
    assert queue.claim(worker_id="completion-worker", now=NOW + timedelta(days=1)) is None
    with engine.connect() as connection:
        task = connection.execute(
            select(TaskRow.status, TaskRow.attempt_count, TaskRow.retry_count).where(
                TaskRow.id == task_id
            )
        ).one()
        outcomes = connection.scalars(
            select(TaskAttemptRow.outcome)
            .where(TaskAttemptRow.task_id == task_id)
            .order_by(TaskAttemptRow.attempt_number)
        ).all()
    assert task == (TaskStatus.WAITING.value, 2, 0)
    assert outcomes == [AttemptOutcome.DEFERRED.value, AttemptOutcome.DEFERRED.value]
    assert queue.request_cancel(task_id, now=NOW + timedelta(days=1)) == TaskStatus.CANCELLED


def test_completion_deferral_uses_clock_after_writer_lock(
    queue_context: tuple[Engine, SQLiteTaskQueue],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(
        TaskSpec(
            kind=TaskKind.COMPLETION,
            target_id="j" * 32,
            operation_key="completion:goal-j",
            input_fingerprint="e" * 64,
            pipeline_run_id=RUN_ID,
            resource_class=ResourceClass.CHEAP,
            expected_generation=1,
        ),
        now=NOW,
    ).task_id
    lease = queue.claim(worker_id="completion-worker", now=NOW, task_kind=TaskKind.COMPLETION)
    assert lease is not None
    entered = Event()
    clock = [NOW + timedelta(seconds=1)]
    original_begin = task_queue_module.begin_immediate
    original_now = task_queue_module._now

    @contextmanager
    def observed_begin(target_engine: Engine) -> Iterator[Connection]:
        entered.set()
        with original_begin(target_engine) as connection:
            yield connection

    def controlled_now(value: datetime | None) -> datetime:
        return clock[0] if value is None else original_now(value)

    monkeypatch.setattr(task_queue_module, "begin_immediate", observed_begin)
    monkeypatch.setattr(task_queue_module, "_now", controlled_now)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with original_begin(engine):
            future = executor.submit(queue.defer_completion, lease, wait_ms=1_000)
            assert entered.wait(5)
            clock[0] = NOW + timedelta(seconds=11)
        assert future.result(timeout=5) is None
    with engine.connect() as connection:
        state = connection.execute(
            select(TaskRow.status, TaskRow.retry_count).where(TaskRow.id == task_id)
        ).one()
        outcome = connection.scalar(
            select(TaskAttemptRow.outcome).where(TaskAttemptRow.task_id == task_id)
        )
    assert state == (TaskStatus.RUNNING.value, 0)
    assert outcome == AttemptOutcome.RUNNING.value
    assert queue.recover_expired(now=NOW + timedelta(seconds=11)).requeued == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(TaskAttemptRow.outcome).where(TaskAttemptRow.task_id == task_id)
            )
            == AttemptOutcome.LOST_LEASE.value
        )

    successor = queue.claim(
        worker_id="completion-worker",
        now=NOW + timedelta(seconds=11),
        task_kind=TaskKind.COMPLETION,
    )
    assert successor is not None
    entered.clear()
    clock[0] = NOW + timedelta(seconds=12)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with original_begin(engine):
            future = executor.submit(queue.defer_completion, successor, wait_ms=1_000)
            assert entered.wait(5)
            clock[0] = NOW + timedelta(seconds=13)
        assert future.result(timeout=5) == TaskStatus.QUEUED
    with engine.connect() as connection:
        scheduled = connection.scalar(select(TaskRow.not_before).where(TaskRow.id == task_id))
    assert scheduled == NOW + timedelta(seconds=14)


def test_heavy_singleton_does_not_block_a_cheap_task(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    _, queue = queue_context
    first_id = queue.enqueue(_spec("a", priority=300), now=NOW).task_id
    second_id = queue.enqueue(_spec("b", priority=200), now=NOW).task_id
    cheap_id = queue.enqueue(
        _spec("c", priority=100, resource_class=ResourceClass.CHEAP), now=NOW
    ).task_id

    first = queue.claim(worker_id="worker-a", now=NOW)
    second = queue.claim(worker_id="worker-b", now=NOW)
    assert first is not None and first.task_id == first_id
    assert second is not None and second.task_id == cheap_id
    assert queue.claim(worker_id="worker-c", now=NOW) is None

    assert queue.complete(first, now=NOW + timedelta(seconds=1)) == CompletionResult.COMPLETED
    third = queue.claim(worker_id="worker-c", now=NOW + timedelta(seconds=1))
    assert third is not None and third.task_id == second_id


def test_dependency_and_not_before_are_enforced_without_sleep(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    _, queue = queue_context
    parent_id = queue.enqueue(_spec("a"), now=NOW).task_id
    child_id = queue.enqueue(_spec("b", depends_on_task_id=parent_id), now=NOW).task_id
    future_id = queue.enqueue(
        _spec("c", not_before=NOW + timedelta(minutes=1), priority=500), now=NOW
    ).task_id

    parent = queue.claim(worker_id="worker-a", now=NOW)
    assert parent is not None and parent.task_id == parent_id
    assert queue.claim(worker_id="worker-b", now=NOW) is None
    queue.complete(parent, now=NOW + timedelta(seconds=1))

    child = queue.claim(worker_id="worker-b", now=NOW + timedelta(seconds=1))
    assert child is not None and child.task_id == child_id
    queue.complete(child, now=NOW + timedelta(seconds=2))
    future = queue.claim(worker_id="worker-c", now=NOW + timedelta(minutes=1))
    assert future is not None and future.task_id == future_id


def test_expiry_boundary_recovers_and_fences_the_old_worker(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a"), now=NOW).task_id
    old_lease = queue.claim(worker_id="worker-a", now=NOW)
    assert old_lease is not None
    expiry = NOW + timedelta(seconds=10)

    assert queue.heartbeat(old_lease, now=expiry) is None
    recovery = queue.recover_expired(now=expiry)
    assert recovery.requeued == 1
    new_lease = queue.claim(worker_id="worker-b", now=expiry)
    assert new_lease is not None and new_lease.attempt_number == 2
    assert new_lease.lease_token != old_lease.lease_token
    assert queue.complete(old_lease, now=expiry) == CompletionResult.LOST_LEASE
    assert queue.heartbeat(old_lease, now=expiry) is None
    assert (
        queue.complete(new_lease, now=expiry + timedelta(seconds=1)) == CompletionResult.COMPLETED
    )

    with engine.connect() as connection:
        attempts = connection.execute(
            select(TaskAttemptRow.attempt_number, TaskAttemptRow.outcome)
            .where(TaskAttemptRow.task_id == task_id)
            .order_by(TaskAttemptRow.attempt_number)
        ).all()
    assert attempts == [
        (1, AttemptOutcome.LOST_LEASE.value),
        (2, AttemptOutcome.SUCCEEDED.value),
    ]


def test_crash_recovery_exhausts_exact_retry_budget(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a", max_retries=1), now=NOW).task_id
    first = queue.claim(worker_id="worker-a", now=NOW)
    assert first is not None
    assert queue.recover_expired(now=NOW + timedelta(seconds=10)).requeued == 1
    second = queue.claim(worker_id="worker-b", now=NOW + timedelta(seconds=10))
    assert second is not None and second.attempt_number == 2

    exhausted = queue.recover_expired(now=NOW + timedelta(seconds=20))
    assert exhausted.failed == 1
    assert _task_status(engine, task_id) == TaskStatus.FAILED.value
    with engine.connect() as connection:
        retry_count = connection.scalar(select(TaskRow.retry_count).where(TaskRow.id == task_id))
    assert retry_count == 1


def test_transient_failure_requeues_with_backoff_but_deterministic_failure_does_not(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    transient_id = queue.enqueue(_spec("a"), now=NOW).task_id
    transient = queue.claim(worker_id="worker-a", now=NOW)
    assert transient is not None
    assert (
        queue.fail(
            transient,
            failure_class=FailureClass.TRANSIENT,
            error_code="PROVIDER_TIMEOUT",
            safe_message="Provider request timed out",
            retry_delay_ms=5_000,
            now=NOW + timedelta(seconds=1),
        )
        == TaskStatus.QUEUED
    )
    assert queue.claim(worker_id="worker-b", now=NOW + timedelta(seconds=5)) is None
    retry = queue.claim(worker_id="worker-b", now=NOW + timedelta(seconds=6))
    assert retry is not None and retry.task_id == transient_id
    queue.complete(retry, now=NOW + timedelta(seconds=7))

    deterministic_id = queue.enqueue(_spec("b"), now=NOW).task_id
    deterministic = queue.claim(worker_id="worker-c", now=NOW + timedelta(seconds=7))
    assert deterministic is not None and deterministic.task_id == deterministic_id
    assert (
        queue.fail(
            deterministic,
            failure_class=FailureClass.DETERMINISTIC,
            error_code="SOURCE_CHANGED",
            safe_message="Source media changed after import",
            now=NOW + timedelta(seconds=8),
        )
        == TaskStatus.FAILED
    )
    assert _task_status(engine, deterministic_id) == TaskStatus.FAILED.value


def test_transient_delivery_failure_keeps_resource_retryable(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    delivery_id = "d" * 32
    task = queue.enqueue(
        replace(
            _spec("d", max_retries=1),
            kind=TaskKind.DELIVERY,
            target_id=delivery_id,
            operation_key=f"delivery:{delivery_id}",
            expected_revision=None,
        ),
        now=NOW,
    )
    with engine.begin() as connection:
        connection.execute(
            insert(DeliveryRow).values(
                id=delivery_id,
                project_id=PROJECT_ID,
                task_id=task.task_id,
                version=1,
                status=DeliveryStatus.QUEUED.value,
                expected_revision_epoch=0,
                expected_generation=1,
                snapshot_fingerprint="d" * 64,
                directory_relative_path="deliveries/v001",
                include_zip=True,
                created_at=NOW,
            )
        )
    lease = queue.claim(worker_id="delivery-a", now=NOW, task_kind=TaskKind.DELIVERY)
    assert lease is not None
    with engine.begin() as connection:
        connection.execute(
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id)
            .values(status=DeliveryStatus.CREATING.value)
        )

    result = queue.fail(
        lease,
        failure_class=FailureClass.TRANSIENT,
        error_code="DELIVERY_IO_TEMPORARY",
        safe_message="temporary output failure",
        retry_delay_ms=0,
        now=NOW + timedelta(seconds=1),
    )

    assert result == TaskStatus.QUEUED
    with engine.connect() as connection:
        delivery = connection.execute(
            select(DeliveryRow.status, DeliveryRow.completed_at).where(
                DeliveryRow.id == delivery_id
            )
        ).one()
    assert delivery == (DeliveryStatus.QUEUED.value, None)
    retry = queue.claim(
        worker_id="delivery-b",
        now=NOW + timedelta(seconds=1),
        task_kind=TaskKind.DELIVERY,
    )
    assert retry is not None and retry.task_id == task.task_id


def test_running_cancel_is_a_request_until_owner_acknowledges(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    queued_id = queue.enqueue(_spec("a"), now=NOW).task_id
    assert queue.request_cancel(queued_id, now=NOW) == TaskStatus.CANCELLED
    assert queue.claim(worker_id="worker-a", now=NOW) is None

    running_id = queue.enqueue(_spec("b"), now=NOW).task_id
    lease = queue.claim(worker_id="worker-b", now=NOW)
    assert lease is not None
    assert queue.request_cancel(running_id, now=NOW + timedelta(seconds=1)) == TaskStatus.RUNNING
    observed = queue.observe(lease, now=NOW + timedelta(milliseconds=1500))
    assert observed is not None
    assert observed.lease_expires_at == lease.lease_expires_at
    assert observed.cancellation_requested is True
    heartbeat = queue.heartbeat(lease, now=NOW + timedelta(seconds=2))
    assert heartbeat is not None and heartbeat.cancellation_requested is True
    assert (
        queue.complete(lease, now=NOW + timedelta(seconds=2))
        == CompletionResult.CANCELLATION_REQUESTED
    )
    assert queue.acknowledge_cancel(lease, now=NOW + timedelta(seconds=3)) is True
    assert _task_status(engine, running_id) == TaskStatus.CANCELLED.value


def test_failure_recording_after_cancel_keeps_cancellation_terminal(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a"), now=NOW).task_id
    lease = queue.claim(worker_id="worker-a", now=NOW)
    assert lease is not None
    queue.request_cancel(task_id, now=NOW + timedelta(seconds=1))

    status = queue.fail(
        lease,
        failure_class=FailureClass.TRANSIENT,
        error_code="PROVIDER_TIMEOUT",
        safe_message="Provider request timed out",
        now=NOW + timedelta(seconds=2),
    )

    assert status == TaskStatus.CANCELLED
    assert _task_status(engine, task_id) == TaskStatus.CANCELLED.value
    assert queue.claim(worker_id="worker-b", now=NOW + timedelta(seconds=3)) is None
    with engine.connect() as connection:
        outcome = connection.scalar(
            select(TaskAttemptRow.outcome).where(TaskAttemptRow.task_id == task_id)
        )
    assert outcome == AttemptOutcome.CANCELLED.value


def test_expired_cancel_request_becomes_cancelled_not_requeued(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a"), now=NOW).task_id
    lease = queue.claim(worker_id="worker-a", now=NOW)
    assert lease is not None
    queue.request_cancel(task_id, now=NOW + timedelta(seconds=1))

    recovered = queue.recover_expired(now=NOW + timedelta(seconds=10))

    assert recovered.cancelled == 1
    assert _task_status(engine, task_id) == TaskStatus.CANCELLED.value


def test_diagnostic_path_is_fenced_to_the_owned_attempt(
    queue_context: tuple[Engine, SQLiteTaskQueue],
) -> None:
    engine, queue = queue_context
    task_id = queue.enqueue(_spec("a", max_retries=1), now=NOW).task_id
    expired = queue.claim(worker_id="worker-a", now=NOW)
    assert expired is not None
    expiry = NOW + timedelta(seconds=10)
    assert queue.recover_expired(now=expiry).requeued == 1
    current = queue.claim(worker_id="worker-b", now=expiry)
    assert current is not None

    expired_path = (
        f".attempts/{expired.task_id}/{expired.lease_token}/diagnostics/ffmpeg-render.json"
    )
    assert (
        queue.fail(
            expired,
            failure_class=FailureClass.DETERMINISTIC,
            error_code="RENDER_FAILED",
            safe_message="The expired render failed",
            diagnostic_relative_path=expired_path,
            now=expiry + timedelta(seconds=1),
        )
        is None
    )
    wrong_path = f".attempts/{current.task_id}/{'f' * 64}/diagnostics/ffmpeg-render.json"
    with pytest.raises(ValueError, match="another attempt"):
        queue.fail(
            current,
            failure_class=FailureClass.DETERMINISTIC,
            error_code="RENDER_FAILED",
            safe_message="The current render failed",
            diagnostic_relative_path=wrong_path,
            now=expiry + timedelta(seconds=1),
        )

    current_path = (
        f".attempts/{current.task_id}/{current.lease_token}/diagnostics/ffmpeg-render.json"
    )
    assert (
        queue.fail(
            current,
            failure_class=FailureClass.DETERMINISTIC,
            error_code="RENDER_FAILED",
            safe_message="The current render failed",
            diagnostic_relative_path=current_path,
            now=expiry + timedelta(seconds=1),
        )
        == TaskStatus.FAILED
    )
    with engine.connect() as connection:
        attempts = connection.execute(
            select(
                TaskAttemptRow.attempt_number,
                TaskAttemptRow.outcome,
                TaskAttemptRow.diagnostic_relative_path,
            )
            .where(TaskAttemptRow.task_id == task_id)
            .order_by(TaskAttemptRow.attempt_number)
        ).all()
    assert attempts == [
        (1, AttemptOutcome.LOST_LEASE.value, None),
        (2, AttemptOutcome.FAILED.value, current_path),
    ]
