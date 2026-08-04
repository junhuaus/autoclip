from __future__ import annotations

import multiprocessing as mp
import os
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from queue import Empty
from typing import Any

import pytest
from sqlalchemy import select

from liveclip.application.stage_runner import RunOneOutcome, StageTaskRunner
from liveclip.db.base import Base
from liveclip.db.engine import begin_immediate, create_sqlite_engine
from liveclip.db.models import TaskAttemptRow, TaskRow
from liveclip.db.task_queue import CompletionResult, SQLiteTaskQueue, TaskLease, TaskSpec
from liveclip.domain.state_transitions import (
    AttemptOutcome,
    FailureClass,
    TaskKind,
    TaskStatus,
)

BASE_TIME = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
LEASE_SECONDS = 5
PROCESS_TIMEOUT_SECONDS = 15.0


def _create_task(database_path: Path) -> str:
    engine = create_sqlite_engine(database_path, busy_timeout_ms=2_000)
    try:
        Base.metadata.create_all(engine)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        return queue.enqueue(
            TaskSpec(
                kind=TaskKind.RENDER,
                target_id="r" * 32,
                operation_key="process-test:render",
                input_fingerprint="a" * 64,
                max_retries=3,
            ),
            now=BASE_TIME,
        ).task_id
    finally:
        engine.dispose(close=True)


