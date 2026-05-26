"""Structured event logging and stats — backed by SQLite.

Events and stats live in .agent.db (WAL mode, indexed by task_id / ts / category).

Usage:
    from core.log import log, Category, timed, stat_inc, stats, recent

    log(Category.AGENT, "coder start", task="...", model="cheap")
    log(Category.TOOL,  "read_file",   path="src/foo.py", ok=True)

    with timed(Category.AGENT, "coder run"):
        result = await coder.run(task)
    # → logs: {message: "coder run", elapsed_s: 4.2, ...}

    stat_inc("librarian.cache_hits")
    print(stats())

    recent(task_id="abc12345")               # all events for one task
    recent(Category.TOOL, task_id="...")     # combine filters
    recent(n=50)                             # last 50 events
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parents[2] / ".agent.db"

_logger = logging.getLogger("one")
logging.basicConfig(
    format="%(asctime)s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

_con: sqlite3.Connection | None = None
_lock = threading.Lock()


def _get_con() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _con.execute("PRAGMA journal_mode=WAL")
        # Ensure schema exists (idempotent — migrations may have already run)
        _con.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ts                REAL    NOT NULL,
                task_id           TEXT,
                category          TEXT    NOT NULL,
                message           TEXT    NOT NULL,
                level             TEXT    NOT NULL DEFAULT 'info',
                model             TEXT,
                provider          TEXT,
                prompt_tokens     INTEGER,
                completion_tokens INTEGER,
                elapsed_s         REAL,
                data              TEXT    NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_events_task_id  ON events(task_id);
            CREATE INDEX IF NOT EXISTS idx_events_ts       ON events(ts);
            CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
            CREATE INDEX IF NOT EXISTS idx_events_cat_task ON events(category, task_id);
            CREATE INDEX IF NOT EXISTS idx_events_level    ON events(level);
            CREATE TABLE IF NOT EXISTS stats (
                key        TEXT    PRIMARY KEY,
                value      INTEGER NOT NULL DEFAULT 0,
                updated_at REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id           TEXT    PRIMARY KEY,
                prompt            TEXT    NOT NULL,
                status            TEXT    NOT NULL DEFAULT 'queued',
                submitted_at      REAL    NOT NULL,
                started_at        REAL,
                finished_at       REAL,
                elapsed_s         REAL,
                prompt_tokens     INTEGER,
                completion_tokens INTEGER,
                tokens_out        INTEGER,
                words_out         INTEGER,
                error             TEXT,
                schedule_id       TEXT,
                parent_task_id    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_submitted ON tasks(submitted_at);
            CREATE TABLE IF NOT EXISTS transcripts (
                task_id    TEXT PRIMARY KEY,
                payload    TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id           TEXT PRIMARY KEY,
                cron         TEXT NOT NULL,
                prompt       TEXT NOT NULL,
                tier         TEXT NOT NULL DEFAULT 'ultra_cheap',
                skills_json  TEXT NOT NULL DEFAULT '[]',
                graders_json TEXT NOT NULL DEFAULT '[]',
                enabled      INTEGER NOT NULL DEFAULT 1,
                catch_up     INTEGER NOT NULL DEFAULT 1,
                created_at   REAL NOT NULL,
                last_run_at  REAL,
                mode         TEXT
            );
        """)
        # Migrations for pre-existing databases (idempotent — ignore "duplicate column").
        for col_def in (
            "ALTER TABLE tasks ADD COLUMN schedule_id TEXT",
            "ALTER TABLE tasks ADD COLUMN parent_task_id TEXT",
            "ALTER TABLE tasks ADD COLUMN result TEXT",
            "ALTER TABLE tasks ADD COLUMN tier TEXT",
            "ALTER TABLE tasks ADD COLUMN skills_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE tasks ADD COLUMN graders_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE tasks ADD COLUMN mode_override TEXT",
            "ALTER TABLE tasks ADD COLUMN mode TEXT",
            "ALTER TABLE tasks ADD COLUMN pr_url TEXT",
            "ALTER TABLE schedules ADD COLUMN mode TEXT",
            "ALTER TABLE schedules ADD COLUMN graders_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE schedules ADD COLUMN catch_up INTEGER NOT NULL DEFAULT 1",
        ):
            try:
                _con.execute(col_def)
            except sqlite3.OperationalError:
                pass
        # Indexes that depend on possibly-just-added columns go after the migration step.
        _con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_tasks_schedule ON tasks(schedule_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_parent   ON tasks(parent_task_id);
        """)
        _con.commit()
    return _con


class Category(StrEnum):
    AGENT     = "AGENT"      # manager routing, skill selection, delegation
    TOOL      = "TOOL"       # tool calls and outcomes
    LIBRARIAN = "LIBRARIAN"  # cache hits/misses, Exa searches
    LEDGER    = "LEDGER"     # lock acquire/release/queue
    COMPACT   = "COMPACT"    # context compaction events
    GATEWAY   = "GATEWAY"    # incoming requests, responses


class Level(StrEnum):
    DEBUG   = "debug"
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"


# Column names promoted out of the JSON data blob
_PROMOTED = {"model", "provider", "prompt_tokens", "completion_tokens", "elapsed_s"}


def log(
    category: Category,
    message: str,
    *,
    level: Level = Level.INFO,
    ui: bool = True,
    model: str | None = None,
    provider: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    elapsed_s: float | None = None,
    **data: Any,
) -> None:
    from core.agents.agent_ctx import AGENT_ID_CTX
    from core.agents.task_ctx import current_task_id
    task_id = current_task_id()
    if task_id and "task_id" not in data:
        data["task_id"] = task_id
    agent_id = AGENT_ID_CTX.get()
    if agent_id and "agent" not in data:
        data["agent"] = agent_id

    extra = f"  {data}" if data else ""
    _logger.info("[%s] %s%s", category, message, extra)

    ts = time.time()
    tid = data.pop("task_id", None)

    # Also promote these fields if passed via **data (legacy callers)
    if model is None:
        model = data.pop("model", None)
    else:
        data.pop("model", None)
    if provider is None:
        provider = data.pop("provider", None)
    else:
        data.pop("provider", None)
    if prompt_tokens is None:
        prompt_tokens = data.pop("prompt_tokens", None)
    else:
        data.pop("prompt_tokens", None)
    if completion_tokens is None:
        completion_tokens = data.pop("completion_tokens", None)
    else:
        data.pop("completion_tokens", None)
    if elapsed_s is None:
        elapsed_s = data.pop("elapsed_s", None)
    else:
        data.pop("elapsed_s", None)

    entry: dict[str, Any] = {
        "ts": ts, "category": str(category), "message": message,
        "level": str(level),
    }
    if not ui:
        entry["ui"] = False
    if tid:
        entry["task_id"] = tid
    if model is not None:
        entry["model"] = model
    if provider is not None:
        entry["provider"] = provider
    if prompt_tokens is not None:
        entry["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        entry["completion_tokens"] = completion_tokens
    if elapsed_s is not None:
        entry["elapsed_s"] = elapsed_s
    entry.update(data)

    try:
        with _lock:
            _get_con().execute(
                """INSERT INTO events
                   (ts, task_id, category, message, level, model, provider,
                    prompt_tokens, completion_tokens, elapsed_s, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    ts, tid, str(category), message, str(level),
                    model, provider, prompt_tokens, completion_tokens, elapsed_s,
                    json.dumps(data),
                ],
            )
            _get_con().commit()
    except Exception:
        pass

    if tid:
        try:
            from core.events import publish
            publish(tid, entry)
        except Exception:
            pass


