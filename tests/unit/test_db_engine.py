from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from liveclip.db.engine import (
    SQLiteRuntime,
    assert_supported_sqlite_runtime,
    begin_immediate,
    create_sqlite_engine,
    sqlite_version_is_wal_safe,
)


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(
        tmp_path / "nested" / "liveclip.sqlite3",
        busy_timeout_ms=25,
    )
    try:
        yield engine
    finally:
        engine.dispose(close=True)


def test_engine_creates_parent_and_configures_every_connection(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "state" / "liveclip.sqlite3"
    engine = create_sqlite_engine(database_path, busy_timeout_ms=137)
    try:
        assert database_path.parent.is_dir()
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 137
                assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 2
    finally:
        engine.dispose(close=True)


def test_foreign_key_enforcement_rejects_orphan_rows(sqlite_engine: Engine) -> None:
    with sqlite_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE children ("
            "id INTEGER PRIMARY KEY, "
            "parent_id INTEGER NOT NULL REFERENCES parents(id)"
            ")"
        )

    with pytest.raises(IntegrityError), sqlite_engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO children (id, parent_id) VALUES (1, 999)")

    with sqlite_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM children").scalar_one() == 0


def test_begin_immediate_excludes_a_second_writer_and_rolls_back(
    sqlite_engine: Engine,
) -> None:
    with sqlite_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE claims (id INTEGER PRIMARY KEY, owner TEXT)")

    class AbortClaim(RuntimeError):
        pass

    with pytest.raises(AbortClaim), begin_immediate(sqlite_engine) as owner:
        owner.exec_driver_sql("INSERT INTO claims (id, owner) VALUES (1, 'worker-a')")

        with pytest.raises(OperationalError, match="locked"), begin_immediate(sqlite_engine):
            pytest.fail("a competing writer unexpectedly acquired the SQLite lock")

        raise AbortClaim("prove the owning transaction rolls back")

    with sqlite_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM claims").scalar_one() == 0

    with begin_immediate(sqlite_engine) as connection:
        connection.exec_driver_sql("INSERT INTO claims (id, owner) VALUES (2, 'worker-b')")

    with sqlite_engine.connect() as connection:
        rows = connection.exec_driver_sql("SELECT id, owner FROM claims").all()
    assert rows == [(2, "worker-b")]


@pytest.mark.parametrize("value", [0, -1])
def test_engine_rejects_nonpositive_busy_timeout(tmp_path: Path, value: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        create_sqlite_engine(tmp_path / "liveclip.sqlite3", busy_timeout_ms=value)


def test_engine_rejects_boolean_busy_timeout(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="integer"):
        create_sqlite_engine(tmp_path / "liveclip.sqlite3", busy_timeout_ms=True)


def test_normal_transactions_use_an_explicit_driver_begin(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as connection, connection.begin():
        driver_connection = connection.connection.driver_connection
        assert driver_connection.in_transaction is True


@pytest.mark.parametrize(
    ("version", "safe"),
    [
        ((3, 44, 5), False),
        ((3, 44, 6), True),
        ((3, 45, 3), False),
        ((3, 50, 6), False),
        ((3, 50, 7), True),
        ((3, 51, 0), False),
        ((3, 51, 2), False),
        ((3, 51, 3), True),
        ((3, 53, 1), True),
    ],
)
def test_wal_runtime_version_gate(version: tuple[int, int, int], safe: bool) -> None:
    assert sqlite_version_is_wal_safe(version) is safe


def test_runtime_gate_reports_unsafe_wal_and_threading() -> None:
    with pytest.raises(RuntimeError, match="WAL concurrency"):
        assert_supported_sqlite_runtime(SQLiteRuntime(version=(3, 51, 0), threadsafety=3))
    with pytest.raises(RuntimeError, match="thread safety"):
        assert_supported_sqlite_runtime(SQLiteRuntime(version=(3, 53, 1), threadsafety=0))