def _claim_after_signal(
    database_path: str,
    worker_id: str,
    claim_time: datetime,
    ready: Any,
    start: Any,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        ready.put(("ready", worker_id))
        if not start.wait(PROCESS_TIMEOUT_SECONDS):
            raise TimeoutError("claim start signal was not received")
        lease = queue.claim(worker_id=worker_id, now=claim_time)
        results.put(("claim", worker_id, lease))
    except BaseException as exc:
        results.put(("error", worker_id, f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _claim_once(
    database_path: str,
    worker_id: str,
    claim_time: datetime,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        results.put(("claim", worker_id, queue.claim(worker_id=worker_id, now=claim_time)))
    except BaseException as exc:
        results.put(("error", worker_id, f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _heartbeat_owner(
    database_path: str,
    heartbeat_signal: Any,
    finish_signal: Any,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        lease = queue.claim(worker_id="heartbeat-owner", now=BASE_TIME)
        if lease is None:
            raise RuntimeError("heartbeat owner did not acquire the task")
        results.put(("claimed", lease))
        if not heartbeat_signal.wait(PROCESS_TIMEOUT_SECONDS):
            raise TimeoutError("heartbeat signal was not received")
        heartbeat = queue.heartbeat(lease, now=BASE_TIME + timedelta(seconds=4))
        if heartbeat is None:
            raise RuntimeError("owner lost its lease before heartbeat")
        results.put(("heartbeat", heartbeat.lease_expires_at))
        if not finish_signal.wait(PROCESS_TIMEOUT_SECONDS):
            raise TimeoutError("owner finish signal was not received")
        completion = queue.complete(lease, now=BASE_TIME + timedelta(seconds=7))
        results.put(("complete", completion.value))
    except BaseException as exc:
        results.put(("error", "heartbeat-owner", f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _claim_then_crash(
    database_path: str,
    claimed_connection: Connection,
) -> None:
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        lease = queue.claim(worker_id="crashed-owner", now=BASE_TIME)
        if lease is None:
            claimed_connection.send(("error", "crashed owner did not acquire the task"))
            os._exit(24)
        claimed_connection.send(("claimed", lease))
        claimed_connection.close()
        os._exit(23)
    except BaseException as exc:
        claimed_connection.send(("error", f"{type(exc).__name__}: {exc}"))
        claimed_connection.close()
        os._exit(24)


def _take_over_and_fence(
    database_path: str,
    old_lease: TaskLease,
    takeover_time: datetime,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        new_lease = queue.claim(worker_id="recovery-owner", now=takeover_time)
        if new_lease is None:
            raise RuntimeError("expired task was not recovered and claimed")
        fence_time = takeover_time + timedelta(milliseconds=250)
        old_completion = queue.complete(old_lease, now=fence_time)
        old_heartbeat = queue.heartbeat(old_lease, now=fence_time)
        new_completion = queue.complete(
            new_lease,
            now=takeover_time + timedelta(seconds=1),
        )
        results.put(
            (
                "takeover",
                new_lease,
                old_completion.value,
                old_heartbeat is None,
                new_completion.value,
            )
        )
    except BaseException as exc:
        results.put(("error", "recovery-owner", f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _hold_writer_lock(
    database_path: str,
    release_signal: Any,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=2_000)
        with begin_immediate(engine):
            results.put(("locked",))
            if not release_signal.wait(PROCESS_TIMEOUT_SECONDS):
                raise TimeoutError("writer lock release signal was not received")
        results.put(("released",))
    except BaseException as exc:
        results.put(("error", "lock-holder", f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _exercise_busy_application_path(
    database_path: str,
    attempt_signal: Any,
    retry_signal: Any,
    results: Any,
) -> None:
    engine = None
    try:
        engine = create_sqlite_engine(Path(database_path), busy_timeout_ms=50)
        queue = SQLiteTaskQueue(engine, lease_seconds=LEASE_SECONDS)
        runner = StageTaskRunner(
            queue=queue,
            repository=object(),  # type: ignore[arg-type]
            pipeline_service=object(),  # type: ignore[arg-type]
            handler=object(),  # type: ignore[arg-type]
            heartbeat_seconds=1,
        )
        results.put(("ready",))
        if not attempt_signal.wait(PROCESS_TIMEOUT_SECONDS):
            raise TimeoutError("busy attempt signal was not received")
        outcome = runner.run_one(worker_id="busy-worker")
        results.put(("application-outcome", outcome.value))
        if not retry_signal.wait(PROCESS_TIMEOUT_SECONDS):
            raise TimeoutError("retry signal was not received")
        lease = queue.claim(worker_id="busy-worker-retry", now=BASE_TIME)
        if lease is None:
            raise RuntimeError("queue did not claim the task after contention cleared")
        completion = queue.complete(lease, now=BASE_TIME + timedelta(seconds=1))
        results.put(("retry", lease.task_id, completion.value))
    except BaseException as exc:
        results.put(("error", "busy-worker", f"{type(exc).__name__}: {exc}"))
    finally:
        if engine is not None:
            engine.dispose(close=True)


def _message(results: Any) -> tuple[Any, ...]:
    try:
        message = results.get(timeout=PROCESS_TIMEOUT_SECONDS)
    except Empty:
        pytest.fail("spawned process did not report within the bounded timeout")
    assert isinstance(message, tuple)
    return message


def _join(process: Any, *, expected_exit_code: int = 0) -> None:
    process.join(PROCESS_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(3)
        pytest.fail(f"spawned process {process.name} exceeded its bounded timeout")
    assert process.exitcode == expected_exit_code


def _terminate(processes: list[Any]) -> None:
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(3)


@pytest.mark.integration
def test_spawned_concurrent_claims_have_exactly_one_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent.sqlite3"
    task_id = _create_task(database_path)
    context = mp.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_after_signal,
            args=(str(database_path), worker_id, BASE_TIME, ready, start, results),
            name=worker_id,
        )
        for worker_id in ("process-worker-a", "process-worker-b")
    ]
    try:
        for process in processes:
            process.start()
        assert {_message(ready)[1] for _ in processes} == {
            "process-worker-a",
            "process-worker-b",
        }
        start.set()
        messages = [_message(results) for _ in processes]
        for process in processes:
            _join(process)
    finally:
        start.set()
        _terminate(processes)

    assert all(message[0] == "claim" for message in messages), messages
    leases = [message[2] for message in messages if message[2] is not None]
    assert len(leases) == 1
    assert leases[0].task_id == task_id
    assert {message[1] for message in messages} == {"process-worker-a", "process-worker-b"}

    engine = create_sqlite_engine(database_path, busy_timeout_ms=2_000)
    try:
        with engine.connect() as connection:
            attempts = connection.execute(
                select(TaskAttemptRow.task_id, TaskAttemptRow.worker_id)
            ).all()
            task = connection.execute(
                select(TaskRow.status, TaskRow.worker_id).where(TaskRow.id == task_id)
            ).one()
        assert attempts == [(task_id, leases[0].worker_id)]
        assert task == (TaskStatus.RUNNING.value, leases[0].worker_id)
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_spawned_heartbeat_prevents_takeover_past_original_expiry(tmp_path: Path) -> None:
    database_path = tmp_path / "heartbeat.sqlite3"
    task_id = _create_task(database_path)
    context = mp.get_context("spawn")
    heartbeat_signal = context.Event()
    finish_signal = context.Event()
    owner_results = context.Queue()
    contender_results = context.Queue()
    owner = context.Process(
        target=_heartbeat_owner,
        args=(str(database_path), heartbeat_signal, finish_signal, owner_results),
        name="heartbeat-owner",
    )
    contender = context.Process(
        target=_claim_once,
        args=(
            str(database_path),
            "heartbeat-contender",
            BASE_TIME + timedelta(seconds=6),
            contender_results,
        ),
        name="heartbeat-contender",
    )
    processes = [owner, contender]
    try:
        owner.start()
        claimed = _message(owner_results)
        assert claimed[0] == "claimed", claimed
        heartbeat_signal.set()
        heartbeat = _message(owner_results)
        assert heartbeat == ("heartbeat", BASE_TIME + timedelta(seconds=9))

        contender.start()
        contender_message = _message(contender_results)
        _join(contender)
        assert contender_message == ("claim", "heartbeat-contender", None)

        finish_signal.set()
        assert _message(owner_results) == ("complete", CompletionResult.COMPLETED.value)
        _join(owner)
    finally:
        heartbeat_signal.set()
        finish_signal.set()
        _terminate(processes)

    assert claimed[1].task_id == task_id
    engine = create_sqlite_engine(database_path, busy_timeout_ms=2_000)
    try:
        with engine.connect() as connection:
            task = connection.execute(
                select(TaskRow.status, TaskRow.attempt_count).where(TaskRow.id == task_id)
            ).one()
            attempts = connection.execute(
                select(TaskAttemptRow.worker_id, TaskAttemptRow.outcome).where(
                    TaskAttemptRow.task_id == task_id
                )
            ).all()
        assert task == (TaskStatus.SUCCEEDED.value, 1)
        assert attempts == [("heartbeat-owner", AttemptOutcome.SUCCEEDED.value)]
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_spawned_owner_crash_recovers_only_after_expiry_and_fences_old_lease(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "crash.sqlite3"
    task_id = _create_task(database_path)
    context = mp.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    crashed_owner = context.Process(
        target=_claim_then_crash,
        args=(str(database_path), child_connection),
        name="crashed-owner",
    )
    early_results = context.Queue()
    recovery_results = context.Queue()
    early_contender = context.Process(
        target=_claim_once,
        args=(
            str(database_path),
            "early-contender",
            BASE_TIME + timedelta(seconds=4, milliseconds=999),
            early_results,
        ),
        name="early-contender",
    )
    recovery_owner: Any = None
    processes = [crashed_owner, early_contender]
    try:
        crashed_owner.start()
        child_connection.close()
        assert parent_connection.poll(PROCESS_TIMEOUT_SECONDS)
        crash_message = parent_connection.recv()
        assert crash_message[0] == "claimed", crash_message
        old_lease = crash_message[1]
        _join(crashed_owner, expected_exit_code=23)

        early_contender.start()
        early_message = _message(early_results)
        _join(early_contender)
        assert early_message == ("claim", "early-contender", None)

        takeover_time = BASE_TIME + timedelta(seconds=LEASE_SECONDS)
        recovery_owner = context.Process(
            target=_take_over_and_fence,
            args=(str(database_path), old_lease, takeover_time, recovery_results),
            name="recovery-owner",
        )
        processes.append(recovery_owner)
        recovery_owner.start()
        recovery_message = _message(recovery_results)
        _join(recovery_owner)
    finally:
        parent_connection.close()
        _terminate(processes)

    assert recovery_message[0] == "takeover", recovery_message
    new_lease = recovery_message[1]
    assert new_lease.task_id == task_id
    assert new_lease.attempt_number == 2
    assert new_lease.lease_token != old_lease.lease_token
    assert recovery_message[2:] == (
        CompletionResult.LOST_LEASE.value,
        True,
        CompletionResult.COMPLETED.value,
    )

    engine = create_sqlite_engine(database_path, busy_timeout_ms=2_000)
    try:
        with engine.connect() as connection:
            task = connection.execute(
                select(
                    TaskRow.status,
                    TaskRow.attempt_count,
                    TaskRow.retry_count,
                    TaskRow.worker_id,
                    TaskRow.lease_token,
                ).where(TaskRow.id == task_id)
            ).one()
            attempts = connection.execute(
                select(
                    TaskAttemptRow.attempt_number,
                    TaskAttemptRow.outcome,
                    TaskAttemptRow.failure_class,
                    TaskAttemptRow.error_code,
                )
                .where(TaskAttemptRow.task_id == task_id)
                .order_by(TaskAttemptRow.attempt_number)
            ).all()
        assert task == (TaskStatus.SUCCEEDED.value, 2, 1, None, None)
        assert attempts == [
            (
                1,
                AttemptOutcome.LOST_LEASE.value,
                FailureClass.TRANSIENT.value,
                "LEASE_EXPIRED",
            ),
            (2, AttemptOutcome.SUCCEEDED.value, None, None),
        ]
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_spawned_begin_immediate_contention_returns_busy_then_retries(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "busy.sqlite3"
    task_id = _create_task(database_path)
    context = mp.get_context("spawn")
    attempt_signal = context.Event()
    retry_signal = context.Event()
    release_signal = context.Event()
    worker_results = context.Queue()
    lock_results = context.Queue()
    worker = context.Process(
        target=_exercise_busy_application_path,
        args=(str(database_path), attempt_signal, retry_signal, worker_results),
        name="busy-worker",
    )
    lock_holder = context.Process(
        target=_hold_writer_lock,
        args=(str(database_path), release_signal, lock_results),
        name="writer-lock-holder",
    )
    processes = [worker, lock_holder]
    try:
        worker.start()
        assert _message(worker_results) == ("ready",)
        lock_holder.start()
        assert _message(lock_results) == ("locked",)

        attempt_signal.set()
        assert _message(worker_results) == (
            "application-outcome",
            RunOneOutcome.BUSY.value,
        )
        assert worker.is_alive()

        release_signal.set()
        assert _message(lock_results) == ("released",)
        _join(lock_holder)
        retry_signal.set()
        assert _message(worker_results) == (
            "retry",
            task_id,
            CompletionResult.COMPLETED.value,
        )
        _join(worker)
    finally:
        attempt_signal.set()
        release_signal.set()
        retry_signal.set()
        _terminate(processes)
