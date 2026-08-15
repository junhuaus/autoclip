from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, select, update

import liveclip.services.janitor as janitor_module
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import PipelineRunRow, ProjectRow, TaskAttemptRow
from liveclip.db.task_queue import SQLiteTaskQueue, TaskSpec
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
)
from liveclip.media.artifacts import attempt_directory
from liveclip.media.secure_files import (
    interrupted_tree_cleanup_path,
    publish_directory_no_replace_no_follow,
)
from liveclip.services.janitor import cleanup_terminal_attempt_worktrees


def test_janitor_prunes_terminal_attempts_and_keeps_referenced_diagnostic(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    project_id = "a" * 32
    run_id = "b" * 32
    data_dir = tmp_path / "projects"
    (data_dir / project_id).mkdir(parents=True)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="Janitor",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"top_n": 1},
                config_fingerprint="d" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=30, data_dir=data_dir)
    first_task = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="c" * 32,
            operation_key="render:janitor:first",
            input_fingerprint="e" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
            max_retries=0,
        ),
        now=now,
    ).task_id
    first_lease = queue.claim(worker_id="janitor-test", now=now)
    assert first_lease is not None and first_lease.task_id == first_task
    first_attempt = attempt_directory(
        data_dir / project_id,
        LeaseIdentity(
            task_id=first_lease.task_id,
            worker_id=first_lease.worker_id,
            lease_token=first_lease.lease_token,
        ),
    )
    diagnostic = first_attempt / "diagnostics" / "ffmpeg-render.json"
    diagnostic.parent.mkdir()
    diagnostic.write_text("{}", encoding="utf-8")
    (first_attempt / "runs" / "large").mkdir(parents=True)
    (first_attempt / "runs" / "large" / "frame.png").write_bytes(b"temporary")
    (first_attempt / "generations" / "1" / "renders").mkdir(parents=True)
    (first_attempt / "generations" / "1" / "renders" / "large.mp4").write_bytes(
        b"large failed render"
    )
    diagnostic_relative = diagnostic.relative_to(data_dir / project_id).as_posix()
    queue.fail(
        first_lease,
        failure_class=FailureClass.DETERMINISTIC,
        error_code="RENDER_FAILED",
        safe_message="The render failed deterministic validation",
        diagnostic_relative_path=diagnostic_relative,
        now=now,
    )

    second_task = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="f" * 32,
            operation_key="render:janitor:second",
            input_fingerprint="1" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
        ),
        now=now,
    ).task_id
    second_lease = queue.claim(worker_id="janitor-test", now=now)
    assert second_lease is not None and second_lease.task_id == second_task
    second_attempt = attempt_directory(
        data_dir / project_id,
        LeaseIdentity(
            task_id=second_lease.task_id,
            worker_id=second_lease.worker_id,
            lease_token=second_lease.lease_token,
        ),
    )
    (second_attempt / "runs").mkdir()
    (second_attempt / "runs" / "temporary.bin").write_bytes(b"temporary")
    queue.complete(second_lease, now=now)

    report = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)

    assert report.inspected == 2
    assert report.cleaned == 2
    assert report.failed == 0
    assert diagnostic.read_text(encoding="utf-8") == "{}"
    assert not (first_attempt / "runs").exists()
    assert not (first_attempt / "generations").exists()
    assert not second_attempt.exists()
    engine.dispose(close=True)


def test_janitor_refuses_recorded_attempt_replacement_and_source_reference(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    project_id = "2" * 32
    run_id = "3" * 32
    data_dir = tmp_path / "projects"
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="Janitor identity",
                source_request_path="/allowed/external.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"top_n": 1},
                config_fingerprint="4" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=30, data_dir=data_dir)
    task_id = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="5" * 32,
            operation_key="render:janitor:identity",
            input_fingerprint="6" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
        ),
        now=now,
    ).task_id
    lease = queue.claim(worker_id="janitor-identity", now=now)
    assert lease is not None and lease.task_id == task_id
    attempt = attempt_directory(
        data_dir / project_id,
        LeaseIdentity(
            task_id=lease.task_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
        ),
    )
    source = attempt / "source-for-another-project.mp4"
    source.write_bytes(b"must survive")
    queue.complete(lease, now=now)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="7" * 32,
                name="References attempt",
                source_request_path=str(source),
                current_generation=0,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )

    blocked = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)
    assert blocked == type(blocked)(inspected=1, cleaned=0, failed=1)
    assert source.read_bytes() == b"must survive"

    with engine.begin() as connection:
        connection.execute(
            update(ProjectRow)
            .where(ProjectRow.id == "7" * 32)
            .values(source_request_path="/allowed/external-after-hidden-test.mp4")
        )
    attempt_identity = (attempt.stat().st_dev, attempt.stat().st_ino)
    interrupted = interrupted_tree_cleanup_path(attempt)
    publish_directory_no_replace_no_follow(
        attempt,
        interrupted,
        expected_identity=attempt_identity,
    )
    interrupted_source = interrupted / source.name
    with engine.begin() as connection:
        connection.execute(
            update(ProjectRow)
            .where(ProjectRow.id == "7" * 32)
            .values(source_request_path=str(interrupted_source))
        )

    hidden_blocked = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)
    assert hidden_blocked == type(hidden_blocked)(inspected=1, cleaned=0, failed=1)
    assert interrupted_source.read_bytes() == b"must survive"

    with engine.begin() as connection:
        connection.execute(ProjectRow.__table__.delete().where(ProjectRow.id == "7" * 32))
    publish_directory_no_replace_no_follow(
        interrupted,
        attempt,
        expected_identity=attempt_identity,
    )
    detached = attempt.with_name(f"{attempt.name}.detached")
    attempt.rename(detached)
    attempt.mkdir()
    replacement = attempt / "replacement.txt"
    replacement.write_text("must also survive", encoding="utf-8")

    replaced = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)
    assert replaced == type(replaced)(inspected=1, cleaned=0, failed=1)
    assert replacement.read_text(encoding="utf-8") == "must also survive"
    assert (detached / source.name).read_bytes() == b"must survive"
    engine.dispose(close=True)


