from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


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
def test_head_repairs_stamped_legacy_asset_scope_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "legacy-assets.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))

    candidate_id = "a" * 32
    render_asset_id = "b" * 32
    delivery_asset_id = "c" * 32
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            );
            INSERT INTO alembic_version (version_num) VALUES ('a71d4f9c2e10');

            CREATE TABLE candidate_clips (
                id VARCHAR(32) NOT NULL PRIMARY KEY
            );
            CREATE TABLE assets (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                project_id VARCHAR(32) NOT NULL,
                producer_attempt_id VARCHAR(32),
                status VARCHAR(20) NOT NULL,
                kind VARCHAR(50) NOT NULL,
                relative_path VARCHAR(500) NOT NULL,
                mime_type VARCHAR(120) NOT NULL,
                input_fingerprint VARCHAR(64) NOT NULL,
                expected_sha256 VARCHAR(64),
                sha256 VARCHAR(64),
                size_bytes BIGINT,
                validation_json JSON,
                generation INTEGER,
                edit_plan_revision INTEGER,
                created_at DATETIME NOT NULL,
                committed_at DATETIME,
                UNIQUE (project_id, relative_path)
            );
            CREATE INDEX ix_assets_kind ON assets (kind);
            CREATE INDEX ix_assets_project_id ON assets (project_id);
            CREATE INDEX ix_assets_status ON assets (status);

            CREATE TABLE render_jobs (
                candidate_clip_id VARCHAR(32) NOT NULL,
                revision_epoch BIGINT NOT NULL,
                asset_id VARCHAR(32),
                subtitle_asset_id VARCHAR(32),
                quality_report_asset_id VARCHAR(32),
                contact_sheet_asset_id VARCHAR(32)
            );
            CREATE TABLE deliveries (
                expected_revision_epoch BIGINT NOT NULL,
                manifest_asset_id VARCHAR(32),
                zip_asset_id VARCHAR(32)
            );
            """
        )
        connection.execute("INSERT INTO candidate_clips (id) VALUES (?)", (candidate_id,))
        for asset_id, relative_path in (
            (render_asset_id, "generation/001/render.mp4"),
            (delivery_asset_id, "deliveries/v001/manifest.json"),
        ):
            connection.execute(
                """
                INSERT INTO assets (
                    id, project_id, status, kind, relative_path, mime_type,
                    input_fingerprint, generation, created_at
                ) VALUES (?, ?, 'committed', 'fixture', ?, 'application/octet-stream', ?, 1, ?)
                """,
                (asset_id, "d" * 32, relative_path, "e" * 64, "2026-08-05T00:00:00+00:00"),
            )
        connection.execute(
            """
            INSERT INTO render_jobs (candidate_clip_id, revision_epoch, asset_id)
            VALUES (?, 7, ?)
            """,
            (candidate_id, render_asset_id),
        )
        connection.execute(
            """
            INSERT INTO deliveries (expected_revision_epoch, manifest_asset_id)
            VALUES (9, ?)
            """,
            (delivery_asset_id,),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
        assert {"candidate_clip_id", "revision_epoch"}.issubset(columns)
        assert connection.execute(
            "SELECT candidate_clip_id, revision_epoch FROM assets WHERE id = ?",
            (render_asset_id,),
        ).fetchone() == (candidate_id, 7)
        assert connection.execute(
            "SELECT candidate_clip_id, revision_epoch FROM assets WHERE id = ?",
            (delivery_asset_id,),
        ).fetchone() == (None, 9)
        assert any(
            row[2] == "candidate_clip_id"
            for row in connection.execute("PRAGMA index_info(ix_assets_candidate_clip_id)")
        )
        assert any(
            row[3] == "candidate_clip_id" and row[2] == "candidate_clips"
            for row in connection.execute("PRAGMA foreign_key_list(assets)")
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()

    command.downgrade(config, "a71d4f9c2e10")
    connection = sqlite3.connect(database_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
        assert {"candidate_clip_id", "revision_epoch"}.issubset(columns)
    finally:
        connection.close()


@pytest.mark.integration
def test_head_removes_legacy_render_task_unique_constraint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "legacy-render-task.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))
    command.upgrade(config, "d2c59b8e4f31")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            with operations.batch_alter_table("render_jobs", schema=None) as batch_op:
                batch_op.create_unique_constraint("uq_render_jobs_task_id", ["task_id"])
        assert any(
            tuple(constraint.get("column_names") or ()) == ("task_id",)
            for constraint in inspect(engine).get_unique_constraints("render_jobs")
        )
    finally:
        engine.dispose(close=True)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        assert not any(
            tuple(constraint.get("column_names") or ()) == ("task_id",)
            for constraint in inspector.get_unique_constraints("render_jobs")
        )
        assert any(
            tuple(index.get("column_names") or ()) == ("task_id",) and not index.get("unique")
            for index in inspector.get_indexes("render_jobs")
        )
    finally:
        engine.dispose(close=True)
    command.check(config)


@pytest.mark.integration
def test_head_stales_legacy_text_proxies_and_preserves_proven_clean_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "legacy-proxy.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    config = Config(str(project_root / "alembic.ini"))
    command.upgrade(config, "e7b14c2d9a60")

    instant = "2026-08-11T00:00:00+00:00"
    dirty_run = "1" * 32
    clean_run = "2" * 32
    dirty_clip = "3" * 32
    clean_clip = "4" * 32
    manual_clip = "5" * 32
    queued_clip = "6" * 32
    queued_task = "7" * 32
    running_clip = "e" * 32
    running_task = "f" * 32
    connection = sqlite3.connect(database_path)
    try:
        for run_id, project_id, contract in (
            (dirty_run, "8" * 32, "edit-plan-v1.caption-v2"),
            (clean_run, "9" * 32, "edit-plan-v1.caption-v2.clean-proxy-v1"),
        ):
            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    id, project_id, generation, status, config_json,
                    config_fingerprint, progress, manual_retry_count,
                    created_at, updated_at
                ) VALUES (?, ?, 1, 'completed', ?, ?, 100, 0, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    json.dumps({"edit_plan_schema_version": contract}),
                    "a" * 64,
                    instant,
                    instant,
                ),
            )
        for clip_id, run_id, project_id, key in (
            (dirty_clip, dirty_run, "8" * 32, "dirty"),
            (clean_clip, clean_run, "9" * 32, "clean"),
            (manual_clip, dirty_run, "8" * 32, "manual"),
            (queued_clip, dirty_run, "8" * 32, "queued"),
            (running_clip, dirty_run, "8" * 32, "running"),
        ):
            connection.execute(
                """
                INSERT INTO candidate_clips (
                    id, project_id, pipeline_run_id, candidate_key,
                    source_start_ms, source_end_ms, allowed_start_ms, allowed_end_ms,
                    transcript_text, context_before, context_after, rule_score,
                    reasons_json, segment_ids_json, current_revision,
                    selected_for_review, created_at
                ) VALUES (?, ?, ?, ?, 0, 1000, 0, 1000, 'fixture', '', '', 50,
                          '[]', '[]', 1, 1, ?)
                """,
                (clip_id, project_id, run_id, key, instant),
            )
        connection.execute(
            """
            INSERT INTO tasks (
                id, kind, target_id, operation_key, input_fingerprint,
                resource_class, pipeline_run_id, status, priority, not_before,
                expected_generation, expected_revision, expected_revision_epoch,
                attempt_count, retry_count, manual_retry_count, max_retries,
                created_at, updated_at
            ) VALUES (?, 'render', ?, 'legacy-proxy-render', ?, 'heavy', ?, 'queued',
                      100, ?, 1, 1, 0, 0, 0, 0, 1, ?, ?)
            """,
            (queued_task, queued_clip, "b" * 64, dirty_run, instant, instant, instant),
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id, kind, target_id, operation_key, input_fingerprint,
                resource_class, pipeline_run_id, status, priority, not_before,
                expected_generation, expected_revision, expected_revision_epoch,
                attempt_count, retry_count, manual_retry_count, max_retries,
                worker_id, lease_token, heartbeat_at, lease_expires_at,
                created_at, updated_at
            ) VALUES (?, 'render', ?, 'legacy-running-proxy-render', ?, 'heavy', ?, 'running',
                      100, ?, 1, 1, 0, 1, 0, 0, 1, 'legacy-worker', ?, ?, ?, ?, ?)
            """,
            (
                running_task,
                running_clip,
                "c" * 64,
                dirty_run,
                instant,
                "d" * 64,
                instant,
                "2026-08-11T00:05:00+00:00",
                instant,
                instant,
            ),
        )
        clean_manual_spec = json.dumps(
            {
                "schema_version": "3",
                "renderer": "ffmpeg-renderer-v2",
                "text_mode": "none",
            }
        )
        for render_id, clip_id, task_id, status, spec_json in (
            ("a" * 32, dirty_clip, None, "succeeded", None),
            ("b" * 32, clean_clip, None, "succeeded", None),
            ("c" * 32, manual_clip, None, "succeeded", clean_manual_spec),
            ("d" * 32, queued_clip, queued_task, "queued", None),
            ("0" * 32, running_clip, running_task, "running", None),
        ):
            connection.execute(
                """
                INSERT INTO render_jobs (
                    id, candidate_clip_id, edit_plan_revision_id, task_id,
                    kind, status, edit_plan_revision, revision_epoch,
                    width, height, spec_fingerprint, spec_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'proxy', ?, 1, 0, 540, 960, ?, ?, ?, ?)
                """,
                (
                    render_id,
                    clip_id,
                    render_id,
                    task_id,
                    status,
                    render_id[0] * 64,
                    spec_json,
                    instant,
                    instant,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    try:
        statuses = dict(connection.execute("SELECT id, status FROM render_jobs"))
        assert statuses == {
            "a" * 32: "stale",
            "b" * 32: "succeeded",
            "c" * 32: "succeeded",
            "d" * 32: "stale",
            "0" * 32: "stale",
        }
        assert connection.execute(
            "SELECT status, error_code FROM tasks WHERE id = ?", (queued_task,)
        ).fetchone() == ("cancelled", "RENDER_CONTRACT_STALE")
        running_state = connection.execute(
            """
            SELECT status, error_code, cancellation_requested_at
            FROM tasks WHERE id = ?
            """,
            (running_task,),
        ).fetchone()
        assert running_state is not None
        assert running_state[:2] == ("running", "RENDER_CONTRACT_STALE")
        assert running_state[2] is not None
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()
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
