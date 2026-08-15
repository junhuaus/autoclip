from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import PipelineRunRow, ProjectRow, SourceMediaRow, StageRunRow, TaskRow
from liveclip.domain.state_transitions import (
    PipelineRunStatus,
    PipelineStage,
    ResourceClass,
    StageRunStatus,
    TaskKind,
    TaskStatus,
)


@pytest.fixture
def schema_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3", busy_timeout_ms=50)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose(close=True)


def _project_values(identifier: str, *, name: str = "Project") -> dict[str, object]:
    return {
        "id": identifier,
        "name": name,
        "source_request_path": "/allowed/source.mp4",
        "current_generation": 0,
        "revision_epoch": 0,
    }


def _run_values(identifier: str, project_id: str, *, generation: int = 1) -> dict[str, object]:
    return {
        "id": identifier,
        "project_id": project_id,
        "generation": generation,
        "status": PipelineRunStatus.QUEUED.value,
        "config_json": {"top_n": 15},
        "config_fingerprint": "a" * 64,
        "progress": 0,
        "manual_retry_count": 0,
    }


def test_schema_contains_every_v1_persistence_entity_and_named_constraints(
    schema_engine: Engine,
) -> None:
    assert set(Base.metadata.tables) == {
        "api_usage",
        "assets",
        "audio_chunks",
        "audit_events",
        "auth_login_attempts",
        "auth_sessions",
        "candidate_clips",
        "caption_cues",
        "deliveries",
        "delivery_clips",
        "edit_package_clips",
        "edit_packages",
        "edit_plan_revisions",
        "idempotency_records",
        "pipeline_runs",
        "projects",
        "render_jobs",
        "review_decisions",
        "source_media",
        "stage_runs",
        "task_attempts",
        "tasks",
        "transcript_segments",
        "transcript_words",
        "transcripts",
        "workspace_users",
        "project_members",
    }
    for table in Base.metadata.sorted_tables:
        assert all(constraint.name for constraint in table.constraints)
        assert all(index.name for index in table.indexes)


def test_foreign_keys_status_checks_and_generation_uniqueness_are_enforced(
    schema_engine: Engine,
) -> None:
    project_id = "p" * 32
    run_id = "r" * 32
    with schema_engine.begin() as connection:
        connection.execute(insert(ProjectRow).values(**_project_values(project_id)))
        connection.execute(insert(PipelineRunRow).values(**_run_values(run_id, project_id)))

    with pytest.raises(IntegrityError), schema_engine.begin() as connection:
        connection.execute(
            insert(PipelineRunRow).values(**_run_values("x" * 32, "missing", generation=2))
        )

    with pytest.raises(IntegrityError), schema_engine.begin() as connection:
        invalid = _run_values("s" * 32, project_id, generation=2)
        invalid["status"] = "not-a-state"
        connection.execute(insert(PipelineRunRow).values(**invalid))

    with pytest.raises(IntegrityError), schema_engine.begin() as connection:
        connection.execute(
            insert(PipelineRunRow).values(**_run_values("t" * 32, project_id, generation=1))
        )


def test_source_fingerprint_is_not_unique_across_explicit_projects(
    schema_engine: Engine,
) -> None:
    project_ids = ("a" * 32, "b" * 32)
    shared_sha = "f" * 64
    with schema_engine.begin() as connection:
        for index, project_id in enumerate(project_ids):
            connection.execute(
                insert(ProjectRow).values(**_project_values(project_id, name=f"Project {index}"))
            )
            connection.execute(
                insert(SourceMediaRow).values(
                    id=str(index + 1) * 32,
                    project_id=project_id,
                    resolved_path=f"/allowed/source-{index}.mp4",
                    filename="same.mp4",
                    sha256=shared_sha,
                    size_bytes=1_024,
                    mtime_ns=1,
                    duration_ms=10_000,
                    width=1920,
                    height=1080,
                    video_codec="h264",
                    audio_codec="aac",
                    frame_rate="24/1",
                    probe_json={"streams": 2},
                )
            )

    with schema_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(SourceMediaRow)) == 2


def test_task_lease_shape_is_enforced_by_sqlite(schema_engine: Engine) -> None:
    project_id = "p" * 32
    run_id = "r" * 32
    stage_id = "s" * 32
    now = datetime.now(UTC)
    with schema_engine.begin() as connection:
        connection.execute(insert(ProjectRow).values(**_project_values(project_id)))
        connection.execute(insert(PipelineRunRow).values(**_run_values(run_id, project_id)))
        connection.execute(
            insert(StageRunRow).values(
                id=stage_id,
                pipeline_run_id=run_id,
                stage=PipelineStage.INGEST.value,
                ordinal=0,
                status=StageRunStatus.QUEUED.value,
                progress=0,
                retry_count=0,
                max_retries=3,
            )
        )

    base_task = {
        "kind": TaskKind.STAGE.value,
        "target_id": stage_id,
        "input_fingerprint": "i" * 64,
        "resource_class": ResourceClass.HEAVY.value,
        "pipeline_run_id": run_id,
        "stage_run_id": stage_id,
        "priority": 100,
        "not_before": now,
        "attempt_count": 0,
        "retry_count": 0,
        "manual_retry_count": 0,
        "max_retries": 3,
    }
    with pytest.raises(IntegrityError), schema_engine.begin() as connection:
        connection.execute(
            insert(TaskRow).values(
                **base_task,
                id="q" * 32,
                operation_key="stage:bad-queued",
                status=TaskStatus.QUEUED.value,
                worker_id="worker-a",
                lease_token="token-a",
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=30),
            )
        )
    with pytest.raises(IntegrityError), schema_engine.begin() as connection:
        connection.execute(
            insert(TaskRow).values(
                **base_task,
                id="u" * 32,
                operation_key="stage:bad-running",
                status=TaskStatus.RUNNING.value,
            )
        )

    with schema_engine.begin() as connection:
        connection.execute(
            insert(TaskRow).values(
                **base_task,
                id="v" * 32,
                operation_key="stage:valid-running",
                status=TaskStatus.RUNNING.value,
                worker_id="worker-a",
                lease_token="token-valid",
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=30),
            )
        )


def test_project_delete_cascades_current_generation_rows(schema_engine: Engine) -> None:
    project_id = "p" * 32
    run_id = "r" * 32
    with schema_engine.begin() as connection:
        connection.execute(insert(ProjectRow).values(**_project_values(project_id)))
        connection.execute(insert(PipelineRunRow).values(**_run_values(run_id, project_id)))
        connection.execute(delete(ProjectRow).where(ProjectRow.id == project_id))

    with schema_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(PipelineRunRow)) == 0


def test_utc_type_rejects_naive_values_and_restores_timezone(schema_engine: Engine) -> None:
    with pytest.raises(StatementError, match="timezone-aware"), Session(schema_engine) as session:
        session.add(
            ProjectRow(
                id="n" * 32,
                name="Naive",
                source_request_path="/allowed/naive.mp4",
                current_generation=0,
                revision_epoch=0,
                created_at=datetime(2026, 8, 3),
            )
        )
        session.commit()

    with Session(schema_engine) as session:
        project = ProjectRow(
            id="z" * 32,
            name="Aware",
            source_request_path="/allowed/aware.mp4",
            current_generation=0,
            revision_epoch=0,
            created_at=datetime(2026, 8, 3, tzinfo=UTC),
        )
        session.add(project)
        session.commit()
        session.expire_all()
        restored = session.get(ProjectRow, project.id)
        assert restored is not None
        assert restored.created_at.tzinfo == UTC
