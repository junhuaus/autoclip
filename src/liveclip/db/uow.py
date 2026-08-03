from __future__ import annotations

from types import TracebackType

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class UnitOfWorkStateError(RuntimeError):
    pass


SessionFactory = sessionmaker[Session]


def create_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class SqlAlchemyUnitOfWork:
    """One short, explicit application transaction.

    External media, filesystem and provider work must happen outside this context.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._finished = False

    @property
    def session(self) -> Session:
        if self._session is None:
            raise UnitOfWorkStateError("unit of work is not active")
        return self._session

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise UnitOfWorkStateError("unit of work cannot be entered twice")
        self._session = self._session_factory()
        self._finished = False
        return self

    def commit(self) -> None:
        if self._finished:
            raise UnitOfWorkStateError("unit of work transaction is already finished")
        self.session.commit()
        self._finished = True

    def rollback(self) -> None:
        if self._finished:
            return
        self.session.rollback()
        self._finished = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        try:
            if exc_type is not None or not self._finished:
                self.rollback()
        finally:
            self.session.close()
            self._session = None
