from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert

from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import PipelineRunRow, ProjectRow
from liveclip.db.task_queue import SQLiteTaskQueue, TaskSpec
from liveclip.domain.state_transitions import (
    FailureClass,
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
)
from liveclip.media.artifacts import attempt_directory
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
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
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
    assert not second_attempt.exists()
    engine.dispose(close=True)