class timed:
    """Context manager (sync and async) that logs an event with elapsed_s on exit.

    Usage:
        with timed(Category.AGENT, "coder run", model="cheap"):
            ...
        async with timed(Category.AGENT, "coder run", model="cheap"):
            ...
    """

    def __init__(self, category: Category, message: str, **data: Any) -> None:
        self._category = category
        self._message = message
        self._data = data
        self._start: float = 0.0

    def __enter__(self) -> "timed":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        log(self._category, self._message, elapsed_s=round(time.monotonic() - self._start, 3), **self._data)

    async def __aenter__(self) -> "timed":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, *_: Any) -> None:
        log(self._category, self._message, elapsed_s=round(time.monotonic() - self._start, 3), **self._data)


def stat_inc(key: str, amount: int = 1) -> None:
    try:
        with _lock:
            _get_con().execute("""
                INSERT INTO stats (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = value + ?, updated_at = ?
            """, [key, amount, time.time(), amount, time.time()])
            _get_con().commit()
    except Exception:
        pass


def stats() -> dict[str, int]:
    try:
        with _lock:
            return {
                row[0]: row[1]
                for row in _get_con().execute("SELECT key, value FROM stats ORDER BY key")
            }
    except Exception:
        return {}


def recent(
    category: Category | None = None,
    n: int = 50,
    task_id: str | None = None,
) -> list[dict]:
    """Return the most recent n events, optionally filtered by category and/or task_id."""
    wheres, params = [], []
    if category is not None:
        wheres.append("category = ?")
        params.append(str(category))
    if task_id is not None:
        wheres.append("task_id = ?")
        params.append(task_id)
    where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    params.append(n)

    try:
        rows = _get_con().execute(
            f"""SELECT ts, task_id, category, message, level, model, provider,
                       prompt_tokens, completion_tokens, elapsed_s, data
                FROM events {where} ORDER BY ts DESC LIMIT ?""",
            params,
        ).fetchall()
    except Exception:
        return []

    results = []
    for ts, tid, cat, msg, level, model, provider, prompt_tokens, completion_tokens, elapsed_s, data_json in rows:
        entry: dict[str, Any] = {"ts": ts, "category": cat, "message": msg, "level": level}
        if tid:
            entry["task_id"] = tid
        if model is not None:
            entry["model"] = model
        if provider is not None:
            entry["provider"] = provider
        if prompt_tokens is not None:
            entry["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            entry["completion_tokens"] = completion_tokens
        if elapsed_s is not None:
            entry["elapsed_s"] = elapsed_s
        try:
            entry.update(json.loads(data_json))
        except Exception:
            pass
        results.append(entry)
    return list(reversed(results))  # chronological order


def tasks_insert(
    task_id: str,
    prompt: str,
    submitted_at: float,
    *,
    schedule_id: str | None = None,
    parent_task_id: str | None = None,
    tier: str | None = None,
    skills: list[str] | None = None,
    graders: list[str] | None = None,
    mode_override: str | None = None,
) -> None:
    try:
        with _lock:
            _get_con().execute(
                """INSERT OR IGNORE INTO tasks
                       (task_id, prompt, status, submitted_at, schedule_id, parent_task_id,
                        tier, skills_json, graders_json, mode_override)
                   VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                [task_id, prompt, submitted_at, schedule_id, parent_task_id, tier,
                 json.dumps(skills or []), json.dumps(graders or []), mode_override],
            )
            _get_con().commit()
    except Exception:
        pass


def task_id_exists(task_id: str) -> bool:
    """True if `task_id` is already in the persistent tasks table."""
    try:
        with _lock:
            row = _get_con().execute("SELECT 1 FROM tasks WHERE task_id = ?", [task_id]).fetchone()
        return row is not None
    except Exception:
        return False


def task_pr_url(task_id: str) -> str | None:
    """Return a persisted PR URL for a task, if one was recorded."""
    try:
        with _lock:
            row = _get_con().execute("SELECT pr_url FROM tasks WHERE task_id = ?", [task_id]).fetchone()
    except Exception:
        return None
    return row[0] if row and row[0] else None


def task_inherited_pr_url(task_id: str | None) -> str | None:
    """Return the nearest PR URL on a task or its ancestors."""
    seen: set[str] = set()
    current = task_id
    while current and current not in seen:
        seen.add(current)
        url = task_pr_url(current)
        if url:
            return url
        current = task_parent_id(current)
    return None


def task_parent_id(task_id: str) -> str | None:
    """Return the parent task id for a follow-up task, if one exists."""
    try:
        with _lock:
            row = _get_con().execute("SELECT parent_task_id FROM tasks WHERE task_id = ?", [task_id]).fetchone()
    except Exception:
        return None
    return row[0] if row and row[0] else None


def task_mode(task_id: str) -> str | None:
    """Return the effective mode for a task, falling back to explicit override for old rows."""
    try:
        with _lock:
            row = _get_con().execute(
                "SELECT mode, mode_override FROM tasks WHERE task_id = ?", [task_id],
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return row[0] or row[1] or None


def task_inherited_mode(task_id: str | None) -> str | None:
    """Return the nearest effective mode on a task or its ancestors."""
    seen: set[str] = set()
    current = task_id
    while current and current not in seen:
        seen.add(current)
        mode = task_mode(current)
        if mode:
            return mode
        current = task_parent_id(current)
    return None


def tasks_mark_orphaned_cancelled() -> int:
    """On gateway startup, any row still showing 'queued' or 'running' is from a
    previous process that died without finalising. They can't possibly still be
    alive (no in-memory record, no SSE subscribers), so mark them cancelled.

    Returns the row count for logging. Idempotent — safe to call repeatedly."""
    try:
        with _lock:
            cur = _get_con().execute(
                """UPDATE tasks
                   SET status = 'cancelled',
                       error  = COALESCE(error, 'interrupted by gateway restart'),
                       finished_at = COALESCE(finished_at, ?)
                   WHERE status IN ('queued', 'running')""",
                [time.time()],
            )
            _get_con().commit()
            return cur.rowcount
    except Exception:
        return 0


def tasks_history(status: str | None = "done", limit: int = 20) -> list[dict]:
    """Read recent tasks from SQLite — survives gateway restarts.

    Used by the @-picker so users can follow up on conversations from prior sessions.
    """
    where, params = "", []
    if status:
        where = "WHERE status = ?"
        params.append(status)
    params.append(limit)
    try:
        rows = _get_con().execute(
            f"""SELECT task_id, prompt, status, submitted_at, finished_at,
                       elapsed_s, parent_task_id, schedule_id, result, tier,
                       skills_json, graders_json, mode_override, mode, pr_url
                FROM tasks {where} ORDER BY submitted_at DESC LIMIT ?""",
            params,
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "task_id":        r[0],  "prompt":         r[1],  "status":        r[2],
            "submitted_at":   r[3],  "finished_at":    r[4],  "elapsed_s":     r[5],
            "parent_task_id": r[6],  "schedule_id":    r[7],
            "result":         r[8],  "tier":           r[9],
            "skills":   json.loads(r[10] or "[]"),
            "graders":  json.loads(r[11] or "[]"),
            "mode_override": r[12],
            "mode": r[13],
            "pr_url": r[14],
        }
        for r in rows
    ]


def transcript_save(task_id: str, payload: dict) -> None:
    """Persist coder conversation history snapshot for later replay."""
    try:
        with _lock:
            _get_con().execute(
                """INSERT INTO transcripts (task_id, payload, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       payload = excluded.payload,
                       updated_at = excluded.updated_at""",
                [task_id, json.dumps(payload), time.time()],
            )
            _get_con().commit()
    except Exception:
        pass


def transcript_load(task_id: str) -> dict | None:
    try:
        with _lock:
            row = _get_con().execute(
                "SELECT payload FROM transcripts WHERE task_id = ?", [task_id],
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def tasks_update(
    task_id: str,
    *,
    status: str,
    started_at: float | None = None,
    finished_at: float | None = None,
    elapsed_s: float | None = None,
    tokens_out: int | None = None,
    words_out: int | None = None,
    error: str | None = None,
    result: str | None = None,
    pr_url: str | None = None,
    mode: str | None = None,
) -> None:
    try:
        with _lock:
            _get_con().execute(
                """UPDATE tasks SET
                       status = ?,
                       started_at = COALESCE(?, started_at),
                       finished_at = COALESCE(?, finished_at),
                       elapsed_s = COALESCE(?, elapsed_s),
                       tokens_out = COALESCE(?, tokens_out),
                       words_out = COALESCE(?, words_out),
                       error = COALESCE(?, error),
                       result = COALESCE(?, result),
                       pr_url = COALESCE(?, pr_url),
                       mode = COALESCE(?, mode)
                   WHERE task_id = ?""",
                [status, started_at, finished_at, elapsed_s, tokens_out, words_out, error, result, pr_url, mode, task_id],
            )
            _get_con().commit()
    except Exception:
        pass
