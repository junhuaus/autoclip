from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sqlalchemy.engine import Engine

from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    SecureFileMissing,
    create_pinned_regular_file_no_follow,
    ensure_directory_no_follow,
    open_pinned_regular_file,
    require_directory_no_follow,
)


class DatabaseBackupError(RuntimeError):
    """A database backup or restore failed without replacing existing data."""


@dataclass(frozen=True, slots=True)
class DatabaseInspection:
    alembic_revision: str
    quick_check: str
    foreign_key_violation_count: int


@dataclass(frozen=True, slots=True)
class DatabaseCopyResult:
    path: Path
    sha256: str
    size_bytes: int
    alembic_revision: str
    quick_check: str
    foreign_key_violation_count: int


def backup_database(engine: Engine, output_path: Path) -> DatabaseCopyResult:
    """Create one consistent SQLite backup and publish it without replacement."""

    output = _prepare_output_path(output_path)
    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.backup.tmp"
    try:
        pinned = create_pinned_regular_file_no_follow(temporary)
    except (OSError, SecureFileError) as exc:
        raise DatabaseBackupError("SQLite backup temporary file is unsafe") from exc
    published = False
    try:
        raw = engine.raw_connection()
        try:
            source = cast(sqlite3.Connection, raw.driver_connection)
            # SQLite creates one closed, transactionally consistent snapshot in
            # process memory. Only our already-pinned descriptor ever receives
            # the serialized bytes, so a pathname swap cannot redirect writes.
            destination = sqlite3.connect(":memory:", timeout=30.0)
            try:
                source.backup(destination)
                destination.commit()
                inspection = _inspect_connection(destination)
                serialized = destination.serialize()
            finally:
                destination.close()
        finally:
            raw.close()
        _write_all(pinned.descriptor, serialized)
        pinned.seal_after_write()
        persisted_inspection = _inspect_pinned_database(pinned)
        if persisted_inspection != inspection:
            raise DatabaseBackupError("serialized SQLite backup differs from its snapshot")
        sha256 = pinned.sha256()
        size_bytes = int(pinned.metadata.st_size)
        _publish_pinned_no_clobber(pinned, output)
        published = True
        return DatabaseCopyResult(
            path=output,
            sha256=sha256,
            size_bytes=size_bytes,
            alembic_revision=inspection.alembic_revision,
            quick_check=inspection.quick_check,
            foreign_key_violation_count=inspection.foreign_key_violation_count,
        )
    except (OSError, sqlite3.Error, SecureFileError, ValueError) as exc:
        if published:
            _unlink_if_same_file(output, pinned)
        raise DatabaseBackupError("SQLite backup could not be created safely") from exc
    finally:
        _unlink_if_same_file(temporary, pinned)
        pinned.close()


def restore_database(backup_path: Path, output_path: Path) -> DatabaseCopyResult:
    """Restore validated backup bytes to a new path without touching a live database."""

    output = _prepare_output_path(output_path)
    source_path = _absolute_path(backup_path)
    temporary = output.parent / f".{output.name}.{uuid.uuid4().hex}.restore.tmp"
    try:
        source = open_pinned_regular_file(source_path)
    except (OSError, SecureFileError) as exc:
        raise DatabaseBackupError("backup source is missing or unsafe") from exc
    try:
        destination = create_pinned_regular_file_no_follow(temporary)
    except (OSError, SecureFileError) as exc:
        source.close()
        raise DatabaseBackupError("SQLite restore temporary file is unsafe") from exc
    published = False
    try:
        _reject_hot_sqlite_sidecars(source_path)
        source_sha256 = _copy_pinned(source.descriptor, destination.descriptor)
        source.validate_binding()
        _reject_hot_sqlite_sidecars(source_path)
        destination.seal_after_write()
        if destination.sha256() != source_sha256:
            raise DatabaseBackupError("restored bytes differ from the selected backup")
        inspection = _inspect_pinned_database(destination)
        _publish_pinned_no_clobber(destination, output)
        published = True
        return DatabaseCopyResult(
            path=output,
            sha256=source_sha256,
            size_bytes=int(destination.metadata.st_size),
            alembic_revision=inspection.alembic_revision,
            quick_check=inspection.quick_check,
            foreign_key_violation_count=inspection.foreign_key_violation_count,
        )
    except DatabaseBackupError:
        if published:
            _unlink_if_same_file(output, destination)
        raise
    except (OSError, sqlite3.Error, SecureFileError, ValueError) as exc:
        if published:
            _unlink_if_same_file(output, destination)
        raise DatabaseBackupError("SQLite backup could not be restored safely") from exc
    finally:
        _unlink_if_same_file(temporary, destination)
        destination.close()
        source.close()


def inspect_database(path: Path) -> DatabaseInspection:
    """Validate a closed SQLite database through a read-only connection."""

    target = _absolute_path(path)
    with open_pinned_regular_file(target) as pinned:
        inspection = _inspect_pinned_database(pinned)
        pinned.validate_binding()
    return inspection


