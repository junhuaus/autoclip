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
