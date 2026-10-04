"""Database access: one SQLAlchemy engine per process, short-lived sessions per unit of work."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from reluai_core.settings import CoreSettings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every module so Alembic sees a single metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    def __init__(self, settings: CoreSettings, *, application_name: str | None = None) -> None:
        self.settings = settings
        self.engine: Engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
                "application_name": application_name or settings.service_name,
            },
        )
        self._sessionmaker = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commit on success, roll back on any exception."""
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(text("SELECT 1")).scalar_one() == 1)

    def dispose(self) -> None:
        self.engine.dispose()


def get_database(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_session(db: Annotated[Database, Depends(get_database)]) -> Iterator[Session]:
    with db.session() as session:
        yield session


DatabaseDep = Annotated[Database, Depends(get_database)]
SessionDep = Annotated[Session, Depends(get_session)]
