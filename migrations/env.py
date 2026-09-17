from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import URL, Connection

from liveclip.db import models
from liveclip.db.engine import create_sqlite_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def _database_path() -> Path:
    configured = os.environ.get("LIVECLIP_DATABASE_PATH") or config.get_main_option(
        "liveclip_database_path"
    )
    if not configured:
        raise RuntimeError("LIVECLIP_DATABASE_PATH is not configured")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _database_url() -> str:
    return URL.create("sqlite+pysqlite", database=str(_database_path())).render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    def migrate_connection(connection: Connection) -> None:
        # SQLite rebuilds CHECK-constrained parent tables by dropping and
        # replacing them. FK actions must be disabled before BEGIN or that
        # temporary DROP can delete task attempts, Assets and journal rows.
        raw = connection.connection.driver_connection
        if connection.in_transaction() or raw.in_transaction:
            raise RuntimeError("migration connection already has an active transaction")
        initial_fk = raw.execute("PRAGMA foreign_keys").fetchone()[0]
        if initial_fk != 1:
            raise RuntimeError("migration connection must start with foreign keys enabled")
        try:
            raw.execute("PRAGMA foreign_keys=OFF")
            if raw.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
                raise RuntimeError("could not disable foreign keys before migration transaction")
            connection = connection.execution_options(sqlite_transaction_mode="IMMEDIATE")
            with connection.begin():
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    render_as_batch=True,
                    compare_type=True,
                    transaction_per_migration=True,
                    transactional_ddl=True,
                )
                with context.begin_transaction():
                    context.run_migrations()
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
                if violations:
                    raise RuntimeError(
                        f"migration foreign-key validation failed: {len(violations)} rows"
                    )
        finally:
            if connection.in_transaction() or raw.in_transaction:
                connection.rollback()
            raw.execute("PRAGMA foreign_keys=ON")
            if raw.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise RuntimeError("could not restore migration foreign-key enforcement")

    provided_connection = config.attributes.get("connection")
    if isinstance(provided_connection, Connection):
        migrate_connection(provided_connection)
        return
    engine = create_sqlite_engine(_database_path())
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose(close=True)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
