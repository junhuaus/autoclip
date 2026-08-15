from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

import liveclip.media.secure_files as secure_files_module
from liveclip.db.engine import create_sqlite_engine
from liveclip.services.database_backup import (
    DatabaseBackupError,
    backup_database,
    restore_database,
)

pytestmark = pytest.mark.integration


def test_wal_backup_restore_is_valid_and_never_clobbers(tmp_path: Path) -> None:
    source = tmp_path / "liveclip.sqlite3"
    engine = create_sqlite_engine(source)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alembic_version(version_num) VALUES ('test-revision')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE parent (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE child ("
                "id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL "
                "REFERENCES parent(id) ON DELETE CASCADE)"
            )
            connection.execute(text("INSERT INTO parent(id, value) VALUES (1, 'before')"))
            connection.exec_driver_sql("INSERT INTO child(id, parent_id) VALUES (1, 1)")

        writer = engine.connect()
        transaction = writer.begin()
        writer.execute(text("UPDATE parent SET value = 'wal-committed' WHERE id = 1"))
        transaction.commit()
        assert (tmp_path / "liveclip.sqlite3-wal").exists()

        with pytest.raises(DatabaseBackupError, match="hot sidecar"):
            restore_database(source, tmp_path / "unsafe-live-restore.sqlite3")
        assert not (tmp_path / "unsafe-live-restore.sqlite3").exists()

        backup_path = tmp_path / "backups" / "backup.sqlite3"
        backup = backup_database(engine, backup_path)
        assert backup.path == backup_path
        assert backup.size_bytes > 0
        assert len(backup.sha256) == 64
        assert backup.alembic_revision == "test-revision"
        assert backup.quick_check == "ok"
        assert backup.foreign_key_violation_count == 0

        with sqlite3.connect(backup_path) as connection:
            assert connection.execute("SELECT value FROM parent WHERE id = 1").fetchone() == (
                "wal-committed",
            )

        restored_path = tmp_path / "restored" / "liveclip.sqlite3"
        restored = restore_database(backup_path, restored_path)
        assert restored.sha256 == backup.sha256
        assert restored.alembic_revision == backup.alembic_revision
        with sqlite3.connect(restored_path) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("SELECT value FROM parent WHERE id = 1").fetchone() == (
                "wal-committed",
            )

        with pytest.raises(DatabaseBackupError, match="already exists"):
            backup_database(engine, backup_path)
        with pytest.raises(DatabaseBackupError, match="already exists"):
            restore_database(backup_path, restored_path)
        writer.close()
    finally:
        engine.dispose(close=True)


def test_restore_rejects_corruption_and_symlink_without_output(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    output = tmp_path / "restored.sqlite3"
    with pytest.raises(DatabaseBackupError):
        restore_database(corrupt, output)
    assert not output.exists()

    valid = tmp_path / "valid.sqlite3"
    with sqlite3.connect(valid) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('revision')")
    symlink = tmp_path / "linked.sqlite3"
    try:
        os.symlink(valid.name, symlink)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(DatabaseBackupError, match="missing or unsafe"):
        restore_database(symlink, output)
    assert not output.exists()


def test_backup_rejects_publication_endpoint_swap_without_false_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite3"
    engine = create_sqlite_engine(source)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('revision')")

    output = tmp_path / "backup.sqlite3"
    detached = tmp_path / "detached-pinned.sqlite3"
    real_rename = secure_files_module._rename_directory_no_replace
    swapped = False

    def swap_before_publish(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped and destination_name == output.name:
            swapped = True
            os.rename(
                source_name,
                detached.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
            poison_fd = os.open(
                source_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_parent_fd,
            )
            try:
                os.write(poison_fd, b"poison")
            finally:
                os.close(poison_fd)
        real_rename(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )

    monkeypatch.setattr(
        secure_files_module,
        "_rename_directory_no_replace",
        swap_before_publish,
    )
    try:
        with pytest.raises(DatabaseBackupError, match="published safely"):
            backup_database(engine, output)
        assert swapped is True
        assert not output.exists()
        assert detached.is_file()
        assert detached.read_bytes() != b"poison"
    finally:
        engine.dispose(close=True)
