from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_investigation_engine(database_url: str) -> Engine:
    """Create a PostgreSQL/SQLite engine without creating or migrating tables."""

    url = make_url(database_url)
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("Investigation persistence supports PostgreSQL or SQLite")

    kwargs: dict[str, Any] = {"hide_parameters": True}
    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 10}
        if not url.database or url.database == ":memory:":
            kwargs["poolclass"] = StaticPool
        else:
            Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["connect_args"] = {"connect_timeout": 5}

    engine = sqlalchemy_create_engine(url, **kwargs)
    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection: sqlite3.Connection, _: object) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
