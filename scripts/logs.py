"""Print all log events for a task_id, formatted for readability."""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parents[1] / ".agent.db"
_COLORS = {
    "AGENT":     "\033[36m",
    "TOOL":      "\033[33m",
    "LIBRARIAN": "\033[35m",
    "LEDGER":    "\033[34m",
    "COMPACT":   "\033[90m",
    "GATEWAY":   "\033[32m",
}
_RESET = "\033[0m"


def _resolve_task_id(con: sqlite3.Connection, task_id: str) -> str:
    if task_id != "latest":
        return task_id
    row = con.execute("SELECT task_id FROM events WHERE task_id IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
    if not row:
        print("no tasks found in log")
        sys.exit(1)
    return row[0]


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: logs.py <task_id|latest>")
        sys.exit(1)

    if not _DB_PATH.exists():
        print("no log database found — run 'task migrate' first")
        sys.exit(1)

    con = sqlite3.connect(str(_DB_PATH))
    task_id = _resolve_task_id(con, sys.argv[1])

    rows = con.execute(
        "SELECT ts, category, message, data FROM events WHERE task_id = ? ORDER BY ts ASC",
        [task_id],
    ).fetchall()

    if not rows:
        print(f"no events found for task_id={task_id!r}")
        sys.exit(1)

    print(f"\n── task {task_id} ── {len(rows)} events ──\n")
    for ts, cat, msg, data_json in rows:
        color = _COLORS.get(cat, "")
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
        try:
            data = json.loads(data_json)
        except Exception:
            data = {}
        extras = "  ".join(f"{k}={v!r}" for k, v in data.items()) if data else ""
        print(f"{color}[{cat:<10}]{_RESET} {t}  {msg}{'  ' + extras if extras else ''}")

    # Summary line
    first_ts, last_ts = rows[0][0], rows[-1][0]
    print(f"\n── elapsed {round(last_ts - first_ts, 1)}s ──\n")
    con.close()


if __name__ == "__main__":
    main()
