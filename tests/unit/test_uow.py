from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import ProjectRow
from liveclip.db.uow import SqlAlchemyUnitOfWork, UnitOfWorkStateError, create_session_factory


@pytest.fixture
def uow_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "uow.sqlite3")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose(close=True)


def _project(identifier: str) -> ProjectRow:
    return ProjectRow(
        id=identifier,
        name="Unit of work",
        source_request_path="/allowed/source.mp4",
        current_generation=0,
        revision_epoch=0,
    )


def _project_count(engine: Engine) -> int:
    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(ProjectRow))
    assert isinstance(count, int)
    return count


def test_uow_requires_explicit_commit(uow_engine: Engine) -> None:
    factory = create_session_factory(uow_engine)
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.session.add(_project("a" * 32))
    assert _project_count(uow_engine) == 0

    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.session.add(_project("b" * 32))
        uow.commit()
    assert _project_count(uow_engine) == 1


def test_uow_rolls_back_exception_and_closes_session(uow_engine: Engine) -> None:
    factory = create_session_factory(uow_engine)
    uow = SqlAlchemyUnitOfWork(factory)
    with pytest.raises(RuntimeError, match="abort"), uow:
        uow.session.add(_project("a" * 32))
        raise RuntimeError("abort")

    assert _project_count(uow_engine) == 0
    with pytest.raises(UnitOfWorkStateError, match="not active"):
        _ = uow.session


def test_uow_rejects_double_finish(uow_engine: Engine) -> None:
    factory = create_session_factory(uow_engine)
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.commit()
        with pytest.raises(UnitOfWorkStateError, match="already finished"):
            uow.commit()
