from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


@pytest.mark.integration
def test_initial_migration_upgrade_check_downgrade_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "liveclip.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.integration
def test_delivery_generation_backfill_uses_owning_pipeline_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "generation-backfill.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))
    command.upgrade(config, "c0a0568060fb")

    instant = "2026-08-03T00:00:00+00:00"
    project_id = "a" * 32
    run_id = "b" * 32
    task_id = "c" * 32
    delivery_id = "d" * 32
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO projects (
                id, name, source_request_path, current_generation,
                current_pipeline_run_id, revision_epoch, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (project_id, "generation two", "/allowed/source.mp4", 2, 0, instant, instant),
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs (
                id, project_id, generation, status, config_json, config_fingerprint,
                progress, manual_retry_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, 2, "completed", "{}", "a" * 64, 100, 0, instant, instant),
        )
        connection.execute(
            "UPDATE projects SET current_pipeline_run_id = ? WHERE id = ?",
            (run_id, project_id),
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id, kind, target_id, operation_key, input_fingerprint, resource_class,
                pipeline_run_id, status, priority, not_before, expected_generation,
                expected_revision_epoch, attempt_count, retry_count, manual_retry_count,
                max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                "delivery",
                delivery_id,
                f"delivery:{delivery_id}",
                "b" * 64,
                "heavy",
                run_id,
                "succeeded",
                100,
                instant,
                2,
                0,
                1,
                0,
                0,
                1,
                instant,
                instant,
            ),
        )
        connection.execute(
            """
            INSERT INTO deliveries (
                id, project_id, task_id, version, status, expected_revision_epoch,
                snapshot_fingerprint, directory_relative_path, include_zip, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery_id,
                project_id,
                task_id,
                1,
                "succeeded",
                0,
                "c" * 64,
                "deliveries/v001",
                1,
                instant,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT expected_generation FROM deliveries WHERE id = ?", (delivery_id,)
        ).fetchone() == (2,)
        column = next(
            row
            for row in connection.execute("PRAGMA table_info(deliveries)")
            if row[1] == "expected_generation"
        )
        assert column[3] == 1
        assert column[4] is None
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()

    script = ScriptDirectory.from_config(config)
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
        assert revision == script.get_current_head()
    finally:
        engine.dispose(close=True)

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert {
            "projects",
            "source_media",
            "pipeline_runs",
            "stage_runs",
            "tasks",
            "task_attempts",
            "assets",
            "audio_chunks",
            "transcript_segments",
            "candidate_clips",
            "edit_plan_revisions",
            "render_jobs",
            "review_decisions",
            "deliveries",
            "api_usage",
        }.issubset(tables)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
