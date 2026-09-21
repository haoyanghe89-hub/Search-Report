from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from marketpulse.domain.collaboration import AgentRole, BlackboardEvent, BlackboardState
from marketpulse.errors import ConfigurationError

metadata = MetaData()
runs = Table(
    "mp_runs",
    metadata,
    Column("run_id", String(100), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
)
events = Table(
    "mp_events",
    metadata,
    Column("run_id", String(100), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("payload", JSON, nullable=False),
)


class StaleBlackboardWrite(RuntimeError):
    """A writer must reload committed state before trying a new decision."""


class BlackboardStore:
    """Transactional blackboard. Credentials never enter snapshots or events."""

    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        if url.get_backend_name() not in {"sqlite", "postgresql"}:
            raise ConfigurationError("黑板仅支持 SQLite 或 PostgreSQL。")
        kwargs: dict[str, Any] = {"hide_parameters": True}
        if url.get_backend_name() == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 10}
            if not url.database or url.database == ":memory:":
                kwargs["poolclass"] = StaticPool
            else:
                Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs["connect_args"] = {"connect_timeout": 5}
            kwargs["pool_pre_ping"] = True
        self.engine = create_engine(url, **kwargs)
        metadata.create_all(self.engine)

    @property
    def backend(self) -> str:
        return self.engine.dialect.name

    def create(self, state: BlackboardState) -> None:
        event = BlackboardEvent(
            run_id=state.run_id, version=0, actor="harness", event="run.created", phase=state.phase
        )
        with self.engine.begin() as conn:
            conn.execute(
                runs.insert().values(
                    run_id=state.run_id, version=0, snapshot=state.model_dump(mode="json")
                )
            )
            conn.execute(
                events.insert().values(
                    run_id=state.run_id, version=0, payload=event.model_dump(mode="json")
                )
            )

    def load(self, run_id: str) -> BlackboardState:
        with self.engine.connect() as conn:
            snapshot = conn.execute(select(runs.c.snapshot).where(runs.c.run_id == run_id)).scalar()
        if snapshot is None:
            raise KeyError(run_id)
        return BlackboardState.model_validate(snapshot)

    def save(self, state: BlackboardState, actor: AgentRole, event: str) -> BlackboardEvent:
        version = state.version + 1
        now = datetime.now(UTC)
        snapshot = state.model_dump(mode="json")
        snapshot.update(version=version, updated_at=now.isoformat())
        record = BlackboardEvent(
            run_id=state.run_id,
            version=version,
            actor=actor,
            event=event,
            phase=state.phase,
            created_at=now,
        )
        with self.engine.begin() as conn:
            result = conn.execute(
                runs.update()
                .where(runs.c.run_id == state.run_id, runs.c.version == state.version)
                .values(version=version, snapshot=snapshot)
            )
            if result.rowcount != 1:
                raise StaleBlackboardWrite("Blackboard version changed; reload before writing")
            conn.execute(
                events.insert().values(
                    run_id=state.run_id, version=version, payload=record.model_dump(mode="json")
                )
            )
        state.version = version
        state.updated_at = now
        return record

    def history(self, run_id: str, *, after_version: int = -1) -> list[BlackboardEvent]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(events.c.payload)
                    .where(events.c.run_id == run_id, events.c.version > after_version)
                    .order_by(events.c.version)
                )
                .scalars()
                .all()
            )
        return [BlackboardEvent.model_validate(row) for row in rows]

    def close(self) -> None:
        self.engine.dispose()