def test_janitor_resumes_process_exit_after_quarantine_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    project_id = "d" * 32
    run_id = "e" * 32
    data_dir = tmp_path / "projects"
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="Janitor interrupted cleanup",
                source_request_path="/allowed/external.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"top_n": 1},
                config_fingerprint="f" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=30, data_dir=data_dir)
    task_id = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="1" * 32,
            operation_key="render:janitor:process-exit",
            input_fingerprint="2" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
        ),
        now=now,
    ).task_id
    lease = queue.claim(worker_id="interrupted-janitor", now=now)
    assert lease is not None and lease.task_id == task_id
    attempt = attempt_directory(
        data_dir / project_id,
        LeaseIdentity(
            task_id=lease.task_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
        ),
    )
    (attempt / "temporary.bin").write_bytes(b"must be cleaned after restart")
    queue.complete(lease, now=now)

    with engine.connect() as connection:
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(
                TaskAttemptRow.task_id == lease.task_id,
                TaskAttemptRow.lease_token == lease.lease_token,
            )
        )
    assert attempt_id is not None
    quarantine = data_dir / ".attempt-cleanup-quarantine" / str(attempt_id)
    interrupted = interrupted_tree_cleanup_path(quarantine)
    real_remove = janitor_module.remove_tree_no_follow

    def terminate_after_quarantine_rename(
        path: Path,
        *,
        required_ancestor: Path,
        expected_identity: tuple[int, int] | None = None,
    ) -> bool:
        del required_ancestor
        assert expected_identity is not None
        publish_directory_no_replace_no_follow(
            path,
            interrupted_tree_cleanup_path(path),
            expected_identity=expected_identity,
        )
        raise KeyboardInterrupt("simulated janitor process exit")

    with monkeypatch.context() as crash:
        crash.setattr(
            janitor_module,
            "remove_tree_no_follow",
            terminate_after_quarantine_rename,
        )
        with pytest.raises(KeyboardInterrupt, match="process exit"):
            cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)

    assert not attempt.exists()
    assert not quarantine.exists()
    assert interrupted.exists()
    monkeypatch.setattr(janitor_module, "remove_tree_no_follow", real_remove)
    resumed = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)
    assert resumed == type(resumed)(inspected=1, cleaned=1, failed=0)
    assert not interrupted.exists()
    engine.dispose(close=True)


def test_janitor_recursive_delete_does_not_hold_sqlite_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    project_id = "8" * 32
    run_id = "9" * 32
    data_dir = tmp_path / "projects"
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3", busy_timeout_ms=500)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="Janitor heartbeat",
                source_request_path="/allowed/external.mp4",
                current_generation=1,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"top_n": 1},
                config_fingerprint="a" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=30, data_dir=data_dir)
    terminal_task_id = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="a" * 32,
            operation_key="render:janitor:terminal",
            input_fingerprint="b" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
        ),
        now=now,
    ).task_id
    terminal_lease = queue.claim(worker_id="terminal-worker", now=now)
    assert terminal_lease is not None and terminal_lease.task_id == terminal_task_id
    terminal_attempt = attempt_directory(
        data_dir / project_id,
        LeaseIdentity(
            task_id=terminal_lease.task_id,
            worker_id=terminal_lease.worker_id,
            lease_token=terminal_lease.lease_token,
        ),
    )
    (terminal_attempt / "large").mkdir()
    (terminal_attempt / "large" / "artifact.bin").write_bytes(b"temporary")
    queue.complete(terminal_lease, now=now)

    active_task_id = queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id="c" * 32,
            operation_key="render:janitor:active",
            input_fingerprint="d" * 64,
            pipeline_run_id=run_id,
            resource_class=ResourceClass.HEAVY,
        ),
        now=now,
    ).task_id
    active_lease = queue.claim(worker_id="active-worker", now=now)
    assert active_lease is not None and active_lease.task_id == active_task_id

    delete_started = threading.Event()
    allow_delete = threading.Event()
    real_remove = janitor_module.remove_tree_no_follow

    def block_recursive_delete(
        path: Path,
        *,
        required_ancestor: Path,
        expected_identity: tuple[int, int] | None = None,
    ) -> bool:
        delete_started.set()
        assert allow_delete.wait(timeout=5)
        return real_remove(
            path,
            required_ancestor=required_ancestor,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(janitor_module, "remove_tree_no_follow", block_recursive_delete)
    reports: list[object] = []
    failures: list[BaseException] = []

    def run_cleanup() -> None:
        try:
            reports.append(cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir))
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    cleanup_thread = threading.Thread(target=run_cleanup)
    cleanup_thread.start()
    assert delete_started.wait(timeout=5)
    try:
        heartbeat = queue.heartbeat(active_lease, now=now)
        assert heartbeat is not None
    finally:
        allow_delete.set()
        cleanup_thread.join(timeout=5)
    assert not cleanup_thread.is_alive()
    assert not failures
    assert reports
    engine.dispose(close=True)
