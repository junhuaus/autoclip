from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry

DEFAULT_BUSY_TIMEOUT_MS = 5_000
MINIMUM_RETURNING_VERSION = (3, 35, 0)


@dataclass(frozen=True, slots=True)
class SQLiteRuntime:
    version: tuple[int, int, int]
    threadsafety: int

    @property
    def supports_returning(self) -> bool:
        return self.version >= MINIMUM_RETURNING_VERSION

    @property
    def wal_concurrency_safe(self) -> bool:
        return sqlite_version_is_wal_safe(self.version)


def inspect_sqlite_runtime() -> SQLiteRuntime:
    version = tuple(sqlite3.sqlite_version_info[:3])
    if len(version) != 3:
        raise RuntimeError("SQLite runtime did not expose a semantic version")
    return SQLiteRuntime(
        version=version,
        threadsafety=sqlite3.threadsafety,
    )


def sqlite_version_is_wal_safe(version: tuple[int, int, int]) -> bool:
    """Return whether the runtime contains SQLite's 2026 WAL-reset race fix."""

    if version >= (3, 51, 3):
        return True
    if (3, 50, 7) <= version < (3, 51, 0):
        return True
    return (3, 44, 6) <= version < (3, 45, 0)


def assert_supported_sqlite_runtime(runtime: SQLiteRuntime | None = None) -> SQLiteRuntime:
    inspected = runtime or inspect_sqlite_runtime()
    rendered_version = ".".join(str(part) for part in inspected.version)
    if not inspected.supports_returning:
        raise RuntimeError(f"SQLite {rendered_version} lacks required UPDATE RETURNING support")
    if not inspected.wal_concurrency_safe:
        raise RuntimeError(
            f"SQLite {rendered_version} is unsafe for LiveClip WAL concurrency; "
            "use 3.51.3+ or an official fixed backport"
        )
    if inspected.threadsafety == 0:
        raise RuntimeError("SQLite runtime was compiled without thread safety")
    return inspected


def create_sqlite_engine(
    database_path: Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    echo: bool = False,
) -> Engine:
    """Create one caller-owned synchronous SQLAlchemy engine for a file database.

    The returned engine is deliberately not stored globally. The composition root
    owns its lifetime and must call ``engine.dispose(close=True)`` during shutdown.
    """

    if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
        raise TypeError("SQLite busy timeout must be an integer number of milliseconds")
    if busy_timeout_ms <= 0:
        raise ValueError("SQLite busy timeout must be positive")
    assert_supported_sqlite_runtime()

    path = Path(database_path).expanduser()
    if path.exists() and path.is_dir():
        raise ValueError("SQLite database path must identify a file")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("SQLite database location cannot be prepared") from exc

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(resolved_path)),
        connect_args={
            "check_same_thread": False,
        },
        echo=echo,
        future=True,
        pool_pre_ping=True,
    )

    def configure_connection(
        dbapi_connection: DBAPIConnection,
        _connection_record: ConnectionPoolEntry,
    ) -> None:
        sqlite_connection = cast(sqlite3.Connection, dbapi_connection)
        sqlite_connection.isolation_level = None
        cursor = sqlite_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {busy_timeout_ms:d}")
            cursor.execute("PRAGMA synchronous = FULL")
        finally:
            cursor.close()

    def emit_explicit_begin(connection: Connection) -> None:
        mode = connection.get_execution_options().get("sqlite_transaction_mode", "DEFERRED")
        if mode == "DEFERRED":
            connection.exec_driver_sql("BEGIN")
        elif mode == "IMMEDIATE":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise ValueError("unsupported SQLite transaction mode")

    event.listen(engine, "connect", configure_connection)
    event.listen(engine, "begin", emit_explicit_begin)

    try:
        raw_connection = engine.raw_connection()
        try:
            cursor = raw_connection.cursor()
            try:
                journal_mode = cursor.execute("PRAGMA journal_mode = WAL").fetchone()
                compile_options = {
                    str(row[0]) for row in cursor.execute("PRAGMA compile_options").fetchall()
                }
            finally:
                cursor.close()
        finally:
            raw_connection.close()
        actual_journal_mode = journal_mode[0] if journal_mode else None
        if str(actual_journal_mode).lower() != "wal":
            raise RuntimeError("SQLite did not enable WAL journal mode")
        if {"OMIT_FOREIGN_KEY", "OMIT_TRIGGER"} & compile_options:
            raise RuntimeError("SQLite runtime omits required foreign-key capabilities")
    except BaseException:
        engine.dispose(close=True)
        raise
    return engine


@contextmanager
def begin_immediate(engine: Engine) -> Iterator[Connection]:
    """Open a short write transaction that acquires SQLite's writer lock now.

    Queue claim/recovery code should perform only bounded database work inside this
    context. Filesystem, FFmpeg, and network work must happen after it exits.
    """

    if engine.dialect.name != "sqlite":
        raise ValueError("BEGIN IMMEDIATE is only supported for SQLite engines")
    with engine.connect() as connection:
        connection = connection.execution_options(sqlite_transaction_mode="IMMEDIATE")
        with connection.begin():
            yield connection
