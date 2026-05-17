"""Resource lock registry — prevents concurrent agent conflicts on shared operations."""

import asyncio
import sqlite3
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from core.log import Category
from core.log import log as _log
from core.log import stat_inc

_DB_PATH = Path(__file__).parents[3] / ".agent.db"


class Ledger:
    """SQLite-backed resource lock registry with asyncio mutual exclusion.

    In-process locking uses asyncio.Lock (fast, no polling).
    SQLite records lock state for visibility — dashboards, the iOS app, debugging.
    Stale locks from crashed sessions are cleared on init.

    Usage:
        ledger = Ledger()
        async with ledger.lock("git:merge", agent_id="coder-1"):
            # only one agent merges at a time
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._mutexes: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS locks (
                resource    TEXT PRIMARY KEY,
                held_by     TEXT NOT NULL,
                acquired_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                resource    TEXT NOT NULL,
                agent_id    TEXT NOT NULL,
                queued_at   REAL NOT NULL
            );
        """)
        # Clear locks left by any previous crashed session
        self._con.execute("DELETE FROM locks")
        self._con.execute("DELETE FROM queue")
        self._con.commit()

    @asynccontextmanager
    async def lock(self, resource: str, agent_id: str) -> AsyncIterator[None]:
        """Acquire an exclusive lock on resource. Queues if already held."""
        mutex = self._mutexes[resource]
        self._enqueue(resource, agent_id)
        _log(Category.LEDGER, "queued", ui=False, resource=resource, agent=agent_id)
        stat_inc("ledger.queued")
        try:
            async with mutex:
                self._dequeue(resource, agent_id)
                self._acquire(resource, agent_id)
                _log(Category.LEDGER, "acquired", ui=False, resource=resource, agent=agent_id)
                stat_inc("ledger.acquired")
                try:
                    yield
                finally:
                    self._release(resource, agent_id)
                    _log(Category.LEDGER, "released", ui=False, resource=resource, agent=agent_id)
        except Exception:
            self._dequeue(resource, agent_id)
            raise

    def status(self) -> dict[str, object]:
        """Current state of all locks and queues — for monitoring/debugging."""
        locks = {
            row[0]: {"held_by": row[1], "since": row[2]}
            for row in self._con.execute("SELECT resource, held_by, acquired_at FROM locks")
        }
        queue = [
            {"resource": row[0], "agent_id": row[1], "queued_at": row[2]}
            for row in self._con.execute(
                "SELECT resource, agent_id, queued_at FROM queue ORDER BY id"
            )
        ]
        return {"locks": locks, "queue": queue}

    def _enqueue(self, resource: str, agent_id: str) -> None:
        self._con.execute(
            "INSERT INTO queue (resource, agent_id, queued_at) VALUES (?, ?, ?)",
            (resource, agent_id, time.time()),
        )
        self._con.commit()

    def _dequeue(self, resource: str, agent_id: str) -> None:
        self._con.execute(
            "DELETE FROM queue WHERE id = ("
            "  SELECT MIN(id) FROM queue WHERE resource = ? AND agent_id = ?"
            ")",
            (resource, agent_id),
        )
        self._con.commit()

    def _acquire(self, resource: str, agent_id: str) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO locks (resource, held_by, acquired_at) VALUES (?, ?, ?)",
            (resource, agent_id, time.time()),
        )
        self._con.commit()

    def _release(self, resource: str, agent_id: str) -> None:
        self._con.execute(
            "DELETE FROM locks WHERE resource = ? AND held_by = ?",
            (resource, agent_id),
        )
        self._con.commit()


# Shared singleton — import and use directly in agents
_ledger: Ledger | None = None


def get_ledger(db_path: Path = _DB_PATH) -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger(db_path)
    return _ledger
