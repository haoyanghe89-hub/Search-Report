"""Single-server ownership acquired before migrations or startup recovery."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import IO

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, make_url


class ServerAlreadyRunning(RuntimeError):
    pass


class ServerOwnership:
    """Cooperative single-instance guard; this is not a distributed fencing system."""

    def __init__(self, engine: Engine, database_url: str) -> None:
        self.engine = engine
        self.url = make_url(database_url)
        self.file: IO[bytes] | None = None
        self.connection: Connection | None = None
        self.held = False
        self._mutex = threading.Lock()

    def acquire(self) -> None:
        if self.url.get_backend_name() == "postgresql":
            connection = self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            try:
                if not connection.scalar(text("SELECT pg_try_advisory_lock(684297305771)")):
                    raise ServerAlreadyRunning("Another API process owns this database")
            except BaseException:
                connection.close()
                raise
            self.connection = connection
        elif self.url.database and self.url.database != ":memory:":
            path = Path(self.url.database).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.with_name(path.name + ".server.lock").open("a+b")
            try:
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise ServerAlreadyRunning("Another API process owns this database") from None
            self.file = handle
        self.held = True

    def healthy(self) -> bool:
        with self._mutex:
            if not self.held:
                return False
            if self.connection is not None:
                try:
                    if self.connection.invalidated or self.connection.closed:
                        self.held = False
                    else:
                        self.connection.execute(text("SELECT 1"))
                except Exception:
                    # Never reconnect silently: a new connection would no longer own the lock.
                    self.held = False
            return self.held

    def release(self) -> None:
        with self._mutex:
            if self.connection is not None:
                try:
                    if self.held and not self.connection.invalidated:
                        self.connection.execute(text("SELECT pg_advisory_unlock(684297305771)"))
                finally:
                    self.connection.close()
                    self.connection = None
            if self.file is not None:
                try:
                    self.file.seek(0)
                    if sys.platform == "win32":
                        import msvcrt

                        msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
                finally:
                    self.file.close()
                    self.file = None
            self.held = False
