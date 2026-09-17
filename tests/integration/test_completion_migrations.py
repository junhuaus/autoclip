"""Disposable SD-4 parent rebuild and migration transaction regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert, inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    AssetRow,
    DeliveryProgressRow,
    DeliveryRow,
    PipelineRunRow,
    ProjectRow,
    SemanticUnitInvocationRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)

pytestmark = pytest.mark.integration
PARENT = "a13f9c6d2e80"
HEAD = "c84f5d1a702e"
GRAPH = (
    ProjectRow,
    PipelineRunRow,
    StageRunRow,
    TaskRow,
    TaskAttemptRow,
    AssetRow,
    SemanticUnitInvocationRow,
)


def populate(engine: Engine) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id="project",
                name="Synthetic",
                source_request_path="/synthetic.mp4",
                current_generation=1,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id="run",
                project_id="project",
                generation=1,
                status="completed",
                config_json={},
                config_fingerprint="a" * 64,
            )
        )
        connection.execute(
            insert(StageRunRow).values(
                id="stage",
                pipeline_run_id="run",
                stage="ingest",
                ordinal=0,
                status="succeeded",
                max_retries=3,
            )
        )
        for identifier, dependency in (("task", None), ("dependent", "task")):
            connection.execute(
                insert(TaskRow).values(
                    id=identifier,
                    kind="stage",
                    target_id="stage",
                    operation_key=f"stage:{identifier}",
                    input_fingerprint="a" * 64,
                    resource_class="heavy",
                    pipeline_run_id="run",
                    stage_run_id="stage",
                    status="succeeded" if dependency is None else "queued",
                    not_before=now,
                    max_retries=3,
                    depends_on_task_id=dependency,
                )
            )
        connection.execute(
            insert(TaskAttemptRow).values(
                id="attempt",
                task_id="task",
                attempt_number=1,
                worker_id="worker",
                lease_token="token",
                outcome="succeeded",
                started_at=now,
                heartbeat_at=now,
                lease_expires_at=now,
                finished_at=now,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id="asset",
                project_id="project",
                producer_attempt_id="attempt",
                kind="semantic_unit_outcome",
                relative_path="synthetic.json",
                mime_type="application/json",
                input_fingerprint="a" * 64,
            )
        )
        connection.execute(
            insert(SemanticUnitInvocationRow).values(
                id="invocation",
                project_id="project",
                pipeline_run_id="run",
                stage_run_id="stage",
                task_id="task",
                producer_attempt_id="attempt",
                generation=1,
                semantic_stage="discovery",
                subject_id="unit.0",
                request_key="a" * 64,
                execution_contract="semantic-bounded-units-v1",
                invocation_number=1,
                reserved_at=now,
                outcome_asset_id="asset",
            )
        )


def snapshot(engine: Engine) -> list[list[dict]]:
    with engine.connect() as connection:
        return [
            [dict(row) for row in connection.execute(select(model).order_by(model.id)).mappings()]
            for model in GRAPH
        ]


@pytest.mark.parametrize("provided", [False, True])
def test_populated_completion_upgrade_preserves_graph_and_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provided: bool
) -> None:
    database = tmp_path / "migration.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, PARENT)
    engine = create_sqlite_engine(database)
    try:
        populate(engine)
        before = snapshot(engine)
        indexes = {
            model.__tablename__: inspect(engine).get_indexes(model.__tablename__) for model in GRAPH
        }
        with engine.connect() as connection:
            if provided:
                config.attributes["connection"] = connection
            command.upgrade(config, HEAD)
            raw = connection.connection.driver_connection
            assert raw.execute("PRAGMA foreign_keys").fetchone() == (1,)
            config.attributes.pop("connection", None)
        assert snapshot(engine) == before
        assert indexes == {name: inspect(engine).get_indexes(name) for name in indexes}
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        command.downgrade(config, PARENT)
        command.upgrade(config, HEAD)
        assert snapshot(engine) == before
        command.check(config)
    finally:
        engine.dispose(close=True)


def test_completion_upgrade_fk_failure_rolls_back_and_restores_enforcement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "rollback.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, PARENT)
    engine = create_sqlite_engine(database)
    try:
        populate(engine)
        before = snapshot(engine)
        with engine.connect() as connection:
            config.attributes["connection"] = connection

            def inject(conn, cursor, statement, parameters, context, executemany):
                if statement == "PRAGMA foreign_key_check":
                    cursor.execute("UPDATE assets SET producer_attempt_id='missing'")

            event.listen(connection, "before_cursor_execute", inject)
            try:
                with pytest.raises(RuntimeError, match="foreign-key validation failed"):
                    command.upgrade(config, HEAD)
            finally:
                event.remove(connection, "before_cursor_execute", inject)
            assert not connection.in_transaction()
            raw = connection.connection.driver_connection
            assert raw.execute("PRAGMA foreign_keys").fetchone() == (1,)
            assert "completion_intents" not in inspect(connection).get_table_names()
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == PARENT
            )
            connection.rollback()
            assert snapshot(engine) == before
            command.upgrade(config, HEAD)
        assert snapshot(engine) == before
    finally:
        engine.dispose(close=True)


def test_completion_migration_rejects_active_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "active.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, PARENT)
    engine = create_sqlite_engine(database)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            with pytest.raises(RuntimeError, match="active transaction"):
                command.upgrade(config, HEAD)
            assert connection.in_transaction()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose(close=True)


def test_delivery_progress_migration_preserves_attempt_evidence_and_rejects_fake_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "progress.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "b71d4c9a20e5")
    engine = create_sqlite_engine(database)
    try:
        populate(engine)
        command.upgrade(config, HEAD)
        now = datetime(2030, 1, 1, tzinfo=UTC)
        with engine.begin() as connection:
            connection.execute(
                insert(DeliveryRow).values(
                    id="delivery",
                    project_id="project",
                    task_id="task",
                    version=1,
                    status="creating",
                    expected_revision_epoch=0,
                    snapshot_fingerprint="b" * 64,
                    directory_relative_path="deliveries/v001",
                    include_zip=True,
                    expected_generation=1,
                )
            )
            connection.execute(
                insert(DeliveryProgressRow).values(
                    delivery_id="delivery",
                    task_attempt_id="attempt",
                    attempt_number=1,
                    expected_generation=1,
                    expected_revision_epoch=0,
                    package_fingerprint="c" * 64,
                    phase="writing_zip",
                    unit="bytes",
                    completed=7,
                    total=11,
                    started_at=now,
                    business_advanced_at=now,
                )
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(DeliveryProgressRow).values(
                    delivery_id="delivery",
                    task_attempt_id="missing",
                    attempt_number=2,
                    expected_generation=1,
                    expected_revision_epoch=0,
                    package_fingerprint="c" * 64,
                    phase="writing_zip",
                    unit="bytes",
                    completed=7,
                    total=11,
                    started_at=now,
                    business_advanced_at=now,
                )
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(update(DeliveryProgressRow).values(unit="files"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(update(DeliveryProgressRow).values(completed=12))
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert connection.execute(select(DeliveryProgressRow.completed)).scalar_one() == 7
        command.check(config)
    finally:
        engine.dispose(close=True)