def _inspect_pinned_database(pinned: PinnedRegularFile) -> DatabaseInspection:
    """Inspect the exact held inode, never a pathname that can be exchanged."""

    uri = f"file:/dev/fd/{pinned.descriptor}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        inspection = _inspect_connection(connection)
    finally:
        connection.close()
    current = os.fstat(pinned.descriptor)
    if (
        current.st_size != pinned.metadata.st_size
        or current.st_mtime_ns != pinned.metadata.st_mtime_ns
        or current.st_ctime_ns != pinned.metadata.st_ctime_ns
    ):
        raise DatabaseBackupError("SQLite backup changed while it was inspected")
    return inspection


def _inspect_connection(connection: sqlite3.Connection) -> DatabaseInspection:
    try:
        connection.execute("PRAGMA query_only = ON")
        quick_rows = tuple(str(row[0]) for row in connection.execute("PRAGMA quick_check"))
        if quick_rows != ("ok",):
            raise DatabaseBackupError("SQLite quick_check did not pass")
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
        revision_rows = tuple(
            str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")
        )
    except sqlite3.Error as exc:
        raise DatabaseBackupError("SQLite backup inspection failed") from exc
    if foreign_keys:
        raise DatabaseBackupError("SQLite foreign_key_check did not pass")
    if len(revision_rows) != 1 or not revision_rows[0]:
        raise DatabaseBackupError("backup has no unique Alembic revision")
    return DatabaseInspection(
        alembic_revision=revision_rows[0],
        quick_check="ok",
        foreign_key_violation_count=len(foreign_keys),
    )


def _reject_hot_sqlite_sidecars(database_path: Path) -> None:
    """Reject a raw live SQLite main file whose committed state may be in a sidecar."""

    for suffix in ("-wal", "-journal"):
        sidecar = database_path.with_name(f"{database_path.name}{suffix}")
        try:
            pinned = open_pinned_regular_file(sidecar)
        except SecureFileMissing:
            continue
        except (OSError, SecureFileError) as exc:
            raise DatabaseBackupError("SQLite backup sidecar is unsafe") from exc
        with pinned:
            if pinned.metadata.st_size > 0:
                raise DatabaseBackupError(
                    "SQLite backup has a hot sidecar; create a verified db-backup first"
                )
            pinned.validate_binding()


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    written = 0
    while written < len(view):
        count = os.pwrite(descriptor, view[written:], written)
        if count <= 0:
            raise DatabaseBackupError("SQLite backup write made no progress")
        written += count


def default_backup_path(data_dir: Path, *, label: str | None = None) -> Path:
    """Return a collision-resistant operator backup path below the data directory."""

    safe_label = "operator" if label is None else label.strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    if not safe_label or any(character not in allowed for character in safe_label):
        raise ValueError(
            "backup label must contain only lowercase ASCII letters, digits, '-' or '_'"
        )
    backup_dir = _absolute_path(data_dir) / "database-backups"
    ensure_directory_no_follow(backup_dir)
    return backup_dir / f"liveclip-{safe_label}-{uuid.uuid4().hex}.sqlite3"


def _prepare_output_path(path: Path) -> Path:
    output = _absolute_path(path)
    if output.name in {"", ".", ".."}:
        raise DatabaseBackupError("database output path must name a file")
    try:
        ensure_directory_no_follow(output.parent)
        require_directory_no_follow(output.parent)
        metadata = os.lstat(output)
    except FileNotFoundError:
        return output
    except (OSError, SecureFileError) as exc:
        raise DatabaseBackupError("database output directory is unsafe") from exc
    if stat.S_ISREG(metadata.st_mode):
        raise DatabaseBackupError("database output already exists; overwrite is forbidden")
    raise DatabaseBackupError("database output endpoint is unsafe")


def _publish_pinned_no_clobber(pinned: PinnedRegularFile, output: Path) -> None:
    try:
        pinned.publish_no_replace(output)
    except SecureFileError as exc:
        message = str(exc)
        if "already exists" in message:
            raise DatabaseBackupError(
                "database output already exists; overwrite is forbidden"
            ) from exc
        raise DatabaseBackupError("database output could not be published safely") from exc


def _unlink_if_same_file(path: Path, pinned: PinnedRegularFile) -> None:
    descriptor = pinned.descriptor
    try:
        current = os.lstat(path)
        opened = os.fstat(descriptor)
    except (FileNotFoundError, OSError):
        return
    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
        opened.st_dev,
        opened.st_ino,
    ):
        try:
            path.unlink()
        except OSError:
            return


def _copy_pinned(source_fd: int, destination_fd: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = os.pread(source_fd, 1024 * 1024, offset)
        if not block:
            break
        digest.update(block)
        view = memoryview(block)
        written = 0
        while written < len(view):
            count = os.write(destination_fd, view[written:])
            if count <= 0:
                raise DatabaseBackupError("restored database write made no progress")
            written += count
        offset += len(block)
    return digest.hexdigest()


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


__all__ = [
    "DatabaseBackupError",
    "DatabaseCopyResult",
    "DatabaseInspection",
    "backup_database",
    "default_backup_path",
    "inspect_database",
    "restore_database",
]
