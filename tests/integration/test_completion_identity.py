"""Disposable migrated SQLite evidence for bounded completion implementation A."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from liveclip.application.completion import (
    CompletionConflict,
    CompletionOptions,
    CompletionResourceNotFound,
    CompletionSnapshot,
)
from liveclip.application.completion_runner import CompletionRunner, ReconciliationResult
from liveclip.application.completion_service import CompletionService
from liveclip.application.idempotency import IdempotencyContext, build_idempotency_context
from liveclip.application.pipeline import LeaseIdentity, PipelineRunConfig
from liveclip.db import completion_repository
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.engine import begin_immediate, create_sqlite_engine
from liveclip.db.models import (
    CompletionIntentRow,
    IdempotencyRecordRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.completion import CompletionIntentStatus, CompletionOutcome, CompletionTarget
from liveclip.domain.state_transitions import TaskKind

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 1, tzinfo=UTC)
OWNER = "a" * 32
OTHER = "b" * 32
PROCESS = CompletionOptions(target=CompletionTarget.PROCESS_ONLY, include_zip=False)


def context(key: str = "create") -> IdempotencyContext:
    return build_idempotency_context(
        raw_key=key,
        caller_scope=OWNER,
        operation_scope="completion:create",
        request_payload={"synthetic": True},
    )


def config() -> PipelineRunConfig:
    return PipelineRunConfig(
        provider="mock",
        top_n=3,
        minimum_clip_ms=8_000,
        maximum_clip_ms=12_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=540,
        preview_height=960,
        video_encoder="libx264",
    )


@dataclass
class Fixture:
    engine: Engine
    root: Path

    @property
    def repository(self) -> SqlAlchemyCompletionRepository:
        return SqlAlchemyCompletionRepository(self.engine)

    @property
    def service(self) -> CompletionService:
        return CompletionService(
            self.repository,
            allowed_source_roots=(self.root,),
            forbidden_source_roots=(self.root / "data",),
        )

    @property
    def queue(self) -> SQLiteTaskQueue:
        return SQLiteTaskQueue(self.engine, lease_seconds=30, data_dir=self.root / "data")

    def create(self, **changes: Any) -> CompletionSnapshot:
        arguments = {
            "source_path": self.root / "synthetic.mp4",
            "config": config(),
            "max_stage_retries": 3,
            "actor_user_id": OWNER,
            "options": PROCESS,
            "idempotency": context(),
            "readiness_guard": lambda: None,
        }
        arguments.update(changes)
        source = arguments["source_path"]
        created_source = not source.exists()
        if created_source:
            source.write_bytes(b"temporary synthetic source reference")
        try:
            return self.service.create_project_and_run_with_goal(**arguments)
        finally:
            if created_source:
                source.unlink()

    def observe(self, now: datetime = NOW) -> ReconciliationResult:
        return CompletionRunner(self.queue, self.repository).run_once(worker_id="worker", now=now)

    def run_status(self, goal: CompletionSnapshot, status: str) -> None:
        with begin_immediate(self.engine) as connection:
            connection.execute(
                update(PipelineRunRow).where(PipelineRunRow.id == goal.run_id).values(status=status)
            )

    def rows(self, model: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(model)).mappings()]

    def task(self, goal: CompletionSnapshot) -> dict[str, Any]:
        return next(row for row in self.rows(TaskRow) if row["target_id"] == goal.intent_id)


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Fixture]:
    database = tmp_path / "disposable.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        for identifier, name in ((OWNER, "completion-owner"), (OTHER, "completion-other")):
            connection.execute(
                insert(WorkspaceUserRow).values(
                    id=identifier,
                    username=name,
                    display_name=name,
                    is_active=True,
                )
            )
    try:
        yield Fixture(engine, tmp_path)
    finally:
        engine.dispose(close=True)


def test_creation_reconnect_replay_and_read_have_no_writes(fixture: Fixture) -> None:
    goal = fixture.create()
    tables = (
        ProjectRow,
        ProjectMemberRow,
        PipelineRunRow,
        StageRunRow,
        CompletionIntentRow,
        TaskRow,
        TaskAttemptRow,
        IdempotencyRecordRow,
    )
    before = [fixture.rows(table) for table in tables]
    assert len(fixture.rows(StageRunRow)) == 6
    assert len(fixture.rows(TaskRow)) == 2
    fixture.engine.dispose(close=True)
    assert fixture.create() == goal
    for _ in range(5):
        assert fixture.service.get(goal.intent_id, actor_user_id=OWNER) == goal
    assert [fixture.rows(table) for table in tables] == before
    assert not (fixture.root / "synthetic.mp4").exists()
    assert not (fixture.root / "data").exists()


def test_new_project_guard_is_transactional_and_replay_skips_missing_capability(
    fixture: Fixture,
) -> None:
    observed_inside_transaction = False

    def require_ready() -> None:
        nonlocal observed_inside_transaction
        with (
            closing(sqlite3.connect(fixture.root / "disposable.sqlite3", timeout=0)) as probe,
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            probe.execute("BEGIN IMMEDIATE")
        observed_inside_transaction = True

    goal = fixture.create(readiness_guard=require_ready)
    assert observed_inside_transaction
    assert not (fixture.root / "synthetic.mp4").exists()

    def unavailable() -> None:
        raise AssertionError("a replay must not require fresh provider capability")

    before = [fixture.rows(table) for table in (ProjectRow, PipelineRunRow, CompletionIntentRow)]
    assert (
        fixture.service.create_project_and_run_with_goal(
            source_path=fixture.root / "synthetic.mp4",
            config=config(),
            max_stage_retries=3,
            actor_user_id=OWNER,
            options=PROCESS,
            idempotency=context(),
            readiness_guard=unavailable,
        )
        == goal
    )
    assert [
        fixture.rows(table) for table in (ProjectRow, PipelineRunRow, CompletionIntentRow)
    ] == before
    with pytest.raises(ValueError, match="does not exist"):
        fixture.service.create_project_and_run_with_goal(
            source_path=fixture.root / "synthetic.mp4",
            config=config(),
            max_stage_retries=3,
            actor_user_id=OWNER,
            options=PROCESS,
            idempotency=context("different-key"),
            readiness_guard=unavailable,
        )
    assert [
        fixture.rows(table) for table in (ProjectRow, PipelineRunRow, CompletionIntentRow)
    ] == before


def test_existing_run_creation_is_idempotent(fixture: Fixture) -> None:
    first = fixture.create()
    arguments = dict(
        project_id=first.project_id,
        run_id=first.run_id,
        actor_user_id=OWNER,
        options=PROCESS,
        idempotency=context("attach"),
    )
    goal = fixture.service.create_for_existing_run(**arguments)
    before = fixture.rows(TaskRow)
    assert fixture.service.create_for_existing_run(**arguments) == goal
    assert fixture.rows(TaskRow) == before
    assert len(fixture.rows(ProjectRow)) == len(fixture.rows(PipelineRunRow)) == 1
    assert len(fixture.rows(CompletionIntentRow)) == 2
    with pytest.raises(CompletionConflict):
        fixture.service.create_for_existing_run(**{**arguments, "run_id": "c" * 32})


@pytest.mark.parametrize("change", ["source", "config", "options", "retries", "caller", "scope"])
def test_actual_arguments_and_scope_cannot_borrow_context(fixture: Fixture, change: str) -> None:
    fixture.create()
    changes: dict[str, Any] = {
        "source": {"source_path": fixture.root / "different.mp4"},
        "config": {"config": config().model_copy(update={"top_n": 2})},
        "options": {"options": CompletionOptions()},
        "retries": {"max_stage_retries": 2},
        "caller": {"idempotency": context().model_copy(update={"caller_scope": OTHER})},
        "scope": {"idempotency": context().model_copy(update={"operation_scope": "other"})},
    }[change]
    before = fixture.rows(TaskRow)
    with pytest.raises(CompletionConflict):
        fixture.create(**changes)
    assert fixture.rows(TaskRow) == before
    assert len(fixture.rows(CompletionIntentRow)) == 1


@pytest.mark.parametrize("existing", [False, True])
def test_creation_fault_rolls_back_entire_graph(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    goal = fixture.create() if existing else None
    tables = (
        ProjectRow,
        ProjectMemberRow,
        PipelineRunRow,
        StageRunRow,
        CompletionIntentRow,
        TaskRow,
        IdempotencyRecordRow,
    )
    before = [fixture.rows(table) for table in tables]

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected before idempotency commit")

    monkeypatch.setattr(completion_repository, "record_idempotent_resource", fail)
    with pytest.raises(RuntimeError, match="injected"):
        if goal:
            fixture.service.create_for_existing_run(
                project_id=goal.project_id,
                run_id=goal.run_id,
                actor_user_id=OWNER,
                options=PROCESS,
                idempotency=context("attach"),
            )
        else:
            fixture.create()
    assert [fixture.rows(table) for table in tables] == before


def revoke(connection: Connection, goal: CompletionSnapshot, mode: str) -> None:
    if mode == "disabled":
        connection.execute(
            update(WorkspaceUserRow).where(WorkspaceUserRow.id == OWNER).values(is_active=False)
        )
    elif mode == "removed":
        connection.execute(
            delete(ProjectMemberRow).where(ProjectMemberRow.project_id == goal.project_id)
        )
    elif mode == "archived":
        connection.execute(
            update(ProjectRow).where(ProjectRow.id == goal.project_id).values(lifecycle="archived")
        )
    else:
        connection.execute(
            update(ProjectMemberRow)
            .where(ProjectMemberRow.project_id == goal.project_id)
            .values(role="viewer")
        )


@pytest.mark.parametrize("mode", ["disabled", "removed", "archived", "downgraded"])
@pytest.mark.parametrize("effect", ["replay", "resume", "ongoing_resume", "cancel", "reconcile"])
def test_authority_is_checked_after_waiting_for_writer(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    effect: str,
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "failed" if effect == "resume" else "completed")
    if effect == "resume":
        assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
        goal = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    lease = (
        fixture.queue.claim_process_only(worker_id="worker", now=NOW)
        if effect == "reconcile"
        else None
    )
    before = fixture.rows(CompletionIntentRow)
    waiting = Event()

    @contextmanager
    def wait_for_writer(engine: Engine) -> Iterator[Connection]:
        waiting.set()
        with begin_immediate(engine) as connection:
            yield connection

    monkeypatch.setattr(completion_repository, "begin_immediate", wait_for_writer)

    def effect_call() -> object:
        if effect == "replay":
            return fixture.create()
        if effect == "reconcile":
            assert lease is not None
            return fixture.repository.reconcile_process_only(lease, now=NOW)
        return getattr(fixture.service, "resume" if effect == "ongoing_resume" else effect)(
            goal.intent_id,
            actor_user_id=OWNER,
            expected_version=goal.version,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with begin_immediate(fixture.engine) as connection:
            future = executor.submit(effect_call)
            assert waiting.wait(5)
            revoke(connection, goal, mode)
        if effect == "reconcile":
            assert future.result(timeout=5) == ReconciliationResult.NEEDS_ACTION
            assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "AUTHORIZATION_REQUIRED"
            assert fixture.task(goal)["status"] == "waiting"
        else:
            with pytest.raises(CompletionResourceNotFound):
                future.result(timeout=5)
            assert fixture.rows(CompletionIntentRow) == before


def test_restart_finishes_exact_completed_run_and_attempt_atomically(fixture: Fixture) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    processing = [row for row in fixture.rows(TaskRow) if row["kind"] != "completion"]
    fixture.engine.dispose(close=True)
    assert fixture.observe() == ReconciliationResult.PROCESSED
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert saved.outcome == CompletionOutcome.PROCESSED
    assert saved.delivery_id is None
    assert fixture.task(goal)["status"] == "succeeded"
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "succeeded"
    assert [row for row in fixture.rows(TaskRow) if row["kind"] != "completion"] == processing
    assert fixture.observe(NOW + timedelta(days=1)) == ReconciliationResult.IDLE


def test_committed_completion_survives_lost_response_and_new_connection(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None

    @contextmanager
    def lose_response_after_commit(engine: Engine) -> Iterator[Connection]:
        with begin_immediate(engine) as connection:
            yield connection
        raise RuntimeError("completion response lost after commit")

    with monkeypatch.context() as patch:
        patch.setattr(completion_repository, "begin_immediate", lose_response_after_commit)
        with pytest.raises(RuntimeError, match="response lost after commit"):
            fixture.repository.reconcile_process_only(lease, now=NOW)

    tables = (ProjectRow, PipelineRunRow, CompletionIntentRow, TaskRow, TaskAttemptRow)
    committed = [fixture.rows(table) for table in tables]
    fixture.engine.dispose(close=True)
    engine = create_sqlite_engine(fixture.root / "disposable.sqlite3")
    try:
        reconnected = Fixture(engine, fixture.root)
        saved = reconnected.service.get(goal.intent_id, actor_user_id=OWNER)
        assert saved.project_id == goal.project_id
        assert saved.run_id == goal.run_id and saved.generation == goal.generation
        assert saved.status == CompletionIntentStatus.SUCCEEDED
        assert saved.outcome == CompletionOutcome.PROCESSED
        assert saved.delivery_id is None
        assert reconnected.task(goal)["id"] == lease.task_id
        assert reconnected.rows(TaskAttemptRow)[0]["outcome"] == "succeeded"
        assert reconnected.create() == saved
        assert reconnected.observe(NOW + timedelta(days=1)) == ReconciliationResult.IDLE
        assert (
            reconnected.repository.reconcile_process_only(lease, now=NOW)
            == ReconciliationResult.LOST_LEASE
        )
        assert [reconnected.rows(table) for table in tables] == committed
    finally:
        engine.dispose(close=True)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_processing_deferrals_are_bounded_without_retry_consumption(
    fixture: Fixture,
    status: str,
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, status)
    for index in range(3):
        now = NOW + timedelta(seconds=10 * index)
        assert fixture.observe(now) == ReconciliationResult.DEFERRED
        task = fixture.task(goal)
        assert task["retry_count"] == 0
        assert task["attempt_count"] == index + 1
        assert task["not_before"] == now + timedelta(seconds=10)
        assert task["worker_id"] is task["lease_token"] is None
        assert fixture.observe(now + timedelta(milliseconds=9_999)) == ReconciliationResult.IDLE
    assert {row["outcome"] for row in fixture.rows(TaskAttemptRow)} == {"deferred"}


@pytest.mark.parametrize(
    "status,code", [("failed", "PROCESSING_FAILED"), ("cancelled", "PROCESSING_CANCELLED")]
)
def test_failed_processing_parks_until_explicit_resume(
    fixture: Fixture,
    status: str,
    code: str,
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, status)
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert saved.blocking_code == code
    before = fixture.rows(TaskAttemptRow), fixture.rows(TaskRow), fixture.rows(CompletionIntentRow)
    directories = sorted(str(path) for path in (fixture.root / "data").rglob("*"))
    for days in (1, 30, 365):
        assert fixture.observe(NOW + timedelta(days=days)) == ReconciliationResult.IDLE
        fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert before == (
        fixture.rows(TaskAttemptRow),
        fixture.rows(TaskRow),
        fixture.rows(CompletionIntentRow),
    )
    assert directories == sorted(str(path) for path in (fixture.root / "data").rglob("*"))
    fixture.run_status(goal, "completed")
    resumed = fixture.service.resume(
        goal.intent_id, actor_user_id=OWNER, expected_version=saved.version
    )
    assert resumed.run_id == goal.run_id
    assert fixture.observe(NOW + timedelta(days=366)) == ReconciliationResult.PROCESSED


def test_generation_change_parks_and_historical_get_is_read_only(fixture: Fixture) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    with fixture.engine.begin() as connection:
        connection.execute(
            update(ProjectRow).where(ProjectRow.id == goal.project_id).values(current_generation=2)
        )
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskRow)
    assert (
        fixture.service.get(goal.intent_id, actor_user_id=OWNER).blocking_code
        == "GENERATION_CHANGED"
    )
    with pytest.raises(CompletionConflict):
        fixture.create()
    assert before == (fixture.rows(CompletionIntentRow), fixture.rows(TaskRow))


@pytest.mark.parametrize("state", ["parked", "queued", "deferred", "running", "recovered"])
@pytest.mark.parametrize("downgrade", [False, True])
def test_resume_cas_and_actor_replacement_do_not_borrow_permission(
    fixture: Fixture, state: str, downgrade: bool
) -> None:
    goal = fixture.create()
    if state == "parked":
        fixture.run_status(goal, "failed")
        fixture.observe()
    elif state == "deferred":
        assert fixture.observe() == ReconciliationResult.DEFERRED
    elif state == "recovered":
        assert fixture.queue.claim_process_only(worker_id="departed", now=NOW) is not None
        assert fixture.observe(NOW + timedelta(seconds=30)) == ReconciliationResult.DEFERRED
        assert fixture.task(goal)["retry_count"] == 1
    lease = (
        fixture.queue.claim_process_only(worker_id="worker", now=NOW)
        if state == "running"
        else None
    )
    tasks_before = fixture.rows(TaskRow)
    attempts_before = fixture.rows(TaskAttemptRow)
    projects_before = fixture.rows(ProjectRow)
    runs_before = fixture.rows(PipelineRunRow)
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    with fixture.engine.begin() as connection:
        connection.execute(
            insert(ProjectMemberRow).values(
                project_id=goal.project_id,
                user_id=OTHER,
                role="editor",
            )
        )
    barrier = Barrier(2)

    def resume() -> object:
        barrier.wait(timeout=5)
        try:
            return fixture.repository.resume(
                goal.intent_id, actor_user_id=OTHER, expected_version=saved.version
            )
        except CompletionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: resume(), range(2)))
    assert results.count("conflict") == 1
    resumed = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert resumed.requester_user_id == OWNER and resumed.actor_user_id == OTHER
    assert resumed.version == saved.version + 1
    assert fixture.rows(ProjectRow) == projects_before
    assert fixture.rows(PipelineRunRow) == runs_before
    assert fixture.rows(TaskAttemptRow) == attempts_before
    if state != "parked":
        assert fixture.rows(TaskRow) == tasks_before
        assert resumed.status == saved.status
    assert fixture.create() == resumed  # Lost resume response is observable by creation replay.
    fixture.run_status(goal, "completed")
    if downgrade:
        with fixture.engine.begin() as connection:
            connection.execute(
                update(ProjectMemberRow)
                .where(ProjectMemberRow.user_id == OTHER)
                .values(role="viewer")
            )
    expected = ReconciliationResult.NEEDS_ACTION if downgrade else ReconciliationResult.PROCESSED
    if lease is not None:
        assert fixture.repository.reconcile_process_only(lease, now=NOW) == expected
    else:
        assert fixture.observe(NOW + timedelta(seconds=40)) == expected
    result = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert result.blocking_code == ("AUTHORIZATION_REQUIRED" if downgrade else None)
    assert result.outcome == (None if downgrade else CompletionOutcome.PROCESSED)


@pytest.mark.parametrize("running", [False, True])
def test_goal_cancel_preserves_processing_and_owned_attempt(
    fixture: Fixture, running: bool
) -> None:
    goal = fixture.create()
    processing = (
        fixture.rows(PipelineRunRow),
        [row for row in fixture.rows(TaskRow) if row["kind"] == "stage"],
    )
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW) if running else None
    cancelled = fixture.service.cancel(goal.intent_id, actor_user_id=OWNER, expected_version=1)
    assert cancelled.outcome == CompletionOutcome.CANCELLED
    if lease:
        assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "running"
        assert (
            fixture.repository.reconcile_process_only(lease, now=NOW)
            == ReconciliationResult.CANCELLED
        )
        assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "cancelled"
    assert fixture.task(goal)["status"] == "cancelled"
    assert processing == (
        fixture.rows(PipelineRunRow),
        [row for row in fixture.rows(TaskRow) if row["kind"] == "stage"],
    )
    with pytest.raises(CompletionConflict):
        fixture.service.resume(
            goal.intent_id, actor_user_id=OWNER, expected_version=cancelled.version
        )


def test_cancelled_completion_owner_expiry_does_not_restart_goal(fixture: Fixture) -> None:
    goal = fixture.create()
    lease = fixture.queue.claim_process_only(worker_id="departed", now=NOW)
    assert lease is not None
    fixture.service.cancel(goal.intent_id, actor_user_id=OWNER, expected_version=goal.version)
    assert fixture.task(goal)["status"] == "running"
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "running"
    assert fixture.queue.recover_expired(now=NOW + timedelta(seconds=30)).cancelled == 1
    assert fixture.task(goal)["status"] == "cancelled"
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "lost_lease"
    before = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow), fixture.rows(CompletionIntentRow)
    assert fixture.observe(NOW + timedelta(days=1)) == ReconciliationResult.IDLE
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW + timedelta(seconds=31))
        == ReconciliationResult.LOST_LEASE
    )
    assert before == (
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
        fixture.rows(CompletionIntentRow),
    )


@pytest.mark.parametrize("run_status", ["queued", "completed"])
def test_reconciliation_expiry_while_waiting_for_writer_cannot_commit(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch, run_status: str
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, run_status)
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    waiting = Event()
    clock = NOW

    @contextmanager
    def wait_for_writer(engine: Engine) -> Iterator[Connection]:
        waiting.set()
        with begin_immediate(engine) as connection:
            yield connection

    monkeypatch.setattr(completion_repository, "begin_immediate", wait_for_writer)
    monkeypatch.setattr(completion_repository, "_instant", lambda _: clock)
    before = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow), fixture.rows(CompletionIntentRow)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with begin_immediate(fixture.engine):
            future = executor.submit(fixture.repository.reconcile_process_only, lease)
            assert waiting.wait(5)
            clock = NOW + timedelta(seconds=30)
        assert future.result(timeout=5) == ReconciliationResult.LOST_LEASE
    assert before == (
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
        fixture.rows(CompletionIntentRow),
    )


def test_resume_waiting_on_cancel_cannot_adopt_cancelled_goal(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    goal = fixture.create()
    waiting = Event()

    @contextmanager
    def wait_for_writer(engine: Engine) -> Iterator[Connection]:
        waiting.set()
        with begin_immediate(engine) as connection:
            yield connection

    monkeypatch.setattr(completion_repository, "begin_immediate", wait_for_writer)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with begin_immediate(fixture.engine) as connection:
            future = executor.submit(
                fixture.repository.resume,
                goal.intent_id,
                actor_user_id=OWNER,
                expected_version=goal.version,
            )
            assert waiting.wait(5)
            # The queue cancellation may commit before the intent cancellation is observed.
            connection.execute(
                update(TaskRow)
                .where(TaskRow.target_id == goal.intent_id)
                .values(status="cancelled", cancellation_requested_at=NOW, completed_at=NOW)
            )
        with pytest.raises(CompletionConflict):
            future.result(timeout=5)
    assert fixture.service.get(goal.intent_id, actor_user_id=OWNER) == goal


def test_cancel_and_reconcile_race_has_one_terminal_outcome(fixture: Fixture) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    barrier = Barrier(2)

    def cancel() -> object:
        barrier.wait(timeout=5)
        try:
            return fixture.service.cancel(
                goal.intent_id, actor_user_id=OWNER, expected_version=goal.version
            )
        except CompletionConflict:
            return "conflict"

    def reconcile() -> ReconciliationResult:
        barrier.wait(timeout=5)
        return fixture.repository.reconcile_process_only(lease, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancellation = executor.submit(cancel)
        reconciliation = executor.submit(reconcile)
        cancelled = cancellation.result(timeout=5)
        result = reconciliation.result(timeout=5)
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    if cancelled == "conflict":
        assert result == ReconciliationResult.PROCESSED
        assert saved.outcome == CompletionOutcome.PROCESSED
    else:
        assert result == ReconciliationResult.CANCELLED
        assert saved.outcome == CompletionOutcome.CANCELLED
    assert fixture.task(goal)["status"] == saved.status.value
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == saved.status.value
    assert fixture.rows(PipelineRunRow)[0]["status"] == "completed"


@pytest.mark.parametrize(
    "goal_status,task_status",
    [("queued", "waiting"), ("waiting_work", "succeeded"), ("needs_action", "queued")],
)
def test_resume_rejects_inconsistent_coordination_without_mutation(
    fixture: Fixture, goal_status: str, task_status: str
) -> None:
    goal = fixture.create()
    with fixture.engine.begin() as connection:
        connection.execute(
            update(CompletionIntentRow)
            .where(CompletionIntentRow.id == goal.intent_id)
            .values(status=goal_status)
        )
        connection.execute(
            update(TaskRow).where(TaskRow.target_id == goal.intent_id).values(status=task_status)
        )
    before = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow), fixture.rows(CompletionIntentRow)
    with pytest.raises(CompletionConflict):
        fixture.service.resume(goal.intent_id, actor_user_id=OWNER, expected_version=goal.version)
    assert before == (
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
        fixture.rows(CompletionIntentRow),
    )


def test_lost_expired_and_successor_lease_cannot_commit(fixture: Fixture) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    for forged in (
        replace(lease, worker_id="other"),
        replace(lease, lease_token="wrong"),
        replace(lease, attempt_number=9),
        replace(lease, kind=TaskKind.STAGE),
    ):
        assert (
            fixture.repository.reconcile_process_only(forged, now=NOW)
            == ReconciliationResult.LOST_LEASE
        )
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW + timedelta(seconds=30))
        == ReconciliationResult.LOST_LEASE
    )
    successor = fixture.queue.claim_process_only(
        worker_id="successor", now=NOW + timedelta(seconds=30)
    )
    assert successor is not None
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW + timedelta(seconds=31))
        == ReconciliationResult.LOST_LEASE
    )
    assert fixture.task(goal)["retry_count"] == 1
    assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "lost_lease"
    assert (
        fixture.repository.reconcile_process_only(successor, now=NOW + timedelta(seconds=31))
        == ReconciliationResult.PROCESSED
    )


def test_completion_fault_rolls_back_goal_task_and_attempt(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskRow), fixture.rows(TaskAttemptRow)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected goal commit failure")

    monkeypatch.setattr(SqlAlchemyCompletionRepository, "_update", fail)
    with pytest.raises(RuntimeError, match="injected"):
        fixture.repository.reconcile_process_only(lease, now=NOW)
    assert before == (
        fixture.rows(CompletionIntentRow),
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
    )


def test_process_only_entry_does_not_claim_delivery_goals(fixture: Fixture) -> None:
    goal = fixture.create(options=CompletionOptions())
    fixture.run_status(goal, "completed")
    for day in (0, 1, 365):
        assert (
            fixture.queue.claim_process_only(
                worker_id="process-only", now=NOW + timedelta(days=day)
            )
            is None
        )
    assert fixture.rows(TaskAttemptRow) == []
    assert fixture.service.get(goal.intent_id, actor_user_id=OWNER) == goal
    assert goal.status == CompletionIntentStatus.QUEUED and goal.delivery_id is goal.outcome is None


@pytest.mark.parametrize(
    "values",
    [
        {"status": "invalid"},
        {"target": "invalid"},
        {"pipeline_run_id": "missing"},
        {"generation": 0},
    ],
)
def test_sqlite_completion_constraints(fixture: Fixture, values: dict[str, Any]) -> None:
    goal = fixture.create()
    with pytest.raises(IntegrityError), fixture.engine.begin() as connection:
        connection.execute(
            update(CompletionIntentRow)
            .where(CompletionIntentRow.id == goal.intent_id)
            .values(**values)
        )


@pytest.mark.parametrize("field", ["pipeline_run_id", "expected_generation", "input_fingerprint"])
def test_cross_row_task_identity_is_enforced(fixture: Fixture, field: str) -> None:
    goal = fixture.create()
    other = fixture.create(idempotency=context("second"))
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    values = {
        "pipeline_run_id": other.run_id,
        "expected_generation": 2,
        "input_fingerprint": "f" * 64,
    }
    with fixture.engine.begin() as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.id == lease.task_id).values(**{field: values[field]})
        )
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskAttemptRow)
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW) == ReconciliationResult.LOST_LEASE
    )
    assert before == (fixture.rows(CompletionIntentRow), fixture.rows(TaskAttemptRow))
    assert (
        next(row for row in fixture.rows(CompletionIntentRow) if row["id"] == goal.intent_id)[
            "outcome_code"
        ]
        is None
    )


def test_exhausted_coordination_is_visible_without_resetting_budget(fixture: Fixture) -> None:
    goal = fixture.create()
    for attempt in range(4):
        lease = fixture.queue.claim_process_only(
            worker_id="disappearing",
            now=NOW + timedelta(seconds=30 * attempt),
        )
        assert lease is not None
    assert fixture.observe(NOW + timedelta(seconds=120)) == ReconciliationResult.IDLE
    assert fixture.task(goal)["status"] == "failed"
    assert fixture.task(goal)["retry_count"] == 3
    before = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow), fixture.rows(CompletionIntentRow)
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert saved.blocking_code == "COORDINATION_RETRIES_EXHAUSTED"
    with pytest.raises(CompletionConflict, match="exhausted"):
        fixture.service.resume(goal.intent_id, actor_user_id=OWNER, expected_version=saved.version)
    assert before == (
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
        fixture.rows(CompletionIntentRow),
    )


@pytest.mark.parametrize("wait_ms", [1_000, 300_000, 999, 300_001, True, 1.5])
def test_queue_deferral_boundaries(fixture: Fixture, wait_ms: Any) -> None:
    goal = fixture.create()
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    if type(wait_ms) is int and 1_000 <= wait_ms <= 300_000:
        fixture.queue.defer_completion(lease, wait_ms=wait_ms, now=NOW)
        assert fixture.task(goal)["not_before"] == NOW + timedelta(milliseconds=wait_ms)
        assert fixture.task(goal)["retry_count"] == 0
        assert fixture.rows(TaskAttemptRow)[0]["outcome"] == "deferred"
    else:
        before = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow)
        with pytest.raises(ValueError):
            fixture.queue.defer_completion(lease, wait_ms=wait_ms, now=NOW)
        assert before == (fixture.rows(TaskRow), fixture.rows(TaskAttemptRow))


def test_inaccessible_goal_has_no_private_details(fixture: Fixture) -> None:
    goal = fixture.create()
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskRow)
    messages = []
    for identifier in (goal.intent_id, "missing"):
        with pytest.raises(CompletionResourceNotFound) as error:
            fixture.service.get(identifier, actor_user_id=OTHER)
        messages.append(str(error.value))
    assert messages[0] == messages[1]
    assert before == (fixture.rows(CompletionIntentRow), fixture.rows(TaskRow))


@pytest.mark.parametrize(
    "values",
    [
        {"resource_class": "heavy"},
        {"pipeline_run_id": None},
        {"status": "invalid"},
    ],
)
def test_sqlite_task_shape_constraints(fixture: Fixture, values: dict[str, Any]) -> None:
    goal = fixture.create()
    task = fixture.task(goal)
    with pytest.raises(IntegrityError), fixture.engine.begin() as connection:
        connection.execute(update(TaskRow).where(TaskRow.id == task["id"]).values(**values))


def test_sqlite_request_and_task_uniqueness(fixture: Fixture) -> None:
    goal = fixture.create()
    row = fixture.rows(CompletionIntentRow)[0]
    row["id"] = "d" * 32
    with pytest.raises(IntegrityError), fixture.engine.begin() as connection:
        connection.execute(insert(CompletionIntentRow).values(**row))
    task = fixture.task(goal)
    task["id"] = "e" * 32
    with pytest.raises(IntegrityError), fixture.engine.begin() as connection:
        connection.execute(insert(TaskRow).values(**task))


def test_downgrade_refuses_completion_history_without_losing_rows(fixture: Fixture) -> None:
    fixture.create()
    assert fixture.observe() == ReconciliationResult.DEFERRED
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskRow), fixture.rows(TaskAttemptRow)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with fixture.engine.connect() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="restore a backup"):
            command.downgrade(config, "a13f9c6d2e80")
        assert not connection.in_transaction()
        raw = connection.connection.driver_connection
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert before == (
        fixture.rows(CompletionIntentRow),
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
    )


def test_processing_cancel_does_not_cancel_goal_coordination(fixture: Fixture) -> None:
    goal = fixture.create()
    SqlAlchemyPipelineRepository(fixture.engine).request_run_cancel(goal.run_id)
    assert fixture.task(goal)["status"] == "queued"
    assert fixture.observe() == ReconciliationResult.NEEDS_ACTION
    assert (
        fixture.service.get(goal.intent_id, actor_user_id=OWNER).blocking_code
        == "PROCESSING_CANCELLED"
    )


@pytest.mark.parametrize("finalization", ["acknowledge", "expired_lease"])
@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("coordinator_running", [False, True])
def test_running_processing_cancel_preserves_completion_coordination(
    fixture: Fixture,
    finalization: str,
    deferred: bool,
    coordinator_running: bool,
) -> None:
    goal = fixture.create()
    if deferred:
        assert fixture.observe() == ReconciliationResult.DEFERRED
    stage_lease = fixture.queue.claim(
        worker_id="processing-owner",
        task_kind=TaskKind.STAGE,
        now=NOW,
        pipeline_run_id=goal.run_id,
    )
    assert stage_lease is not None
    coordinator = (
        fixture.queue.claim_process_only(worker_id="coordinator", now=NOW + timedelta(seconds=15))
        if coordinator_running
        else None
    )
    if coordinator_running:
        assert coordinator is not None
    pipeline = SqlAlchemyPipelineRepository(fixture.engine)
    pipeline.request_run_cancel(goal.run_id)
    completion_before = fixture.task(goal)
    assert completion_before["status"] == ("running" if coordinator_running else "queued")
    goal_before = fixture.rows(CompletionIntentRow)
    reconcile_at = NOW + timedelta(seconds=30)
    if finalization == "acknowledge":
        assert pipeline.cancel_stage(
            LeaseIdentity(
                task_id=stage_lease.task_id,
                worker_id=stage_lease.worker_id,
                lease_token=stage_lease.lease_token,
            )
        )
        expected_attempt_outcome = "cancelled"
    else:
        recovered = fixture.queue.recover_expired(now=reconcile_at)
        assert recovered.cancelled == 1
        expected_attempt_outcome = "lost_lease"
    assert fixture.task(goal) == completion_before
    assert fixture.rows(CompletionIntentRow) == goal_before
    assert fixture.rows(PipelineRunRow)[0]["status"] == "cancelled"
    processing_attempt = next(
        row for row in fixture.rows(TaskAttemptRow) if row["task_id"] == stage_lease.task_id
    )
    assert processing_attempt["outcome"] == expected_attempt_outcome
    if coordinator is None:
        assert fixture.observe(reconcile_at) == ReconciliationResult.NEEDS_ACTION
    else:
        assert (
            fixture.repository.reconcile_process_only(coordinator, now=reconcile_at)
            == ReconciliationResult.NEEDS_ACTION
        )
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    assert saved.status == CompletionIntentStatus.NEEDS_ACTION
    assert saved.blocking_code == "PROCESSING_CANCELLED"
    assert fixture.task(goal)["status"] == "waiting"
    assert fixture.task(goal)["retry_count"] == completion_before["retry_count"]
    before_idle = fixture.rows(TaskRow), fixture.rows(TaskAttemptRow)
    assert fixture.observe(reconcile_at + timedelta(days=1)) == ReconciliationResult.IDLE
    assert before_idle == (fixture.rows(TaskRow), fixture.rows(TaskAttemptRow))


def test_concurrent_creation_commits_one_identity(fixture: Fixture) -> None:
    # Keep the shared source alive for both callers. Fixture.create() otherwise
    # lets each thread own deletion of the same temporary file.
    source = fixture.root / "synthetic.mp4"
    assert not source.exists()
    source.write_bytes(b"temporary synthetic source reference")
    barrier = Barrier(2)

    def create() -> CompletionSnapshot:
        barrier.wait(timeout=5)
        return fixture.create()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create)
        second = executor.submit(create)
        assert first.result(timeout=10) == second.result(timeout=10)
    assert source.read_bytes() == b"temporary synthetic source reference"
    assert len(fixture.rows(ProjectRow)) == len(fixture.rows(PipelineRunRow)) == 1
    assert len(fixture.rows(CompletionIntentRow)) == len(fixture.rows(IdempotencyRecordRow)) == 1
    assert len(fixture.rows(TaskRow)) == 2


@pytest.mark.parametrize(
    "values",
    [
        {"worker_id": "replacement"},
        {"attempt_number": 10},
        {"lease_expires_at": NOW},
        {"outcome": "deferred"},
    ],
)
def test_persisted_attempt_fence_is_required(fixture: Fixture, values: dict[str, Any]) -> None:
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None
    with fixture.engine.begin() as connection:
        connection.execute(
            update(TaskAttemptRow).where(TaskAttemptRow.task_id == lease.task_id).values(**values)
        )
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskRow), fixture.rows(TaskAttemptRow)
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW) == ReconciliationResult.LOST_LEASE
    )
    assert before == (
        fixture.rows(CompletionIntentRow),
        fixture.rows(TaskRow),
        fixture.rows(TaskAttemptRow),
    )


def test_individual_foreign_keys_do_not_authorize_mixed_project_run(fixture: Fixture) -> None:
    goal = fixture.create()
    other = fixture.create(idempotency=context("other-project"))
    lease = fixture.queue.claim_process_only(worker_id="worker", now=NOW)
    assert lease is not None and lease.target_id == goal.intent_id
    with fixture.engine.begin() as connection:
        connection.execute(
            update(CompletionIntentRow)
            .where(CompletionIntentRow.id == goal.intent_id)
            .values(project_id=other.project_id)
        )
    before = fixture.rows(CompletionIntentRow), fixture.rows(TaskAttemptRow)
    assert (
        fixture.repository.reconcile_process_only(lease, now=NOW) == ReconciliationResult.LOST_LEASE
    )
    assert before == (fixture.rows(CompletionIntentRow), fixture.rows(TaskAttemptRow))
