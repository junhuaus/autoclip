"""Stage 19a migration d5e8a1c3f907: upgrade/downgrade round trip."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

PARENT = "c84f5d1a702e"
REVISION = "d5e8a1c3f907"
DELETE_GUARD_REVISION = "e4b2c7d9a1f3"
ACKNOWLEDGE_REVISION = "f6a1b3c5d7e9"
NEW_TABLES = {
    "dual_profile_imports",
    "dual_profile_import_clips",
    "dual_profile_clip_decisions",
    "customer_deliveries",
    "customer_delivery_clips",
    "customer_share_links",
}
IMMUTABLE_TRIGGERS = {
    "dual_profile_imports_immutable",
    "dual_profile_import_clips_immutable",
    "dual_profile_clip_decisions_immutable",
    "customer_delivery_clips_immutable",
    "dual_profile_imports_delete_guard",
    "dual_profile_import_clips_delete_guard",
    "dual_profile_clip_decisions_delete_guard",
    "customer_delivery_clips_delete_guard",
    "customer_deliveries_delete_guard",
}


def _snapshot(database_path: Path) -> tuple[set[str], set[str]]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            triggers = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose(close=True)
    return tables, triggers


@pytest.mark.integration
def test_dual_profile_customer_delivery_migration_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "dual-profile.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == ACKNOWLEDGE_REVISION
    revision = script.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PARENT

    command.upgrade(config, PARENT)
    tables, triggers = _snapshot(database_path)
    assert not tables & NEW_TABLES
    assert not triggers & IMMUTABLE_TRIGGERS

    command.upgrade(config, "head")
    command.check(config)
    tables, triggers = _snapshot(database_path)
    assert tables >= NEW_TABLES
    assert triggers >= IMMUTABLE_TRIGGERS
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        assert {
            tuple(value["column_names"])
            for value in inspector.get_unique_constraints("dual_profile_imports")
        } == {("project_id",), ("imported_by", "snapshot_fingerprint")}
        assert {
            "title_override",
            "hook_override",
            "summary_override",
            "actor_user_id",
            "decided_at",
            "sequence",
        } <= {value["name"] for value in inspector.get_columns("dual_profile_clip_decisions")}
        assert {
            tuple(value["column_names"])
            for value in inspector.get_unique_constraints("customer_share_links")
        } == {("token_sha256",)}
        assert "token" not in {
            value["name"] for value in inspector.get_columns("customer_share_links")
        }
    finally:
        engine.dispose(close=True)

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        columns = {
            value["name"] for value in inspect(engine).get_columns("dual_profile_clip_decisions")
        }
        assert "acknowledge_warnings" in columns
    finally:
        engine.dispose(close=True)
    command.downgrade(config, DELETE_GUARD_REVISION)
    tables, triggers = _snapshot(database_path)
    assert triggers >= IMMUTABLE_TRIGGERS
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        columns = {
            value["name"] for value in inspect(engine).get_columns("dual_profile_clip_decisions")
        }
        assert "acknowledge_warnings" not in columns
    finally:
        engine.dispose(close=True)

    command.downgrade(config, REVISION)
    tables, triggers = _snapshot(database_path)
    assert tables >= NEW_TABLES
    assert not {name for name in triggers if name.endswith("_delete_guard")}

    command.downgrade(config, PARENT)
    tables, triggers = _snapshot(database_path)
    assert not tables & NEW_TABLES
    assert not triggers & IMMUTABLE_TRIGGERS

    command.upgrade(config, "head")
    command.check(config)
    tables, triggers = _snapshot(database_path)
    assert tables >= NEW_TABLES
    assert triggers >= IMMUTABLE_TRIGGERS
