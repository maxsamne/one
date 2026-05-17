"""Session board — shared notebook for parallel coder loops (blackboard pattern)."""

import sqlite3
import threading
import time
from pathlib import Path

from core.agents.agent_ctx import CURRENT_TURN

_DB_PATH = Path(__file__).parents[3] / ".agent.db"

_VALID_KINDS = ("progress", "request", "response")


class Board:
    """Append-only shared log keyed by task_id.

    Each row carries: who wrote it (role), what kind (progress/request/response),
    optional target_role for routing, optional responded_to_seq for response tracking,
    and a free-text payload. `turn` is set deterministically from CURRENT_TURN context.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS board (
                seq              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id          TEXT NOT NULL,
                role             TEXT NOT NULL,
                kind             TEXT NOT NULL CHECK(kind IN ('progress','request','response')),
                target_role      TEXT,
                responded_to_seq INTEGER,
                payload          TEXT NOT NULL,
                turn             INTEGER NOT NULL,
                ts               REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_board_task ON board(task_id, seq);
        """)
        self._con.commit()

    def post(
        self,
        task_id: str,
        role: str,
        kind: str,
        payload: str,
        *,
        target_role: str | None = None,
        responded_to_seq: int | None = None,
    ) -> int:
        if kind not in _VALID_KINDS:
            raise ValueError(f"invalid kind {kind!r}, must be one of {_VALID_KINDS}")
        if kind in ("request", "response") and not target_role:
            raise ValueError(f"{kind} requires target_role")
        if kind == "response" and responded_to_seq is None:
            raise ValueError("response requires responded_to_seq")

        turn = CURRENT_TURN.get()
        ts = time.time()
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO board (task_id, role, kind, target_role, responded_to_seq, payload, turn, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, role, kind, target_role, responded_to_seq, payload, turn, ts),
            )
            self._con.commit()
            return cur.lastrowid

    def read_since(self, task_id: str, role: str, since_seq: int) -> list[dict]:
        """Entries from OTHER roles after since_seq. Excludes the caller's own writes."""
        rows = self._con.execute(
            "SELECT seq, role, kind, target_role, responded_to_seq, payload, turn, ts "
            "FROM board WHERE task_id = ? AND seq > ? AND role != ? "
            "ORDER BY seq ASC",
            (task_id, since_seq, role),
        ).fetchall()
        return [
            {"seq": r[0], "role": r[1], "kind": r[2], "target_role": r[3],
             "responded_to_seq": r[4], "payload": r[5], "turn": r[6], "ts": r[7]}
            for r in rows
        ]

    def open_requests_for(self, task_id: str, role: str) -> list[dict]:
        """Requests addressed to `role` with no response yet."""
        rows = self._con.execute(
            "SELECT seq, role, payload FROM board "
            "WHERE task_id = ? AND kind = 'request' AND target_role = ? "
            "AND seq NOT IN ("
            "  SELECT responded_to_seq FROM board "
            "  WHERE task_id = ? AND kind = 'response' AND responded_to_seq IS NOT NULL"
            ") ORDER BY seq ASC",
            (task_id, role, task_id),
        ).fetchall()
        return [{"seq": r[0], "from_role": r[1], "payload": r[2]} for r in rows]

    def max_seq(self, task_id: str) -> int:
        row = self._con.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM board WHERE task_id = ?", (task_id,)
        ).fetchone()
        return int(row[0]) if row else 0


_singleton: Board | None = None


def get_board() -> Board:
    global _singleton
    if _singleton is None:
        _singleton = Board()
    return _singleton
