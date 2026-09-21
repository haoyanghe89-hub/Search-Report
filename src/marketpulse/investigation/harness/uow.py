from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.persistence.repositories import (
    InvestigationRepository,
    PersistedEntity,
)


class UnitOfWork:
    """One short database transaction shared by all Harness repository writes."""

    def __init__(
        self, sessions: sessionmaker[Session], repository: InvestigationRepository
    ) -> None:
        self._sessions = sessions
        self.repository = repository
        self._session: Session | None = None
        self._committed = False

    def __enter__(self) -> UnitOfWork:
        self._session = self._sessions()
        self._committed = False
        return self

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not open")
        return self._session

    def add(self, entity: PersistedEntity) -> None:
        self.repository.add_in_session(self.session, entity)

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        self.session.rollback()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
